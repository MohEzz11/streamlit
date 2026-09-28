"""Staff directory, profile pages, and the staff member's own profile/feedback."""

import datetime as dt

import pandas as pd
import streamlit as st

from ..permissions import ROLE_LABELS
from ..security import generate_password
from ..services import actions as ca_svc, checklists as ck, scoring as sc, staff as staff_svc, users as users_svc
from . import common as ui


def directory():
    a = ui.actor()
    c = ui.conn()
    st.header("Staff directory")
    ui.flash_show()
    if st.session_state.get("view_staff_id"):
        if st.button("← Back to directory"):
            st.session_state.pop("view_staff_id")
            st.rerun()
        profile_view(st.session_state["view_staff_id"])
        return
    c1, c2, c3 = st.columns(3)
    q = c1.text_input("Search name, employee ID or job title", key="dir_q")
    with c2:
        dept = ui.dept_filter("dir_dept")
    status = c3.selectbox("Employment status", [None] + list(staff_svc.EMPLOYMENT_STATUSES),
                          format_func=lambda s: "All" if s is None else s.replace("_", " ").title(), key="dir_status")
    people = ui.guard(staff_svc.search_staff, c, a, q or None, dept, status)
    st.caption(f"{len(people)} profile(s)")
    for p in people:
        cols = st.columns([4, 3, 2, 1])
        cols[0].write(f"**{p['full_name']}**{' (DEMO)' if p['is_demo'] else ''}  \n{p['employee_id']} · {p['job_title']}")
        cols[1].write(f"{p['department']}  \n{p['outlet'] or ''}")
        cols[2].write(p["employment_status"].replace("_", " ").title())
        if cols[3].button("Open", key=f"open_{p['id']}"):
            st.session_state["view_staff_id"] = p["id"]
            st.rerun()
    if ui.can("staff.edit"):
        st.divider()
        with st.expander("➕ New staff profile"):
            profile_form(None)


def profile_view(staff_id):
    a = ui.actor()
    c = ui.conn()
    s = ui.guard(staff_svc.get_staff, c, a, staff_id)
    if not s:
        st.error("Profile not found.")
        return
    top = st.columns([1, 3])
    with top[0]:
        if s["photo_evidence_id"]:
            ui.show_evidence(s["photo_evidence_id"], caption=s["full_name"])
        else:
            st.markdown("### 👤")
    with top[1]:
        st.subheader(s["full_name"] + (" (DEMO)" if s["is_demo"] else ""))
        st.write(f"{s['employee_id']} · {s['job_title']} · {s['department']}"
                 + (f" · {s['outlet']}" if s["outlet"] else ""))
        st.write(f"Status: **{s['employment_status'].replace('_', ' ').title()}** · Shift pattern: "
                 f"{s['shift_pattern'] or '-'} · Supervisor: {s['supervisor'] or '-'} · Start date: {s['start_date'] or '-'}")
        st.caption(f"Work phone: {s['work_phone'] or '-'} · Work email: {s['work_email'] or '-'}")
    tabs = ["Certifications", "Duties", "Performance", "Coaching & actions", "Other details"]
    if ui.can("staff.edit", s["department_id"]):
        tabs += ["Edit profile", "Access"]
    if ui.can("admin.audit") or ui.can("staff.edit", s["department_id"]):
        tabs.append("Change history")
    t = dict(zip(tabs, st.tabs(tabs)))
    with t["Certifications"]:
        certs_panel(s)
    with t["Duties"]:
        d1, d2 = ui.date_range_picker(f"pd_{staff_id}", 14)
        duties = [d for d in ck.dept_duties(c, a, d1, s["department_id"], date_to=d2)
                  if staff_id in (d["assigned_staff_id"], d["completed_by_staff_id"])]
        st.dataframe(ui.df(duties, ["duty_date", "title", "assignee", "effective_status", "response_value",
                                    "completed_by_name", "verification_status"]),
                     hide_index=True, width="stretch")
    with t["Performance"]:
        performance_panel(s)
    with t["Coaching & actions"]:
        coaching_panel(s)
    with t["Other details"]:
        if s["notes"]:
            st.write(f"**Profile notes:** {s['notes']}")
        for f in s["custom_fields"]:
            st.write(f"**{f['label']}:** {f['value'] or '-'}")
        if not s["custom_fields"] and not s["notes"]:
            st.caption("No additional details.")
        if ui.can("staff.edit", s["department_id"]) and s["custom_fields"]:
            with st.form(f"cf_{staff_id}"):
                vals = {f["id"]: st.text_input(f["label"], f["value"] or "", key=f"cf_{staff_id}_{f['id']}")
                        for f in s["custom_fields"]}
                if st.form_submit_button("Save details"):
                    def _save_all():
                        for fid, v in vals.items():
                            staff_svc.set_field_value(c, a, staff_id, fid, v)
                    ui.save(_save_all, success="Details saved.")
    if "Edit profile" in t:
        with t["Edit profile"]:
            profile_form(s)
            photo = st.file_uploader("Profile photo (JPEG/PNG/WebP)", type=["jpg", "jpeg", "png", "webp"],
                                     key=f"photo_{staff_id}")
            if photo and st.button("Upload photo"):
                ui.save(staff_svc.set_photo, c, a, staff_id, photo.name, photo.getvalue(), success="Photo updated.")
        with t["Access"]:
            access_panel(s)
    if "Change history" in t:
        with t["Change history"]:
            hist = ui.svc.entity_history(c, a, "staff", staff_id)
            st.dataframe(pd.DataFrame(hist), hide_index=True, width="stretch") if hist else st.caption("No changes.")


