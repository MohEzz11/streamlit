"""Staff profiles, configurable profile fields and certifications."""

import datetime as dt

from .. import audit
from ..db import row, rows, transaction, utcnow
from ..permissions import PermissionDenied, dept_scope, has, require
from ..security import ValidationError, clean_text
from .common import get_setting, parse_date, store_evidence, today_local

EMPLOYMENT_STATUSES = ("active", "on_leave", "suspended", "terminated")
SHIFT_PATTERNS = ("Morning", "Afternoon", "Night", "Split", "Rotating", "Other")

_PROFILE_FIELDS = ("employee_id", "full_name", "job_title", "department_id", "employment_status",
                   "work_phone", "work_email", "start_date", "outlet_id", "supervisor_staff_id",
                   "shift_pattern", "notes")


def can_view_staff(actor, s):
    if actor.staff_id and actor.staff_id == s["id"]:
        return True
    return has(actor, "staff.view", s["department_id"])


def get_staff(conn, actor, staff_id):
    s = row(conn, """SELECT s.*, d.name AS department, o.name AS outlet, sup.full_name AS supervisor
                     FROM hp_staff s JOIN hp_departments d ON d.id=s.department_id
                     LEFT JOIN hp_outlets o ON o.id=s.outlet_id
                     LEFT JOIN hp_staff sup ON sup.id=s.supervisor_staff_id WHERE s.id=?""", (staff_id,))
    if not s:
        return None
    if not can_view_staff(actor, s):
        raise PermissionDenied("You do not have permission to view this profile.")
    fields = rows(conn, """SELECT f.id, f.field_key, f.label, f.field_type, f.visible_to_staff, v.value
                           FROM hp_profile_fields f
                           LEFT JOIN hp_staff_field_values v ON v.field_id=f.id AND v.staff_id=?
                           WHERE f.active=1 ORDER BY f.label""", (staff_id,))
    if actor.role == "staff":
        # Internal notes and staff-hidden fields are not shown to staff.
        s["notes"] = None
        fields = [f for f in fields if f["visible_to_staff"]]
    s["custom_fields"] = fields
    return s


def search_staff(conn, actor, q=None, department_id=None, status=None, include_demo=True):
    if actor.role == "staff":
        raise PermissionDenied("Staff members can only view their own profile.")
    require(actor, "staff.view")
    scope = dept_scope(actor)
    sql = """SELECT s.id, s.employee_id, s.full_name, s.job_title, s.employment_status, s.department_id,
                    d.name AS department, o.name AS outlet, s.shift_pattern, s.is_demo, s.photo_evidence_id
             FROM hp_staff s JOIN hp_departments d ON d.id=s.department_id
             LEFT JOIN hp_outlets o ON o.id=s.outlet_id WHERE 1=1"""
    params = []
    if scope is not None:
        sql += " AND s.department_id=?"
        params.append(scope)
    if department_id:
        sql += " AND s.department_id=?"
        params.append(department_id)
    if status:
        sql += " AND s.employment_status=?"
        params.append(status)
    if not include_demo:
        sql += " AND s.is_demo=0"
    if q:
        sql += " AND (s.full_name LIKE ? OR s.employee_id LIKE ? OR s.job_title LIKE ?)"
        params += [f"%{q}%"] * 3
    return rows(conn, sql + " ORDER BY s.full_name", params)


def staff_options(conn, actor, department_id=None, active_only=True):
    """Lightweight list for pickers, scoped to what the actor can see."""
    scope = dept_scope(actor)
    sql = "SELECT id, employee_id, full_name, department_id, job_title FROM hp_staff WHERE 1=1"
    params = []
    if active_only:
        sql += " AND employment_status IN ('active','on_leave')"
    if scope is not None:
        sql += " AND department_id=?"
        params.append(scope)
    if department_id:
        sql += " AND department_id=?"
        params.append(department_id)
    return rows(conn, sql + " ORDER BY full_name", params)


