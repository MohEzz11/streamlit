"""Heygen Passport management commands.

    python -m heygen_passport.manage init            # migrate + reference data
    python -m heygen_passport.manage create-admin    # first administrator (prompts)
    python -m heygen_passport.manage create-user --role manager
    python -m heygen_passport.manage migrate
    python -m heygen_passport.manage rollback --confirm   # backs up DB first
    python -m heygen_passport.manage seed-demo       # clearly marked demo data
    python -m heygen_passport.manage remove-demo
    python -m heygen_passport.manage daily           # generate duties + raise alerts
    python -m heygen_passport.manage status
"""

import argparse
import getpass
import os
import sys

from . import config, db, seed
from .security import ValidationError
from .services import alerts, checklists, users


def _password(args):
    env = os.environ.get("HEYGEN_NEW_USER_PASSWORD")
    if env:
        return env
    while True:
        pw = getpass.getpass("Password (min 10 chars, mixed): ")
        if pw == getpass.getpass("Repeat password: "):
            return pw
        print("Passwords do not match.")


def main(argv=None):
    p = argparse.ArgumentParser(prog="heygen_passport.manage")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    rb = sub.add_parser("rollback")
    rb.add_argument("--confirm", action="store_true")
    sub.add_parser("init")
    for name in ("create-admin", "create-user"):
        c = sub.add_parser(name)
        c.add_argument("--username", default=None)
        if name == "create-user":
            c.add_argument("--role", choices=("manager", "admin"), required=True)
    sub.add_parser("seed-demo")
    sub.add_parser("remove-demo")
    d = sub.add_parser("daily")
    d.add_argument("--date", default=None)
    sub.add_parser("status")
    args = p.parse_args(argv)

    conn = db.connect()
    print(f"Database: {config.DB_PATH}")
    try:
        if args.cmd == "migrate":
            print("Applied:", db.migrate_up(conn) or "nothing (up to date)")
        elif args.cmd == "rollback":
            if not args.confirm:
                print("Rollback drops the latest migration's hp_ tables. Re-run with --confirm. "
                      "A backup copy is taken first.")
                return 1
            version, bak = db.migrate_down(conn)
            print(f"Rolled back {version}. Backup: {bak}")
        elif args.cmd == "init":
            print("Applied migrations:", db.migrate_up(conn) or "none (up to date)")
            print("Reference data added:", seed.init_reference_data(conn) or "none (already present)")
        elif args.cmd in ("create-admin", "create-user"):
            db.migrate_up(conn)
            role = "admin" if args.cmd == "create-admin" else args.role
            if args.cmd == "create-admin" and conn.execute(
                    "SELECT COUNT(*) FROM hp_users WHERE role='admin' AND active=1").fetchone()[0]:
                print("An active administrator already exists. Use the Users page to add more, "
                      "or 'create-user --role admin' on the server.")
                return 1
            username = args.username or input("Username: ").strip()
            uid = users.create_user(conn, None, username, _password(args), role, must_change_password=False)
            print(f"Created {role} '{username}' (id {uid}).")
        elif args.cmd == "seed-demo":
            creds = seed.seed_demo(conn)
            if creds is None:
                print("Demo data already present.")
            else:
                print("Demo accounts (DEMO data only; remove with 'remove-demo'):")
                for u, pw, role in creds:
                    print(f"  {role:<11} {u:<14} {pw}")
        elif args.cmd == "remove-demo":
            s, u = seed.remove_demo(conn)
            print(f"Removed {s} demo staff profiles and {u} demo accounts.")
        elif args.cmd == "daily":
            n = checklists.generate_duties(conn, args.date)
            a = alerts.scan(conn)
            print(f"Created {n} duty instance(s); raised {a} new alert(s).")
        elif args.cmd == "status":
            print("Migrations:", sorted(db.applied_versions(conn)))
            for t in ("hp_users", "hp_staff", "hp_templates", "hp_duties", "hp_expiry_items", "hp_audit_log"):
                print(f"  {t}: {conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]}")
    except ValidationError as e:
        print(f"Error: {e}")
        return 1
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
