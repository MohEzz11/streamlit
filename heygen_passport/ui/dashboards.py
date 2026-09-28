"""Role home screens: staff, supervisor and manager dashboards."""

import pandas as pd
import streamlit as st

from ..services import actions as ca_svc, alerts as al_svc, checklists as ck, expiry as ex_svc
from ..services import scoring as sc_svc, staff as staff_svc
from . import common as ui
from .duties import duty_card


def _scan_alerts():
    # Raise new alerts at most once a minute per session.
    import time
    last = st.session_state.get("hp_last_scan", 0)
    if time.time() - last > 60:
        ck.generate_duties(ui.conn())
        al_svc.scan(ui.conn())
        st.session_state["hp_last_scan"] = time.time()


def staff_home():
    a = ui.actor()
    c = ui.conn()
    _scan_alerts()
    today = ui.svc.today_local(c)
    st.header("My duties today")
    st.caption(f"{today.strftime('%A %d %B %Y')} · hotel time {ui.svc.now_local(c).strftime('%H:%M')}")
    ui.flash_show()
    if not a.staff_id:
        st.info("Your account is not linked to a staff profile, so no personal duties are shown.")
        return
    duties = ck.my_duties(c, a)
    backlog = ck.my_overdue_backlog(c, a)
    open_d = [d for d in duties if d["effective_status"] in ("not_started", "in_progress", "overdue")]
    overdue = [d for d in duties if d["effective_status"] == "overdue"]
    m = st.columns(3)
    m[0].metric("To do", len(open_d))
    m[1].metric("Overdue", len(overdue) + len(backlog))
    m[2].metric("Done", len(duties) - len(open_d))
    if backlog:
        st.subheader("⚠️ Overdue from previous days")
        for d in backlog:
            duty_card(d, "backlog")
    if not duties:
        st.info("No duties assigned to you today.")
    else:
        st.subheader("Today")
        for d in duties:
            duty_card(d, "mine", expanded=(d["effective_status"] == "overdue" and d is duties[0]))
    st.divider()
    st.subheader("Expiry reminders")
    items = ex_svc.list_items(c, a, status=["expired", "expiring_soon", "action_required"])
    mine = [i for i in items if i["responsible_staff_id"] == a.staff_id] or items
    if not mine:
        st.success("No items expiring soon in your department.")
    for i in mine[:15]:
        cols = st.columns([3, 2])
        cols[0].write(f"**{i['name']}** · {i['location'] or ''} · expires {i['effective_expiry']}")
        with cols[1]:
            ui.badge(i["status"])
    if items:
        st.page_link(st.session_state["hp_pages"]["expiry"], label="Record an expiry action →")
    my_alerts = [x for x in al_svc.list_alerts(c, a) if x["staff_id"] == a.staff_id and x["alert_type"].startswith("cert")]
    for x in my_alerts:
        st.warning(x["message"])


def _alerts_panel(dept=None, limit=15):
    a = ui.actor()
    c = ui.conn()
    alerts = al_svc.list_alerts(c, a, department_id=dept)
    st.subheader(f"Open alerts ({len(alerts)})")
    if not alerts:
        st.success("No open alerts.")
    for x in alerts[:limit]:
        cols = st.columns([5, 1])
        cols[0].write(f"{'🔴' if x['severity'] == 'high' else '🟠'} **{al_svc.ALERT_TYPES.get(x['alert_type'], x['alert_type'])}** "
                      f"- {x['message']}  \n<span class='hp-meta'>{ui.esc(x['department'])} · raised {ui.esc(ui.fmt(x['created_at']))}</span>",
                      unsafe_allow_html=True)
        if ui.can("alerts.ack", x["department_id"]) and cols[1].button("Acknowledge", key=f"ack_{x['id']}"):
            ui.save(al_svc.acknowledge, c, a, x["id"], success="Alert acknowledged.")
    if len(alerts) > limit:
        st.caption(f"{len(alerts) - limit} more alert(s) - see Reports > Alerts.")


