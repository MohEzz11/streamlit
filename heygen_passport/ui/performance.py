"""Team performance, scoring configuration, corrective actions and reports."""

import pandas as pd
import streamlit as st

from ..services import actions as ca_svc, alerts as al_svc, checklists as ck, expiry as ex
from ..services import scoring as sc, staff as staff_svc, users as users_svc
from . import common as ui


def performance_page():
    a = ui.actor()
    c = ui.conn()
    st.header("Performance")
    ui.flash_show()
    tabs = ["Team traffic lights", "How scores are calculated"]
    if ui.can("score.configure"):
        tabs.append("Scoring configuration")
    t = st.tabs(tabs)
    with t[0]:
        d1, d2 = ui.date_range_picker("tp", 30)
        dept = ui.dept_filter("tp_dept")
        perf = sc.team_performance(c, a, d1, d2, dept)
        colour = st.multiselect("Show", ["green", "amber", "red", "none"], default=["green", "amber", "red", "none"],
                                format_func=lambda k: f"{ui.ICON[k]} {sc.COLOR_LABELS[k]}")
        perf = [p for p in perf if p["color"] in colour]
        frame = pd.DataFrame([{"Traffic light": f"{ui.ICON[p['color']]} {p['color_label']}", "Name": p["full_name"],
                               "Employee ID": p["employee_id"], "Role": p["job_title"], "Score %": p["score"],
                               "Reasons": " | ".join(p["reasons"])} for p in perf])
        if frame.empty:
            st.info("No staff in this view.")
        else:
            st.dataframe(frame, hide_index=True, width="stretch")
            ui.csv_button(frame, f"performance_{d1}_{d2}.csv")
        for p in perf:
            if st.button(f"Open {p['full_name']}", key=f"perf_open_{p['staff_id']}"):
                st.session_state["view_staff_id"] = p["staff_id"]
                st.switch_page(st.session_state["hp_pages"]["staff"])
    with t[1]:
        st.markdown(sc.__doc__.split("How a staff member's score is calculated (also shown in the interface):")[1])
        g, am, scale = sc.thresholds(c)
        st.info(f"Current settings: scale 0-{scale:g}; Green ≥ {g:g}%; Amber ≥ {am:g}%; Red below {am:g}%.")
        crit = sc.criteria(c)
        st.dataframe(ui.df(crit, ["name", "source", "category", "weight", "department", "description"]),
                     hide_index=True, width="stretch")
    if ui.can("score.configure"):
        with t[2]:
            config_tab()


def config_tab():
    a = ui.actor()
    c = ui.conn()
    g, am, scale = sc.thresholds(c)
    with st.form("thresholds"):
        c1, c2, c3 = st.columns(3)
        ng = c1.number_input("Green threshold %", 1.0, 100.0, g)
        na = c2.number_input("Amber threshold %", 0.0, 99.0, am)
        ns = c3.number_input("Score scale maximum", 1.0, 100.0, scale)
        if st.form_submit_button("Save thresholds"):
            ui.save(sc.save_thresholds, c, a, ng, na, ns, success="Thresholds saved.")
    depts = ui.svc.departments(c)
    for cr in sc.criteria(c, active_only=False) + [None]:
        d = cr or {}
        label = "➕ New criterion" if cr is None else f"{cr['name']} · weight {cr['weight']:g} · {cr['source']}" + (
            "" if cr["active"] else " [inactive]")
        with st.expander(label):
            with st.form(f"crit_{d.get('id', 'new')}"):
                name = st.text_input("Name", d.get("name", ""))
                desc = st.text_area("Description", d.get("description") or "")
                srcs = list(sc.SOURCES)
                src = st.selectbox("Source", srcs, index=srcs.index(d.get("source", "manual")), format_func=sc.SOURCES.get)
                cats = list(sc.CATEGORIES)
                cat = st.selectbox("Category", cats, index=cats.index(d.get("category", "observation")))
                w = st.number_input("Weight", 0.0, 100.0, float(d.get("weight", 10)))
                opts = [None] + depts
                di = next((i for i, x in enumerate(opts) if x and x["id"] == d.get("department_id")), 0)
                dept = st.selectbox("Applies to", opts, index=di, format_func=lambda x: "All departments" if x is None else x["name"])
                active = st.checkbox("Active", bool(d.get("active", 1)))
                if st.form_submit_button("Save criterion"):
                    ui.save(sc.save_criterion, c, a, {"name": name, "description": desc, "source": src, "category": cat,
                                                      "weight": w, "department_id": dept["id"] if dept else None,
                                                      "active": active}, criterion_id=d.get("id"),
                            success="Criterion saved.")


