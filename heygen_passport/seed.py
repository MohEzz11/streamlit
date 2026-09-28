"""Reference data (departments, starter checklists, categories, criteria)
and optional clearly-marked demo data.

Starter checklists are EXAMPLES ONLY. Limits such as temperatures must be
confirmed against the hotel's HACCP plan, approved procedures and current
Dubai Municipality guidance before use.
"""

import datetime as dt

from . import config
from .db import IntegrityError, insert_if_absent, row, rows, scalar, transaction, utcnow
from .permissions import Actor
from .security import generate_password
from .services import checklists, expiry, regsources, scoring, staff as staff_svc, users
from .services.common import today_local

SYSTEM = Actor(user_id=None, username="system-seed", role="admin")
# Seeding uses an internal admin-like actor that also has manager rights.
SEED_MANAGER = Actor(user_id=None, username="system-seed", role="manager")

STARTER_NOTE = ("Starter example only. Confirm limits and wording against the hotel HACCP plan, "
                "approved procedures and current Dubai Municipality guidance before use.")

DEPARTMENTS = [("KITCHEN", "Kitchen"), ("STEWARDING", "Stewarding"), ("FNB", "Food & Beverage")]
OUTLETS = {"KITCHEN": ["Main Kitchen", "Pastry", "Banquet Kitchen"],
           "STEWARDING": ["Main Dishwash", "Pot Wash", "Chemical Store"],
           "FNB": ["All-Day Dining", "Lobby Lounge", "Pool Bar", "Banquets"]}

REG_SOURCES = [
    {"title": "Dubai Municipality - Food traders and establishments", "authority": "Dubai Municipality",
     "url": "https://www.dm.gov.ae/municipality-business/food-traders-establishments/",
     "version": "To be confirmed", "notes": "Official starting reference. Confirm current requirements."},
    {"title": "Dubai Municipality - Laws and legislation", "authority": "Dubai Municipality",
     "url": "https://www.dm.gov.ae/municipality-business/",
     "version": "To be confirmed", "notes": "Official starting reference for applicable food legislation."},
    {"title": "Dubai Municipality - Technical guidelines list (incl. kitchen and food-area guidance)",
     "authority": "Dubai Municipality",
     "url": "https://www.dm.gov.ae/municipality-business/technical-guidelines-list/",
     "version": "To be confirmed",
     "notes": "Record the exact guideline title, code and version used for each checklist item."},
    {"title": "Hotel HACCP plan / food safety management system", "authority": "Hotel (internal)",
     "version": "To be confirmed", "notes": "Link items to the hotel's approved procedure numbers."},
]