def profile_form(s):
    a = ui.actor()
    c = ui.conn()
    s = s or {}
    k = f"pf_{s.get('id', 'new')}"
    depts = [d for d in ui.svc.visible_departments(c, a) if ui.can("staff.edit", d["id"])]
    di = next((i for i, d in enumerate(depts) if d["id"] == s.get("department_id")), 0)
    dept = st.selectbox("Department", depts, index=di, format_func=lambda d: d["name"], key=f"{k}_dept")
    with st.form(k):
        c1, c2 = st.columns(2)
        emp = c1.text_input("Employee ID", s.get("employee_id", ""))
        name = c2.text_input("Full name", s.get("full_name", ""))
        c3, c4 = st.columns(2)
        title = c3.text_input("Job title", s.get("job_title", ""))
        sts = list(staff_svc.EMPLOYMENT_STATUSES)
        status = c4.selectbox("Employment status", sts, index=sts.index(s.get("employment_status", "active")))
        outs = [None] + ui.svc.outlets(c, dept["id"] if dept else None)
        oi = next((i for i, o in enumerate(outs) if o and o["id"] == s.get("outlet_id")), 0)
        outlet = st.selectbox("Outlet / work area", outs, index=oi, format_func=lambda o: "-" if o is None else o["name"])
        sups = [None] + [p for p in staff_svc.staff_options(c, a) if p["id"] != s.get("id")]
        si = next((i for i, p in enumerate(sups) if p and p["id"] == s.get("supervisor_staff_id")), 0)
        sup = st.selectbox("Supervisor", sups, index=si, format_func=lambda p: "-" if p is None else f"{p['full_name']} ({p['employee_id']})")
        c5, c6 = st.columns(2)
        start = c5.date_input("Start date", dt.date.fromisoformat(s["start_date"]) if s.get("start_date") else None,
                              min_value=dt.date(1970, 1, 1))
        shifts = list(staff_svc.SHIFT_PATTERNS)
        cur = s.get("shift_pattern") if s.get("shift_pattern") in shifts else "Morning"
        shift = c6.selectbox("Shift pattern", shifts, index=shifts.index(cur))
        c7, c8 = st.columns(2)
        phone = c7.text_input("Work phone", s.get("work_phone") or "")
        email = c8.text_input("Work email", s.get("work_email") or "")
        notes = st.text_area("Profile notes (not shown to the staff member)", s.get("notes") or "")
        st.caption("Collect only what is needed for hotel operations. Do not record ID documents, medical details "
                   "or home addresses here.")
        if st.form_submit_button("Save profile", type="primary"):
            ui.save(staff_svc.save_staff, c, a, {
                "employee_id": emp, "full_name": name, "job_title": title, "department_id": dept["id"] if dept else None,
                "employment_status": status, "outlet_id": outlet["id"] if outlet else None,
                "supervisor_staff_id": sup["id"] if sup else None, "start_date": start, "shift_pattern": shift,
                "work_phone": phone, "work_email": email, "notes": notes}, staff_id=s.get("id"),
                success="Profile saved.")


