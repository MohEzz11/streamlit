"""Duty cards, the completion flow and the department duty board."""

import datetime as dt

import streamlit as st

from ..services import checklists as ck, staff as staff_svc
from . import common as ui


def _header(d):
    due = ui.fmt(d["due_at"], with_date=False) if d["due_at"] else "end of day"
    icon = {"overdue": "🔴", "exception": "🟠", "completed": "✅", "in_progress": "🔵"}.get(d["effective_status"], "⬜")
    return f"{icon} {d['title']}  ·  due {due}  ·  {ui.status_text(d['effective_status'])}"


def _meta(d):
    bits = [d["department"]]
    if d.get("outlet"):
        bits.append(d["outlet"])
    if d.get("shift") and d["shift"] != "any":
        bits.append(f"{d['shift'].title()} shift")
    bits.append(f"Assigned to: {d['assignee'] or 'any team member on shift'}")
    return " · ".join(bits)


def duty_card(d, key_prefix, allow_complete=True, allow_verify=False, expanded=False):
    with st.expander(_header(d), expanded=expanded):
        c1, c2, c3 = st.columns(3)
        with c1:
            ui.badge(d["effective_status"])
        with c2:
            ui.badge(d["risk_level"], f"Food-safety risk: {d['risk_level']}")
        with c3:
            if d["verification_status"]:
                ui.badge(d["verification_status"])
        st.markdown(f'<span class="hp-meta">{ui.esc(_meta(d))}</span>', unsafe_allow_html=True)
        if d["instructions"]:
            st.write(d["instructions"])
        rng = []
        if d["min_value"] is not None:
            rng.append(f"min {d['min_value']:g}")
        if d["max_value"] is not None:
            rng.append(f"max {d['max_value']:g}")
        if rng:
            st.caption(f"Acceptable range: {' / '.join(rng)} {d['unit'] or ''}")
        if d.get("reg_source_title"):
            st.caption(f"Reference: {d['reg_source_title']}"
                       + (f" (v. {d['reg_source_version']})" if d.get("reg_source_version") else "")
                       + (f" - {d['reg_clause']}" if d.get("reg_clause") else ""))
        if d["status"] in ("completed", "exception"):
            unit = (d["unit"] or "") if d["response_type"] == "numeric" else ""
            st.write(f"**Result:** {d['response_value'] or '-'} {unit}")
            who = d["completed_by_name"] or d["completed_by_username"]
            st.caption(f"Recorded by {who} at {ui.fmt(d['completed_at'])}")
            if d["comment"]:
                st.caption(f"Comment: {d['comment']}")
            if d["exception_details"]:
                st.warning(f"Exception: {d['exception_details']}")
            if d["verified_at"]:
                st.caption(f"{ui.status_text(d['verification_status'])} by {d['verified_by_name']} at "
                           f"{ui.fmt(d['verified_at'])}" + (f" - {d['verification_note']}" if d["verification_note"] else ""))
            ui.show_evidence(d["evidence_id"], caption=f"Evidence #{d['id']}")
        if d["verification_status"] == "rejected":
            st.error(f"Rejected by supervisor: {d['verification_note']}. Please redo this check.")
        can_record = d["status"] in ("not_started", "in_progress") or d["verification_status"] == "rejected"
        if allow_complete and can_record:
            completion_form(d, key_prefix)
        if allow_verify and d["verification_status"] == "pending":
            verify_form(d, key_prefix)


def completion_form(d, key_prefix):
    k = f"{key_prefix}_{d['id']}"
    a = ui.actor()
    if d["status"] == "not_started":
        if st.button("Start", key=f"start_{k}"):
            ui.save(ck.start_duty, ui.conn(), a, d["id"], success="Duty started.")
    with st.form(f"form_{k}", clear_on_submit=False):
        rt = d["response_type"]
        value = None
        if rt == "yes_no":
            value = st.radio("Answer", ["yes", "no"], index=None, horizontal=True, key=f"v_{k}",
                             format_func=str.title)
        elif rt == "pass_fail":
            value = st.radio("Result", ["pass", "fail"], index=None, horizontal=True, key=f"v_{k}",
                             format_func=str.title)
        elif rt == "numeric":
            value = st.number_input(f"Reading ({d['unit'] or 'value'})", value=None, step=0.1, format="%.1f",
                                    key=f"v_{k}")
        elif rt == "text":
            value = st.text_area("Response", key=f"v_{k}", max_chars=2000)
        photo = st.file_uploader("Photo / evidence" + (" (required)" if rt == "photo" else " (optional)"),
                                 type=["jpg", "jpeg", "png", "webp", "pdf"], key=f"f_{k}")
        comment = st.text_input("Comment (optional)", key=f"c_{k}", max_chars=2000)
        exc = st.text_area("Exception details - required if the check fails or the reading is out of range: "
                           "what happened and what did you do?", key=f"e_{k}", max_chars=2000)
        raise_exc = st.checkbox("Raise an exception (problem found / could not complete)", key=f"x_{k}")
        if st.form_submit_button("Submit result", type="primary", width="stretch"):
            res = ui.save(ck.complete_duty, ui.conn(), a, d["id"], value=value, comment=comment,
                          evidence=ui.upload_tuple(photo), exception_details=exc, raise_exception=raise_exc,
                          success="Result recorded.", rerun=False)
            if res:
                if res["status"] == "exception":
                    st.session_state["hp_flash"] = ("ok", "⚠️ Exception recorded and a corrective action was "
                                                    "opened for your supervisor. Recorded at "
                                                    + ui.fmt(res["saved_at"], with_date=False) + " (hotel time).")
                st.rerun()


