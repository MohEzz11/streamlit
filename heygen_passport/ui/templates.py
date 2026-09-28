"""Checklist templates, items, assignments (schedules) and regulatory references."""

import datetime as dt

import streamlit as st

from ..services import checklists as ck, regsources as rs, staff as staff_svc
from . import common as ui

DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def page():
    st.header("Checklists and assignments")
    ui.flash_show()
    st.caption("Starter templates are examples only. Confirm every limit and instruction against the hotel's "
               "HACCP plan, approved procedures and current Dubai Municipality guidance.")
    t1, t2, t3 = st.tabs(["Templates", "Assignments", "Regulatory references"])
    with t1:
        templates_tab()
    with t2:
        schedules_tab()
    with t3:
        references_tab()


def templates_tab():
    a = ui.actor()
    c = ui.conn()
    dept = ui.dept_filter("tpl_dept")
    show_inactive = st.toggle("Show inactive", key="tpl_inactive")
    tpls = ck.list_templates(c, a, dept, include_inactive=show_inactive)
    with st.expander("➕ New template"):
        with st.form("new_tpl"):
            depts = ui.svc.visible_departments(c, a)
            d = st.selectbox("Department", depts, format_func=lambda x: x["name"])
            name = st.text_input("Template name")
            desc = st.text_area("Description")
            if st.form_submit_button("Create template", type="primary"):
                ui.save(ck.save_template, c, a, d["id"] if d else None, name, desc, success="Template created.")
    if not tpls:
        st.info("No templates yet.")
        return
    pick = st.selectbox("Template", tpls, format_func=lambda t: f"{t['department']} - {t['name']} "
                        f"({t['item_count']} items){'' if t['active'] else ' [inactive]'}", key="tpl_pick")
    t = ck.get_template(c, a, pick["id"])
    with st.form(f"edit_tpl_{t['id']}"):
        name = st.text_input("Name", t["name"])
        desc = st.text_area("Description", t["description"] or "")
        active = st.checkbox("Active", bool(t["active"]))
        if st.form_submit_button("Save template"):
            ui.save(ck.save_template, c, a, t["department_id"], name, desc, template_id=t["id"], active=active,
                    success="Template saved.")
    st.subheader("Items")
    sources = rs.list_sources(c, a)
    for it in t["items"]:
        label = f"{'' if it['active'] else '[inactive] '}{it['title']} · {ck.RESPONSE_TYPES[it['response_type']]}" \
                f" · due {it['due_time'] or 'end of day'} · risk {it['risk_level']}"
        with st.expander(label):
            item_form(t, it, sources)
    with st.expander("➕ Add item"):
        item_form(t, None, sources)


def item_form(t, it, sources):
    a = ui.actor()
    c = ui.conn()
    it = it or {}
    k = f"item_{t['id']}_{it.get('id', 'new')}"
    with st.form(k):
        title = st.text_input("Title", it.get("title", ""))
        instr = st.text_area("Instructions", it.get("instructions") or "")
        rts = list(ck.RESPONSE_TYPES)
        rt = st.selectbox("Response type", rts, index=rts.index(it.get("response_type", "yes_no")),
                          format_func=ck.RESPONSE_TYPES.get)
        st.caption("For Yes/No items, phrase the question so that 'Yes' means compliant. "
                   "'No', 'Fail' or an out-of-range reading raises an exception.")
        c1, c2, c3 = st.columns(3)
        mn = c1.number_input("Min acceptable", value=it.get("min_value"), key=f"{k}_mn")
        mx = c2.number_input("Max acceptable", value=it.get("max_value"), key=f"{k}_mx")
        unit = c3.text_input("Unit", it.get("unit") or "")
        c4, c5, c6 = st.columns(3)
        prio = c4.selectbox("Priority", ck.PRIORITIES, index=ck.PRIORITIES.index(it.get("priority", "medium")))
        risk = c5.selectbox("Food-safety risk", ck.RISK_LEVELS, index=ck.RISK_LEVELS.index(it.get("risk_level", "low")))
        verify = c6.checkbox("Supervisor verification", bool(it.get("requires_verification")))
        c7, c8, c9 = st.columns(3)
        due = c7.text_input("Due time (HH:MM, blank = end of day)", it.get("due_time") or "")
        win = c8.number_input("Completion window (minutes before due)", 0, 1440, int(it.get("window_minutes", 60)))
        order = c9.number_input("Sort order", 0, 999, int(it.get("sort_order", 0)))
        src_opts = [None] + sources
        cur = next((i for i, s in enumerate(src_opts) if s and s["id"] == it.get("reg_source_id")), 0)
        src = st.selectbox("Regulatory / procedure reference", src_opts, index=cur,
                           format_func=lambda s: "None" if s is None else f"{s['title']} (v. {s['version'] or '?'})")
        clause = st.text_input("Clause / section", it.get("reg_clause") or "")
        active = st.checkbox("Active", bool(it.get("active", 1)))
        if st.form_submit_button("Save item", type="primary"):
            ui.save(ck.save_template_item, c, a, t["id"], {
                "title": title, "instructions": instr, "response_type": rt, "min_value": mn, "max_value": mx,
                "unit": unit, "priority": prio, "risk_level": risk, "requires_verification": verify, "due_time": due,
                "window_minutes": win, "sort_order": order, "reg_source_id": src["id"] if src else None,
                "reg_clause": clause, "active": active}, item_id=it.get("id"), success="Checklist item saved.")
    st.caption("Changes apply to duties generated after saving; already generated duties keep their snapshot.")


