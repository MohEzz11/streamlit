"""Checklist templates, schedules (assignments), daily duty instances,
completion and supervisor verification."""

import datetime as dt

from .. import audit
from ..db import row, rows, scalar, transaction, utcnow
from ..permissions import PermissionDenied, dept_scope, has, require
from ..security import ValidationError, clean_text
from .actions import _insert_ca
from .common import local_to_utc_iso, parse_date, store_evidence, today_local

RESPONSE_TYPES = {"yes_no": "Yes / No", "pass_fail": "Pass / Fail", "numeric": "Numeric reading",
                  "text": "Text", "photo": "Photo / evidence"}
PRIORITIES = ("low", "medium", "high")
RISK_LEVELS = ("low", "medium", "high", "critical")
SHIFTS = ("any", "morning", "afternoon", "night")
STATUS_LABELS = {"not_started": "Not started", "in_progress": "In progress", "completed": "Completed",
                 "overdue": "Overdue", "exception": "Exception raised"}

_ITEM_FIELDS = ("title", "instructions", "response_type", "min_value", "max_value", "unit", "priority",
                "risk_level", "requires_verification", "due_time", "window_minutes", "sort_order",
                "reg_source_id", "reg_clause", "active")


# ---------------------------------------------------------------- templates
def list_templates(conn, actor, department_id=None, include_inactive=False):
    require(actor, "duty.view_dept")
    scope = dept_scope(actor)
    sql = """SELECT t.*, d.name AS department,
                    (SELECT COUNT(*) FROM hp_template_items i WHERE i.template_id=t.id AND i.active=1) AS item_count
             FROM hp_templates t JOIN hp_departments d ON d.id=t.department_id WHERE 1=1"""
    params = []
    if scope is not None:
        sql += " AND t.department_id=?"
        params.append(scope)
    if department_id:
        sql += " AND t.department_id=?"
        params.append(department_id)
    if not include_inactive:
        sql += " AND t.active=1"
    return rows(conn, sql + " ORDER BY d.name, t.name", params)


def get_template(conn, actor, template_id):
    t = row(conn, "SELECT * FROM hp_templates WHERE id=?", (template_id,))
    if not t:
        return None
    require(actor, "duty.view_dept", t["department_id"])
    t["items"] = rows(conn, """SELECT i.*, r.title AS reg_source_title, r.version AS reg_source_version
                               FROM hp_template_items i LEFT JOIN hp_reg_sources r ON r.id=i.reg_source_id
                               WHERE i.template_id=? ORDER BY i.active DESC, i.sort_order, i.id""", (template_id,))
    return t


def save_template(conn, actor, department_id, name, description=None, template_id=None, active=True,
                  is_starter=False):
    name = clean_text(name, "Template name", 120, required=True)
    description = clean_text(description, "Description", 2000)
    require(actor, "template.manage", department_id)
    with transaction(conn):
        if template_id:
            old = row(conn, "SELECT * FROM hp_templates WHERE id=?", (template_id,))
            if not old:
                raise ValidationError("Template not found.")
            require(actor, "template.manage", old["department_id"])
            conn.execute("""UPDATE hp_templates SET department_id=?, name=?, description=?, active=?,
                            updated_at=?, updated_by=? WHERE id=?""",
                         (department_id, name, description, int(active), utcnow(), actor.user_id, template_id))
            audit.log(conn, actor, "template.update", "template", template_id, department_id,
                      name=name, active=active, old_name=old["name"])
        else:
            cur = conn.execute("""INSERT INTO hp_templates(department_id, name, description, is_starter,
                                  created_at, created_by) VALUES (?,?,?,?,?,?)""",
                               (department_id, name, description, int(is_starter), utcnow(), actor.user_id))
            template_id = cur.lastrowid
            audit.log(conn, actor, "template.create", "template", template_id, department_id, name=name)
    return template_id