def actions_page():
    a = ui.actor()
    c = ui.conn()
    st.header("Corrective actions")
    ui.flash_show()
    c1, c2 = st.columns(2)
    with c1:
        dept = ui.dept_filter("ca_dept") if a.role != "staff" else None
    status = c2.selectbox("Status", [None] + list(ca_svc.CA_STATUSES), format_func=lambda s: "All" if s is None else s.title(),
                          key="ca_status")
    cas = ca_svc.list_corrective_actions(c, a, status=status, department_id=dept)
    ui.csv_button(ui.df(cas), "corrective_actions.csv")
    if not cas:
        st.info("No corrective actions match.")
    for ca in cas:
        flag = " · ⚠️ OVERDUE" if ca["is_overdue"] else ""
        with st.expander(f"#{ca['id']} {ca['title']} · {ca['severity']} · {ca['status']}{flag}"):
            ui.badge(ca["status"])
            st.write(ca["description"] or "")
            st.caption(f"Source: {ca['source_type']} {ca['source_id'] or ''} · Department: {ca['department'] or '-'} · "
                       f"Staff: {ca['staff_name'] or '-'} · Raised by {ca['created_by_name'] or 'system'} at "
                       f"{ui.fmt(ca['created_at'])} · Owner: {ca['owner'] or 'unassigned'} · Due: {ca['due_date'] or '-'}")
            if ca["resolved_at"]:
                st.success(f"Resolved by {ca['resolved_by_name']} at {ui.fmt(ca['resolved_at'])}: {ca['resolution']}")
            if ca["source_type"] == "duty" and ca["source_id"]:
                d = ck.get_duty(c, a, ca["source_id"]) if ui.can("duty.view_dept", ca["department_id"]) else None
                if d:
                    st.caption(f"Duty: {d['title']} on {d['duty_date']} - recorded {d['response_value'] or '-'} "
                               f"{d['unit'] or ''} by {d['completed_by_name'] or d['completed_by_username']}")
                    ui.show_evidence(d["evidence_id"], caption=f"Duty {d['id']} evidence")
            manager_ok = ui.can("ca.manage", ca["department_id"])
            if ca["status"] in ("open", "in_progress") and (manager_ok or ca["owner_user_id"] == a.user_id):
                with st.form(f"ca_{ca['id']}"):
                    owner = None
                    due = None
                    if manager_ok:
                        owners = [None] + users_svc.users_for_assignment(c, ca["department_id"])
                        oi = next((i for i, o in enumerate(owners) if o and o["id"] == ca["owner_user_id"]), 0)
                        owner = st.selectbox("Owner", owners, index=oi,
                                             format_func=lambda o: "Unassigned" if o is None else f"{o['username']} ({o['role']})")
                        due = st.date_input("Due date", pd.to_datetime(ca["due_date"]).date() if ca["due_date"] else None)
                    sts = ["open", "in_progress", "resolved"] + (["cancelled"] if manager_ok else [])
                    new_status = st.selectbox("Status", sts, index=sts.index(ca["status"]))
                    res = st.text_area("Resolution / progress note (required to resolve)", ca["resolution"] or "")
                    if st.form_submit_button("Save", type="primary"):
                        ui.save(ca_svc.update_corrective_action, c, a, ca["id"],
                                owner_user_id=owner["id"] if owner else None,
                                due_date=due if manager_ok else None, status=new_status, resolution=res,
                                set_owner=manager_ok, success="Corrective action updated.")
            hist = ui.svc.entity_history(c, a, "corrective_action", ca["id"])
            if hist:
                st.caption("History: " + " → ".join(f"{h['action'].split('.')[-1]} by {h['username']} "
                                                     f"({ui.fmt(h['at'])})" for h in hist))
    if ui.can("ca.manage"):
        st.divider()
        with st.expander("➕ Raise a corrective action"):
            depts = ui.svc.visible_departments(c, a)
            dsel = st.selectbox("Department", depts, format_func=lambda d: d["name"], key="newca_dept")
            with st.form("new_ca"):
                title = st.text_input("Title")
                desc = st.text_area("Description")
                sev = st.selectbox("Severity", ca_svc.SEVERITIES, index=1)
                people = [None] + staff_svc.staff_options(c, a, dsel["id"])
                person = st.selectbox("Staff member concerned (only if responsibility is recorded)", people,
                                      format_func=lambda p: "-" if p is None else p["full_name"])
                owners = [None] + users_svc.users_for_assignment(c, dsel["id"])
                owner = st.selectbox("Owner", owners, format_func=lambda o: "Unassigned" if o is None else o["username"])
                due = st.date_input("Due date", None)
                if st.form_submit_button("Raise", type="primary"):
                    ui.save(ca_svc.create_corrective_action, c, a, dsel["id"], title, desc, sev,
                            person["id"] if person else None, owner["id"] if owner else None, due,
                            success="Corrective action raised.")


