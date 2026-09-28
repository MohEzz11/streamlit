"""User accounts, login and access management."""

import datetime as dt

from .. import audit, config
from ..db import row, rows, transaction, utcnow
from ..permissions import Actor, ROLES, PermissionDenied, require
from ..security import (ValidationError, check_password_strength, clean_text,
                        hash_password, verify_password)

_DUMMY_HASH = hash_password("unused-dummy-password")
GENERIC_LOGIN_ERROR = "Invalid username or password, or the account is locked."


def actor_from_user(u):
    return Actor(user_id=u["id"], username=u["username"], role=u["role"],
                 staff_id=u["staff_id"], department_id=u["department_id"],
                 can_score=bool(u["can_score"]))


def load_actor(conn, user_id):
    """Reload the actor from the DB each request so role changes and
    deactivation take effect immediately."""
    u = row(conn, "SELECT * FROM hp_users WHERE id=? AND active=1", (user_id,))
    return (actor_from_user(u), u) if u else (None, None)


def authenticate(conn, username, password):
    """Return (actor, user_row) or raise ValidationError with a generic message."""
    username = (username or "").strip()
    u = row(conn, "SELECT * FROM hp_users WHERE username=?", (username,))
    now = dt.datetime.now(dt.timezone.utc)
    if not u or not u["active"]:
        # Hash anyway to keep timing similar for unknown users.
        verify_password(password or "", _DUMMY_HASH)
        with transaction(conn):
            audit.log(conn, None, "login.failed", "user", None, username=username[:60])
        raise ValidationError(GENERIC_LOGIN_ERROR)
    if u["locked_until"] and dt.datetime.fromisoformat(u["locked_until"]) > now:
        with transaction(conn):
            audit.log(conn, None, "login.locked", "user", u["id"], username=username)
        raise ValidationError(GENERIC_LOGIN_ERROR)
    if not verify_password(password or "", u["password_hash"]):
        attempts = u["failed_attempts"] + 1
        locked = None
        if attempts >= config.MAX_FAILED_LOGINS:
            locked = (now + dt.timedelta(minutes=config.LOCKOUT_MINUTES)).replace(microsecond=0).isoformat()
            attempts = 0
        with transaction(conn):
            conn.execute("UPDATE hp_users SET failed_attempts=?, locked_until=? WHERE id=?",
                         (attempts, locked, u["id"]))
            audit.log(conn, None, "login.failed", "user", u["id"], username=username, locked=bool(locked))
        raise ValidationError(GENERIC_LOGIN_ERROR)
    with transaction(conn):
        conn.execute("UPDATE hp_users SET failed_attempts=0, locked_until=NULL, last_login_at=? WHERE id=?",
                     (utcnow(), u["id"]))
        audit.log(conn, actor_from_user(u), "login.success", "user", u["id"])
    return actor_from_user(u), u


def _validate_username(username):
    username = clean_text(username, "Username", 40, required=True)
    if not all(c.isalnum() or c in "._-@" for c in username):
        raise ValidationError("Username may contain letters, digits and . _ - @ only.")
    return username


def _check_role_grant(actor, role):
    """Managers may manage staff and supervisor accounts; only administrators
    may create or change manager and administrator accounts."""
    if role not in ROLES:
        raise ValidationError("Unknown role.")
    if actor.role == "admin":
        return
    require(actor, "access.manage")
    if role not in ("staff", "supervisor"):
        raise PermissionDenied("Only an administrator can grant manager or administrator access.")


