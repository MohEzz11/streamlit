import datetime as dt
import os

import pytest

from heygen_passport import db, seed
from heygen_passport.permissions import PermissionDenied
from heygen_passport.security import ValidationError
from heygen_passport.services import (actions, alerts, checklists as ck, common, expiry as ex, scoring as sc,
                                      staff as staff_svc, users)

PW = "Str0ng#Password"


@pytest.fixture()
def env(tmp_path):
    conn = db.connect(tmp_path / "t.db")
    db.migrate_up(conn)
    seed.init_reference_data(conn)
    seed.seed_demo(conn)
    users.create_user(conn, None, "admin", PW, "admin", must_change_password=False)

    def login(username):
        u = db.row(conn, "SELECT * FROM hp_users WHERE username=?", (username,))
        return users.actor_from_user(u)
    return conn, login


def _ids(conn):
    return {r["employee_id"]: r["id"] for r in db.rows(conn, "SELECT id, employee_id FROM hp_staff")}


def test_migration_up_down_up(tmp_path):
    path = tmp_path / "m.db"
    conn = db.connect(path)
    assert db.migrate_up(conn) == ["0001"]
    assert db.migrate_up(conn) == []
    version, bak = db.migrate_down(conn, path)
    assert version == "0001" and bak.exists()
    assert not db.rows(conn, "SELECT name FROM sqlite_master WHERE name LIKE 'hp_staff'")
    assert db.migrate_up(conn) == ["0001"]


def test_login_and_lockout(env):
    conn, login = env
    with pytest.raises(ValidationError):
        users.authenticate(conn, "admin", "wrong")
    actor, _ = users.authenticate(conn, "admin", PW)
    assert actor.role == "admin"
    for _ in range(5):
        with pytest.raises(ValidationError):
            users.authenticate(conn, "admin", "wrong")
    with pytest.raises(ValidationError):  # locked even with the right password
        users.authenticate(conn, "admin", PW)


def test_staff_cannot_view_others_or_score(env):
    conn, login = env
    ids = _ids(conn)
    ravi = login("demo-k002")
    assert staff_svc.get_staff(conn, ravi, ids["DEMO-K002"])["notes"] is None  # own profile, notes hidden
    with pytest.raises(PermissionDenied):
        staff_svc.get_staff(conn, ravi, ids["DEMO-K003"])
    with pytest.raises(PermissionDenied):
        staff_svc.search_staff(conn, ravi)
    crit = [c for c in sc.criteria(conn) if c["source"] == "manual"][0]
    with pytest.raises(PermissionDenied):
        sc.award_score(conn, ravi, ids["DEMO-K003"], crit["id"], 5, "x")
    with pytest.raises(PermissionDenied):
        staff_svc.save_staff(conn, ravi, {"employee_id": "X", "full_name": "X", "job_title": "X",
                                          "department_id": 1}, staff_id=ids["DEMO-K003"])


def test_supervisor_scoped_to_department_and_needs_score_grant(env):
    conn, login = env
    ids = _ids(conn)
    sup = login("demo-k001")
    with pytest.raises(PermissionDenied):
        staff_svc.get_staff(conn, sup, ids["DEMO-F002"])  # other department
    crit = [c for c in sc.criteria(conn) if c["source"] == "manual"][0]
    with pytest.raises(PermissionDenied):
        sc.award_score(conn, sup, ids["DEMO-K002"], crit["id"], 4, "good")
    admin = login("admin")
    uid = db.scalar(conn, "SELECT id FROM hp_users WHERE username='demo-k001'")
    users.update_user(conn, admin, uid, can_score=True)
    sup = login("demo-k001")
    sc.award_score(conn, sup, ids["DEMO-K002"], crit["id"], 4, "good hygiene")
    with pytest.raises(PermissionDenied):
        sc.award_score(conn, sup, ids["DEMO-F002"], crit["id"], 4, "other dept")