def _validate_item(data):
    c = {}
    c["title"] = clean_text(data.get("title"), "Title", 200, required=True)
    c["instructions"] = clean_text(data.get("instructions"), "Instructions", 4000)
    c["response_type"] = data.get("response_type")
    if c["response_type"] not in RESPONSE_TYPES:
        raise ValidationError("Choose a response type.")
    for k in ("min_value", "max_value"):
        v = data.get(k)
        c[k] = float(v) if v not in (None, "") else None
    if c["response_type"] != "numeric":
        c["min_value"] = c["max_value"] = None
    if c["min_value"] is not None and c["max_value"] is not None and c["min_value"] > c["max_value"]:
        raise ValidationError("Minimum cannot be greater than maximum.")
    c["unit"] = clean_text(data.get("unit"), "Unit", 20)
    c["priority"] = data.get("priority") or "medium"
    c["risk_level"] = data.get("risk_level") or "low"
    if c["priority"] not in PRIORITIES or c["risk_level"] not in RISK_LEVELS:
        raise ValidationError("Invalid priority or risk level.")
    c["requires_verification"] = int(bool(data.get("requires_verification")))
    due = (data.get("due_time") or "").strip() or None
    if due:
        try:
            due = dt.datetime.strptime(due, "%H:%M").strftime("%H:%M")
        except ValueError:
            raise ValidationError("Due time must be HH:MM (24-hour).")
    c["due_time"] = due
    c["window_minutes"] = max(0, int(data.get("window_minutes") or 60))
    c["sort_order"] = int(data.get("sort_order") or 0)
    c["reg_source_id"] = int(data["reg_source_id"]) if data.get("reg_source_id") else None
    c["reg_clause"] = clean_text(data.get("reg_clause"), "Reference clause", 200)
    c["active"] = int(data.get("active", True))
    return c


def save_template_item(conn, actor, template_id, data, item_id=None):
    t = row(conn, "SELECT * FROM hp_templates WHERE id=?", (template_id,))
    if not t:
        raise ValidationError("Template not found.")
    require(actor, "template.manage", t["department_id"])
    c = _validate_item(data)
    with transaction(conn):
        if item_id:
            old = row(conn, "SELECT * FROM hp_template_items WHERE id=? AND template_id=?", (item_id, template_id))
            if not old:
                raise ValidationError("Checklist item not found.")
            changes = {k: {"old": old[k], "new": c[k]} for k in _ITEM_FIELDS if old[k] != c[k]}
            sets = ", ".join(f"{k}=?" for k in _ITEM_FIELDS)
            conn.execute(f"UPDATE hp_template_items SET {sets}, updated_at=?, updated_by=? WHERE id=?",
                         [c[k] for k in _ITEM_FIELDS] + [utcnow(), actor.user_id, item_id])
            audit.log(conn, actor, "template_item.update", "template_item", item_id, t["department_id"],
                      template_id=template_id, **changes)
        else:
            cols = ", ".join(_ITEM_FIELDS)
            marks = ", ".join("?" for _ in _ITEM_FIELDS)
            cur = conn.execute(f"""INSERT INTO hp_template_items(template_id, {cols}, created_at, created_by)
                                   VALUES (?, {marks}, ?, ?)""",
                               [template_id] + [c[k] for k in _ITEM_FIELDS] + [utcnow(), actor.user_id])
            item_id = cur.lastrowid
            audit.log(conn, actor, "template_item.create", "template_item", item_id, t["department_id"],
                      template_id=template_id, title=c["title"])
    return item_id


# ---------------------------------------------------------------- schedules
def list_schedules(conn, actor, department_id=None, include_inactive=False):
    require(actor, "duty.view_dept")
    scope = dept_scope(actor)
    sql = """SELECT sc.*, t.name AS template, d.name AS department, o.name AS outlet, s.full_name AS assignee
             FROM hp_schedules sc JOIN hp_templates t ON t.id=sc.template_id
             JOIN hp_departments d ON d.id=sc.department_id LEFT JOIN hp_outlets o ON o.id=sc.outlet_id
             LEFT JOIN hp_staff s ON s.id=sc.assigned_staff_id WHERE 1=1"""
    params = []
    if scope is not None:
        sql += " AND sc.department_id=?"
        params.append(scope)
    if department_id:
        sql += " AND sc.department_id=?"
        params.append(department_id)
    if not include_inactive:
        sql += " AND sc.active=1"
    return rows(conn, sql + " ORDER BY d.name, t.name", params)


