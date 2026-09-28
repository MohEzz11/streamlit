"""Shared helpers: settings, hotel time zone, lookups, evidence storage,
departments/outlets administration and the audit viewer."""

import datetime as dt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .. import audit, config
from ..db import row, rows, scalar, transaction, utcnow
from ..permissions import require, dept_scope, PermissionDenied
from ..security import ValidationError, clean_text, sniff_upload


# ---------------------------------------------------------------- settings
def get_setting(conn, key):
    v = scalar(conn, "SELECT value FROM hp_settings WHERE key=?", (key,))
    return v if v is not None else config.DEFAULT_SETTINGS.get(key)


def get_settings(conn):
    out = dict(config.DEFAULT_SETTINGS)
    out.update({r["key"]: r["value"] for r in rows(conn, "SELECT key, value FROM hp_settings")})
    return out


def set_setting(conn, actor, key, value, perm="admin.settings"):
    require(actor, perm)
    value = str(value).strip()
    if key == "timezone":
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValidationError(f"Unknown time zone: {value}")
    old = get_setting(conn, key)
    with transaction(conn):
        conn.execute("""INSERT INTO hp_settings(key, value, updated_by, updated_at) VALUES (?,?,?,?)
                        ON CONFLICT(key) DO UPDATE SET value=excluded.value,
                        updated_by=excluded.updated_by, updated_at=excluded.updated_at""",
                     (key, value, actor.user_id, utcnow()))
        audit.log(conn, actor, "setting.update", "setting", None, key=key, old=old, new=value)


# -------------------------------------------------------------------- time
def hotel_tz(conn):
    try:
        return ZoneInfo(get_setting(conn, "timezone"))
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("Asia/Dubai")


def now_local(conn):
    return dt.datetime.now(hotel_tz(conn))


def today_local(conn):
    return now_local(conn).date()


def local_to_utc_iso(conn, day, hhmm):
    h, m = (int(x) for x in hhmm.split(":"))
    local = dt.datetime.combine(day, dt.time(h, m), tzinfo=hotel_tz(conn))
    return local.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat()


def fmt_local(conn, iso, with_date=True):
    """Format a stored UTC timestamp in hotel local time."""
    if not iso:
        return ""
    try:
        t = dt.datetime.fromisoformat(iso)
    except ValueError:
        return iso
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    t = t.astimezone(hotel_tz(conn))
    return t.strftime("%d %b %Y %H:%M" if with_date else "%H:%M")


def parse_date(value, field, required=False):
    if value in (None, ""):
        if required:
            raise ValidationError(f"{field} is required.")
        return None
    if isinstance(value, dt.date):
        return value.isoformat()
    try:
        return dt.date.fromisoformat(str(value)).isoformat()
    except ValueError:
        raise ValidationError(f"{field} must be a date (YYYY-MM-DD).")


# ----------------------------------------------------------------- lookups
def departments(conn, active_only=True):
    return rows(conn, "SELECT * FROM hp_departments" + (" WHERE active=1" if active_only else "")
                + " ORDER BY name")


def outlets(conn, department_id=None, active_only=True):
    sql = "SELECT o.*, d.name AS department_name FROM hp_outlets o LEFT JOIN hp_departments d ON d.id=o.department_id WHERE 1=1"
    params = []
    if active_only:
        sql += " AND o.active=1"
    if department_id:
        sql += " AND (o.department_id=? OR o.department_id IS NULL)"
        params.append(department_id)
    return rows(conn, sql + " ORDER BY o.name", params)


def visible_departments(conn, actor):
    scope = dept_scope(actor)
    return [d for d in departments(conn) if scope is None or d["id"] == scope]


def save_department(conn, actor, code, name, dept_id=None, active=True):
    require(actor, "admin.departments")
    code = clean_text(code, "Code", 20, required=True).upper()
    name = clean_text(name, "Name", 80, required=True)
    with transaction(conn):
        if dept_id:
            conn.execute("UPDATE hp_departments SET code=?, name=?, active=? WHERE id=?",
                         (code, name, int(active), dept_id))
            audit.log(conn, actor, "department.update", "department", dept_id, code=code, name=name, active=active)
        else:
            cur = conn.execute("INSERT INTO hp_departments(code, name, active, created_at) VALUES (?,?,?,?)",
                               (code, name, int(active), utcnow()))
            dept_id = cur.lastrowid
            audit.log(conn, actor, "department.create", "department", dept_id, code=code, name=name)
    return dept_id