# (title, instructions, response_type, min, max, unit, priority, risk, verify, due_time)
Y = "yes_no"
P = "pass_fail"
N = "numeric"
T = "text"
PH = "photo"
STARTER_TEMPLATES = {
    "KITCHEN": [
        ("Kitchen opening checks", [
            ("Personal hygiene and uniform check", "All team members: clean uniform, hair covered, no jewellery, "
             "nails short, cuts covered with blue plaster, fit for work (no symptoms of illness). Answer Yes if all comply.",
             Y, None, None, None, "high", "high", False, "07:00"),
            ("Chiller temperature reading", "Read the chiller display/probe. Record the air temperature.",
             N, None, 5, "°C", "high", "critical", True, "07:30"),
            ("Freezer temperature reading", "Read the freezer display/probe. Record the temperature.",
             N, None, -18, "°C", "high", "critical", True, "07:30"),
            ("Food storage and segregation", "Raw below ready-to-eat, covered, labelled, off the floor, "
             "vegetarian/allergen items separated. Answer Pass if compliant.", P, None, None, None, "high", "high", False, "08:00"),
            ("Food expiry and date-label check", "Check all items for use-by dates and labels. Remove expired "
             "items and record them in Expiry tracking.", P, None, None, None, "high", "high", False, "08:00"),
            ("Equipment condition", "Probes calibrated and sanitised, equipment clean and working. Report faults.",
             P, None, None, None, "medium", "medium", False, "08:00"),
        ]),
        ("Kitchen production and holding checks", [
            ("Cooking core temperature", "Probe the thickest part of a cooked item. Record the core temperature.",
             N, 75, None, "°C", "high", "critical", True, "12:00"),
            ("Hot holding temperature", "Probe hot-held food. Record the lowest reading.",
             N, 60, None, "°C", "high", "critical", False, "13:00"),
            ("Cold holding temperature", "Probe cold-held food. Record the highest reading.",
             N, None, 5, "°C", "high", "critical", False, "13:00"),
            ("Cooling record", "Record the food temperature at the end of the cooling period.",
             N, None, 5, "°C", "high", "critical", True, "15:00"),
            ("Reheating temperature", "If food was reheated, record the core temperature reached.",
             N, 75, None, "°C", "medium", "high", False, "18:00"),
            ("Allergen controls", "Allergen matrix up to date, separate utensils/boards used, allergen orders "
             "prepared separately. Answer Pass if compliant.", P, None, None, None, "high", "critical", True, "11:00"),
            ("Cross-contamination prevention", "Colour-coded boards/knives in use, hand-wash stations stocked.",
             P, None, None, None, "high", "high", False, "11:00"),
        ]),
        ("Kitchen closing and handover", [
            ("Cleaning and sanitising completed", "Surfaces, equipment and floors cleaned and sanitised per schedule. "
             "Attach a photo of the cleaned area.", PH, None, None, None, "medium", "high", True, "22:00"),
            ("Equipment handover", "Note equipment issues, stock concerns or open actions for the next shift.",
             T, None, None, None, "medium", "low", False, "22:30"),
        ]),
    ],
    "STEWARDING": [
        ("Stewarding daily checks", [
            ("Dishwasher wash temperature", "Record the wash tank temperature from the machine display.",
             N, 60, None, "°C", "high", "high", True, "07:30"),
            ("Dishwasher final rinse temperature", "Record the final rinse temperature (or chemical sanitiser "
             "concentration if a low-temperature machine - confirm with manufacturer).", N, 82, None, "°C",
             "high", "critical", True, "07:30"),
            ("Clean utensil and equipment storage", "Clean items stored inverted/covered, off the floor, dry.",
             P, None, None, None, "medium", "medium", False, "09:00"),
            ("Chemical labelling and safe storage", "All chemicals labelled, stored away from food, SDS available, "
             "dispensers working.", P, None, None, None, "high", "high", False, "09:00"),
            ("Chemical and supply expiry check", "Check chemical and relevant supply expiry dates. Record items in "
             "Expiry tracking.", P, None, None, None, "medium", "medium", False, "10:00"),
            ("Waste handling", "Bins lidded, lined, emptied; waste area clean; segregation followed.",
             P, None, None, None, "medium", "medium", False, "15:00"),
            ("Cleaning schedule and area checks", "Scheduled deep-clean tasks for today completed. Attach a photo.",
             PH, None, None, None, "medium", "medium", True, "20:00"),
            ("Equipment faults / maintenance escalation", "List any faults and the work order number raised, "
             "or write 'None'.", T, None, None, None, "medium", "medium", False, "21:00"),
        ]),
    ],
    "FNB": [
        ("F&B outlet opening", [
            ("Staff hygiene and uniform check", "Clean uniform, name badge, hair tidy, no strong fragrance, fit for "
             "work. Answer Yes if all comply.", Y, None, None, None, "high", "high", False, "06:30"),
            ("Outlet cleanliness and setup", "Tables, chairs, cutlery, glassware and linen clean and set to standard.",
             P, None, None, None, "medium", "low", False, "06:45"),
            ("Food display temperature", "Probe chilled display items (highest reading).",
             N, None, 5, "°C", "high", "critical", True, "07:00"),
            ("Buffet and service-area check", "Sneeze guards, serving utensils per dish, labels incl. allergens, "
             "hot/cold holding equipment working.", P, None, None, None, "high", "high", True, "07:00"),
            ("Allergen communication briefing", "Team briefed on today's menu allergens and how to escalate "
             "guest allergen requests.", Y, None, None, None, "high", "critical", False, "06:45"),
            ("Expiry and date-label checks (F&B items)", "Check milk, juices, garnishes, syrups and opened bottles "
             "for dates and labels.", P, None, None, None, "high", "high", False, "07:00"),
        ]),
        ("F&B service handover and closing", [
            ("Guest-service handover", "Record VIPs, allergy guests, complaints and pending requests for next shift.",
             T, None, None, None, "medium", "medium", False, "15:00"),
            ("Cleaning and closing duties", "Outlet cleaned, food returned/discarded per procedure, equipment off. "
             "Attach photo.", PH, None, None, None, "medium", "medium", True, "23:00"),
        ]),
    ],
}