def save_schedule(conn, actor, data, schedule_id=None):
    t = row(conn, "SELECT * FROM hp_templates WHERE id=?", (data.get("template_id"),))
    if not t:
        raise ValidationError("Choose a checklist template.")
    dept = t["department_id"]
    require(actor, "schedule.manage", dept)
    shift = data.get("shift") or "any"
    if shift not in SHIFTS:
        raise ValidationError("Invalid shift.")
    start = parse_date(data.get("start_date"), "Start date", required=True)
    end = parse_date(data.get("end_date"), "End date")
    if end and end < start:
        raise ValidationError("End date cannot be before start date.")
    days = sorted({int(d) for d in (data.get("days_of_week") or range(7))})
    if not days or any(d < 0 or d > 6 for d in days):
        raise ValidationError("Choose at least one day of the week.")
    staff_id = int(data["assigned_staff_id"]) if data.get("assigned_staff_id") else None
    if staff_id:
        s = row(conn, "SELECT department_id FROM hp_staff WHERE id=?", (staff_id,))
        if not s or s["department_id"] != dept:
            raise ValidationError("The assigned staff member must be in the template's department.")
    outlet_id = int(data["outlet_id"]) if data.get("outlet_id") else None
    job_title = clean_text(data.get("job_title"), "Role", 80)
    vals = (t["id"], dept, outlet_id, job_title, shift, staff_id, start, end,
            ",".join(str(d) for d in days), int(data.get("active", True)))
    with transaction(conn):
        if schedule_id:
            old = row(conn, "SELECT * FROM hp_schedules WHERE id=?", (schedule_id,))
            if not old:
                raise ValidationError("Assignment not found.")
            require(actor, "schedule.manage", old["department_id"])
            conn.execute("""UPDATE hp_schedules SET template_id=?, department_id=?, outlet_id=?, job_title=?,
                            shift=?, assigned_staff_id=?, start_date=?, end_date=?, days_of_week=?, active=?,
                            updated_at=?, updated_by=? WHERE id=?""", vals + (utcnow(), actor.user_id, schedule_id))
            audit.log(conn, actor, "schedule.update", "schedule", schedule_id, dept,
                      template_id=t["id"], assigned_staff_id=staff_id, shift=shift, start=start, end=end,
                      active=bool(vals[-1]))
        else:
            cur = conn.execute("""INSERT INTO hp_schedules(template_id, department_id, outlet_id, job_title, shift,
                                  assigned_staff_id, start_date, end_date, days_of_week, active, created_at, created_by)
                                  VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", vals + (utcnow(), actor.user_id))
            schedule_id = cur.lastrowid
            audit.log(conn, actor, "schedule.create", "schedule", schedule_id, dept,
                      template_id=t["id"], assigned_staff_id=staff_id, shift=shift, start=start, end=end)
    return schedule_id


# ------------------------------------------------------ duty generation
def generate_duties(conn, day=None, actor=None):
    """Create duty instances for a date from active schedules. Idempotent:
    existing instances are never modified or duplicated."""
    day = day or today_local(conn)
    if isinstance(day, str):
        day = dt.date.fromisoformat(day)
    iso = day.isoformat()
    scheds = rows(conn, """SELECT sc.* FROM hp_schedules sc JOIN hp_templates t ON t.id=sc.template_id
                           WHERE sc.active=1 AND t.active=1 AND sc.start_date<=? AND (sc.end_date IS NULL OR sc.end_date>=?)""",
                  (iso, iso))
    created = 0
    with transaction(conn):
        for sc in scheds:
            if str(day.weekday()) not in sc["days_of_week"].split(","):
                continue
            items = rows(conn, "SELECT * FROM hp_template_items WHERE template_id=? AND active=1", (sc["template_id"],))
            for it in items:
                due_at = local_to_utc_iso(conn, day, it["due_time"] or "23:59")
                win = (dt.datetime.fromisoformat(due_at) - dt.timedelta(minutes=it["window_minutes"])).isoformat()
                cur = conn.execute(
                    """INSERT OR IGNORE INTO hp_duties(schedule_id, template_item_id, duty_date, department_id,
                           outlet_id, job_title, shift, assigned_staff_id, title, instructions, response_type,
                           min_value, max_value, unit, priority, risk_level, requires_verification, due_at,
                           window_start_at, reg_source_id, reg_clause, created_at, created_by)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (sc["id"], it["id"], iso, sc["department_id"], sc["outlet_id"], sc["job_title"], sc["shift"],
                     sc["assigned_staff_id"], it["title"], it["instructions"], it["response_type"], it["min_value"],
                     it["max_value"], it["unit"], it["priority"], it["risk_level"], it["requires_verification"],
                     due_at, win, it["reg_source_id"], it["reg_clause"], utcnow(), getattr(actor, "user_id", None)))
                created += cur.rowcount
        if created:
            audit.log(conn, actor, "duty.generate", "duty", None, None, date=iso, created=created)
    return created


