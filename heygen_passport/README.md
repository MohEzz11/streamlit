# Heygen Passport

Hotel operations app for **Kitchen, Stewarding and F&B** teams. It covers staff profiles, daily duties and checklists, expiry tracking, corrective actions, and performance scoring with traffic lights.

It is built with the repository's existing stack (Python 3.11 and Streamlit). It runs **alongside** the existing portfolio app on its own port and has its own database. It never reads or writes the portfolio app's files.

| | Existing app | Heygen Passport |
|---|---|---|
| Entry point | `app.py` | `heygen_passport/app.py` |
| Port | 8501 | **8502** (override with `HEYGEN_PORT`) |
| Data | `portfolios.json` | SQLite `heygen_passport/data/heygen_passport.db` (override with `HEYGEN_DB_PATH`) |
| Auth | `st.secrets` credentials | Own `hp_users` table, salted PBKDF2-SHA256 hashes |

## Quick start

```bash
pip install -r heygen_passport/requirements.txt
python -m heygen_passport.manage init           # create tables and reference data (safe to repeat)
python -m heygen_passport.manage create-admin   # first administrator (prompts for username and password)
./heygen_passport/run.sh                        # serves http://<host>:8502
```

Then sign in as the administrator and:

1. Under **Administration**, check departments, outlets, the hotel name and the time zone (default `Asia/Dubai`).
2. Under **Users & access**, create **Heygen Manager** accounts. Managers can also be created on the server with `python -m heygen_passport.manage create-user --role manager`.
3. Managers create staff profiles in the **Staff directory** and give each person a login from the profile's **Access** tab. A temporary password is shown once, and the person must change it at first sign-in.
4. Review the starter checklists (**Checklists**), then create **Assignments** that link templates to a department, outlet, role, shift, days and, optionally, a responsible person.
5. Once a day, run `python -m heygen_passport.manage daily` (for example from cron at 00:05 hotel time). It creates the day's duties and raises alerts. Dashboards also do this automatically when they are opened.

### Demo data (optional, for training only)

```bash
python -m heygen_passport.manage seed-demo     # prints demo logins; every record is DEMO-prefixed, is_demo=1
python -m heygen_passport.manage remove-demo   # deletes only is_demo records
```

## Database and migrations

* Every table is prefixed `hp_`. Migrations live in `migrations/NNNN_name.up.sql` with a matching `.down.sql` file, and applied versions are tracked in `hp_schema_migrations`.
* `manage migrate` applies pending migrations. `manage rollback --confirm` takes a timestamped backup copy of the database file **first**, then reverts only the latest migration.
* Reference seeding is additive only. It never overwrites records you have edited.
* Indexes cover the common filters: duty date, department and status; assignee; verification queue; expiry date and state; alert state; audit time and entity.
* Back up the DB file regularly. SQLite's online backup is used by `db.backup()`, and `sqlite3 file.db ".backup copy.db"` also works.

## Roles (enforced in `services/*` via `permissions.require`, not only in the UI)

| Role | Can |
|---|---|
| Staff member | See own profile, own and shift-pool duties, complete them, record expiry actions in own department, and see own scores, feedback, coaching notes and certifications |
| Department supervisor | Everything a staff member can do, plus manage templates and assignments for their own department, verify or reject checks (never their own), raise, assign and resolve corrective actions, manage expiry items, write coaching notes, and view reports. Can award scores **only if** granted "may award scores" |
| Heygen Manager | All departments; configure scoring criteria, weights and thresholds; award scores; expiry categories and reminder periods; staff profiles and certifications; staff and supervisor accounts; regulatory references |
| Administrator | Everything a manager can do except award scores, plus manage all accounts and roles, departments and outlets, system settings, configurable profile fields and the audit log |

## Security notes

* No credentials in source. The first admin is created from the CLI, and temporary passwords are random.
* An account locks for 15 minutes after 5 failed logins, and the error message does not say whether the username exists. Sessions time out after 30 idle minutes (`HEYGEN_SESSION_IDLE_MINUTES`). Role and deactivation changes apply on the user's next click.
* All SQL is parameterised. User text is escaped before any HTML rendering. Uploads are limited to 5 MB and checked by file signature (JPEG, PNG, WebP, PDF only). XSRF protection is on (the existing app disables it; this app does not).
* Every create, change, assign, complete, verify, score, expiry check, alert, and corrective-action raise and resolve writes to `hp_audit_log` with user and UTC time. Times are shown in hotel local time.
* Saves are atomic. The UI shows either "Recorded at HH:MM" or "NOT saved: reason", and on failure the entry stays on screen.

## Scoring

See the **Performance > How scores are calculated** tab or `services/scoring.py`. In short, the score is a weighted average of the criteria that have data in the date range. Automatic duty scoring counts **only duties explicitly assigned to the person**. Raising an exception counts as doing the duty. Every traffic light is shown with its % and its reasons.

## Tests

```bash
python -m pytest heygen_passport/tests -q
```

## Food-safety disclaimer

Starter checklists, temperature limits and expiry rules are **examples** only. The hotel's food safety manager must review them against the hotel's HACCP plan and approved procedures, and against current Dubai Municipality requirements:
<https://www.dm.gov.ae/municipality-business/food-traders-establishments/>, <https://www.dm.gov.ae/municipality-business/>, <https://www.dm.gov.ae/municipality-business/technical-guidelines-list/>.
This application supports the food-safety management system. It does not certify compliance, and it does not replace the HACCP plan, training or official inspections.
