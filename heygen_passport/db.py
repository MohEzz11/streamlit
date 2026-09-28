"""SQLite access and reversible migrations.

Migrations live in migrations/NNNN_name.up.sql with a matching .down.sql.
Applied versions are tracked in hp_schema_migrations. Rolling back always
takes a timestamped backup copy of the database file first.
"""

import shutil
import sqlite3
import datetime as dt
from contextlib import contextmanager
from pathlib import Path

from . import config


def utcnow():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def connect(path=None):
    path = Path(path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=15, isolation_level=None,
                           check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 15000")
    return conn


@contextmanager
def transaction(conn):
    """Run a block atomically. Any exception rolls everything back so a
    checklist or expiry action is either fully recorded or not at all."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def _ensure_migration_table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS hp_schema_migrations (
        version TEXT PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)""")


def _migration_files():
    ups = sorted(config.MIGRATIONS_DIR.glob("*.up.sql"))
    out = []
    for up in ups:
        stem = up.name[: -len(".up.sql")]
        version, _, name = stem.partition("_")
        down = up.with_name(f"{stem}.down.sql")
        out.append((version, name, up, down))
    return out


def applied_versions(conn):
    _ensure_migration_table(conn)
    return {r["version"] for r in conn.execute("SELECT version FROM hp_schema_migrations")}


def migrate_up(conn):
    """Apply all pending migrations. Returns list of applied versions."""
    done = applied_versions(conn)
    applied = []
    for version, name, up, _down in _migration_files():
        if version in done:
            continue
        sql = up.read_text(encoding="utf-8")
        conn.executescript("BEGIN;\n" + sql + f"""
            INSERT INTO hp_schema_migrations(version, name, applied_at)
            VALUES ('{version}', '{name}', '{utcnow()}');
            COMMIT;""")
        applied.append(version)
    return applied


def backup(db_path=None):
    src = Path(db_path or config.DB_PATH)
    if not src.exists():
        return None
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dst = src.with_name(f"{src.stem}.backup-{stamp}{src.suffix}")
    conn = sqlite3.connect(str(src))
    try:
        target = sqlite3.connect(str(dst))
        conn.backup(target)
        target.close()
    finally:
        conn.close()
    return dst


def migrate_down(conn, db_path=None):
    """Roll back the most recent migration after taking a backup."""
    done = applied_versions(conn)
    files = [f for f in _migration_files() if f[0] in done]
    if not files:
        return None, None
    version, name, _up, down = files[-1]
    bak = backup(db_path)
    conn.executescript("BEGIN;\n" + down.read_text(encoding="utf-8") + f"""
        DELETE FROM hp_schema_migrations WHERE version = '{version}';
        COMMIT;""")
    return version, bak


def rows(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def row(conn, sql, params=()):
    r = conn.execute(sql, params).fetchone()
    return dict(r) if r else None


def scalar(conn, sql, params=()):
    r = conn.execute(sql, params).fetchone()
    return r[0] if r else None