def supervisor_dashboard():
    a = ui.actor()
    c = ui.conn()
    _scan_alerts()
    today = ui.svc.today_local(c)
    st.header("Supervisor dashboard")
    ui.flash_show()
    dept = ui.dept_filter("sup_dept")
    summary = ck.completion_summary(c, a, today, department_id=dept)
    for name, s in summary.items():
        st.subheader(name)
        m = st.columns(5)
        m[0].metric("Completion", f"{s['completion_pct'] or 0:.0f}%", help=f"{s['completed'] + s['exception']} of {s['total']} recorded")
        m[1].metric("Overdue", s["overdue"], help=f"{s['critical_overdue']} high/critical risk")
        m[2].metric("Exceptions", s["exception"])
        m[3].metric("Awaiting verification", s["awaiting_verification"])
        m[4].metric("Not started", s["not_started"])
    if not summary:
        st.info("No duties today yet. Set up assignments under Checklists.")
    t1, t2, t3, t4 = st.tabs(["Awaiting verification", "Overdue & exceptions", "Expiry alerts", "Corrective actions"])
    with t1:
        pend = ck.dept_duties(c, a, today - pd.Timedelta(days=7), dept, date_to=today, awaiting_verification=True)
        if not pend:
            st.success("Nothing awaiting verification.")
        for d in pend:
            duty_card(d, "sv_verify", allow_complete=False, allow_verify=True)
    with t2:
        duties = [d for d in ck.dept_duties(c, a, today, dept) if d["effective_status"] in ("overdue", "exception")]
        if not duties:
            st.success("No overdue duties or exceptions today.")
        for d in duties:
            duty_card(d, "sv_over", allow_complete=True, allow_verify=True)
    with t3:
        items = ex_svc.list_items(c, a, department_id=dept, status=["expired", "expiring_soon", "action_required"])
        frame = ui.df(items, ["status_label", "name", "category", "department", "location", "batch_lot",
                              "effective_expiry", "days_left", "responsible"],
                      {"status_label": "Status", "effective_expiry": "Effective expiry", "days_left": "Days left"})
        st.dataframe(frame, hide_index=True, width="stretch") if not frame.empty else st.success("No expiry alerts.")
        certs = staff_svc.certifications(c, a, department_id=dept)
        certs = [x for x in certs if x["status"] in ("expired", "expiring_soon")]
        if certs:
            st.write("**Certifications expiring / expired**")
            st.dataframe(ui.df(certs, ["full_name", "name", "expiry_date", "status"]), hide_index=True,
                         width="stretch")
    with t4:
        cas = ca_svc.list_corrective_actions(c, a, department_id=dept, open_only=True)
        st.dataframe(ui.df(cas, ["id", "severity", "title", "department", "owner", "due_date", "status", "is_overdue"]),
                     hide_index=True, width="stretch") if cas else st.success("No open corrective actions.")
        st.page_link(st.session_state["hp_pages"]["actions"], label="Manage corrective actions →")
    st.divider()
    _alerts_panel(dept)


def manager_dashboard():
    a = ui.actor()
    c = ui.conn()
    _scan_alerts()
    today = ui.svc.today_local(c)
    st.header("Manager dashboard")
    ui.flash_show()
    st.subheader("Today across departments")
    summary = ck.completion_summary(c, a, today)
    if summary:
        rows = [{"Department": k, "Completion %": v["completion_pct"], "Recorded": v["completed"] + v["exception"],
                 "Total": v["total"], "Overdue": v["overdue"], "High/critical overdue": v["critical_overdue"],
                 "Exceptions": v["exception"], "Awaiting verification": v["awaiting_verification"]}
                for k, v in summary.items()]
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    else:
        st.info("No duties today yet.")
    st.subheader("Performance traffic lights")
    d1, d2 = ui.date_range_picker("mgr_perf", 30)
    dept = ui.dept_filter("mgr_dept")
    perf = sc_svc.team_performance(c, a, d1, d2, dept)
    counts = {k: sum(1 for p in perf if p["color"] == k) for k in ("green", "amber", "red", "none")}
    m = st.columns(4)
    m[0].metric("🟢 Green (meeting target)", counts["green"])
    m[1].metric("🟠 Amber (needs attention)", counts["amber"])
    m[2].metric("🔴 Red (below target / urgent)", counts["red"])
    m[3].metric("⚪ No data", counts["none"])
    frame = pd.DataFrame([{"Status": f"{ui.ICON[p['color']]} {p['color_label']}", "Name": p["full_name"],
                           "Role": p["job_title"], "Score %": p["score"], "Reasons": " | ".join(p["reasons"])}
                          for p in sorted(perf, key=lambda p: (p["score"] is None, p["score"] or 0))])
    if not frame.empty:
        st.dataframe(frame, hide_index=True, width="stretch")
    daily = ck.dept_duties(c, a, d1, dept, date_to=d2)
    if daily:
        dd = pd.DataFrame(daily)
        dd["recorded"] = dd["status"].isin(["completed", "exception"])
        tr = dd.groupby(["duty_date", "department"])["recorded"].mean().mul(100).round(1).unstack()
        st.write("**Duty completion % by day**")
        st.line_chart(tr)
    t1, t2, t3 = st.tabs(["Expiring certifications", "Expiring / expired items", "Unresolved corrective actions"])
    with t1:
        certs = [x for x in staff_svc.certifications(c, a, department_id=dept) if x["status"] in ("expired", "expiring_soon")]
        st.dataframe(ui.df(certs, ["status", "full_name", "department", "name", "expiry_date"]), hide_index=True,
                     width="stretch") if certs else st.success("All certifications in date.")
    with t2:
        items = ex_svc.list_items(c, a, department_id=dept, status=["expired", "expiring_soon", "action_required"])
        st.dataframe(ui.df(items, ["status_label", "name", "department", "location", "effective_expiry", "days_left",
                                   "responsible"]), hide_index=True, width="stretch") if items else st.success("Nothing expiring.")
    with t3:
        cas = ca_svc.list_corrective_actions(c, a, department_id=dept, open_only=True)
        st.dataframe(ui.df(cas, ["id", "severity", "title", "department", "staff_name", "owner", "due_date",
                                 "is_overdue", "created_at"]), hide_index=True, width="stretch") \
            if cas else st.success("No unresolved corrective actions.")
    st.divider()
    _alerts_panel(dept)
