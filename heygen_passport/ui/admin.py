"""User access management and administrator settings."""

import pandas as pd
import streamlit as st

from ..permissions import ROLE_LABELS
from ..security import generate_password
from ..services import staff as staff_svc, users as users_svc
from . import common as ui


def users_page():
    a = ui.actor()
    c = ui.conn()
    st.header("Users and access")
    ui.flash_show()
    if a.role != "admin":
        st.caption("Managers can create and manage staff and supervisor accounts. Manager and administrator "
                   "accounts are managed by an administrator.")
    us = users_svc.list_users(c, a)
    q = st.text_input("Search", key="u_q")
    if q:
        us = [u for u in us if q.lower() in (u["username"] + (u["full_name"] or "")).lower()]
    st.dataframe(ui.df(us, ["username", "role", "full_name", "employee_id", "department", "active", "can_score",
                            "last_login_at", "is_demo"]), hide_index=True, width="stretch")
    pick = st.selectbox("Manage account", [None] + us, format_func=lambda u: "Choose..." if u is None else
                        f"{u['username']} ({ROLE_LABELS[u['role']]})", key="u_pick")
    if pick:
        user_edit_form(pick)
    st.divider()
    with st.expander("➕ New account"):
        roles = ["staff", "supervisor"] + (["manager", "admin"] if a.role == "admin" else [])
        role = st.selectbox("Role", roles, format_func=ROLE_LABELS.get, key="nu_role")
        people = [None] + staff_svc.staff_options(c, a)
        with st.form("new_user"):
            username = st.text_input("Username")
            person = st.selectbox("Linked staff profile" + (" (required)" if role == "staff" else " (optional)"), people,
                                  format_func=lambda p: "-" if p is None else f"{p['full_name']} ({p['employee_id']})")
            depts = [None] + ui.svc.departments(c)
            dept = st.selectbox("Department (taken from the profile when linked)", depts,
                                format_func=lambda d: "-" if d is None else d["name"])
            can_score = st.checkbox("Supervisor may award scores", disabled=role != "supervisor")
            if st.form_submit_button("Create account", type="primary"):
                pw = generate_password()
                res = ui.save(users_svc.create_user, c, a, username, pw, role,
                              staff_id=person["id"] if person else None,
                              department_id=(person["department_id"] if person else (dept["id"] if dept else None)),
                              can_score=can_score, rerun=False, success="Account created.")
                if res:
                    st.session_state["hp_flash"] = ("ok", f"✅ Account '{username}' created. Temporary password: {pw} "
                                                    "- share it privately; it must be changed at first login.")
                    st.rerun()


def user_edit_form(u):
    a = ui.actor()
    c = ui.conn()
    roles = ["staff", "supervisor"] + (["manager", "admin"] if a.role == "admin" else [])
    if u["role"] not in roles:
        st.info("Only an administrator can change this account.")
        return
    with st.form(f"ue_{u['id']}"):
        role = st.selectbox("Role", roles, index=roles.index(u["role"]), format_func=ROLE_LABELS.get)
        depts = [None] + ui.svc.departments(c)
        di = next((i for i, d in enumerate(depts) if d and d["id"] == u["department_id"]), 0)
        dept = st.selectbox("Department", depts, index=di, format_func=lambda d: "-" if d is None else d["name"])
        active = st.checkbox("Active (can sign in)", bool(u["active"]))
        can_score = st.checkbox("Supervisor may award scores", bool(u["can_score"]))
        if st.form_submit_button("Save account"):
            ui.save(users_svc.update_user, c, a, u["id"], role=role, department_id=dept["id"] if dept else None,
                    active=active, can_score=can_score, success="Account updated.")
    if st.button("Reset password", key=f"rp_{u['id']}"):
        pw = generate_password()
        if ui.save(users_svc.reset_password, c, a, u["id"], pw, rerun=False, success="Password reset."):
            st.session_state["hp_flash"] = ("ok", f"✅ Temporary password for {u['username']}: {pw} - share it "
                                            "privately; it must be changed at next login.")
            st.rerun()


