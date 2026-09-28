"""Expiry item tracking, actions and category configuration."""

import datetime as dt

import streamlit as st

from ..services import expiry as ex, staff as staff_svc
from . import common as ui


def page():
    a = ui.actor()
    st.header("Expiry tracking")
    ui.flash_show()
    st.caption("Follow the hotel's approved food-safety procedures. Each category has its own reminder period and "
               "optional shelf-life rule after opening or preparation; the earliest date applies.")
    tabs = ["Items"]
    if ui.can("expiry.manage_items"):
        tabs.append("Add item")
    if ui.can("expiry.configure"):
        tabs.append("Categories and reminders")
    t = st.tabs(tabs)
    with t[0]:
        items_tab()
    if "Add item" in tabs:
        with t[1]:
            item_form(None)
    if "Categories and reminders" in tabs:
        with t[-1]:
            categories_tab()


def items_tab():
    a = ui.actor()
    c = ui.conn()
    c1, c2, c3 = st.columns(3)
    with c1:
        dept = ui.dept_filter("ex_dept")
    status = c2.selectbox("Status", [None, "expired", "expiring_soon", "action_required", "ok", "removed", "disposed"],
                          format_func=lambda s: "All open" if s is None else ex.STATUS_LABELS[s], key="ex_status")
    q = c3.text_input("Search name / batch / location", key="ex_q")
    items = ex.list_items(c, a, dept, status, q=q or None, include_closed=status in ("removed", "disposed"))
    frame = ui.df(items, ["status_label", "name", "category", "department", "location", "batch_lot", "quantity", "unit",
                          "date_type", "expiry_date", "opened_on", "prepared_on", "effective_expiry", "days_left",
                          "responsible"])
    ui.csv_button(frame, "expiry_items.csv")
    if not items:
        st.info("No items match.")
    for it in items[:100]:
        head = f"{it['name']} · {it['location'] or '-'} · effective expiry {it['effective_expiry']} · {it['status_label']}"
        with st.expander(head):
            ui.badge(it["status"])
            st.write(f"**Category:** {it['category']} · **Department:** {it['department']} · "
                     f"**Batch/lot:** {it['batch_lot'] or '-'} · **Qty:** {it['quantity'] if it['quantity'] is not None else '-'} {it['unit'] or ''}")
            st.write(f"**{ex.DATE_TYPES[it['date_type']]}:** {it['expiry_date']}"
                     + (f" · **Opened:** {it['opened_on']}" if it["opened_on"] else "")
                     + (f" · **Prepared:** {it['prepared_on']}" if it["prepared_on"] else "")
                     + f" · **Responsible:** {it['responsible'] or '-'}")
            if it["procedure_note"]:
                st.caption(it["procedure_note"])
            action_form(it)
            detail = ex.get_item(c, a, it["id"])
            if detail["actions"]:
                st.write("**History**")
                for h in detail["actions"]:
                    st.caption(f"{ui.fmt(h['performed_at'])} · {h['performed_by_name']} · "
                               f"{ex.ACTIONS[h['action']]}" + (f" - {h['note']}" if h["note"] else ""))
                    ui.show_evidence(h["evidence_id"], caption=f"Action {h['id']}")
            if ui.can("expiry.manage_items", it["department_id"]):
                with st.popover("Edit item details"):
                    item_form(it)


def action_form(it):
    a = ui.actor()
    c = ui.conn()
    if it["state"] in ("removed", "disposed"):
        return
    with st.form(f"exa_{it['id']}"):
        opts = [k for k in ex.ACTIONS if not (k == "checked_ok" and it["status"] == "expired")]
        act = st.selectbox("Action taken", opts, format_func=ex.ACTIONS.get)
        note = st.text_input("Note (required for removal, disposal and escalation)")
        ev = st.file_uploader("Photo / evidence" + (" (required for removal/disposal)" if it["requires_evidence"] else ""),
                              type=["jpg", "jpeg", "png", "webp", "pdf"], key=f"exf_{it['id']}")
        if st.form_submit_button("Record action", type="primary", width="stretch"):
            ui.save(ex.record_action, c, a, it["id"], act, note, ui.upload_tuple(ev),
                    success=f"'{ex.ACTIONS[act]}' recorded for {it['name']}.")