def certs_panel(s):
    a = ui.actor()
    c = ui.conn()
    certs = staff_svc.certifications(c, a, staff_id=s["id"])
    for cert in certs:
        cols = st.columns([4, 2])
        cols[0].write(f"**{cert['name']}** · {cert['issuer'] or ''} · issued {cert['issue_date'] or '-'} · "
                      f"expires {cert['expiry_date'] or '-'}")
        with cols[1]:
            ui.badge(cert["status"])
        ui.show_evidence(cert["evidence_id"], caption=f"Certificate {cert['id']}")
    if not certs:
        st.caption("No certifications recorded.")
    if ui.can("cert.manage", s["department_id"]):
        opts = [None] + certs
        with st.expander("Add / update certification"):
            pick = st.selectbox("Certification", opts, format_func=lambda x: "New certification" if x is None else x["name"],
                                key=f"certpick_{s['id']}")
            p = pick or {}
            with st.form(f"cert_{s['id']}_{p.get('id', 'new')}"):
                name = st.text_input("Name", p.get("name", ""))
                ctype = st.text_input("Type", p.get("cert_type", "food_safety"))
                issuer = st.text_input("Issuer", p.get("issuer") or "")
                no = st.text_input("Certificate number", p.get("certificate_no") or "")
                c1, c2 = st.columns(2)
                iss = c1.date_input("Issue date", dt.date.fromisoformat(p["issue_date"]) if p.get("issue_date") else None)
                exp = c2.date_input("Expiry date", dt.date.fromisoformat(p["expiry_date"]) if p.get("expiry_date") else None)
                f = st.file_uploader("Certificate copy (optional)", type=["jpg", "jpeg", "png", "webp", "pdf"])
                if st.form_submit_button("Save certification"):
                    ui.save(staff_svc.save_certification, c, a, s["id"], {
                        "name": name, "cert_type": ctype, "issuer": issuer, "certificate_no": no,
                        "issue_date": iss, "expiry_date": exp}, cert_id=p.get("id"), evidence=ui.upload_tuple(f),
                        success="Certification saved.")


def performance_panel(s, own=False):
    a = ui.actor()
    c = ui.conn()
    d1, d2 = ui.date_range_picker(f"perf_{s['id']}", 30)
    p = sc.performance(c, a, s["id"], d1, d2)
    cols = st.columns([1, 3])
    cols[0].metric("Score", "-" if p["score"] is None else f"{p['score']:.0f}%")
    with cols[1]:
        ui.badge(p["color"])
        st.caption(f"Green ≥ {p['thresholds']['green']:g}% · Amber ≥ {p['thresholds']['amber']:g}% · below = Red")
    for r in p["reasons"]:
        st.write(f"- {r}")
    tr = pd.DataFrame(sc.trend(c, a, s["id"], d1, d2))
    if not tr.empty and tr["score"].notna().any():
        st.line_chart(tr.set_index("period_start")["score"])
    scores = sc.list_scores(c, a, s["id"], d1, d2)
    if scores:
        st.write("**Scores awarded**")
        st.dataframe(ui.df(scores, ["score_date", "criterion", "score", "scale_max", "reason", "source_type",
                                    "awarded_by_name"]), hide_index=True, width="stretch")
    if not own and ui.can("score.award", s["department_id"]) and a.staff_id != s["id"]:
        award_form(s)
    if not own and scores and (ui.can("score.configure") or ui.can("score.award", s["department_id"])):
        with st.expander("Void a score (keeps the record, excludes it from calculation)"):
            pick = st.selectbox("Score", scores, format_func=lambda x: f"{x['score_date']} {x['criterion']} {x['score']:g}",
                                key=f"void_{s['id']}")
            reason = st.text_input("Reason", key=f"voidr_{s['id']}")
            if st.button("Void score", key=f"voidb_{s['id']}"):
                ui.save(sc.void_score, c, a, pick["id"], reason, success="Score voided.")


def award_form(s):
    a = ui.actor()
    c = ui.conn()
    crits = [x for x in sc.criteria(c, department_id=s["department_id"]) if x["source"] == "manual"]
    _g, _a, scale = sc.thresholds(c)
    with st.expander("Award a score"):
        with st.form(f"award_{s['id']}"):
            crit = st.selectbox("Criterion", crits, format_func=lambda x: f"{x['name']} (weight {x['weight']:g})")
            score = st.slider(f"Score (0-{scale:g})", 0.0, float(scale), float(scale), 0.5)
            reason = st.text_area("Reason / observation (required, visible to the staff member)")
            c1, c2 = st.columns(2)
            src = c1.selectbox("Linked to", [None, "observation", "duty", "training", "exception", "other"],
                               format_func=lambda x: "-" if x is None else x)
            src_id = c2.number_input("Record ID (e.g. duty #)", value=None, step=1)
            day = st.date_input("Date", ui.svc.today_local(c))
            if st.form_submit_button("Award score", type="primary"):
                ui.save(sc.award_score, c, a, s["id"], crit["id"] if crit else None, score, reason, day, src,
                        int(src_id) if src_id else None, success="Score awarded.")


