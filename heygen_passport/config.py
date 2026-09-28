"""Runtime configuration. Everything comes from environment variables so no
paths, credentials or secrets live in source code."""

import os
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent

# SQLite database file for Heygen Passport. Kept separate from any other
# system's data. Override with HEYGEN_DB_PATH (e.g. on a persistent volume).
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