def save_outlet(conn, actor, name, department_id=None, outlet_id=None, active=True):
    require(actor, "admin.departments")
    name = clean_text(name, "Outlet name", 80, required=True)
    with transaction(conn):
        if outlet_id:
            conn.execute("UPDATE hp_outlets SET name=?, department_id=?, active=? WHERE id=?",
                         (name, department_id, int(active), outlet_id))
            audit.log(conn, actor, "outlet.update", "outlet", outlet_id, name=name, active=active)
        else:
            cur = conn.execute("INSERT INTO hp_outlets(name, department_id, active, created_at) VALUES (?,?,?,?)",
                               (name, department_id, int(active), utcnow()))
            outlet_id = cur.lastrowid
            audit.log(conn, actor, "outlet.create", "outlet", outlet_id, name=name, department_id=department_id)
    return outlet_id


# ---------------------------------------------------------------- evidence
def store_evidence(conn, actor, filename, data, images_only=False):
    """Store an uploaded file. Must be called inside the caller's transaction."""
    mime = sniff_upload(data, images_only=images_only)
    filename = clean_text(filename, "File name", 200) or "upload"
    cur = conn.execute("""INSERT INTO hp_evidence(filename, mime_type, size_bytes, data, uploaded_by, uploaded_at)
                          VALUES (?,?,?,?,?,?)""",
                       (filename, mime, len(data), data, actor.user_id, utcnow()))
    return cur.lastrowid


def get_evidence(conn, actor, evidence_id):
    """Return evidence only if the actor may see the record it belongs to."""
    ev = row(conn, "SELECT * FROM hp_evidence WHERE id=?", (evidence_id,))
    if not ev:
        return None
    if actor.all_departments:
        return ev
    # Find the owning record's department / staff.
    owners = rows(conn, """
        SELECT department_id, assigned_staff_id AS staff_id FROM hp_duties WHERE evidence_id=:e
        UNION ALL SELECT i.department_id, NULL FROM hp_expiry_actions a JOIN hp_expiry_items i ON i.id=a.item_id WHERE a.evidence_id=:e
        UNION ALL SELECT s.department_id, s.id FROM hp_staff s WHERE s.photo_evidence_id=:e
        UNION ALL SELECT s.department_id, s.id FROM hp_certifications c JOIN hp_staff s ON s.id=c.staff_id WHERE c.evidence_id=:e
    """, {"e": evidence_id})
    for o in owners:
        if actor.role == "staff":
            if o["staff_id"] == actor.staff_id or (o["staff_id"] is None and o["department_id"] == actor.department_id):
                return ev
        elif o["department_id"] == actor.department_id:
            return ev
    if ev["uploaded_by"] == actor.user_id:
        return ev
    raise PermissionDenied("You do not have permission to view this file.")


# ------------------------------------------------------------------- audit
def audit_log(conn, actor, entity_type=None, username=None, date_from=None, date_to=None, limit=500):
    require(actor, "admin.audit")
    sql = "SELECT * FROM hp_audit_log WHERE 1=1"
    params = []
    if entity_type:
        sql += " AND entity_type=?"
        params.append(entity_type)
    if username:
        sql += " AND username LIKE ?"
        params.append(f"%{username}%")
    if date_from:
        sql += " AND at >= ?"
        params.append(str(date_from))
    if date_to:
        sql += " AND at < date(?, '+1 day')"
        params.append(str(date_to))
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(int(limit))
    return rows(conn, sql, params)


def entity_history(conn, actor, entity_type, entity_id):
    """Audit entries for one record, for anyone allowed to see that record."""
    return rows(conn, "SELECT at, username, action, details FROM hp_audit_log "
                      "WHERE entity_type=? AND entity_id=? ORDER BY id", (entity_type, entity_id))
