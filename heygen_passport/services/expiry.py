"""Expiry tracking for food, beverages, chemicals, first-aid and other items.

Rules are per category (reminder period, optional shelf life after opening
or preparation) because items do not all follow the same expiry rules. The
effective expiry date is the earliest of the labelled date and any
opened/prepared shelf-life limit.
"""

import datetime as dt

from .. import audit
from ..db import row, rows, transaction, utcnow
from ..permissions import dept_scope, require
from ..security import ValidationError, clean_text
from .actions import _insert_ca
from .common import parse_date, store_evidence, today_local

KINDS = ("food", "beverage", "prepared_food", "chemical", "first_aid", "supply", "other")
DATE_TYPES = {"use_by": "Use by", "best_before": "Best before", "expiry": "Expiry"}
ACTIONS = {"checked_ok": "Checked - OK", "removed": "Removed from use", "disposed": "Disposed",
           "replaced": "Replaced", "escalated": "Escalated to supervisor",
           "action_required": "Action required"}
STATUS_LABELS = {"ok": "OK", "expiring_soon": "Expiring soon", "expired": "Expired",
                 "removed": "Removed", "disposed": "Disposed", "action_required": "Action required"}


# -------------------------------------------------------------- categories
def categories(conn, active_only=True):
    return rows(conn, "SELECT * FROM hp_expiry_categories" + (" WHERE active=1" if active_only else "")
                + " ORDER BY name")