REPORTS = {
    "duties": "Duty completion and verification",
    "exceptions": "Exceptions and failed readings",
    "expiry": "Expiry items (incl. closed)",
    "certifications": "Certifications",
    "performance": "Performance traffic lights",
    "actions": "Corrective actions",
    "alerts": "Alerts (incl. acknowledged)",
}


def reports_page():
    a = ui.actor()
    c = ui.conn()
    st.header("Reports")
    st.caption("Reports support the hotel's food-safety management system. They do not certify compliance with "
               "Dubai Municipality requirements or replace the HACCP plan, training or official inspections.")
    kind = st.selectbox("Report", list(REPORTS), format_func=REPORTS.get)
    d1, d2 = ui.date_range_picker("rep", 7)
    dept = ui.dept_filter("rep_dept")
    if kind in ("duties", "exceptions"):
        data = ck.dept_duties(c, a, d1, dept, date_to=d2)
        if kind == "exceptions":
            data = [d for d in data if d["status"] == "exception" or d["response_ok"] == 0]
        frame = ui.df(data, ["duty_date", "department", "outlet", "title", "risk_level", "assignee", "effective_status",
                             "response_value", "unit", "min_value", "max_value", "exception_details", "completed_by_name",
                             "completed_at", "verification_status", "verified_by_name", "verified_at",
                             "reg_source_title", "reg_source_version", "reg_clause"])
    elif kind == "expiry":
        data = ex.list_items(c, a, dept, include_closed=True)
        frame = ui.df(data, ["status_label", "name", "category", "department", "location", "batch_lot", "quantity", "unit",
                             "date_type", "expiry_date", "opened_on", "prepared_on", "effective_expiry", "responsible",
                             "last_checked_at"])
    elif kind == "certifications":
        frame = ui.df(staff_svc.certifications(c, a, department_id=dept),
                      ["full_name", "employee_id", "department", "name", "issuer", "issue_date", "expiry_date", "status"])
    elif kind == "performance":
        perf = sc.team_performance(c, a, d1, d2, dept)
        frame = pd.DataFrame([{"name": p["full_name"], "employee_id": p["employee_id"], "score_pct": p["score"],
                               "traffic_light": p["color_label"], "reasons": " | ".join(p["reasons"])} for p in perf])
    elif kind == "actions":
        data = [x for x in ca_svc.list_corrective_actions(c, a, department_id=dept)
                if str(d1) <= x["created_at"][:10] <= str(d2)]
        frame = ui.df(data, ["id", "created_at", "department", "source_type", "title", "severity", "staff_name", "owner",
                             "due_date", "status", "resolution", "resolved_by_name", "resolved_at"])
    else:
        data = [x for x in al_svc.list_alerts(c, a, open_only=False, department_id=dept, limit=5000)
                if str(d1) <= x["created_at"][:10] <= str(d2)]
        frame = ui.df(data, ["created_at", "alert_type", "severity", "department", "message", "acknowledged_at"])
    st.caption(f"{len(frame)} row(s)")
    st.dataframe(frame, hide_index=True, width="stretch")
    ui.csv_button(frame, f"heygen_{kind}_{d1}_{d2}.csv")
