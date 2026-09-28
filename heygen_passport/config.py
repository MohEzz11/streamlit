"""Runtime configuration.

Settings come from environment variables, or from an optional
``heygen_passport/local.env`` file (KEY=VALUE per line) that stays on the
hotel's machine and is never committed. No credentials live in source code.
"""

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
LOCAL_ENV_FILE = Path(os.environ.get("HEYGEN_ENV_FILE", PACKAGE_DIR / "local.env"))


def _load_local_env(path):
    """Load KEY=VALUE lines into os.environ without overriding real env vars."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_local_env(LOCAL_ENV_FILE)

# Database engine: "mssql" (Microsoft SQL Server, the hotel's local server)
# or "sqlite" (a single file; only for demos and automated tests).
DB_ENGINE = os.environ.get("HEYGEN_DB_ENGINE", "mssql").strip().lower()

# --- Microsoft SQL Server --------------------------------------------------
# Heygen Passport uses its OWN database on the server (default HeygenPassport).
MSSQL_SERVER = os.environ.get("HEYGEN_MSSQL_SERVER", r"localhost")
MSSQL_DATABASE = os.environ.get("HEYGEN_MSSQL_DATABASE", "HeygenPassport")
MSSQL_DRIVER = os.environ.get("HEYGEN_MSSQL_DRIVER", "ODBC Driver 18 for SQL Server")
# Leave user/password empty to use Windows authentication (Trusted_Connection).
MSSQL_USER = os.environ.get("HEYGEN_MSSQL_USER", "")
MSSQL_PASSWORD = os.environ.get("HEYGEN_MSSQL_PASSWORD", "")
# Local SQL Server installs usually have a self-signed certificate.
MSSQL_TRUST_CERT = os.environ.get("HEYGEN_MSSQL_TRUST_CERT", "yes").lower() in ("1", "yes", "true")
MSSQL_ENCRYPT = os.environ.get("HEYGEN_MSSQL_ENCRYPT", "yes").lower() in ("1", "yes", "true")
# Folder ON THE SQL SERVER MACHINE where rollback backups (.bak) are written.
MSSQL_BACKUP_DIR = os.environ.get("HEYGEN_MSSQL_BACKUP_DIR", "")

# --- SQLite (demo / tests only) --------------------------------------------
DB_PATH = Path(os.environ.get("HEYGEN_DB_PATH", PACKAGE_DIR / "data" / "heygen_passport.db"))

# Port for the Streamlit server. 8501 is used by the existing portfolio app.
PORT = int(os.environ.get("HEYGEN_PORT", "8502"))

MIGRATIONS_DIR = PACKAGE_DIR / "migrations"

# Upload limits for photos and evidence.
MAX_UPLOAD_BYTES = int(os.environ.get("HEYGEN_MAX_UPLOAD_BYTES", str(5 * 1024 * 1024)))

# Login protection.
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15
SESSION_IDLE_MINUTES = int(os.environ.get("HEYGEN_SESSION_IDLE_MINUTES", "30"))

# Default settings written on first init; editable by administrators later.
DEFAULT_SETTINGS = {
    "hotel_name": "Hotel",
    "timezone": "Asia/Dubai",
    "score_scale_max": "5",
    "score_green_threshold": "80",
    "score_amber_threshold": "60",
    "cert_reminder_days": "30",
    "duty_due_soon_minutes": "30",
}