def verify_form(d, key_prefix):
    k = f"{key_prefix}_{d['id']}"
    with st.form(f"verify_{k}"):
        note = st.text_input("Verification note (required to reject)", key=f"vn_{k}")
        c1, c2 = st.columns(2)
        ok = c1.form_submit_button("Verify ✔", type="primary", width="stretch")
        rej = c2.form_submit_button("Reject - redo ✖", width="stretch")
        if ok or rej:
            ui.save(ck.verify_duty, ui.conn(), ui.actor(), d["id"], approve=ok, note=note,
                    success="Verified." if ok else "Rejected; staff asked to redo.")


def duty_board():
    """Department duties: filter by date/status, verify, reassign, add one-off duties."""
    a = ui.actor()
    c = ui.conn()
    st.header("Daily duties")
    ui.flash_show()
    c1, c2, c3 = st.columns(3)
    with c1:
        dept = ui.dept_filter("board_dept")
    day = c2.date_input("Date", ui.svc.today_local(c), key="board_day")
    status = c3.selectbox("Status", [None, "overdue", "not_started", "in_progress", "exception", "completed"],
                          format_func=lambda s: "All" if s is None else ui.status_text(s), key="board_status")
    if st.button("Generate duties for this date from assignments", help="Safe to repeat; never duplicates."):
        n = ui.save(ck.generate_duties, c, day, a, success="Duty list updated.", rerun=False)
        if n is not None:
            st.session_state["hp_flash"] = ("ok", f"✅ {n} new duty instance(s) created.")
            st.rerun()
    duties = ui.guard(ck.dept_duties, c, a, day, dept, status)
    summary = ck.completion_summary(c, a, day, department_id=dept)
    if summary:
        tot = {k: sum(s[k] for s in summary.values()) for k in ("total", "completed", "exception", "overdue",
                                                                 "awaiting_verification")}
        m = st.columns(4)
        m[0].metric("Recorded", f"{tot['completed'] + tot['exception']} / {tot['total']}")
        m[1].metric("Overdue", tot["overdue"])
        m[2].metric("Exceptions", tot["exception"])
        m[3].metric("Awaiting verification", tot["awaiting_verification"])
    if not duties:
        st.info("No duties for this date and filter. Create assignments under Checklists, then generate duties.")
    for d in duties:
        duty_card(d, "board", allow_complete=True, allow_verify=ui.can("duty.verify", d["department_id"]))
        if ui.can("schedule.manage", d["department_id"]) and d["status"] != "completed":
            opts = [None] + staff_svc.staff_options(c, a, d["department_id"])
            with st.popover(f"Reassign #{d['id']}"):
                pick = st.selectbox("Assign to", opts, key=f"as_{d['id']}",
                                    format_func=lambda s: "Anyone on shift (unassigned)" if s is None
                                    else f"{s['full_name']} ({s['employee_id']})")
                if st.button("Save assignment", key=f"asb_{d['id']}"):
                    ui.save(ck.assign_duty, c, a, d["id"], pick["id"] if pick else None, success="Duty reassigned.")
    frame = ui.df(duties, ["duty_date", "department", "outlet", "title", "assignee", "effective_status",
                           "response_value", "unit", "completed_by_name", "completed_at", "verification_status",
                           "verified_by_name", "exception_details"])
    ui.csv_button(frame, f"duties_{day}.csv")
    if ui.can("schedule.manage"):
        st.divider()
        adhoc_form()


def adhoc_form():
    a = ui.actor()
    c = ui.conn()
    with st.expander("➕ Add a one-off duty"):
        depts = ui.svc.visible_departments(c, a)
        dept = st.selectbox("Department", depts, format_func=lambda d: d["name"], key="adhoc_dept")
        with st.form("adhoc"):
            title = st.text_input("Title")
            instr = st.text_area("Instructions")
            rt = st.selectbox("Response type", list(ck.RESPONSE_TYPES), format_func=ck.RESPONSE_TYPES.get)
            c1, c2, c3 = st.columns(3)
            mn = c1.number_input("Min (numeric)", value=None)
            mx = c2.number_input("Max (numeric)", value=None)
            unit = c3.text_input("Unit")
            c4, c5, c6 = st.columns(3)
            prio = c4.selectbox("Priority", ck.PRIORITIES, index=1)
            risk = c5.selectbox("Food-safety risk", ck.RISK_LEVELS)
            due = c6.time_input("Due time", dt.time(12, 0))
            day = st.date_input("Date", ui.svc.today_local(c))
            staff = [None] + staff_svc.staff_options(c, a, dept["id"] if dept else None)
            who = st.selectbox("Assign to", staff, format_func=lambda s: "Anyone on shift" if s is None
                               else f"{s['full_name']} ({s['employee_id']})")
            verify = st.checkbox("Requires supervisor verification")
            if st.form_submit_button("Create duty", type="primary"):
                ui.save(ck.create_adhoc_duty, c, a, {
                    "department_id": dept["id"] if dept else None, "title": title, "instructions": instr,
                    "response_type": rt, "min_value": mn, "max_value": mx, "unit": unit, "priority": prio,
                    "risk_level": risk, "due_time": due.strftime("%H:%M"), "duty_date": day,
                    "assigned_staff_id": who["id"] if who else None, "requires_verification": verify},
                    success="Duty created.")