def create_user(conn, actor, username, password, role, staff_id=None, department_id=None,
                can_score=False, is_demo=False, must_change_password=True):
    if actor is not None:  # actor None only for the bootstrap CLI
        _check_role_grant(actor, role)
    username = _validate_username(username)
    check_password_strength(password)
    if role in ("staff", "supervisor") and not department_id:
        raise ValidationError("Staff and supervisor accounts need a department.")
    if role == "staff" and not staff_id:
        raise ValidationError("A staff account must be linked to a staff profile.")
    if staff_id:
        s = row(conn, "SELECT department_id FROM hp_staff WHERE id=?", (staff_id,))
        if not s:
            raise ValidationError("Staff profile not found.")
        if role in ("staff", "supervisor"):
            department_id = s["department_id"]
    with transaction(conn):
        if row(conn, "SELECT id FROM hp_users WHERE username=?", (username,)):
            raise ValidationError("That username is already taken.")
        if staff_id and row(conn, "SELECT id FROM hp_users WHERE staff_id=?", (staff_id,)):
            raise ValidationError("That staff member already has an account.")
        cur = conn.execute(
            """INSERT INTO hp_users(username, password_hash, role, staff_id, department_id, can_score,
                                    must_change_password, is_demo, created_at, created_by)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (username, hash_password(password), role, staff_id, department_id,
             int(bool(can_score) and role == "supervisor"), int(must_change_password), int(is_demo),
             utcnow(), getattr(actor, "user_id", None)))
        uid = cur.lastrowid
        audit.log(conn, actor, "user.create", "user", uid, department_id,
                  username=username, role=role, staff_id=staff_id, can_score=can_score)
    return uid


def update_user(conn, actor, user_id, role=None, department_id=None, active=None, can_score=None):
    target = row(conn, "SELECT * FROM hp_users WHERE id=?", (user_id,))
    if not target:
        raise ValidationError("User not found.")
    _check_role_grant(actor, target["role"])
    new_role = role or target["role"]
    _check_role_grant(actor, new_role)
    if user_id == actor.user_id and (active is False or new_role != target["role"]):
        raise ValidationError("You cannot deactivate yourself or change your own role.")
    changes = {}
    fields = {"role": new_role,
              "department_id": department_id if department_id is not None else target["department_id"],
              "active": int(active) if active is not None else target["active"],
              "can_score": int(bool(can_score)) if can_score is not None else target["can_score"]}
    if fields["role"] != "supervisor":
        fields["can_score"] = 0
    for k, v in fields.items():
        if v != target[k]:
            changes[k] = {"old": target[k], "new": v}
    if not changes:
        return
    with transaction(conn):
        conn.execute("""UPDATE hp_users SET role=?, department_id=?, active=?, can_score=?,
                        updated_at=?, updated_by=? WHERE id=?""",
                     (fields["role"], fields["department_id"], fields["active"], fields["can_score"],
                      utcnow(), actor.user_id, user_id))
        audit.log(conn, actor, "user.update", "user", user_id, fields["department_id"], **changes)


def reset_password(conn, actor, user_id, new_password):
    target = row(conn, "SELECT * FROM hp_users WHERE id=?", (user_id,))
    if not target:
        raise ValidationError("User not found.")
    _check_role_grant(actor, target["role"])
    check_password_strength(new_password)
    with transaction(conn):
        conn.execute("""UPDATE hp_users SET password_hash=?, must_change_password=1, failed_attempts=0,
                        locked_until=NULL, updated_at=?, updated_by=? WHERE id=?""",
                     (hash_password(new_password), utcnow(), actor.user_id, user_id))
        audit.log(conn, actor, "user.password_reset", "user", user_id)
    return True


def change_own_password(conn, actor, current, new):
    u = row(conn, "SELECT * FROM hp_users WHERE id=?", (actor.user_id,))
    if not u or not verify_password(current or "", u["password_hash"]):
        raise ValidationError("Current password is incorrect.")
    if current == new:
        raise ValidationError("New password must be different.")
    check_password_strength(new)
    with transaction(conn):
        conn.execute("UPDATE hp_users SET password_hash=?, must_change_password=0, updated_at=? WHERE id=?",
                     (hash_password(new), utcnow(), actor.user_id))
        audit.log(conn, actor, "user.password_change", "user", actor.user_id)
    return True


def list_users(conn, actor):
    require(actor, "access.manage")
    sql = """SELECT u.id, u.username, u.role, u.active, u.can_score, u.last_login_at, u.is_demo,
                    u.department_id, d.name AS department, s.full_name, s.employee_id, u.staff_id
             FROM hp_users u LEFT JOIN hp_departments d ON d.id=u.department_id
             LEFT JOIN hp_staff s ON s.id=u.staff_id"""
    if actor.role != "admin":
        sql += " WHERE u.role IN ('staff','supervisor')"
    return rows(conn, sql + " ORDER BY u.username")


def user_count(conn):
    return conn.execute("SELECT COUNT(*) FROM hp_users").fetchone()[0]


def users_for_assignment(conn, department_id=None):
    """Users who can own corrective actions."""
    sql = "SELECT id, username, role FROM hp_users WHERE active=1"
    params = []
    if department_id:
        sql += " AND (role IN ('manager','admin') OR department_id=?)"
        params.append(department_id)
    return rows(conn, sql + " ORDER BY username", params)