def schedules_tab():
    a = ui.actor()
    c = ui.conn()
    dept = ui.dept_filter("sch_dept")
    scheds = ck.list_schedules(c, a, dept, include_inactive=st.toggle("Show inactive", key="sch_inactive"))
    st.caption("An assignment applies a template to a department, optional outlet, role (job title), shift and "
               "dates. Assign a named person to make them personally responsible; leave it unassigned for any "
               "matching team member on shift (unassigned duties never count against an individual's score).")
    for s in scheds:
        days = ", ".join(DAYS[int(x)] for x in s["days_of_week"].split(","))
        with st.expander(f"{'' if s['active'] else '[inactive] '}{s['template']} · {s['department']} · "
                         f"{s['assignee'] or 'unassigned pool'} · {s['shift']} · {days}"):
            schedule_form(s)
    with st.expander("➕ New assignment"):
        schedule_form(None)


def schedule_form(s):
    a = ui.actor()
    c = ui.conn()
    s = s or {}
    k = f"sch_{s.get('id', 'new')}"
    tpls = ck.list_templates(c, a)
    if not tpls:
        st.info("Create a template first.")
        return
    ti = next((i for i, t in enumerate(tpls) if t["id"] == s.get("template_id")), 0)
    tpl = st.selectbox("Template", tpls, index=ti, format_func=lambda t: f"{t['department']} - {t['name']}",
                       key=f"{k}_tpl")
    with st.form(k):
        outs = [None] + ui.svc.outlets(c, tpl["department_id"])
        oi = next((i for i, o in enumerate(outs) if o and o["id"] == s.get("outlet_id")), 0)
        outlet = st.selectbox("Outlet / work area", outs, index=oi, format_func=lambda o: "All" if o is None else o["name"])
        titles = [None] + staff_svc.job_titles(c, tpl["department_id"])
        ji = titles.index(s.get("job_title")) if s.get("job_title") in titles else 0
        job = st.selectbox("Role (job title)", titles, index=ji, format_func=lambda j: "Any role" if j is None else j)
        shift = st.selectbox("Shift", ck.SHIFTS, index=ck.SHIFTS.index(s.get("shift", "any")))
        people = [None] + staff_svc.staff_options(c, a, tpl["department_id"])
        pi = next((i for i, p in enumerate(people) if p and p["id"] == s.get("assigned_staff_id")), 0)
        who = st.selectbox("Responsible person", people, index=pi,
                           format_func=lambda p: "Unassigned (anyone matching on shift)" if p is None
                           else f"{p['full_name']} ({p['employee_id']})")
        c1, c2 = st.columns(2)
        start = c1.date_input("Start date", dt.date.fromisoformat(s["start_date"]) if s.get("start_date")
                              else ui.svc.today_local(c))
        end = c2.date_input("End date (optional)", dt.date.fromisoformat(s["end_date"]) if s.get("end_date") else None)
        cur_days = [int(x) for x in s.get("days_of_week", "0,1,2,3,4,5,6").split(",")]
        days = st.multiselect("Days", list(range(7)), default=cur_days, format_func=lambda i: DAYS[i])
        active = st.checkbox("Active", bool(s.get("active", 1)))
        if st.form_submit_button("Save assignment", type="primary"):
            ui.save(ck.save_schedule, c, a, {
                "template_id": tpl["id"], "outlet_id": outlet["id"] if outlet else None, "job_title": job,
                "shift": shift, "assigned_staff_id": who["id"] if who else None, "start_date": start,
                "end_date": end, "days_of_week": days, "active": active}, schedule_id=s.get("id"),
                success="Assignment saved. Use 'Generate duties' on the Duties page to apply it today.")


def references_tab():
    a = ui.actor()
    c = ui.conn()
    st.caption("Each checklist item can trace to a source document, version and review date. Update these when "
               "official Dubai Municipality guidance or hotel procedures change. This application does not certify "
               "compliance and does not replace the HACCP plan, training or official inspections.")
    for r in rs.list_sources(c, a, include_inactive=True):
        flag = " ⚠️ review overdue" if r["review_overdue"] else ""
        with st.expander(f"{r['title']} · v. {r['version'] or '?'} · review {r['review_date'] or '-'}{flag} · "
                         f"{r['linked_items']} linked items"):
            if r["url"]:
                st.link_button("Open source", r["url"])
            if ui.can("regsource.manage"):
                source_form(r)
            else:
                st.write(r["notes"] or "")
    if ui.can("regsource.manage"):
        with st.expander("➕ Add reference"):
            source_form(None)


def source_form(r):
    a = ui.actor()
    c = ui.conn()
    r = r or {}
    with st.form(f"src_{r.get('id', 'new')}"):
        title = st.text_input("Title", r.get("title", ""))
        auth = st.text_input("Authority / owner", r.get("authority", "Dubai Municipality"))
        c1, c2 = st.columns(2)
        ref = c1.text_input("Document reference / code", r.get("document_ref") or "")
        ver = c2.text_input("Version", r.get("version") or "")
        url = st.text_input("URL", r.get("url") or "")
        rev = st.date_input("Next review date", dt.date.fromisoformat(r["review_date"]) if r.get("review_date") else None)
        notes = st.text_area("Notes", r.get("notes") or "")
        active = st.checkbox("Active", bool(r.get("active", 1)))
        if st.form_submit_button("Save reference"):
            ui.save(rs.save_source, c, a, {"title": title, "authority": auth, "document_ref": ref, "version": ver,
                                           "url": url, "review_date": rev, "notes": notes, "active": active},
                    source_id=r.get("id"), success="Reference saved.")
