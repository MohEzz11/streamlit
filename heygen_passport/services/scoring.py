"""Configurable performance scoring with traffic-light indicators.

How a staff member's score is calculated (also shown in the interface):

1. Each active criterion that applies to the staff member's department gives
   a percentage for the selected date range:
   - manual criteria: average of awarded scores / scale maximum x 100;
   - auto_duty_completion: only duties explicitly ASSIGNED to the person
     and already due. On time = 1, late = 0.5, not recorded = 0.
     Raising an exception counts as recorded (reporting a problem is the
     correct behaviour). Unassigned pool duties never count against anyone;
   - auto_training: share of the person's certifications that are in date.
2. Criteria with no data in the range are left out (not counted as zero).
3. Overall % = sum(weight x criterion %) / sum(weights of criteria with data).
4. Colour: Green if >= green threshold, Amber if >= amber threshold, else Red.
   An open critical corrective action or an overdue follow-up linked to the
   person also shows Red ("urgent follow-up"), with the reason listed.
"""

import datetime as dt

from .. import audit
from ..db import row, rows, transaction, utcnow
from ..permissions import PermissionDenied, dept_scope, has, require
from ..security import ValidationError, clean_text
from .common import get_setting, parse_date, today_local

SOURCES = {"manual": "Manual score (observation / review)",
           "auto_duty_completion": "Automatic: assigned duty completion",
           "auto_training": "Automatic: certifications in date"}
CATEGORIES = ("duty", "observation", "training", "exception", "other")
COLOR_LABELS = {"green": "Green - meeting target", "amber": "Amber - needs attention",
                "red": "Red - below target / urgent follow-up", "none": "No data"}


def thresholds(conn):
    return (float(get_setting(conn, "score_green_threshold")), float(get_setting(conn, "score_amber_threshold")),
            float(get_setting(conn, "score_scale_max")))


def save_thresholds(conn, actor, green, amber, scale_max):
    require(actor, "score.configure")
    green, amber, scale_max = float(green), float(amber), float(scale_max)
    if not (0 < amber < green <= 100):
        raise ValidationError("Thresholds must satisfy 0 < amber < green <= 100.")
    if not (1 <= scale_max <= 100):
        raise ValidationError("Scale maximum must be between 1 and 100.")
    from .common import set_setting
    set_setting(conn, actor, "score_green_threshold", green, perm="score.configure")
    set_setting(conn, actor, "score_amber_threshold", amber, perm="score.configure")
    set_setting(conn, actor, "score_scale_max", scale_max, perm="score.configure")


def criteria(conn, active_only=True, department_id=None):
    sql = """SELECT c.*, d.name AS department FROM hp_score_criteria c
             LEFT JOIN hp_departments d ON d.id=c.department_id WHERE 1=1"""
    params = []
    if active_only:
        sql += " AND c.active=1"
    if department_id:
        sql += " AND (c.department_id IS NULL OR c.department_id=?)"
        params.append(department_id)
    return rows(conn, sql + " ORDER BY c.name", params)


def save_criterion(conn, actor, data, criterion_id=None):
    require(actor, "score.configure")
    name = clean_text(data.get("name"), "Criterion name", 80, required=True)
    desc = clean_text(data.get("description"), "Description", 1000)
    source = data.get("source") or "manual"
    category = data.get("category") or "observation"
    if source not in SOURCES or category not in CATEGORIES:
        raise ValidationError("Invalid source or category.")
    weight = float(data.get("weight") if data.get("weight") not in (None, "") else 1)
    if weight < 0 or weight > 100:
        raise ValidationError("Weight must be between 0 and 100.")
    dept = int(data["department_id"]) if data.get("department_id") else None
    vals = (name, desc, source, category, weight, dept, int(data.get("active", True)))
    with transaction(conn):
        if criterion_id:
            old = row(conn, "SELECT * FROM hp_score_criteria WHERE id=?", (criterion_id,))
            conn.execute("""UPDATE hp_score_criteria SET name=?, description=?, source=?, category=?, weight=?,
                            department_id=?, active=?, updated_at=?, updated_by=? WHERE id=?""",
                         vals + (utcnow(), actor.user_id, criterion_id))
            audit.log(conn, actor, "score_criterion.update", "score_criterion", criterion_id,
                      old={k: old[k] for k in ("name", "weight", "source", "active", "department_id")},
                      new={"name": name, "weight": weight, "source": source, "active": vals[-1], "department_id": dept})
        else:
            cur = conn.execute("""INSERT INTO hp_score_criteria(name, description, source, category, weight,
                                  department_id, active, created_at, created_by) VALUES (?,?,?,?,?,?,?,?,?)""",
                               vals + (utcnow(), actor.user_id))
            criterion_id = cur.lastrowid
            audit.log(conn, actor, "score_criterion.create", "score_criterion", criterion_id,
                      name=name, weight=weight, source=source)
    return criterion_id