def job_titles(conn, department_id=None):
    sql = "SELECT DISTINCT job_title FROM hp_staff"
    params = []
    if department_id:
        sql += " WHERE department_id=?"
        params.append(department_id)
    return [r["job_title"] for r in rows(conn, sql + " ORDER BY job_title", params)]


def _validate_profile(conn, data):
    out = {}
    out["employee_id"] = clean_text(data.get("employee_id"), "Employee ID", 30, required=True)
    out["full_name"] = clean_text(data.get("full_name"), "Full name", 120, required=True)
    out["job_title"] = clean_text(data.get("job_title"), "Job title", 80, required=True)
    if not data.get("department_id"):
        raise ValidationError("Department is required.")
    out["department_id"] = int(data["department_id"])
    status = data.get("employment_status") or "active"
    if status not in EMPLOYMENT_STATUSES:
        raise ValidationError("Invalid employment status.")
    out["employment_status"] = status
    out["work_phone"] = clean_text(data.get("work_phone"), "Work phone", 30)
    email = clean_text(data.get("work_email"), "Work email", 120)
    if email and ("@" not in email or " " in email):
        raise ValidationError("Work email looks invalid.")
    out["work_email"] = email
    out["start_date"] = parse_date(data.get("start_date"), "Start date")
    out["outlet_id"] = int(data["outlet_id"]) if data.get("outlet_id") else None
    out["supervisor_staff_id"] = int(data["supervisor_staff_id"]) if data.get("supervisor_staff_id") else None
    out["shift_pattern"] = clean_text(data.get("shift_pattern"), "Shift pattern", 60)
    out["notes"] = clean_text(data.get("notes"), "Profile notes", 4000)
    return out


def save_staff(conn, actor, data, staff_id=None, is_demo=False):
    clean = _validate_profile(conn, data)
    require(actor, "staff.edit", clean["department_id"])
    with transaction(conn):
        dup = row(conn, "SELECT id FROM hp_staff WHERE employee_id=?", (clean["employee_id"],))
        if dup and dup["id"] != staff_id:
            raise ValidationError("Another profile already uses that Employee ID.")
        if staff_id:
            old = row(conn, "SELECT * FROM hp_staff WHERE id=?", (staff_id,))
            if not old:
                raise ValidationError("Profile not found.")
            require(actor, "staff.edit", old["department_id"])
            if clean["supervisor_staff_id"] == staff_id:
                raise ValidationError("A staff member cannot supervise themselves.")
            changes = {k: {"old": old[k], "new": clean[k]} for k in _PROFILE_FIELDS if old[k] != clean[k]}
            if not changes:
                return staff_id
            sets = ", ".join(f"{k}=?" for k in _PROFILE_FIELDS)
            conn.execute(f"UPDATE hp_staff SET {sets}, updated_at=?, updated_by=? WHERE id=?",
                         [clean[k] for k in _PROFILE_FIELDS] + [utcnow(), actor.user_id, staff_id])
            # Keep a linked staff/supervisor account in the same department.
            if "department_id" in changes:
                conn.execute("""UPDATE hp_users SET department_id=? WHERE staff_id=?
                                AND role IN ('staff','supervisor')""", (clean["department_id"], staff_id))
            audit.log(conn, actor, "staff.update", "staff", staff_id, clean["department_id"], **changes)
        else:
            cols = ", ".join(_PROFILE_FIELDS)
            marks = ", ".join("?" for _ in _PROFILE_FIELDS)
            cur = conn.execute(
                f"INSERT INTO hp_staff({cols}, is_demo, created_at, created_by) VALUES ({marks},?,?,?)",
                [clean[k] for k in _PROFILE_FIELDS] + [int(is_demo), utcnow(), actor.user_id])
            staff_id = cur.lastrowid
            audit.log(conn, actor, "staff.create", "staff", staff_id, clean["department_id"],
                      employee_id=clean["employee_id"], full_name=clean["full_name"])
    return staff_id