def create_adhoc_duty(conn, actor, data):
    """A one-off duty assigned for a date (e.g. a follow-up check)."""
    dept = int(data.get("department_id") or 0)
    require(actor, "schedule.manage", dept)
    c = _validate_item(data)
    day = dt.date.fromisoformat(parse_date(data.get("duty_date"), "Date", required=True))
    staff_id = int(data["assigned_staff_id"]) if data.get("assigned_staff_id") else None
    if staff_id:
        s = row(conn, "SELECT department_id FROM hp_staff WHERE id=?", (staff_id,))
        if not s or s["department_id"] != dept:
            raise ValidationError("The assigned staff member must be in the same department.")
    due_at = local_to_utc_iso(conn, day, c["due_time"] or "23:59")
    win = (dt.datetime.fromisoformat(due_at) - dt.timedelta(minutes=c["window_minutes"])).isoformat()
    with transaction(conn):
        cur = conn.execute(
            """INSERT INTO hp_duties(duty_date, department_id, outlet_id, shift, assigned_staff_id, title,
                   instructions, response_type, min_value, max_value, unit, priority, risk_level,
                   requires_verification, due_at, window_start_at, reg_source_id, reg_clause, created_at, created_by)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (day.isoformat(), dept, data.get("outlet_id") or None, data.get("shift") or "any", staff_id,
             c["title"], c["instructions"], c["response_type"], c["min_value"], c["max_value"], c["unit"],
             c["priority"], c["risk_level"], c["requires_verification"], due_at, win, c["reg_source_id"],
             c["reg_clause"], utcnow(), actor.user_id))
        audit.log(conn, actor, "duty.create", "duty", cur.lastrowid, dept, title=c["title"],
                  assigned_staff_id=staff_id, date=day.isoformat())
    return cur.lastrowid


def assign_duty(conn, actor, duty_id, staff_id):
    d = row(conn, "SELECT * FROM hp_duties WHERE id=?", (duty_id,))
    if not d:
        raise ValidationError("Duty not found.")
    require(actor, "schedule.manage", d["department_id"])
    if d["status"] == "completed":
        raise ValidationError("Completed duties cannot be reassigned.")
    if staff_id:
        s = row(conn, "SELECT department_id FROM hp_staff WHERE id=?", (staff_id,))
        if not s or s["department_id"] != d["department_id"]:
            raise ValidationError("The staff member must be in the duty's department.")
    with transaction(conn):
        conn.execute("UPDATE hp_duties SET assigned_staff_id=? WHERE id=?", (staff_id, duty_id))
        audit.log(conn, actor, "duty.assign", "duty", duty_id, d["department_id"],
                  old=d["assigned_staff_id"], new=staff_id)


# --------------------------------------------------------- duty queries
_DUTY_SELECT = """SELECT du.*, dp.name AS department, o.name AS outlet, s.full_name AS assignee,
                         cs.full_name AS completed_by_name, cu.username AS completed_by_username,
                         vu.username AS verified_by_name, r.title AS reg_source_title,
                         r.version AS reg_source_version,
                         CASE WHEN du.status IN ('not_started','in_progress') AND du.due_at < :now
                              THEN 'overdue' ELSE du.status END AS effective_status
                  FROM hp_duties du JOIN hp_departments dp ON dp.id=du.department_id
                  LEFT JOIN hp_outlets o ON o.id=du.outlet_id
                  LEFT JOIN hp_staff s ON s.id=du.assigned_staff_id
                  LEFT JOIN hp_staff cs ON cs.id=du.completed_by_staff_id
                  LEFT JOIN hp_users cu ON cu.id=du.completed_by_user_id
                  LEFT JOIN hp_users vu ON vu.id=du.verified_by_user_id
                  LEFT JOIN hp_reg_sources r ON r.id=du.reg_source_id"""

_ORDER = """ ORDER BY CASE WHEN du.status IN ('not_started','in_progress') AND du.due_at < :now THEN 0
                           WHEN du.status IN ('not_started','in_progress') THEN 1
                           WHEN du.status='exception' THEN 2 ELSE 3 END,
                      du.due_at, CASE du.risk_level WHEN 'critical' THEN 0 WHEN 'high' THEN 1 ELSE 2 END"""


def _staff_pool_clause(staff):
    """Duties a staff member is responsible for: assigned to them, or
    unassigned duties matching their department, outlet, role and shift."""
    shift = (staff["shift_pattern"] or "").lower()
    shift_match = shift if shift in ("morning", "afternoon", "night") else None
    clause = """(du.assigned_staff_id=:sid OR (du.assigned_staff_id IS NULL AND du.department_id=:dept
                 AND (du.outlet_id IS NULL OR du.outlet_id=:outlet)
                 AND (du.job_title IS NULL OR du.job_title=:job)
                 AND (du.shift='any' OR :shift IS NULL OR du.shift=:shift)))"""
    return clause, {"sid": staff["id"], "dept": staff["department_id"], "outlet": staff["outlet_id"] or -1,
                    "job": staff["job_title"], "shift": shift_match}


def my_duties(conn, actor, day=None):
    require(actor, "duty.view_own")
    if not actor.staff_id:
        return []
    staff = row(conn, "SELECT * FROM hp_staff WHERE id=?", (actor.staff_id,))
    clause, params = _staff_pool_clause(staff)
    params.update({"now": utcnow(), "day": (day or today_local(conn)).isoformat()})
    return rows(conn, _DUTY_SELECT + f" WHERE du.duty_date=:day AND {clause}" + _ORDER, params)


def my_overdue_backlog(conn, actor, days=3):
    """Overdue duties from previous days still open for this staff member."""
    if not actor.staff_id:
        return []
    staff = row(conn, "SELECT * FROM hp_staff WHERE id=?", (actor.staff_id,))
    clause, params = _staff_pool_clause(staff)
    today = today_local(conn)
    params.update({"now": utcnow(), "from": (today - dt.timedelta(days=days)).isoformat(),
                   "today": today.isoformat()})
    return rows(conn, _DUTY_SELECT + f""" WHERE du.duty_date>=:from AND du.duty_date<:today
                AND du.status IN ('not_started','in_progress') AND {clause}""" + _ORDER, params)


def dept_duties(conn, actor, day=None, department_id=None, status=None, date_to=None, awaiting_verification=False):
    require(actor, "duty.view_dept", department_id)
    scope = dept_scope(actor)
    day = day or today_local(conn)
    params = {"now": utcnow(), "d1": str(day), "d2": str(date_to or day)}
    sql = _DUTY_SELECT + " WHERE du.duty_date BETWEEN :d1 AND :d2"
    if scope is not None:
        sql += " AND du.department_id=:scope"
        params["scope"] = scope
    if department_id:
        sql += " AND du.department_id=:dept"
        params["dept"] = department_id
    if awaiting_verification:
        sql += " AND du.verification_status='pending'"
    out = rows(conn, sql + _ORDER, params)
    if status:
        out = [d for d in out if d["effective_status"] == status]
    return out


def get_duty(conn, actor, duty_id):
    d = row(conn, _DUTY_SELECT + " WHERE du.id=:id", {"id": duty_id, "now": utcnow()})
    if not d:
        return None
    if not _can_complete(conn, actor, d) and not has(actor, "duty.view_dept", d["department_id"]):
        raise PermissionDenied("You do not have permission to view this duty.")
    return d


def _can_complete(conn, actor, d):
    if has(actor, "duty.view_dept", d["department_id"]) and actor.role != "staff":
        return True
    if actor.role != "staff" or not actor.staff_id:
        return False
    if d["assigned_staff_id"] == actor.staff_id:
        return True
    if d["assigned_staff_id"] is not None:
        return False
    staff = row(conn, "SELECT * FROM hp_staff WHERE id=?", (actor.staff_id,))
    clause, params = _staff_pool_clause(staff)
    params["id"] = d["id"]
    return bool(scalar(conn, f"SELECT 1 FROM hp_duties du WHERE du.id=:id AND {clause}", params))


# ---------------------------------------------------------- completion
def _evaluate(d, value, has_evidence):
    """Validate the response and return (stored_value, ok) where ok is
    1 (acceptable), 0 (failed reading/check) or None (not evaluated)."""
    rt = d["response_type"]
    if rt == "yes_no":
        if value not in ("yes", "no"):
            raise ValidationError("Answer Yes or No.")
        return value, 1 if value == "yes" else 0
    if rt == "pass_fail":
        if value not in ("pass", "fail"):
            raise ValidationError("Choose Pass or Fail.")
        return value, 1 if value == "pass" else 0
    if rt == "numeric":
        try:
            num = float(value)
        except (TypeError, ValueError):
            raise ValidationError("Enter a numeric reading.")
        ok = 1
        if d["min_value"] is not None and num < d["min_value"]:
            ok = 0
        if d["max_value"] is not None and num > d["max_value"]:
            ok = 0
        return f"{num:g}", ok
    if rt == "text":
        v = clean_text(value, "Response", 2000, required=True)
        return v, None
    if rt == "photo":
        if not has_evidence:
            raise ValidationError("A photo or evidence file is required.")
        return "evidence attached", None
    raise ValidationError("Unknown response type.")


def start_duty(conn, actor, duty_id):
    d = row(conn, "SELECT * FROM hp_duties WHERE id=?", (duty_id,))
    if not d or not _can_complete(conn, actor, d):
        raise PermissionDenied("You cannot work on this duty.")
    if d["status"] != "not_started":
        return
    with transaction(conn):
        conn.execute("UPDATE hp_duties SET status='in_progress', started_at=? WHERE id=?", (utcnow(), duty_id))
        audit.log(conn, actor, "duty.start", "duty", duty_id, d["department_id"])


def complete_duty(conn, actor, duty_id, value=None, comment=None, evidence=None,
                  exception_details=None, raise_exception=False):
    """Record a duty result. Returns a dict describing what was saved.

    A failed check/reading (or an explicitly raised exception) sets status
    'exception', requires exception details and opens a corrective action.
    """
    require(actor, "duty.complete_own")
    d = row(conn, "SELECT * FROM hp_duties WHERE id=?", (duty_id,))
    if not d:
        raise ValidationError("Duty not found.")
    if not _can_complete(conn, actor, d):
        raise PermissionDenied("This duty is not assigned to you.")
    if d["status"] in ("completed", "exception") and d["verification_status"] != "rejected":
        raise ValidationError("This duty has already been recorded. Ask a supervisor if it needs correcting.")
    if d["duty_date"] > today_local(conn).isoformat():
        raise ValidationError("Future duties cannot be completed yet.")
    comment = clean_text(comment, "Comment", 2000)
    exception_details = clean_text(exception_details, "Exception details", 2000)
    if raise_exception and not value and d["response_type"] != "photo":
        stored, ok = None, 0
    else:
        stored, ok = _evaluate(d, value, bool(evidence))
    failed = ok == 0 or raise_exception
    if failed and not exception_details:
        raise ValidationError("This result is outside the acceptable range or failed. Describe what "
                              "happened and what you did immediately (exception details).")
    status = "exception" if failed else "completed"
    needs_verification = bool(d["requires_verification"]) or failed
    now = utcnow()
    with transaction(conn):
        ev_id = store_evidence(conn, actor, evidence[0], evidence[1]) if evidence else d["evidence_id"]
        conn.execute("""UPDATE hp_duties SET status=?, response_value=?, response_ok=?, evidence_id=?, comment=?,
                        exception_details=?, started_at=COALESCE(started_at, ?), completed_at=?,
                        completed_by_user_id=?, completed_by_staff_id=?, verification_status=?,
                        verified_by_user_id=NULL, verified_at=NULL WHERE id=?""",
                     (status, stored, ok, ev_id, comment, exception_details, now, now, actor.user_id,
                      actor.staff_id, "pending" if needs_verification else None, duty_id))
        audit.log(conn, actor, "duty.exception" if failed else "duty.complete", "duty", duty_id,
                  d["department_id"], value=stored, ok=ok, late=bool(d["due_at"] and now > d["due_at"]),
                  exception_details=exception_details)
        ca_id = None
        if failed:
            sev = {"critical": "critical", "high": "high"}.get(d["risk_level"], "medium")
            ca_id = _insert_ca(conn, actor, "duty", duty_id, d["department_id"],
                               f"Exception: {d['title']}",
                               f"Recorded value: {stored or 'n/a'}. Details: {exception_details}",
                               severity=sev, staff_id=None)
    return {"status": status, "value": stored, "ok": ok, "corrective_action_id": ca_id,
            "needs_verification": needs_verification, "saved_at": now}


def verify_duty(conn, actor, duty_id, approve, note=None):
    d = row(conn, "SELECT * FROM hp_duties WHERE id=?", (duty_id,))
    if not d:
        raise ValidationError("Duty not found.")
    require(actor, "duty.verify", d["department_id"])
    if d["status"] not in ("completed", "exception"):
        raise ValidationError("Only recorded duties can be verified.")
    if d["completed_by_user_id"] == actor.user_id:
        raise PermissionDenied("You cannot verify a check you completed yourself.")
    note = clean_text(note, "Verification note", 2000)
    if not approve and not note:
        raise ValidationError("Explain why the check is rejected so staff can redo it.")
    with transaction(conn):
        if approve:
            conn.execute("""UPDATE hp_duties SET verification_status='verified', verified_by_user_id=?,
                            verified_at=?, verification_note=? WHERE id=?""",
                         (actor.user_id, utcnow(), note, duty_id))
        else:
            conn.execute("""UPDATE hp_duties SET verification_status='rejected', verified_by_user_id=?,
                            verified_at=?, verification_note=?, status='in_progress' WHERE id=?""",
                         (actor.user_id, utcnow(), note, duty_id))
        audit.log(conn, actor, "duty.verify" if approve else "duty.reject", "duty", duty_id,
                  d["department_id"], note=note, previous_value=d["response_value"])


# ------------------------------------------------------------ summaries
def completion_summary(conn, actor, date_from, date_to=None, department_id=None):
    duties = dept_duties(conn, actor, date_from, department_id, date_to=date_to)
    out = {}
    for d in duties:
        s = out.setdefault(d["department"], {"department_id": d["department_id"], "total": 0, "completed": 0,
                                             "not_started": 0, "in_progress": 0, "overdue": 0, "exception": 0,
                                             "awaiting_verification": 0, "critical_overdue": 0})
        s["total"] += 1
        s[d["effective_status"]] += 1
        if d["verification_status"] == "pending":
            s["awaiting_verification"] += 1
        if d["effective_status"] == "overdue" and d["risk_level"] in ("critical", "high"):
            s["critical_overdue"] += 1
    for s in out.values():
        done = s["completed"] + s["exception"]
        s["completion_pct"] = round(100 * done / s["total"], 1) if s["total"] else None
    return out
