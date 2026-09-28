"""Heygen Passport - Streamlit entry point.

Run with:  ./heygen_passport/run.sh   (serves on port 8502 by default)
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st  # noqa: E402

from heygen_passport import config  # noqa: E402
from heygen_passport.permissions import ROLE_LABELS  # noqa: E402
from heygen_passport.security import ValidationError  # noqa: E402
from heygen_passport.services import users as users_svc  # noqa: E402
from heygen_passport.ui import admin, common as ui, dashboards, duties, expiry, performance, staff, templates  # noqa: E402

st.set_page_config(page_title="Heygen Passport", page_icon="🛂", layout="wide")
st.markdown(ui.CSS, unsafe_allow_html=True)


def logout(reason=None):
    for k in list(st.session_state.keys()):
        if k != "hp_conn":
            del st.session_state[k]
    if reason:
        st.session_state["hp_login_msg"] = reason
    st.rerun()


def login_screen():
    c = ui.conn()
    st.title("🛂 Heygen Passport")
    st.caption(ui.svc.get_setting(c, "hotel_name") + " · Kitchen · Stewarding · Food & Beverage")
    if st.session_state.get("hp_login_msg"):
        st.info(st.session_state.pop("hp_login_msg"))
    if users_svc.user_count(c) == 0:
        st.warning("No accounts exist yet. An administrator must create the first account on the server with:  \n"
                   "`python -m heygen_passport.manage create-admin`")
    with st.form("login"):
        username = st.text_input("Username", autocomplete="username")
        password = st.text_input("Password", type="password", autocomplete="current-password")
        if st.form_submit_button("Sign in", type="primary", width="stretch"):
            try:
                actor, u = users_svc.authenticate(c, username, password)
            except ValidationError as e:
                st.error(str(e))
            else:
                st.session_state.update(hp_user_id=actor.user_id, hp_last_seen=time.time(),
                                        hp_must_change=bool(u["must_change_password"]))
                st.rerun()


def current_actor():
    uid = st.session_state.get("hp_user_id")
    if not uid:
        return None
    if time.time() - st.session_state.get("hp_last_seen", 0) > config.SESSION_IDLE_MINUTES * 60:
        logout("You were signed out after a period of inactivity.")
    st.session_state["hp_last_seen"] = time.time()
    actor, _u = users_svc.load_actor(ui.conn(), uid)
    if actor is None:
        logout("Your account is no longer active.")
    st.session_state["hp_actor"] = actor
    return actor


def main():
    actor = current_actor()
    if actor is None:
        login_screen()
        return
    if st.session_state.get("hp_must_change"):
        st.title("🛂 Heygen Passport")
        st.warning("Please set a new password before continuing.")
        staff.password_form(forced=True)
        if st.button("Sign out"):
            logout()
        return

    P = st.Page
    pages = {}
    if actor.role == "staff":
        pages["home"] = P(dashboards.staff_home, title="My duties", icon="✅", url_path="home", default=True)
    elif actor.role == "supervisor":
        pages["home"] = P(dashboards.supervisor_dashboard, title="Dashboard", icon="📋", url_path="home", default=True)
        pages["mine"] = P(dashboards.staff_home, title="My duties", icon="✅", url_path="my-duties")
    else:
        pages["home"] = P(dashboards.manager_dashboard, title="Dashboard", icon="📊", url_path="home", default=True)
    if ui.can("duty.view_dept"):
        pages["duties"] = P(duties.duty_board, title="Daily duties", icon="🗓️", url_path="duties")
        pages["templates"] = P(templates.page, title="Checklists", icon="🧾", url_path="checklists")
    pages["expiry"] = P(expiry.page, title="Expiry tracking", icon="⏳", url_path="expiry")
    pages["actions"] = P(performance.actions_page, title="Corrective actions", icon="🛠️", url_path="actions")
    if ui.can("staff.view"):
        pages["staff"] = P(staff.directory, title="Staff directory", icon="👥", url_path="staff")
    if ui.can("score.view"):
        pages["performance"] = P(performance.performance_page, title="Performance", icon="🚦", url_path="performance")
    if ui.can("reports.view"):
        pages["reports"] = P(performance.reports_page, title="Reports", icon="📈", url_path="reports")
    if ui.can("access.manage"):
        pages["users"] = P(admin.users_page, title="Users & access", icon="🔐", url_path="users")
    if ui.can("admin.settings"):
        pages["admin"] = P(admin.admin_page, title="Administration", icon="⚙️", url_path="admin")
    pages["profile"] = P(staff.my_profile, title="My profile & feedback", icon="🙂", url_path="profile")
    st.session_state["hp_pages"] = pages

    with st.sidebar:
        st.markdown(f"**{ui.esc(actor.username)}**  \n{ROLE_LABELS[actor.role]}")
        st.caption(f"Hotel time: {ui.svc.now_local(ui.conn()).strftime('%a %d %b %H:%M')} "
                   f"({ui.svc.get_setting(ui.conn(), 'timezone')})")
        if st.button("Sign out", width="stretch"):
            logout("Signed out.")
    nav = st.navigation(list(pages.values()))
    nav.run()


main()