EXPIRY_CATEGORIES = [
    {"name": "Raw food", "kind": "food", "reminder_days": 2},
    {"name": "Opened food items", "kind": "food", "reminder_days": 1, "shelf_life_after_open_days": 3},
    {"name": "Prepared food", "kind": "prepared_food", "reminder_days": 1, "shelf_life_after_prep_days": 2,
     "requires_evidence": True},
    {"name": "Beverages", "kind": "beverage", "reminder_days": 7},
    {"name": "Opened beverages / mixers", "kind": "beverage", "reminder_days": 1, "shelf_life_after_open_days": 5},
    {"name": "Cleaning chemicals", "kind": "chemical", "reminder_days": 30},
    {"name": "First-aid supplies", "kind": "first_aid", "reminder_days": 30},
    {"name": "Controlled supplies", "kind": "supply", "reminder_days": 14},
]

CRITERIA = [
    {"name": "Assigned duty completion", "source": "auto_duty_completion", "category": "duty", "weight": 40,
     "description": "Automatic: on-time recording of duties explicitly assigned to the person."},
    {"name": "Food-safety certifications in date", "source": "auto_training", "category": "training", "weight": 20,
     "description": "Automatic: share of the person's certifications that are not expired."},
    {"name": "Hygiene and food-safety observation", "source": "manual", "category": "observation", "weight": 25,
     "description": "Verified supervisor/manager observation of hygiene and food-safety practice."},
    {"name": "Exception handling and reporting", "source": "manual", "category": "exception", "weight": 15,
     "description": "Quality of documented exceptions and corrective actions taken."},
]


def init_reference_data(conn):
    """Idempotent: only inserts what is missing, never overwrites edits."""
    report = []
    now = utcnow()
    with transaction(conn):
        for k, v in config.DEFAULT_SETTINGS.items():
            insert_if_absent(conn, "hp_settings", {"[key]": k, "value": v, "updated_at": now}, ["[key]"])
        for code, name in DEPARTMENTS:
            if not row(conn, "SELECT id FROM hp_departments WHERE code=?", (code,)):
                conn.execute("INSERT INTO hp_departments(code, name, created_at) VALUES (?,?,?)", (code, name, now))
                report.append(f"department {name}")
        for code, names in OUTLETS.items():
            did = row(conn, "SELECT id FROM hp_departments WHERE code=?", (code,))["id"]
            for n in names:
                insert_if_absent(conn, "hp_outlets", {"department_id": did, "name": n, "created_at": now},
                                 ["department_id", "name"])
    review = (today_local(conn) + dt.timedelta(days=90)).isoformat()
    if not scalar(conn, "SELECT COUNT(*) FROM hp_reg_sources"):
        for src in REG_SOURCES:
            regsources.save_source(conn, SEED_MANAGER, dict(src, review_date=review))
        report.append("regulatory references")
    src_id = row(conn, "SELECT id FROM hp_reg_sources WHERE title LIKE 'Hotel HACCP%'")["id"]
    if not scalar(conn, "SELECT COUNT(*) FROM hp_expiry_categories"):
        for c in EXPIRY_CATEGORIES:
            expiry.save_category(conn, SEED_MANAGER, dict(c, procedure_note=STARTER_NOTE))
        report.append("expiry categories")
    if not scalar(conn, "SELECT COUNT(*) FROM hp_score_criteria"):
        for c in CRITERIA:
            scoring.save_criterion(conn, SEED_MANAGER, c)
        report.append("scoring criteria")
    if not scalar(conn, "SELECT COUNT(*) FROM hp_templates WHERE is_starter=1"):
        for code, templates in STARTER_TEMPLATES.items():
            did = row(conn, "SELECT id FROM hp_departments WHERE code=?", (code,))["id"]
            for tname, items in templates:
                tid = checklists.save_template(conn, SEED_MANAGER, did, tname, STARTER_NOTE, is_starter=True)
                for i, (title, instr, rt, mn, mx, unit, prio, risk, verify, due) in enumerate(items):
                    checklists.save_template_item(conn, SEED_MANAGER, tid, {
                        "title": title, "instructions": instr, "response_type": rt, "min_value": mn,
                        "max_value": mx, "unit": unit, "priority": prio, "risk_level": risk,
                        "requires_verification": verify, "due_time": due, "window_minutes": 60,
                        "sort_order": i, "reg_source_id": src_id, "reg_clause": "Review required"})
        report.append("starter checklist templates")
    return report