def save_category(conn, actor, data, category_id=None):
    require(actor, "expiry.configure")
    name = clean_text(data.get("name"), "Category name", 80, required=True)
    kind = data.get("kind")
    if kind not in KINDS:
        raise ValidationError("Choose a category type.")
    reminder = int(data.get("reminder_days") or 0)
    if reminder < 0 or reminder > 365:
        raise ValidationError("Reminder period must be between 0 and 365 days.")

    def opt_int(k, label):
        v = data.get(k)
        if v in (None, "", 0):
            return None
        v = int(v)
        if v < 0:
            raise ValidationError(f"{label} cannot be negative.")
        return v
    after_open = opt_int("shelf_life_after_open_days", "Shelf life after opening")
    after_prep = opt_int("shelf_life_after_prep_days", "Shelf life after preparation")
    note = clean_text(data.get("procedure_note"), "Procedure note", 2000)
    vals = (name, kind, reminder, after_open, after_prep, int(bool(data.get("requires_evidence"))), note,
            int(data.get("active", True)))
    with transaction(conn):
        if category_id:
            old = row(conn, "SELECT * FROM hp_expiry_categories WHERE id=?", (category_id,))
            conn.execute("""UPDATE hp_expiry_categories SET name=?, kind=?, reminder_days=?,
                            shelf_life_after_open_days=?, shelf_life_after_prep_days=?, requires_evidence=?,
                            procedure_note=?, active=?, updated_at=?, updated_by=? WHERE id=?""",
                         vals + (utcnow(), actor.user_id, category_id))
            audit.log(conn, actor, "expiry_category.update", "expiry_category", category_id,
                      old={k: old[k] for k in ("name", "reminder_days", "shelf_life_after_open_days",
                                               "shelf_life_after_prep_days", "active")},
                      new={"name": name, "reminder_days": reminder, "after_open": after_open,
                           "after_prep": after_prep, "active": vals[-1]})
        else:
            if row(conn, "SELECT id FROM hp_expiry_categories WHERE name=?", (name,)):
                raise ValidationError("A category with that name already exists.")
            cur = conn.execute("""INSERT INTO hp_expiry_categories(name, kind, reminder_days,
                                  shelf_life_after_open_days, shelf_life_after_prep_days, requires_evidence,
                                  procedure_note, active, created_at, created_by) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                               vals + (utcnow(), actor.user_id))
            category_id = cur.lastrowid
            audit.log(conn, actor, "expiry_category.create", "expiry_category", category_id, name=name,
                      reminder_days=reminder)
    return category_id


# ------------------------------------------------------------------ status
def effective_expiry(item):
    dates = [dt.date.fromisoformat(item["expiry_date"])]
    if item.get("opened_on") and item.get("shelf_life_after_open_days"):
        dates.append(dt.date.fromisoformat(item["opened_on"]) + dt.timedelta(days=item["shelf_life_after_open_days"]))
    if item.get("prepared_on") and item.get("shelf_life_after_prep_days"):
        dates.append(dt.date.fromisoformat(item["prepared_on"]) + dt.timedelta(days=item["shelf_life_after_prep_days"]))
    return min(dates)


def compute_status(item, today):
    if item["state"] in ("removed", "disposed"):
        return item["state"]
    eff = effective_expiry(item)
    if eff < today:
        return "expired"
    if item["state"] == "action_required":
        return "action_required"
    if (eff - today).days <= item["reminder_days"]:
        return "expiring_soon"
    return "ok"


def _decorate(conn, items):
    today = today_local(conn)
    for it in items:
        eff = effective_expiry(it)
        it["effective_expiry"] = eff.isoformat()
        it["days_left"] = (eff - today).days
        it["status"] = compute_status(it, today)
        it["status_label"] = STATUS_LABELS[it["status"]]
    return items


_ITEM_SELECT = """SELECT i.*, c.name AS category, c.kind, c.reminder_days, c.shelf_life_after_open_days,
                         c.shelf_life_after_prep_days, c.requires_evidence, c.procedure_note,
                         d.name AS department, s.full_name AS responsible
                  FROM hp_expiry_items i JOIN hp_expiry_categories c ON c.id=i.category_id
                  JOIN hp_departments d ON d.id=i.department_id
                  LEFT JOIN hp_staff s ON s.id=i.responsible_staff_id"""


def list_items(conn, actor, department_id=None, status=None, category_id=None, q=None,
               include_closed=False, responsible_staff_id=None):
    require(actor, "expiry.view")
    scope = dept_scope(actor)
    sql = _ITEM_SELECT + " WHERE 1=1"
    params = []
    if scope is not None:
        sql += " AND i.department_id=?"
        params.append(scope)
    if department_id:
        sql += " AND i.department_id=?"
        params.append(department_id)
    if category_id:
        sql += " AND i.category_id=?"
        params.append(category_id)
    if responsible_staff_id:
        sql += " AND i.responsible_staff_id=?"
        params.append(responsible_staff_id)
    if not include_closed:
        sql += " AND i.state IN ('active','action_required')"
    if q:
        sql += " AND (i.name LIKE ? OR i.batch_lot LIKE ? OR i.location LIKE ?)"
        params += [f"%{q}%"] * 3
    items = _decorate(conn, rows(conn, sql, params))
    if status:
        wanted = {status} if isinstance(status, str) else set(status)
        items = [i for i in items if i["status"] in wanted]
    order = {"expired": 0, "action_required": 1, "expiring_soon": 2, "ok": 3, "removed": 4, "disposed": 5}
    items.sort(key=lambda i: (order[i["status"]], i["effective_expiry"]))
    return items


def get_item(conn, actor, item_id):
    it = row(conn, _ITEM_SELECT + " WHERE i.id=?", (item_id,))
    if not it:
        return None
    require(actor, "expiry.view", it["department_id"])
    _decorate(conn, [it])
    it["actions"] = rows(conn, """SELECT a.*, u.username AS performed_by_name FROM hp_expiry_actions a
                                  JOIN hp_users u ON u.id=a.performed_by WHERE a.item_id=? ORDER BY a.id DESC""",
                         (item_id,))
    return it


_ITEM_FIELDS = ("name", "category_id", "department_id", "location", "batch_lot", "quantity", "unit", "date_type",
                "expiry_date", "opened_on", "prepared_on", "responsible_staff_id", "notes")


def save_item(conn, actor, data, item_id=None, is_demo=False):
    c = {
        "name": clean_text(data.get("name"), "Item name", 120, required=True),
        "category_id": int(data.get("category_id") or 0),
        "department_id": int(data.get("department_id") or 0),
        "location": clean_text(data.get("location"), "Storage location", 120),
        "batch_lot": clean_text(data.get("batch_lot"), "Batch / lot", 60),
        "quantity": float(data["quantity"]) if data.get("quantity") not in (None, "") else None,
        "unit": clean_text(data.get("unit"), "Unit", 20),
        "date_type": data.get("date_type") or "use_by",
        "expiry_date": parse_date(data.get("expiry_date"), "Expiry date", required=True),
        "opened_on": parse_date(data.get("opened_on"), "Opened on"),
        "prepared_on": parse_date(data.get("prepared_on"), "Prepared on"),
        "responsible_staff_id": int(data["responsible_staff_id"]) if data.get("responsible_staff_id") else None,
        "notes": clean_text(data.get("notes"), "Notes", 2000),
    }
    if c["date_type"] not in DATE_TYPES:
        raise ValidationError("Invalid date type.")
    if not row(conn, "SELECT id FROM hp_expiry_categories WHERE id=? AND active=1", (c["category_id"],)):
        raise ValidationError("Choose a category.")
    if c["quantity"] is not None and c["quantity"] < 0:
        raise ValidationError("Quantity cannot be negative.")
    require(actor, "expiry.manage_items", c["department_id"])
    with transaction(conn):
        if item_id:
            old = row(conn, "SELECT * FROM hp_expiry_items WHERE id=?", (item_id,))
            if not old:
                raise ValidationError("Item not found.")
            require(actor, "expiry.manage_items", old["department_id"])
            changes = {k: {"old": old[k], "new": c[k]} for k in _ITEM_FIELDS if old[k] != c[k]}
            sets = ", ".join(f"{k}=?" for k in _ITEM_FIELDS)
            conn.execute(f"UPDATE hp_expiry_items SET {sets}, updated_at=?, updated_by=? WHERE id=?",
                         [c[k] for k in _ITEM_FIELDS] + [utcnow(), actor.user_id, item_id])
            audit.log(conn, actor, "expiry_item.update", "expiry_item", item_id, c["department_id"], **changes)
        else:
            cols = ", ".join(_ITEM_FIELDS)
            marks = ", ".join("?" for _ in _ITEM_FIELDS)
            cur = conn.execute(f"""INSERT INTO hp_expiry_items({cols}, is_demo, created_at, created_by)
                                   VALUES ({marks}, ?, ?, ?)""",
                               [c[k] for k in _ITEM_FIELDS] + [int(is_demo), utcnow(), actor.user_id])
            item_id = cur.lastrowid
            audit.log(conn, actor, "expiry_item.create", "expiry_item", item_id, c["department_id"],
                      name=c["name"], expiry_date=c["expiry_date"])
    return item_id


def record_action(conn, actor, item_id, action, note=None, evidence=None):
    """Record an expiry check or action. Staff may act on items in their own
    department; the action and who did it are always kept."""
    it = row(conn, _ITEM_SELECT + " WHERE i.id=?", (item_id,))
    if not it:
        raise ValidationError("Item not found.")
    require(actor, "expiry.record_action", it["department_id"])
    if action not in ACTIONS:
        raise ValidationError("Choose an action.")
    note = clean_text(note, "Note", 2000)
    if action in ("disposed", "removed", "escalated", "action_required") and not note:
        raise ValidationError("Add a short note (e.g. quantity disposed, reason, who was informed).")
    if it["requires_evidence"] and action in ("disposed", "removed") and not evidence:
        raise ValidationError("This category requires photo evidence for removal or disposal.")
    _decorate(conn, [it])
    if action == "checked_ok" and it["status"] == "expired":
        raise ValidationError("This item is past its expiry date. Remove or dispose of it, or escalate.")
    new_state = {"removed": "removed", "disposed": "disposed", "action_required": "action_required",
                 "escalated": "action_required"}.get(action, it["state"])
    if action == "replaced":
        new_state = "removed"
    now = utcnow()
    with transaction(conn):
        ev_id = store_evidence(conn, actor, evidence[0], evidence[1]) if evidence else None
        cur = conn.execute("""INSERT INTO hp_expiry_actions(item_id, action, note, evidence_id, performed_by,
                              performed_at) VALUES (?,?,?,?,?,?)""", (item_id, action, note, ev_id, actor.user_id, now))
        conn.execute("""UPDATE hp_expiry_items SET state=?, last_checked_at=?, last_checked_by=?,
                        updated_at=?, updated_by=? WHERE id=?""", (new_state, now, actor.user_id, now,
                                                                   actor.user_id, item_id))
        audit.log(conn, actor, f"expiry.{action}", "expiry_item", item_id, it["department_id"],
                  status_before=it["status"], state_after=new_state, note=note)
        if action == "escalated":
            _insert_ca(conn, actor, "expiry", item_id, it["department_id"], f"Expiry escalation: {it['name']}",
                       note, severity="high" if it["kind"] in ("food", "prepared_food", "beverage") else "medium")
    return {"action_id": cur.lastrowid, "state": new_state, "saved_at": now}
