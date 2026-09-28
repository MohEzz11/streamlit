"""Corrective actions and coaching notes."""

from .. import audit
from ..db import row, rows, transaction, utcnow
from ..permissions import PermissionDenied, dept_scope, has, require
from ..security import ValidationError, clean_text
from .common import parse_date, today_local

CA_STATUSES = ("open", "in_progress", "resolved", "cancelled")
SEVERITIES = ("low", "medium", "high", "critical")


def _insert_ca(conn, actor, source_type, source_id, department_id, title, description=None,
               severity="medium", staff_id=None, owner_user_id=None, due_date=None):
    """Create a corrective action inside the caller's transaction."""
    cur = conn.execute(
        """INSERT INTO hp_corrective_actions(source_type, source_id, department_id, staff_id, title,
               description, severity, owner_user_id, due_date, created_at, created_by)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (source_type, source_id, department_id, staff_id, title, description, severity,
         owner_user_id, due_date, utcnow(), getattr(actor, "user_id", None)))
    audit.log(conn, actor, "corrective_action.create", "corrective_action", cur.lastrowid, department_id,
              source_type=source_type, source_id=source_id, title=title, severity=severity,
              owner_user_id=owner_user_id, staff_id=staff_id)
    return cur.lastrowid


def create_corrective_action(conn, actor, department_id, title, description=None, severity="medium",
                             staff_id=None, owner_user_id=None, due_date=None,
                             source_type="manual", source_id=None):
    require(actor, "ca.manage", department_id)
    title = clean_text(title, "Title", 200, required=True)
    description = clean_text(description, "Description", 4000)
    if severity not in SEVERITIES:
        raise ValidationError("Invalid severity.")
    due_date = parse_date(due_date, "Due date")
    _check_owner(conn, owner_user_id, department_id)
    with transaction(conn):
        return _insert_ca(conn, actor, source_type, source_id, department_id, title, description,
                          severity, staff_id, owner_user_id, due_date)


def _check_owner(conn, owner_user_id, department_id):
    if not owner_user_id:
        return
    u = row(conn, "SELECT role, department_id, active FROM hp_users WHERE id=?", (owner_user_id,))
    if not u or not u["active"]:
        raise ValidationError("Owner not found or inactive.")
    if u["role"] in ("staff", "supervisor") and department_id and u["department_id"] != department_id:
        raise ValidationError("The owner must belong to the same department.")


def list_corrective_actions(conn, actor, status=None, department_id=None, staff_id=None, open_only=False):
    scope = dept_scope(actor)
    sql = """SELECT ca.*, d.name AS department, s.full_name AS staff_name, ou.username AS owner,
                    cu.username AS created_by_name, ru.username AS resolved_by_name
             FROM hp_corrective_actions ca LEFT JOIN hp_departments d ON d.id=ca.department_id
             LEFT JOIN hp_staff s ON s.id=ca.staff_id LEFT JOIN hp_users ou ON ou.id=ca.owner_user_id
             LEFT JOIN hp_users cu ON cu.id=ca.created_by LEFT JOIN hp_users ru ON ru.id=ca.resolved_by
             WHERE 1=1"""
    params = []
    if actor.role == "staff":
        # Staff see actions they own or that concern them.
        sql += " AND (ca.owner_user_id=? OR ca.staff_id=?)"
        params += [actor.user_id, actor.staff_id or -1]
    else:
        require(actor, "ca.view")
        if scope is not None:
            sql += " AND (ca.department_id=? OR ca.owner_user_id=?)"
            params += [scope, actor.user_id]
    if department_id:
        sql += " AND ca.department_id=?"
        params.append(department_id)
    if staff_id:
        sql += " AND ca.staff_id=?"
        params.append(staff_id)
    if status:
        sql += " AND ca.status=?"
        params.append(status)
    if open_only:
        sql += " AND ca.status IN ('open','in_progress')"
    out = rows(conn, sql + """ ORDER BY CASE ca.status WHEN 'open' THEN 0 WHEN 'in_progress' THEN 1 ELSE 2 END,
                               CASE ca.severity WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                               ca.due_date IS NULL, ca.due_date""", params)
    today = today_local(conn).isoformat()
    for ca in out:
        ca["is_overdue"] = bool(ca["status"] in ("open", "in_progress") and ca["due_date"] and ca["due_date"] < today)
    return out


def update_corrective_action(conn, actor, ca_id, owner_user_id=None, due_date=None, status=None,
                             resolution=None, set_owner=False):
    ca = row(conn, "SELECT * FROM hp_corrective_actions WHERE id=?", (ca_id,))
    if not ca:
        raise ValidationError("Corrective action not found.")
    is_owner = ca["owner_user_id"] == actor.user_id
    manager_ok = has(actor, "ca.manage", ca["department_id"])
    if not (manager_ok or is_owner):
        raise PermissionDenied("You do not have permission to update this corrective action.")
    if (set_owner or due_date is not None) and not manager_ok:
        raise PermissionDenied("Only supervisors or managers can reassign or reschedule.")
    if status and status not in CA_STATUSES:
        raise ValidationError("Invalid status.")
    if status == "cancelled" and not manager_ok:
        raise PermissionDenied("Only supervisors or managers can cancel a corrective action.")
    resolution = clean_text(resolution, "Resolution", 4000)
    if status == "resolved" and not resolution:
        raise ValidationError("Describe how the issue was resolved.")
    changes = {}
    new = dict(ca)
    if set_owner:
        _check_owner(conn, owner_user_id, ca["department_id"])
        new["owner_user_id"] = owner_user_id
    if due_date is not None:
        new["due_date"] = parse_date(due_date, "Due date")
    if status:
        new["status"] = status
    if resolution:
        new["resolution"] = resolution
    if status == "resolved" and ca["status"] != "resolved":
        new["resolved_by"], new["resolved_at"] = actor.user_id, utcnow()
    if status in ("open", "in_progress") and ca["status"] in ("resolved", "cancelled"):
        new["resolved_by"], new["resolved_at"] = None, None
    for k in ("owner_user_id", "due_date", "status", "resolution", "resolved_by", "resolved_at"):
        if new[k] != ca[k]:
            changes[k] = {"old": ca[k], "new": new[k]}
    if not changes:
        return
    action = "corrective_action.resolve" if status == "resolved" else (
        "corrective_action.assign" if "owner_user_id" in changes else "corrective_action.update")
    with transaction(conn):
        conn.execute("""UPDATE hp_corrective_actions SET owner_user_id=?, due_date=?, status=?, resolution=?,
                        resolved_by=?, resolved_at=?, updated_at=?, updated_by=? WHERE id=?""",
                     (new["owner_user_id"], new["due_date"], new["status"], new["resolution"],
                      new["resolved_by"], new["resolved_at"], utcnow(), actor.user_id, ca_id))
        audit.log(conn, actor, action, "corrective_action", ca_id, ca["department_id"], **changes)


# --------------------------------------------------------------- coaching
def add_coaching_note(conn, actor, staff_id, note, follow_up_date=None, visible_to_staff=True):
    s = row(conn, "SELECT department_id FROM hp_staff WHERE id=?", (staff_id,))
    if not s:
        raise ValidationError("Staff member not found.")
    require(actor, "coaching.manage", s["department_id"])
    note = clean_text(note, "Coaching note", 4000, required=True)
    follow_up_date = parse_date(follow_up_date, "Follow-up date")
    with transaction(conn):
        cur = conn.execute("""INSERT INTO hp_coaching_notes(staff_id, note, visible_to_staff, follow_up_date,
                              created_at, created_by) VALUES (?,?,?,?,?,?)""",
                           (staff_id, note, int(visible_to_staff), follow_up_date, utcnow(), actor.user_id))
        audit.log(conn, actor, "coaching.create", "coaching_note", cur.lastrowid, s["department_id"],
                  staff_id=staff_id, follow_up_date=follow_up_date)
    return cur.lastrowid


def resolve_coaching_note(conn, actor, note_id, resolution):
    n = row(conn, """SELECT c.*, s.department_id FROM hp_coaching_notes c JOIN hp_staff s ON s.id=c.staff_id
                     WHERE c.id=?""", (note_id,))
    if not n:
        raise ValidationError("Note not found.")
    require(actor, "coaching.manage", n["department_id"])
    resolution = clean_text(resolution, "Resolution", 2000, required=True)
    with transaction(conn):
        conn.execute("UPDATE hp_coaching_notes SET resolved_at=?, resolved_by=?, resolution=? WHERE id=?",
                     (utcnow(), actor.user_id, resolution, note_id))
        audit.log(conn, actor, "coaching.resolve", "coaching_note", note_id, n["department_id"],
                  resolution=resolution)


def coaching_notes(conn, actor, staff_id):
    s = row(conn, "SELECT department_id FROM hp_staff WHERE id=?", (staff_id,))
    if not s:
        return []
    own = actor.staff_id == staff_id
    if not own and not has(actor, "coaching.manage", s["department_id"]):
        raise PermissionDenied("You do not have permission to view these notes.")
    sql = """SELECT c.*, u.username AS created_by_name, r.username AS resolved_by_name
             FROM hp_coaching_notes c LEFT JOIN hp_users u ON u.id=c.created_by
             LEFT JOIN hp_users r ON r.id=c.resolved_by WHERE c.staff_id=?"""
    if own and actor.role == "staff":
        sql += " AND c.visible_to_staff=1"
    return rows(conn, sql + " ORDER BY c.created_at DESC", (staff_id,))