def item_form(it):
    a = ui.actor()
    c = ui.conn()
    it = it or {}
    k = f"exi_{it.get('id', 'new')}"
    cats = ex.categories(c)
    depts = [d for d in ui.svc.visible_departments(c, a) if ui.can("expiry.manage_items", d["id"])]
    if not cats or not depts:
        st.info("No categories or departments available.")
        return
    di = next((i for i, d in enumerate(depts) if d["id"] == it.get("department_id")), 0)
    dept = st.selectbox("Department", depts, index=di, format_func=lambda d: d["name"], key=f"{k}_dept")
    with st.form(k):
        name = st.text_input("Item name", it.get("name", ""))
        ci = next((i for i, x in enumerate(cats) if x["id"] == it.get("category_id")), 0)
        cat = st.selectbox("Category", cats, index=ci, format_func=lambda x: f"{x['name']} (reminder {x['reminder_days']}d)")
        c1, c2 = st.columns(2)
        loc = c1.text_input("Storage location", it.get("location") or "")
        lot = c2.text_input("Batch / lot", it.get("batch_lot") or "")
        c3, c4 = st.columns(2)
        qty = c3.number_input("Quantity", value=it.get("quantity"), min_value=0.0)
        unit = c4.text_input("Unit", it.get("unit") or "")
        dts = list(ex.DATE_TYPES)
        dtype = st.selectbox("Date type", dts, index=dts.index(it.get("date_type", "use_by")), format_func=ex.DATE_TYPES.get)
        c5, c6, c7 = st.columns(3)
        exp = c5.date_input("Expiry date", dt.date.fromisoformat(it["expiry_date"]) if it.get("expiry_date")
                            else ui.svc.today_local(c))
        opened = c6.date_input("Opened on", dt.date.fromisoformat(it["opened_on"]) if it.get("opened_on") else None)
        prep = c7.date_input("Prepared on", dt.date.fromisoformat(it["prepared_on"]) if it.get("prepared_on") else None)
        people = [None] + staff_svc.staff_options(c, a, dept["id"])
        pi = next((i for i, p in enumerate(people) if p and p["id"] == it.get("responsible_staff_id")), 0)
        resp = st.selectbox("Responsible staff member", people, index=pi,
                            format_func=lambda p: "-" if p is None else f"{p['full_name']} ({p['employee_id']})")
        notes = st.text_area("Notes", it.get("notes") or "")
        if st.form_submit_button("Save item", type="primary"):
            ui.save(ex.save_item, c, a, {
                "name": name, "category_id": cat["id"], "department_id": dept["id"], "location": loc,
                "batch_lot": lot, "quantity": qty, "unit": unit, "date_type": dtype, "expiry_date": exp,
                "opened_on": opened, "prepared_on": prep, "responsible_staff_id": resp["id"] if resp else None,
                "notes": notes}, item_id=it.get("id"), success="Expiry item saved.")


def categories_tab():
    a = ui.actor()
    c = ui.conn()
    for cat in ex.categories(c, active_only=False) + [None]:
        cat_d = cat or {}
        label = "➕ New category" if cat is None else (
            f"{cat['name']} · {cat['kind']} · remind {cat['reminder_days']}d"
            + (f" · {cat['shelf_life_after_open_days']}d after opening" if cat["shelf_life_after_open_days"] else "")
            + (f" · {cat['shelf_life_after_prep_days']}d after prep" if cat["shelf_life_after_prep_days"] else "")
            + ("" if cat["active"] else " [inactive]"))
        with st.expander(label):
            with st.form(f"cat_{cat_d.get('id', 'new')}"):
                name = st.text_input("Name", cat_d.get("name", ""))
                kind = st.selectbox("Type", ex.KINDS, index=ex.KINDS.index(cat_d.get("kind", "food")))
                c1, c2, c3 = st.columns(3)
                rem = c1.number_input("Reminder (days before expiry)", 0, 365, int(cat_d.get("reminder_days", 3)))
                ao = c2.number_input("Shelf life after opening (days, 0 = n/a)", 0, 3650,
                                     int(cat_d.get("shelf_life_after_open_days") or 0))
                ap = c3.number_input("Shelf life after preparation (days, 0 = n/a)", 0, 3650,
                                     int(cat_d.get("shelf_life_after_prep_days") or 0))
                evid = st.checkbox("Require photo evidence for removal/disposal", bool(cat_d.get("requires_evidence")))
                note = st.text_area("Procedure note (shown to staff)", cat_d.get("procedure_note") or "")
                active = st.checkbox("Active", bool(cat_d.get("active", 1)))
                if st.form_submit_button("Save category"):
                    ui.save(ex.save_category, c, a, {
                        "name": name, "kind": kind, "reminder_days": rem, "shelf_life_after_open_days": ao,
                        "shelf_life_after_prep_days": ap, "requires_evidence": evid, "procedure_note": note,
                        "active": active}, category_id=cat_d.get("id"), success="Category saved.")