# ------------------------------------------------------------------ demo
DEMO_STAFF = [
    ("KITCHEN", "DEMO-K001", "Demo Chef Aisha", "Sous Chef", "Main Kitchen", "Morning", "supervisor"),
    ("KITCHEN", "DEMO-K002", "Demo Cook Ravi", "Commis Chef", "Main Kitchen", "Morning", "staff"),
    ("KITCHEN", "DEMO-K003", "Demo Cook Maria", "Chef de Partie", "Pastry", "Afternoon", None),
    ("STEWARDING", "DEMO-S001", "Demo Steward Lead Omar", "Chief Steward", "Main Dishwash", "Morning", "supervisor"),
    ("STEWARDING", "DEMO-S002", "Demo Steward Joy", "Steward", "Main Dishwash", "Morning", "staff"),
    ("FNB", "DEMO-F001", "Demo Supervisor Leila", "F&B Supervisor", "All-Day Dining", "Morning", "supervisor"),
    ("FNB", "DEMO-F002", "Demo Server Sam", "Waiter", "All-Day Dining", "Morning", "staff"),
]


def seed_demo(conn):
    """Create clearly marked demo staff, accounts, schedules and expiry
    items. Every demo record has is_demo=1 and a DEMO- prefix. Returns
    the generated demo login credentials."""
    if scalar(conn, "SELECT COUNT(*) FROM hp_staff WHERE is_demo=1"):
        return None
    creds = []
    today = today_local(conn)
    dept = {r["code"]: r["id"] for r in rows(conn, "SELECT id, code FROM hp_departments")}
    outlet = {(r["department_id"], r["name"]): r["id"] for r in rows(conn, "SELECT * FROM hp_outlets")}
    ids = {}
    for code, emp, name, title, out, shift, role in DEMO_STAFF:
        sid = staff_svc.save_staff(conn, SEED_MANAGER, {
            "employee_id": emp, "full_name": name, "job_title": title, "department_id": dept[code],
            "outlet_id": outlet.get((dept[code], out)), "shift_pattern": shift,
            "start_date": (today - dt.timedelta(days=400)).isoformat(),
            "work_email": f"{emp.lower()}@example.invalid", "notes": "DEMO RECORD - not a real person."},
            is_demo=True)
        ids[emp] = sid
        staff_svc.save_certification(conn, SEED_MANAGER, sid, {
            "name": "Food Safety Training (PIC/handler)", "cert_type": "food_safety", "issuer": "Demo provider",
            "issue_date": (today - dt.timedelta(days=700)).isoformat(),
            "expiry_date": (today + dt.timedelta(days=20 if emp.endswith("2") else 200)).isoformat()})
        if role:
            pw = generate_password()
            users.create_user(conn, None, emp.lower(), pw, role, staff_id=sid, department_id=dept[code],
                              can_score=False, is_demo=True, must_change_password=False)
            creds.append((emp.lower(), pw, role))
    # Supervisors of staff.
    for code, emp, *_ in DEMO_STAFF:
        sup = {"KITCHEN": "DEMO-K001", "STEWARDING": "DEMO-S001", "FNB": "DEMO-F001"}[code]
        if emp != sup:
            conn.execute("UPDATE hp_staff SET supervisor_staff_id=? WHERE id=?", (ids[sup], ids[emp]))
    pw = generate_password()
    users.create_user(conn, None, "demo.manager", pw, "manager", is_demo=True, must_change_password=False)
    creds.append(("demo.manager", pw, "manager"))
    # Schedules: assign each department's templates daily.
    for t in rows(conn, "SELECT * FROM hp_templates WHERE is_starter=1"):
        code = row(conn, "SELECT code FROM hp_departments WHERE id=?", (t["department_id"],))["code"]
        assignee = {"KITCHEN": ids["DEMO-K002"], "STEWARDING": ids["DEMO-S002"], "FNB": ids["DEMO-F002"]}[code]
        checklists.save_schedule(conn, SEED_MANAGER, {
            "template_id": t["id"], "assigned_staff_id": assignee, "shift": "any",
            "start_date": (today - dt.timedelta(days=7)).isoformat(), "days_of_week": list(range(7))})
    cats = {r["name"]: r["id"] for r in rows(conn, "SELECT id, name FROM hp_expiry_categories")}
    demo_items = [
        ("DEMO Chicken breast", "Raw food", "KITCHEN", "Walk-in chiller 1", "LOT-DEMO-01", 10, "kg", 1, None),
        ("DEMO Opened mayonnaise", "Opened food items", "KITCHEN", "Line chiller", "LOT-DEMO-02", 1, "jar", 30, -2),
        ("DEMO Cooked rice", "Prepared food", "KITCHEN", "Walk-in chiller 2", None, 3, "kg", 1, None),
        ("DEMO Yoghurt", "Raw food", "KITCHEN", "Walk-in chiller 1", "LOT-DEMO-03", 12, "cups", -1, None),
        ("DEMO Dishwash detergent", "Cleaning chemicals", "STEWARDING", "Chemical store", "LOT-DEMO-04", 4, "drums", 20, None),
        ("DEMO First-aid kit refill", "First-aid supplies", "STEWARDING", "Dishwash office", None, 1, "kit", 90, None),
        ("DEMO Fresh orange juice", "Beverages", "FNB", "Bar chiller", "LOT-DEMO-05", 5, "L", 2, None),
        ("DEMO Opened tonic water", "Opened beverages / mixers", "FNB", "Pool bar", None, 6, "bottles", 60, -6),
    ]
    for name, cat, code, loc, lot, qty, unit, exp_days, opened in demo_items:
        expiry.save_item(conn, SEED_MANAGER, {
            "name": name, "category_id": cats[cat], "department_id": dept[code], "location": loc, "batch_lot": lot,
            "quantity": qty, "unit": unit, "expiry_date": (today + dt.timedelta(days=exp_days)).isoformat(),
            "opened_on": (today + dt.timedelta(days=opened)).isoformat() if opened is not None else None,
            "prepared_on": today.isoformat() if cat == "Prepared food" else None,
            "responsible_staff_id": ids.get({"KITCHEN": "DEMO-K002", "STEWARDING": "DEMO-S002",
                                             "FNB": "DEMO-F002"}[code])}, is_demo=True)
    return creds