def test_manager_cannot_create_admin(env):
    conn, login = env
    mgr = login("demo.manager")
    with pytest.raises(PermissionDenied):
        users.create_user(conn, mgr, "newadmin", PW, "admin")


def test_duty_completion_exception_and_verification(env):
    conn, login = env
    ck.generate_duties(conn)
    assert ck.generate_duties(conn) == 0  # idempotent
    ravi = login("demo-k002")
    mine = ck.my_duties(conn, ravi)
    chiller = next(d for d in mine if d["title"] == "Chiller temperature reading")
    # Out of range without exception details -> rejected, nothing saved.
    with pytest.raises(ValidationError):
        ck.complete_duty(conn, ravi, chiller["id"], value=9)
    assert db.row(conn, "SELECT status FROM hp_duties WHERE id=?", (chiller["id"],))["status"] == "not_started"
    res = ck.complete_duty(conn, ravi, chiller["id"], value=9, exception_details="Door left open; moved stock")
    assert res["status"] == "exception" and res["corrective_action_id"]
    # Cannot record twice.
    with pytest.raises(ValidationError):
        ck.complete_duty(conn, ravi, chiller["id"], value=4)
    # Staff cannot verify; supervisor of another department cannot either.
    with pytest.raises(PermissionDenied):
        ck.verify_duty(conn, ravi, chiller["id"], True)
    with pytest.raises(PermissionDenied):
        ck.verify_duty(conn, login("demo-f001"), chiller["id"], True)
    sup = login("demo-k001")
    ck.verify_duty(conn, sup, chiller["id"], False, "Re-probe after 30 minutes")
    ck.complete_duty(conn, ravi, chiller["id"], value=4)
    ck.verify_duty(conn, sup, chiller["id"], True)
    d = db.row(conn, "SELECT * FROM hp_duties WHERE id=?", (chiller["id"],))
    assert d["status"] == "completed" and d["verification_status"] == "verified"
    acts = [r["action"] for r in db.rows(conn, "SELECT action FROM hp_audit_log WHERE entity_type='duty' "
                                               "AND entity_id=? ORDER BY id", (chiller["id"],))]
    assert acts == ["duty.exception", "duty.reject", "duty.complete", "duty.verify"]


def test_other_staff_cannot_complete_assigned_duty(env):
    conn, login = env
    ck.generate_duties(conn)
    ravi_duty = ck.my_duties(conn, login("demo-k002"))[0]
    with pytest.raises(PermissionDenied):
        ck.complete_duty(conn, login("demo-s002"), ravi_duty["id"], value="yes")


def test_expiry_rules_and_actions(env):
    conn, login = env
    today = common.today_local(conn)
    items = {i["name"]: i for i in ex.list_items(conn, login("admin"))}
    assert items["DEMO Yoghurt"]["status"] == "expired"
    # Opened 2 days ago with 3-day shelf life -> effective expiry tomorrow, despite 30-day label.
    assert items["DEMO Opened mayonnaise"]["effective_expiry"] == (today + dt.timedelta(days=1)).isoformat()
    assert items["DEMO Opened mayonnaise"]["status"] == "expiring_soon"
    assert items["DEMO Dishwash detergent"]["status"] == "expiring_soon"  # 20 days, 30-day reminder
    ravi = login("demo-k002")
    yog = items["DEMO Yoghurt"]["id"]
    with pytest.raises(ValidationError):
        ex.record_action(conn, ravi, yog, "checked_ok")
    with pytest.raises(ValidationError):
        ex.record_action(conn, ravi, yog, "disposed")  # note required
    ex.record_action(conn, ravi, yog, "disposed", "12 cups binned")
    assert db.row(conn, "SELECT state FROM hp_expiry_items WHERE id=?", (yog,))["state"] == "disposed"
    with pytest.raises(PermissionDenied):  # other department
        ex.record_action(conn, login("demo-s002"), items["DEMO Chicken breast"]["id"], "checked_ok")
    with pytest.raises(PermissionDenied):  # staff cannot configure
        ex.save_category(conn, ravi, {"name": "x", "kind": "food", "reminder_days": 1})


