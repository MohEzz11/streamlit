# Heygen Passport

Hotel operations app for **Kitchen, Stewarding and F&B** teams. It covers staff profiles, daily duties and checklists, expiry tracking, corrective actions, and performance scoring with traffic lights.

It is built with Python 3.11 and Streamlit. The database is **your local Microsoft SQL Server**, in its own **separate database** (default name `HeygenPassport`). The app runs alongside the existing portfolio app on its own port, and it never reads or writes the portfolio app's files or any other database.

| | Existing app | Heygen Passport |
|---|---|---|
| Entry point | `app.py` | `heygen_passport/app.py` |
| Port | 8501 | **8502** (override with `HEYGEN_PORT`) |
| Data | `portfolios.json` | **Microsoft SQL Server**, separate database `HeygenPassport`, all tables prefixed `hp_` |
| Auth | `st.secrets` credentials | Own `hp_users` table, salted PBKDF2-SHA256 hashes |

GitHub only stores the **code**. Hotel data lives only in your SQL Server, and connection settings live only in `heygen_passport/local.env` on your machine, which Git ignores.

## Setup on Windows with a local SQL Server

**Before you start**, the PC that runs the app needs:

* SQL Server 2016 or later (Express is fine) running, and a Windows or SQL login that is allowed to **create a database**. Only the first setup needs that right; afterwards the login only needs to own `HeygenPassport`.
* Python 3.11 or later.
* **Microsoft ODBC Driver 18 for SQL Server** (or 17: set `HEYGEN_MSSQL_DRIVER` to match). Check under *ODBC Data Sources (64-bit) > Drivers*.

**Steps:**

```bat
cd path\to\streamlit
pip install -r heygen_passport\requirements.txt
copy heygen_passport\local.env.example heygen_passport\local.env
notepad heygen_passport\local.env
```

In `local.env`:
* set `HEYGEN_MSSQL_SERVER` to your instance (for example `localhost\SQLEXPRESS`);
* leave user and password empty to use Windows authentication, or enter a **dedicated** SQL login (never `sa`).

Then:

```bat
python -m heygen_passport.manage check          :: tests the connection, creates HeygenPassport if missing
python -m heygen_passport.manage init           :: creates the hp_ tables and reference data (safe to repeat)
python -m heygen_passport.manage create-admin   :: first administrator (asks for username and password)
heygen_passport\run_windows.bat                 :: starts the app on http://<this-pc>:8502
```

On Linux or macOS, use `./heygen_passport/run.sh` instead of the `.bat` file.

Staff phones and tablets on the hotel network open `http://<this-pc-name-or-IP>:8502`. Allow port 8502 through Windows Firewall for the hotel network only, and put the app behind HTTPS before wider use.

Then sign in as the administrator and:

1. Under **Administration**, check departments, outlets, the hotel name and the time zone (default `Asia/Dubai`).
2. Under **Users & access**, create **Heygen Manager** accounts, or run `python -m heygen_passport.manage create-user --role manager`.
3. Managers create staff profiles in the **Staff directory** and give each person a login from the profile's **Access** tab. A temporary password is shown once, and the person must change it at first sign-in.
4. Review the starter checklists (**Checklists**), then create **Assignments** that link templates to a department, outlet, role, shift, days and, optionally, a responsible person.
5. Schedule `python -m heygen_passport.manage daily` once a day at about 00:05 hotel time (Windows Task Scheduler, starting in the repository folder). It creates the day's duties and raises alerts. Dashboards also do this automatically when opened.

### Demo data (optional, for training only)

```bat
python -m heygen_passport.manage seed-demo     :: prints demo logins; every record is DEMO-prefixed, is_demo=1
python -m heygen_passport.manage remove-demo   :: deletes only is_demo records
```

## Database and migrations

* `init` creates the separate `HeygenPassport` database only if it does not exist, and never modifies any other database.
* Every table is prefixed `hp_`. Migrations live in `migrations/mssql/NNNN_name.up.sql` with a matching `.down.sql`, and applied versions are tracked in `hp_schema_migrations`. Each migration runs in a transaction.
* `manage rollback --confirm` first writes a `COPY_ONLY` `.bak` of `HeygenPassport` to `HEYGEN_MSSQL_BACKUP_DIR` (a folder on the SQL Server machine). It refuses to run if that folder is not set, then reverts only the latest migration.
* Reference seeding is additive only. It never overwrites records you have edited.
* Indexes cover the common filters: duty date, department and status; assignee; verification queue; expiry date and state; alert state; audit time and entity.
* Include `HeygenPassport` in the hotel's normal SQL Server backup plan (full plus log backups, as your IT policy requires).
* Dates and times are stored as ISO text (UTC timestamps, hotel-local business dates), so the same logic runs on SQL Server and on the SQLite build.
* SQLite (`HEYGEN_DB_ENGINE=sqlite`) remains available only for automated tests and offline demos. Its migrations live in `migrations/sqlite/`.

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
python -m pytest heygen_passport/tests -q                  # SQLite
HEYGEN_TEST_MSSQL=1 python -m pytest heygen_passport/tests -q   # also on SQL Server (HEYGEN_MSSQL_* settings;
                                                            # creates and drops throwaway hp_test_* databases)
```

## Food-safety disclaimer

Starter checklists, temperature limits and expiry rules are **examples** only. The hotel's food safety manager must review them against the hotel's HACCP plan and approved procedures, and against current Dubai Municipality requirements:
<https://www.dm.gov.ae/municipality-business/food-traders-establishments/>, <https://www.dm.gov.ae/municipality-business/>, <https://www.dm.gov.ae/municipality-business/technical-guidelines-list/>.
This application supports the food-safety management system. It does not certify compliance, and it does not replace the HACCP plan, training or official inspections.