def coaching_panel(s, own=False):
    a = ui.actor()
    c = ui.conn()
    notes = ca_svc.coaching_notes(c, a, s["id"])
    for n in notes:
        st.write(f"**{ui.fmt(n['created_at'])}** · {n['created_by_name']}: {n['note']}")
        meta = []
        if n["follow_up_date"]:
            meta.append(f"Follow-up: {n['follow_up_date']}")
        if n["resolved_at"]:
            meta.append(f"Resolved {ui.fmt(n['resolved_at'])} by {n['resolved_by_name']}: {n['resolution']}")
        if not n["visible_to_staff"]:
            meta.append("Not visible to staff")
        if meta:
            st.caption(" · ".join(meta))
        if not own and not n["resolved_at"] and ui.can("coaching.manage", s["department_id"]):
            with st.popover("Resolve"):
                res = st.text_input("Resolution", key=f"cres_{n['id']}")
                if st.button("Save resolution", key=f"cresb_{n['id']}"):
                    ui.save(ca_svc.resolve_coaching_note, c, a, n["id"], res, success="Follow-up resolved.")
    if not notes:
        st.caption("No coaching notes.")
    if not own and ui.can("coaching.manage", s["department_id"]):
        with st.form(f"coach_{s['id']}"):
            note = st.text_area("New coaching note")
            fu = st.date_input("Follow-up date (optional)", None)
            vis = st.checkbox("Visible to the staff member", True)
            if st.form_submit_button("Add note"):
                ui.save(ca_svc.add_coaching_note, c, a, s["id"], note, fu, vis, success="Coaching note added.")
    cas = ca_svc.list_corrective_actions(c, a, staff_id=s["id"])
    if cas:
        st.write("**Corrective actions linked to this person**")
        st.dataframe(ui.df(cas, ["id", "title", "severity", "status", "due_date", "owner", "resolution"]),
                     hide_index=True, width="stretch")


def access_panel(s):
    a = ui.actor()
    c = ui.conn()
    u = next((x for x in users_svc.list_users(c, a) if x["staff_id"] == s["id"]), None) if ui.can("access.manage") else None
    if u:
        st.write(f"Account: **{u['username']}** · {ROLE_LABELS[u['role']]} · {'active' if u['active'] else 'disabled'}")
        from .admin import user_edit_form
        user_edit_form(u)
    elif ui.can("access.manage"):
        st.write("No login account yet.")
        with st.form(f"acc_{s['id']}"):
            username = st.text_input("Username", s["employee_id"].lower())
            roles = ["staff", "supervisor"] + (["manager", "admin"] if a.role == "admin" else [])
            role = st.selectbox("Role", roles, format_func=ROLE_LABELS.get)
            can_score = st.checkbox("Supervisor may award scores")
            if st.form_submit_button("Create account"):
                pw = generate_password()
                res = ui.save(users_svc.create_user, c, a, username, pw, role, staff_id=s["id"],
                              department_id=s["department_id"], can_score=can_score, rerun=False,
                              success="Account created.")
                if res:
                    st.session_state["hp_flash"] = ("ok", f"✅ Account '{username}' created. Temporary password: "
                                                    f"{pw} - give it to the person privately; they must change it at first login.")
                    st.rerun()


def my_profile():
    a = ui.actor()
    c = ui.conn()
    st.header("My profile and feedback")
    ui.flash_show()
    if not a.staff_id:
        st.info("Your account is not linked to a staff profile.")
    else:
        s = staff_svc.get_staff(c, a, a.staff_id)
        st.subheader(s["full_name"])
        st.write(f"{s['employee_id']} · {s['job_title']} · {s['department']}" + (f" · {s['outlet']}" if s["outlet"] else ""))
        st.write(f"Shift pattern: {s['shift_pattern'] or '-'} · Supervisor: {s['supervisor'] or '-'}")
        st.caption(f"Work phone: {s['work_phone'] or '-'} · Work email: {s['work_email'] or '-'}")
        for f in s["custom_fields"]:
            st.write(f"**{f['label']}:** {f['value'] or '-'}")
        t1, t2, t3, t4 = st.tabs(["Certifications", "Performance & feedback", "Coaching & actions", "Duty history"])
        with t1:
            certs_panel(s)
        with t2:
            performance_panel(s, own=True)
        with t3:
            coaching_panel(s, own=True)
        with t4:
            d1, d2 = ui.date_range_picker("myhist", 14)
            hist = []
            day = d1
            while day <= d2:
                hist += ck.my_duties(c, a, day)
                day += dt.timedelta(days=1)
            st.dataframe(ui.df(hist, ["duty_date", "title", "effective_status", "response_value", "completed_at",
                                      "verification_status", "verification_note"]), hide_index=True, width="stretch")
    st.divider()
    password_form()


def password_form(forced=False):
    a = ui.actor()
    c = ui.conn()
    st.subheader("Change password")
    with st.form("pw"):
        cur = st.text_input("Current password", type="password")
        new = st.text_input("New password (min 10 characters, mix of letters, digits, symbols)", type="password")
        rep = st.text_input("Repeat new password", type="password")
        if st.form_submit_button("Change password", type="primary"):
            if new != rep:
                st.error("NOT saved: new passwords do not match.")
            else:
                ok = ui.save(users_svc.change_own_password, c, a, cur, new, success="Password changed.", rerun=False)
                if not ok:
                    return
                st.session_state["hp_must_change"] = False
                st.rerun()