def test_alerts_scan_idempotent_and_scoped(env):
    conn, login = env
    ck.generate_duties(conn)
    n = alerts.scan(conn)
    assert n > 0 and alerts.scan(conn) == 0
    joy = login("demo-s002")
    for a in alerts.list_alerts(conn, joy):
        assert a["department_id"] == joy.department_id or a["staff_id"] == joy.staff_id


def test_scoring_only_counts_assigned_duties(env):
    conn, login = env
    ids = _ids(conn)
    today = common.today_local(conn)
    mgr = login("demo.manager")
    # Maria has no assigned duties; unassigned pool duties must not count against her.
    p = sc.performance(conn, mgr, ids["DEMO-K003"], today - dt.timedelta(days=7), today)
    assert all(c["criterion"] != "Assigned duty completion" for c in p["components"])
    crit = [c for c in sc.criteria(conn) if c["source"] == "manual"][0]
    sc.award_score(conn, mgr, ids["DEMO-K003"], crit["id"], 2, "Hairnet not worn during prep")
    p = sc.performance(conn, mgr, ids["DEMO-K003"], today - dt.timedelta(days=7), today)
    assert p["score"] is not None and p["reasons"]
    with pytest.raises(ValidationError):
        sc.award_score(conn, mgr, ids["DEMO-K003"], crit["id"], 99, "too high")
    with pytest.raises(ValidationError):
        sc.award_score(conn, mgr, ids["DEMO-K003"], crit["id"], 3, "")


def test_corrective_action_owner_flow(env):
    conn, login = env
    sup = login("demo-k001")
    ravi = login("demo-k002")
    ca = actions.create_corrective_action(conn, sup, sup.department_id, "Fix chiller door seal",
                                          owner_user_id=ravi.user_id)
    with pytest.raises(ValidationError):
        actions.update_corrective_action(conn, ravi, ca, status="resolved")
    with pytest.raises(PermissionDenied):
        actions.update_corrective_action(conn, ravi, ca, owner_user_id=None, set_owner=True)
    actions.update_corrective_action(conn, ravi, ca, status="resolved", resolution="Engineering replaced seal")
    r = db.row(conn, "SELECT * FROM hp_corrective_actions WHERE id=?", (ca,))
    assert r["status"] == "resolved" and r["resolved_by"] == ravi.user_id


def test_evidence_upload_validation(env):
    conn, login = env
    ck.generate_duties(conn)
    ravi = login("demo-k002")
    photo_duty = next(d for d in ck.my_duties(conn, ravi) if d["response_type"] == "photo")
    with pytest.raises(ValidationError):
        ck.complete_duty(conn, ravi, photo_duty["id"], evidence=("x.html", b"<script>alert(1)</script>"))
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 100
    ck.complete_duty(conn, ravi, photo_duty["id"], evidence=("clean.png", png))
    d = db.row(conn, "SELECT evidence_id FROM hp_duties WHERE id=?", (photo_duty["id"],))
    assert common.get_evidence(conn, ravi, d["evidence_id"])["mime_type"] == "image/png"
    with pytest.raises(PermissionDenied):
        common.get_evidence(conn, login("demo-f002"), d["evidence_id"])


def test_remove_demo_leaves_real_data(env):
    conn, login = env
    admin = login("admin")
    real = staff_svc.save_staff(conn, admin, {"employee_id": "E100", "full_name": "Real Person",
                                              "job_title": "Cook", "department_id": 1})
    seed.remove_demo(conn)
    assert db.scalar(conn, "SELECT COUNT(*) FROM hp_staff") == 1
    assert db.scalar(conn, "SELECT id FROM hp_staff") == real
    assert db.scalar(conn, "SELECT COUNT(*) FROM hp_templates") > 0