def award_score(conn, actor, staff_id, criterion_id, score, reason, score_date=None,
                source_type=None, source_id=None):
    s = row(conn, "SELECT id, department_id FROM hp_staff WHERE id=?", (staff_id,))
    if not s:
        raise ValidationError("Staff member not found.")
    require(actor, "score.award", s["department_id"])
    if actor.staff_id and actor.staff_id == staff_id:
        raise PermissionDenied("You cannot score yourself.")
    c = row(conn, "SELECT * FROM hp_score_criteria WHERE id=? AND active=1", (criterion_id,))
    if not c or c["source"] != "manual":
        raise ValidationError("Choose an active manual scoring criterion.")
    if c["department_id"] and c["department_id"] != s["department_id"]:
        raise ValidationError("This criterion does not apply to the staff member's department.")
    _g, _a, scale_max = thresholds(conn)
    try:
        score = float(score)
    except (TypeError, ValueError):
        raise ValidationError("Score must be a number.")
    if not 0 <= score <= scale_max:
        raise ValidationError(f"Score must be between 0 and {scale_max:g}.")
    reason = clean_text(reason, "Reason", 2000, required=True)
    score_date = parse_date(score_date, "Date") or today_local(conn).isoformat()
    if source_type and source_type not in CATEGORIES:
        raise ValidationError("Invalid evidence type.")
    if source_type == "duty" and source_id:
        d = row(conn, "SELECT assigned_staff_id, completed_by_staff_id FROM hp_duties WHERE id=?", (source_id,))
        if not d or staff_id not in (d["assigned_staff_id"], d["completed_by_staff_id"]):
            raise ValidationError("That duty is not recorded as assigned to or completed by this staff member.")
    with transaction(conn):
        cur = conn.execute("""INSERT INTO hp_scores(staff_id, criterion_id, score, scale_max, score_date, reason,
                              source_type, source_id, awarded_by, awarded_at) VALUES (?,?,?,?,?,?,?,?,?,?)""",
                           (staff_id, criterion_id, score, scale_max, score_date, reason, source_type,
                            source_id, actor.user_id, utcnow()))
        audit.log(conn, actor, "score.award", "score", cur.lastrowid, s["department_id"], staff_id=staff_id,
                  criterion=c["name"], score=score, scale_max=scale_max, reason=reason)
    return cur.lastrowid


def void_score(conn, actor, score_id, reason):
    sc = row(conn, """SELECT sc.*, s.department_id FROM hp_scores sc JOIN hp_staff s ON s.id=sc.staff_id
                      WHERE sc.id=?""", (score_id,))
    if not sc:
        raise ValidationError("Score not found.")
    if not (has(actor, "score.configure") or (sc["awarded_by"] == actor.user_id
                                              and has(actor, "score.award", sc["department_id"]))):
        raise PermissionDenied("You cannot void this score.")
    reason = clean_text(reason, "Reason", 1000, required=True)
    with transaction(conn):
        conn.execute("UPDATE hp_scores SET voided=1, voided_by=?, voided_at=?, void_reason=? WHERE id=?",
                     (actor.user_id, utcnow(), reason, score_id))
        audit.log(conn, actor, "score.void", "score", score_id, sc["department_id"], reason=reason)


def _check_view(conn, actor, staff_id):
    s = row(conn, "SELECT * FROM hp_staff WHERE id=?", (staff_id,))
    if not s:
        raise ValidationError("Staff member not found.")
    if actor.staff_id != staff_id and not has(actor, "score.view", s["department_id"]):
        raise PermissionDenied("You do not have permission to view this performance record.")
    return s


def list_scores(conn, actor, staff_id, date_from=None, date_to=None, include_voided=False):
    _check_view(conn, actor, staff_id)
    sql = """SELECT sc.*, c.name AS criterion, u.username AS awarded_by_name FROM hp_scores sc
             JOIN hp_score_criteria c ON c.id=sc.criterion_id JOIN hp_users u ON u.id=sc.awarded_by
             WHERE sc.staff_id=?"""
    params = [staff_id]
    if not include_voided:
        sql += " AND sc.voided=0"
    if date_from:
        sql += " AND sc.score_date>=?"
        params.append(str(date_from))
    if date_to:
        sql += " AND sc.score_date<=?"
        params.append(str(date_to))
    return rows(conn, sql + " ORDER BY sc.score_date DESC, sc.id DESC", params)


def _duty_component(conn, staff_id, d1, d2):
    now = utcnow()
    ds = rows(conn, """SELECT status, completed_at, due_at FROM hp_duties
                       WHERE assigned_staff_id=? AND duty_date BETWEEN ? AND ? AND due_at < ?""",
              (staff_id, d1, d2, now))
    if not ds:
        return None
    on_time = late = missed = 0
    for d in ds:
        if d["status"] in ("completed", "exception"):
            if d["completed_at"] and d["due_at"] and d["completed_at"] > d["due_at"]:
                late += 1
            else:
                on_time += 1
        else:
            missed += 1
    pct = 100 * (on_time + 0.5 * late) / len(ds)
    return pct, f"{on_time + late} of {len(ds)} assigned duties recorded ({late} late, {missed} not recorded)"