def remove_demo(conn):
    """Delete only records flagged is_demo=1 (and rows that depend on them)."""
    with transaction(conn):
        sids = [r["id"] for r in rows(conn, "SELECT id FROM hp_staff WHERE is_demo=1")]
        uids = [r["id"] for r in rows(conn, "SELECT id FROM hp_users WHERE is_demo=1")]
        q = lambda ids: ",".join(str(int(i)) for i in ids) or "NULL"  # noqa: E731
        conn.execute("DELETE FROM hp_expiry_actions WHERE item_id IN (SELECT id FROM hp_expiry_items WHERE is_demo=1)")
        conn.execute("DELETE FROM hp_expiry_items WHERE is_demo=1")
        conn.execute(f"DELETE FROM hp_scores WHERE staff_id IN ({q(sids)})")
        conn.execute(f"DELETE FROM hp_coaching_notes WHERE staff_id IN ({q(sids)})")
        conn.execute(f"DELETE FROM hp_certifications WHERE staff_id IN ({q(sids)})")
        conn.execute(f"DELETE FROM hp_staff_field_values WHERE staff_id IN ({q(sids)})")
        conn.execute(f"DELETE FROM hp_corrective_actions WHERE staff_id IN ({q(sids)}) OR owner_user_id IN ({q(uids)})")
        conn.execute(f"DELETE FROM hp_duties WHERE assigned_staff_id IN ({q(sids)})")
        conn.execute(f"DELETE FROM hp_schedules WHERE assigned_staff_id IN ({q(sids)})")
        conn.execute(f"UPDATE hp_duties SET completed_by_user_id=NULL, verified_by_user_id=NULL "
                     f"WHERE completed_by_user_id IN ({q(uids)}) OR verified_by_user_id IN ({q(uids)})")
        conn.execute(f"UPDATE hp_duties SET completed_by_staff_id=NULL WHERE completed_by_staff_id IN ({q(sids)})")
        conn.execute(f"DELETE FROM hp_alerts WHERE staff_id IN ({q(sids)})")
        for uid in uids:
            try:
                conn.execute("DELETE FROM hp_users WHERE id=?", (uid,))
            except IntegrityError:
                # Demo user acted on real records: keep the audit link, disable login.
                conn.execute("UPDATE hp_users SET active=0 WHERE id=?", (uid,))
        conn.execute(f"UPDATE hp_staff SET supervisor_staff_id=NULL WHERE supervisor_staff_id IN ({q(sids)})")
        conn.execute(f"DELETE FROM hp_staff WHERE id IN ({q(sids)})")
    return len(sids), len(uids)
