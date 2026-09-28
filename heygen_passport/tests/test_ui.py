"""UI smoke tests: sign in as each role and render every page it can reach."""

import uuid
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from heygen_passport import config, db, seed
from heygen_passport.security import hash_password
from heygen_passport.services import users

from .conftest import ENGINES

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


@pytest.fixture(scope="module", params=ENGINES)
def dbpath(request, tmp_path_factory):
    """Prepare a seeded database on each engine; the app under test reads
    the same config module, so it connects to this database."""
    saved = (config.DB_ENGINE, config.DB_PATH, config.MSSQL_DATABASE)
    if request.param == "sqlite":
        config.DB_ENGINE, config.DB_PATH = "sqlite", tmp_path_factory.mktemp("ui") / "ui.db"
    else:
        config.DB_ENGINE, config.MSSQL_DATABASE = "mssql", f"hp_uitest_{uuid.uuid4().hex[:10]}"
        db.create_mssql_database(config.MSSQL_DATABASE)
    conn = db.connect()
    db.migrate_up(conn)
    seed.init_reference_data(conn)
    seed.seed_demo(conn)
    for name, role, staff_emp in (("t.staff", "staff", "DEMO-K002"), ("t.sup", "supervisor", "DEMO-K001"),
                                  ("t.mgr", "manager", None), ("t.admin", "admin", None)):
        sid = db.scalar(conn, "SELECT id FROM hp_staff WHERE employee_id=?", (staff_emp,)) if staff_emp else None
        # Demo staff already have accounts; reuse them with a known password.
        existing = db.scalar(conn, "SELECT id FROM hp_users WHERE staff_id=?", (sid,)) if sid else None
        if existing:
            conn.execute("UPDATE hp_users SET username=?, password_hash=? WHERE id=?",
                         (name, hash_password(PW), existing))
        else:
            users.create_user(conn, None, name, PW, role, must_change_password=False)
    conn.close()
    yield request.param
    if request.param == "mssql":
        master = db.pyodbc.connect(db.mssql_connection_string("master"), autocommit=True)
        master.cursor().execute(f"ALTER DATABASE [{config.MSSQL_DATABASE}] SET SINGLE_USER WITH ROLLBACK "
                                f"IMMEDIATE; DROP DATABASE [{config.MSSQL_DATABASE}]")
        master.close()
    config.DB_ENGINE, config.DB_PATH, config.MSSQL_DATABASE = saved


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