def admin_page():
    a = ui.actor()
    c = ui.conn()
    st.header("Administration")
    ui.flash_show()
    t1, t2, t3, t4 = st.tabs(["Departments and outlets", "System settings", "Profile fields", "Audit log"])
    with t1:
        for d in ui.svc.departments(c, active_only=False) + [None]:
            dd = d or {}
            with st.expander("➕ New department" if d is None else f"{d['name']} ({d['code']})"
                             + ("" if d["active"] else " [inactive]")):
                with st.form(f"dep_{dd.get('id', 'new')}"):
                    code = st.text_input("Code", dd.get("code", ""))
                    name = st.text_input("Name", dd.get("name", ""))
                    active = st.checkbox("Active", bool(dd.get("active", 1)))
                    if st.form_submit_button("Save department"):
                        ui.save(ui.svc.save_department, c, a, code, name, dd.get("id"), active, success="Department saved.")
        st.subheader("Outlets / work areas")
        outs = ui.svc.outlets(c, active_only=False)
        st.dataframe(ui.df(outs, ["id", "name", "department_name", "active"]), hide_index=True, width="stretch")
        with st.form("outlet"):
            pick = st.selectbox("Outlet", [None] + outs, format_func=lambda o: "New outlet" if o is None else o["name"])
            name = st.text_input("Name (for new or rename)")
            depts = [None] + ui.svc.departments(c)
            dept = st.selectbox("Department", depts, format_func=lambda d: "Shared / none" if d is None else d["name"])
            active = st.checkbox("Active", True)
            if st.form_submit_button("Save outlet"):
                ui.save(ui.svc.save_outlet, c, a, name or (pick["name"] if pick else ""), dept["id"] if dept else None,
                        pick["id"] if pick else None, active, success="Outlet saved.")
    with t2:
        s = ui.svc.get_settings(c)
        with st.form("settings"):
            hotel = st.text_input("Hotel name", s["hotel_name"])
            tz = st.text_input("Time zone (IANA, e.g. Asia/Dubai)", s["timezone"])
            cert = st.number_input("Certification reminder (days before expiry)", 1, 365, int(s["cert_reminder_days"]))
            if st.form_submit_button("Save settings"):
                def _save():
                    ui.svc.set_setting(c, a, "hotel_name", hotel)
                    ui.svc.set_setting(c, a, "timezone", tz)
                    ui.svc.set_setting(c, a, "cert_reminder_days", int(cert))
                ui.save(_save, success="Settings saved.")
        st.caption("Scoring thresholds are configured by Heygen Managers under Performance. Expiry reminder periods "
                   "are configured per category under Expiry tracking.")
    with t3:
        st.caption("Add only fields with a clear operational need. Do not collect sensitive personal data "
                   "(ID/passport numbers, medical, religious or financial details).")
        for f in staff_svc.profile_fields(c) + [None]:
            ff = f or {}
            with st.expander("➕ New field" if f is None else f"{f['label']} ({f['field_type']})"
                             + ("" if f["active"] else " [inactive]")):
                with st.form(f"pfld_{ff.get('id', 'new')}"):
                    label = st.text_input("Label", ff.get("label", ""))
                    types = ["text", "date", "number", "yes_no"]
                    ftype = st.selectbox("Type", types, index=types.index(ff.get("field_type", "text")))
                    vis = st.checkbox("Visible to the staff member", bool(ff.get("visible_to_staff", 1)))
                    active = st.checkbox("Active", bool(ff.get("active", 1)))
                    if st.form_submit_button("Save field"):
                        ui.save(staff_svc.save_profile_field, c, a, label, ftype, vis, ff.get("id"), active,
                                success="Field saved.")
    with t4:
        c1, c2 = st.columns(2)
        ent = c1.text_input("Entity type (e.g. duty, staff, score, expiry_item)", key="aud_ent")
        who = c2.text_input("Username contains", key="aud_user")
        d1, d2 = ui.date_range_picker("aud", 7)
        log = ui.svc.audit_log(c, a, ent or None, who or None, d1, d2, limit=2000)
        frame = pd.DataFrame(log)
        if not frame.empty:
            frame["at"] = frame["at"].map(lambda x: ui.fmt(x))
            frame["details"] = frame["details"].map(lambda x: x[:300] if isinstance(x, str) else "")
        st.dataframe(frame, hide_index=True, width="stretch")
        ui.csv_button(frame, f"audit_{d1}_{d2}.csv")
