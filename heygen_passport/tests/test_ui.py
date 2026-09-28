"""UI smoke tests: sign in as each role and render every page it can reach."""

import os
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from heygen_passport import config, db, seed
from heygen_passport.services import users

APP = str(Path(__file__).resolve().parents[1] / "app.py")
PW = "Str0ng#Password"

PAGES = {
    "staff": ["home", "expiry", "actions", "profile"],
    "supervisor": ["home", "my-duties", "duties", "checklists", "expiry", "actions", "staff", "performance",
                   "reports", "profile"],
    "manager": ["home", "duties", "checklists", "expiry", "actions", "staff", "performance", "reports", "users",
                "profile"],
    "admin": ["home", "duties", "checklists", "expiry", "actions", "staff", "performance", "reports", "users",
              "admin", "profile"],
}


@pytest.fixture(scope="module")
def dbpath(tmp_path_factory):
    path = tmp_path_factory.mktemp("ui") / "ui.db"
    old = config.DB_PATH
    config.DB_PATH = path
    conn = db.connect(path)
    db.migrate_up(conn)
    seed.init_reference_data(conn)
    seed.seed_demo(conn)
    for name, role, staff_emp in (("t.staff", "staff", "DEMO-K002"), ("t.sup", "supervisor", "DEMO-K001"),
                                  ("t.mgr", "manager", None), ("t.admin", "admin", None)):
        sid = db.scalar(conn, "SELECT id FROM hp_staff WHERE employee_id=?", (staff_emp,)) if staff_emp else None
        # Demo staff already have accounts; reuse their profile via a fresh password.
        existing = db.scalar(conn, "SELECT id FROM hp_users WHERE staff_id=?", (sid,)) if sid else None
        if existing:
            conn.execute("UPDATE hp_users SET username=? WHERE id=?", (name, existing))
            conn.execute("UPDATE hp_users SET password_hash=? WHERE id=?",
                         (__import__("heygen_passport.security", fromlist=["x"]).hash_password(PW), existing))
        else:
            users.create_user(conn, None, name, PW, role, must_change_password=False)
    conn.close()
    yield path
    config.DB_PATH = old


def _login(username):
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    at.text_input[0].input(username)
    at.text_input[1].input(PW)
    at.button[0].click()
    at.run()
    assert not at.exception, at.exception
    return at


def _goto(at, url_path):
    """Select a callable st.Page by url_path (AppTest.switch_page only
    supports file-based pages)."""
    matches = [h for h, info in at._registered_pages.items()
               if info.get("url_pathname") in (url_path, "" if url_path == "home" else None)]
    assert matches, (url_path, at._registered_pages)
    at._page_hash = matches[0]
    at.run()


@pytest.mark.parametrize("role", list(PAGES))
def test_role_pages_render(dbpath, role):
    at = _login(f"t.{role if role != 'supervisor' else 'sup'}".replace("t.manager", "t.mgr"))
    assert not at.error, [e.value for e in at.error]
    for page in PAGES[role]:
        _goto(at, page)
        assert not at.exception, (page, at.exception)


def test_bad_login_shows_error(dbpath):
    at = AppTest.from_file(APP, default_timeout=60)
    at.run()
    at.text_input[0].input("t.admin")
    at.text_input[1].input("nope")
    at.button[0].click()
    at.run()
    assert any("Invalid username or password" in e.value for e in at.error)