def _training_component(conn, staff_id, d2):
    cs = rows(conn, "SELECT name, expiry_date FROM hp_certifications WHERE staff_id=?", (staff_id,))
    if not cs:
        return None
    valid = [c for c in cs if not c["expiry_date"] or c["expiry_date"] >= str(d2)]
    expired = [c["name"] for c in cs if c not in valid]
    reason = f"{len(valid)} of {len(cs)} certifications in date"
    if expired:
        reason += f" (expired: {', '.join(expired)})"
    return 100 * len(valid) / len(cs), reason


def performance(conn, actor, staff_id, date_from, date_to):
    """Return the score breakdown, colour and reasons for one staff member."""
    s = _check_view(conn, actor, staff_id)
    return _performance(conn, s, str(date_from), str(date_to))


def _performance(conn, s, d1, d2):
    green, amber, _scale = thresholds(conn)
    comps = []
    for c in criteria(conn, department_id=s["department_id"]):
        if c["weight"] <= 0:
            continue
        res = None
        if c["source"] == "manual":
            sc = rows(conn, """SELECT score, scale_max FROM hp_scores WHERE staff_id=? AND criterion_id=?
                               AND voided=0 AND score_date BETWEEN ? AND ?""", (s["id"], c["id"], d1, d2))
            if sc:
                pct = sum(100 * x["score"] / x["scale_max"] for x in sc) / len(sc)
                avg = sum(x["score"] for x in sc) / len(sc)
                res = pct, f"average {avg:.1f}/{sc[0]['scale_max']:g} over {len(sc)} score(s)"
        elif c["source"] == "auto_duty_completion":
            res = _duty_component(conn, s["id"], d1, d2)
        elif c["source"] == "auto_training":
            res = _training_component(conn, s["id"], d2)
        if res:
            comps.append({"criterion": c["name"], "weight": c["weight"], "pct": round(res[0], 1), "reason": res[1]})
    total_w = sum(c["weight"] for c in comps)
    overall = round(sum(c["weight"] * c["pct"] for c in comps) / total_w, 1) if total_w else None
    reasons = [f"{c['criterion']} (weight {c['weight']:g}): {c['pct']:.0f}% - {c['reason']}" for c in comps]
    if overall is None:
        color = "none"
    elif overall >= green:
        color = "green"
    elif overall >= amber:
        color = "amber"
    else:
        color = "red"
    today = today_local(conn).isoformat()
    urgent = rows(conn, """SELECT title, severity, due_date FROM hp_corrective_actions WHERE staff_id=?
                           AND status IN ('open','in_progress') AND (severity='critical' OR due_date < ?)""",
                  (s["id"], today))
    overdue_fu = rows(conn, """SELECT note FROM hp_coaching_notes WHERE staff_id=? AND resolved_at IS NULL
                               AND follow_up_date < ?""", (s["id"], today))
    if urgent or overdue_fu:
        color = "red"
        for u in urgent:
            reasons.append(f"Urgent follow-up: corrective action '{u['title']}' ({u['severity']}"
                           + (f", due {u['due_date']}" if u["due_date"] else "") + ")")
        if overdue_fu:
            reasons.append(f"Urgent follow-up: {len(overdue_fu)} coaching follow-up(s) overdue")
    if overall is None and not reasons:
        reasons.append("No scored activity in this date range.")
    return {"staff_id": s["id"], "full_name": s["full_name"], "employee_id": s["employee_id"],
            "department_id": s["department_id"], "score": overall, "color": color,
            "color_label": COLOR_LABELS[color], "components": comps, "reasons": reasons,
            "thresholds": {"green": green, "amber": amber}}


def team_performance(conn, actor, date_from, date_to, department_id=None):
    require(actor, "score.view", department_id)
    scope = dept_scope(actor)
    sql = "SELECT * FROM hp_staff WHERE employment_status IN ('active','on_leave')"
    params = []
    if scope is not None:
        sql += " AND department_id=?"
        params.append(scope)
    if department_id:
        sql += " AND department_id=?"
        params.append(department_id)
    out = []
    for s in rows(conn, sql + " ORDER BY full_name", params):
        p = _performance(conn, s, str(date_from), str(date_to))
        p["job_title"] = s["job_title"]
        out.append(p)
    return out


def trend(conn, actor, staff_id, date_from, date_to, bucket_days=7):
    """Score per period (default weekly) for charts."""
    s = _check_view(conn, actor, staff_id)
    d1 = dt.date.fromisoformat(str(date_from))
    d2 = dt.date.fromisoformat(str(date_to))
    out = []
    cur = d1
    while cur <= d2:
        end = min(cur + dt.timedelta(days=bucket_days - 1), d2)
        p = _performance(conn, s, cur.isoformat(), end.isoformat())
        out.append({"period_start": cur.isoformat(), "score": p["score"]})
        cur = end + dt.timedelta(days=1)
    return out
