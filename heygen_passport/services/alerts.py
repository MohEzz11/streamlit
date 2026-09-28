"""Alerts: generated idempotently from current data, acknowledged by
supervisors/managers, and kept as a permanent record."""

import datetime as dt

from .. import audit
from ..db import insert_if_absent, row, rows, transaction, utcnow
from ..permissions import PermissionDenied, dept_scope, has
from .common import get_setting, today_local
from .expiry import _ITEM_SELECT, _decorate

ALERT_TYPES = {
    "expiry_soon": "Item expiring soon", "expired": "Item expired",
    "cert_soon": "Certification expiring soon", "cert_expired": "Certification expired",
    "duty_overdue": "Critical/high-risk check overdue", "failed_reading": "Failed check or reading",
    "ca_overdue": "Corrective action overdue",
}


def _add(conn, key, atype, severity, entity_type, entity_id, dept, staff_id, message):
    cur = insert_if_absent(conn, "hp_alerts", {
        "alert_key": key, "alert_type": atype, "severity": severity, "entity_type": entity_type,
        "entity_id": entity_id, "department_id": dept, "staff_id": staff_id, "message": message,
        "created_at": utcnow()}, ["alert_key"])
    if cur.rowcount:
        audit.log(conn, None, "alert.raise", "alert", cur.lastrowid, dept, type=atype, message=message)
    return cur.rowcount


def scan(conn):
    """Raise any new alerts. Safe to call often; returns number created."""
    today = today_local(conn)
    cert_days = int(get_setting(conn, "cert_reminder_days"))
    n = 0
    with transaction(conn):
        items = _decorate(conn, rows(conn, _ITEM_SELECT + " WHERE i.state IN ('active','action_required')"))
        for it in items:
            if it["status"] == "expired":
                n += _add(conn, f"expired:{it['id']}:{it['effective_expiry']}", "expired", "high", "expiry_item",
                          it["id"], it["department_id"], it["responsible_staff_id"],
                          f"{it['name']} ({it['location'] or 'no location'}) expired on {it['effective_expiry']}.")
            elif it["status"] == "expiring_soon":
                n += _add(conn, f"expiry_soon:{it['id']}:{it['effective_expiry']}", "expiry_soon", "medium",
                          "expiry_item", it["id"], it["department_id"], it["responsible_staff_id"],
                          f"{it['name']} expires on {it['effective_expiry']} ({it['days_left']} day(s) left).")
        certs = rows(conn, """SELECT c.*, s.full_name, s.department_id FROM hp_certifications c
                              JOIN hp_staff s ON s.id=c.staff_id WHERE c.expiry_date IS NOT NULL
                              AND s.employment_status IN ('active','on_leave')""")
        for c in certs:
            exp = dt.date.fromisoformat(c["expiry_date"])
            if exp < today:
                n += _add(conn, f"cert_expired:{c['id']}:{c['expiry_date']}", "cert_expired", "high", "certification",
                          c["id"], c["department_id"], c["staff_id"],
                          f"{c['full_name']}: {c['name']} expired on {c['expiry_date']}.")
            elif (exp - today).days <= cert_days:
                n += _add(conn, f"cert_soon:{c['id']}:{c['expiry_date']}", "cert_soon", "medium", "certification",
                          c["id"], c["department_id"], c["staff_id"],
                          f"{c['full_name']}: {c['name']} expires on {c['expiry_date']}.")
        now = utcnow()
        for d in rows(conn, """SELECT id, title, department_id, assigned_staff_id, duty_date FROM hp_duties
                               WHERE status IN ('not_started','in_progress') AND due_at < ?
                               AND risk_level IN ('high','critical') AND duty_date >= ?""",
                      (now, (today - dt.timedelta(days=7)).isoformat())):
            n += _add(conn, f"duty_overdue:{d['id']}", "duty_overdue", "high", "duty", d["id"], d["department_id"],
                      d["assigned_staff_id"], f"Overdue check: {d['title']} ({d['duty_date']}).")
        for d in rows(conn, """SELECT id, title, department_id, response_value, unit, completed_at FROM hp_duties
                               WHERE status='exception' AND completed_at IS NOT NULL"""):
            n += _add(conn, f"failed_reading:{d['id']}:{d['completed_at']}", "failed_reading", "high", "duty",
                      d["id"], d["department_id"], None,
                      f"Failed/exception: {d['title']} - recorded {d['response_value'] or 'n/a'} {d['unit'] or ''}".strip())
        for ca in rows(conn, """SELECT id, title, department_id, staff_id, due_date FROM hp_corrective_actions
                                WHERE status IN ('open','in_progress') AND due_date < ?""", (today.isoformat(),)):
            n += _add(conn, f"ca_overdue:{ca['id']}:{ca['due_date']}", "ca_overdue", "high", "corrective_action",
                      ca["id"], ca["department_id"], ca["staff_id"],
                      f"Corrective action overdue since {ca['due_date']}: {ca['title']}")
    return n


def list_alerts(conn, actor, open_only=True, department_id=None, limit=200):
    scope = dept_scope(actor)
    sql = "SELECT a.*, d.name AS department FROM hp_alerts a LEFT JOIN hp_departments d ON d.id=a.department_id WHERE 1=1"
    params = []
    if actor.role == "staff":
        # Staff see department expiry alerts plus alerts about themselves.
        sql += " AND ((a.department_id=? AND a.alert_type IN ('expiry_soon','expired')) OR a.staff_id=?)"
        params += [actor.department_id or -1, actor.staff_id or -1]
    elif scope is not None:
        sql += " AND a.department_id=?"
        params.append(scope)
    if department_id:
        sql += " AND a.department_id=?"
        params.append(department_id)
    if open_only:
        sql += " AND a.acknowledged_at IS NULL"
    sql += " ORDER BY CASE a.severity WHEN 'high' THEN 0 ELSE 1 END, a.id DESC LIMIT ?"
    params.append(limit)
    return rows(conn, sql, params)


def acknowledge(conn, actor, alert_id):
    a = row(conn, "SELECT * FROM hp_alerts WHERE id=?", (alert_id,))
    if not a:
        return
    if not has(actor, "alerts.ack", a["department_id"]):
        raise PermissionDenied("You cannot acknowledge this alert.")
    with transaction(conn):
        conn.execute("UPDATE hp_alerts SET acknowledged_by=?, acknowledged_at=? WHERE id=? AND acknowledged_at IS NULL",
                     (actor.user_id, utcnow(), alert_id))
        audit.log(conn, actor, "alert.acknowledge", "alert", alert_id, a["department_id"], message=a["message"])