def set_photo(conn, actor, staff_id, filename, data):
    s = row(conn, "SELECT department_id FROM hp_staff WHERE id=?", (staff_id,))
    if not s:
        raise ValidationError("Profile not found.")
    require(actor, "staff.edit", s["department_id"])
    with transaction(conn):
        ev = store_evidence(conn, actor, filename, data, images_only=True)
        conn.execute("UPDATE hp_staff SET photo_evidence_id=?, updated_at=?, updated_by=? WHERE id=?",
                     (ev, utcnow(), actor.user_id, staff_id))
        audit.log(conn, actor, "staff.photo_update", "staff", staff_id, s["department_id"])


# -------------------------------------------------- configurable fields
def profile_fields(conn, active_only=False):
    return rows(conn, "SELECT * FROM hp_profile_fields" + (" WHERE active=1" if active_only else "")
                + " ORDER BY label")


def save_profile_field(conn, actor, label, field_type="text", visible_to_staff=True, field_id=None, active=True):
    require(actor, "admin.profile_fields")
    label = clean_text(label, "Label", 60, required=True)
    if field_type not in ("text", "date", "number", "yes_no"):
        raise ValidationError("Invalid field type.")
    key = "".join(c if c.isalnum() else "_" for c in label.lower()).strip("_")[:40]
    with transaction(conn):
        if field_id:
            conn.execute("UPDATE hp_profile_fields SET label=?, field_type=?, visible_to_staff=?, active=? WHERE id=?",
                         (label, field_type, int(visible_to_staff), int(active), field_id))
            audit.log(conn, actor, "profile_field.update", "profile_field", field_id, label=label, active=active)
        else:
            if row(conn, "SELECT id FROM hp_profile_fields WHERE field_key=?", (key,)):
                raise ValidationError("A field with that name already exists.")
            cur = conn.execute("""INSERT INTO hp_profile_fields(field_key, label, field_type, visible_to_staff, created_at)
                                  VALUES (?,?,?,?,?)""", (key, label, field_type, int(visible_to_staff), utcnow()))
            field_id = cur.lastrowid
            audit.log(conn, actor, "profile_field.create", "profile_field", field_id, label=label)
    return field_id


def set_field_value(conn, actor, staff_id, field_id, value):
    s = row(conn, "SELECT department_id FROM hp_staff WHERE id=?", (staff_id,))
    require(actor, "staff.edit", s["department_id"] if s else None)
    f = row(conn, "SELECT * FROM hp_profile_fields WHERE id=?", (field_id,))
    if not s or not f:
        raise ValidationError("Profile or field not found.")
    value = clean_text(str(value) if value is not None else "", f["label"], 500)
    if value and f["field_type"] == "date":
        value = parse_date(value, f["label"])
    if value and f["field_type"] == "number":
        try:
            float(value)
        except ValueError:
            raise ValidationError(f"{f['label']} must be a number.")
    old = row(conn, "SELECT value FROM hp_staff_field_values WHERE staff_id=? AND field_id=?", (staff_id, field_id))
    if (old or {}).get("value") == value:
        return
    with transaction(conn):
        if old:
            conn.execute("""UPDATE hp_staff_field_values SET value=?, updated_at=?, updated_by=?
                            WHERE staff_id=? AND field_id=?""", (value, utcnow(), actor.user_id, staff_id, field_id))
        else:
            conn.execute("""INSERT INTO hp_staff_field_values(staff_id, field_id, value, updated_at, updated_by)
                            VALUES (?,?,?,?,?)""", (staff_id, field_id, value, utcnow(), actor.user_id))
        audit.log(conn, actor, "staff.field_update", "staff", staff_id, s["department_id"],
                  field=f["label"], old=(old or {}).get("value"), new=value)


# ------------------------------------------------------ certifications
def cert_status(conn, expiry_date):
    if not expiry_date:
        return "no_expiry"
    days = (dt.date.fromisoformat(expiry_date) - today_local(conn)).days
    if days < 0:
        return "expired"
    if days <= int(get_setting(conn, "cert_reminder_days")):
        return "expiring_soon"
    return "ok"


def certifications(conn, actor, staff_id=None, department_id=None, status=None):
    if staff_id is not None:
        s = row(conn, "SELECT id, department_id FROM hp_staff WHERE id=?", (staff_id,))
        if not s or not (actor.staff_id == staff_id or has(actor, "cert.view", s["department_id"])):
            raise PermissionDenied("You do not have permission to view these certifications.")
    else:
        require(actor, "cert.view")
    scope = dept_scope(actor)
    sql = """SELECT c.*, s.full_name, s.employee_id, s.department_id, d.name AS department
             FROM hp_certifications c JOIN hp_staff s ON s.id=c.staff_id
             JOIN hp_departments d ON d.id=s.department_id WHERE s.employment_status != 'terminated'"""
    params = []
    if staff_id is not None:
        sql += " AND c.staff_id=?"
        params.append(staff_id)
    elif scope is not None:
        sql += " AND s.department_id=?"
        params.append(scope)
    if department_id:
        sql += " AND s.department_id=?"
        params.append(department_id)
    out = rows(conn, sql + " ORDER BY CASE WHEN c.expiry_date IS NULL THEN 1 ELSE 0 END, c.expiry_date", params)
    for c in out:
        c["status"] = cert_status(conn, c["expiry_date"])
    if status:
        out = [c for c in out if c["status"] == status]
    return out


def save_certification(conn, actor, staff_id, data, cert_id=None, evidence=None):
    s = row(conn, "SELECT department_id FROM hp_staff WHERE id=?", (staff_id,))
    if not s:
        raise ValidationError("Profile not found.")
    require(actor, "cert.manage", s["department_id"])
    clean = {
        "name": clean_text(data.get("name"), "Certification name", 120, required=True),
        "cert_type": clean_text(data.get("cert_type"), "Type", 40) or "food_safety",
        "issuer": clean_text(data.get("issuer"), "Issuer", 120),
        "certificate_no": clean_text(data.get("certificate_no"), "Certificate number", 60),
        "issue_date": parse_date(data.get("issue_date"), "Issue date"),
        "expiry_date": parse_date(data.get("expiry_date"), "Expiry date"),
    }
    if clean["issue_date"] and clean["expiry_date"] and clean["expiry_date"] < clean["issue_date"]:
        raise ValidationError("Expiry date cannot be before the issue date.")
    with transaction(conn):
        ev_id = store_evidence(conn, actor, evidence[0], evidence[1]) if evidence else None
        if cert_id:
            old = row(conn, "SELECT * FROM hp_certifications WHERE id=? AND staff_id=?", (cert_id, staff_id))
            if not old:
                raise ValidationError("Certification not found.")
            conn.execute("""UPDATE hp_certifications SET name=?, cert_type=?, issuer=?, certificate_no=?,
                            issue_date=?, expiry_date=?, evidence_id=COALESCE(?, evidence_id),
                            updated_at=?, updated_by=? WHERE id=?""",
                         (clean["name"], clean["cert_type"], clean["issuer"], clean["certificate_no"],
                          clean["issue_date"], clean["expiry_date"], ev_id, utcnow(), actor.user_id, cert_id))
            audit.log(conn, actor, "certification.update", "certification", cert_id, s["department_id"],
                      staff_id=staff_id, **{k: {"old": old[k], "new": v} for k, v in clean.items() if old[k] != v})
        else:
            cur = conn.execute("""INSERT INTO hp_certifications(staff_id, name, cert_type, issuer, certificate_no,
                                  issue_date, expiry_date, evidence_id, created_at, created_by)
                                  VALUES (?,?,?,?,?,?,?,?,?,?)""",
                               (staff_id, clean["name"], clean["cert_type"], clean["issuer"],
                                clean["certificate_no"], clean["issue_date"], clean["expiry_date"],
                                ev_id, utcnow(), actor.user_id))
            cert_id = cur.lastrowid
            audit.log(conn, actor, "certification.create", "certification", cert_id, s["department_id"],
                      staff_id=staff_id, name=clean["name"], expiry_date=clean["expiry_date"])
    return cert_id
