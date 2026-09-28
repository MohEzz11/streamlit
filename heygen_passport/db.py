"""Database access for Microsoft SQL Server (production) and SQLite
(demos/tests), plus reversible migrations.

Services write one SQL dialect: the common subset of T-SQL and SQLite, with
``?`` or ``:name`` parameters. The Connection wrapper below smooths over the
few remaining differences (named parameters, LIMIT, returning new ids,
transactions) so business code does not branch on the engine.

Migrations live in migrations/<engine>/NNNN_name.up.sql with a matching
.down.sql, and applied versions are tracked in hp_schema_migrations. Rolling
back always takes a backup first.
"""

import datetime as dt
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from . import config

try:  # pyodbc is only needed for SQL Server.
    import pyodbc
except ImportError:  # pragma: no cover - sqlite-only installs
    pyodbc = None

IntegrityError = (sqlite3.IntegrityError,) + ((pyodbc.IntegrityError,) if pyodbc else ())
OperationalError = (sqlite3.OperationalError,) + (
    (pyodbc.OperationalError, pyodbc.InterfaceError) if pyodbc else ())

# Tables whose primary key is not an identity "id" column.
_NO_ID_TABLES = {"hp_settings", "hp_staff_field_values", "hp_schema_migrations"}
_INSERT_RE = re.compile(r"^\s*INSERT\s+INTO\s+(\w+)\s*\(([^)]*)\)\s*", re.I)
_NAMED_RE = re.compile(r"(?<![:\w]):([A-Za-z_]\w*)")
_LIMIT_RE = re.compile(r"\s+LIMIT\s+(\?|\d+)\s*$", re.I)
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_]{1,100}$")


def utcnow():
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


class Row(dict):
    """A result row usable as a dict (row["col"]) or by position (row[0])."""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class Result:
    def __init__(self, rows=None, rowcount=-1, lastrowid=None):
        self._rows = rows or []
        self.rowcount = rowcount
        self.lastrowid = lastrowid

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


def _rows_from_cursor(cur):
    if cur.description is None:
        return []
    cols = [d[0] for d in cur.description]
    return [Row(zip(cols, r)) for r in cur.fetchall()]


class Connection:
    """Thin wrapper with one interface for both engines."""

    def __init__(self, raw, dialect, label):
        self.raw = raw
        self.dialect = dialect
        self.label = label
        self._depth = 0

    # -- statements -------------------------------------------------------
    def _translate(self, sql, params):
        if self.dialect != "mssql":
            return sql, params
        if isinstance(params, dict):
            names = _NAMED_RE.findall(sql)
            sql = _NAMED_RE.sub("?", sql)
            params = [params[n] for n in names]
        m = _LIMIT_RE.search(sql)
        if m:
            sql = sql[: m.start()] + f" OFFSET 0 ROWS FETCH NEXT {m.group(1)} ROWS ONLY"
        return sql, list(params or [])

    def execute(self, sql, params=()):
        sql, params = self._translate(sql, params)
        if self.dialect == "sqlite":
            cur = self.raw.execute(sql, params)
            rows = [Row(zip([d[0] for d in cur.description], r)) for r in cur.fetchall()] \
                if cur.description else []
            return Result(rows, cur.rowcount, cur.lastrowid)
        cur = self.raw.cursor()
        try:
            m = _INSERT_RE.match(sql)
            if m and m.group(1).lower() not in _NO_ID_TABLES:
                # Return the new identity value in the same statement.
                sql = sql[: m.end()] + "OUTPUT INSERTED.id " + sql[m.end():]
                cur.execute(sql, params)
                got = cur.fetchall()
                new_id = int(got[0][0]) if got else None
                return Result([], 1 if got else 0, new_id)
            cur.execute(sql, params)
            return Result(_rows_from_cursor(cur), cur.rowcount)
        finally:
            cur.close()

    def run_script(self, script):
        """Run a migration script. SQL Server scripts are split on GO lines."""
        if self.dialect == "sqlite":
            self.raw.executescript(script)
            return
        for batch in re.split(r"^\s*GO\s*$", script, flags=re.M | re.I):
            if batch.strip():
                cur = self.raw.cursor()
                cur.execute(batch)
                cur.close()

    # -- transactions -----------------------------------------------------
    def begin(self):
        if self._depth == 0:
            if self.dialect == "sqlite":
                self.raw.execute("BEGIN IMMEDIATE")
            else:
                self.raw.autocommit = False
        self._depth += 1

    def commit(self):
        self._depth -= 1
        if self._depth == 0:
            self.raw.commit() if self.dialect == "mssql" else self.raw.execute("COMMIT")
            if self.dialect == "mssql":
                self.raw.autocommit = True

    def rollback(self):
        self._depth = 0
        if self.dialect == "sqlite":
            if self.raw.in_transaction:
                self.raw.execute("ROLLBACK")
        else:
            self.raw.rollback()
            self.raw.autocommit = True

    def close(self):
        self.raw.close()


# ------------------------------------------------------------------ connect
def mssql_connection_string(database=None):
    parts = [f"DRIVER={{{config.MSSQL_DRIVER}}}", f"SERVER={config.MSSQL_SERVER}",
             f"DATABASE={database or config.MSSQL_DATABASE}"]
    if config.MSSQL_USER:
        parts += [f"UID={config.MSSQL_USER}", "PWD={" + config.MSSQL_PASSWORD.replace("}", "}}") + "}"]
    else:
        parts.append("Trusted_Connection=yes")
    parts.append(f"Encrypt={'yes' if config.MSSQL_ENCRYPT else 'no'}")
    if config.MSSQL_TRUST_CERT:
        parts.append("TrustServerCertificate=yes")
    parts.append("APP=HeygenPassport")
    return ";".join(parts) + ";"


def connect(path=None, engine=None):
    """Open a connection. Passing a path always means a SQLite file."""
    engine = "sqlite" if path else (engine or config.DB_ENGINE)
    if engine == "mssql":
        if pyodbc is None:
            raise RuntimeError("pyodbc is not installed. Run: pip install pyodbc")
        raw = pyodbc.connect(mssql_connection_string(), autocommit=True, timeout=15)
        return Connection(raw, "mssql", f"{config.MSSQL_SERVER}/{config.MSSQL_DATABASE}")
    if engine != "sqlite":
        raise RuntimeError(f"Unknown HEYGEN_DB_ENGINE '{engine}' (use mssql or sqlite).")
    path = Path(path or config.DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = sqlite3.connect(str(path), timeout=15, isolation_level=None, check_same_thread=False)
    raw.execute("PRAGMA foreign_keys = ON")
    raw.execute("PRAGMA journal_mode = WAL")
    raw.execute("PRAGMA busy_timeout = 15000")
    return Connection(raw, "sqlite", str(path))


def create_mssql_database(name=None):
    """Create the separate Heygen database on the SQL Server if it does not
    exist. Never touches any other database. Returns True if created."""
    name = name or config.MSSQL_DATABASE
    if not _SAFE_NAME.match(name):
        raise ValueError("Database name may only contain letters, digits and underscores.")
    raw = pyodbc.connect(mssql_connection_string("master"), autocommit=True, timeout=15)
    try:
        cur = raw.cursor()
        cur.execute("SELECT DB_ID(?)", name)
        if cur.fetchone()[0] is not None:
            return False
        cur.execute(f"CREATE DATABASE [{name}]")
        return True
    finally:
        raw.close()


@contextmanager
def transaction(conn):
    """Run a block atomically. Any exception rolls everything back so a
    checklist or expiry action is either fully recorded or not at all."""
    conn.begin()
    try:
        yield conn
    except BaseException:
        conn.rollback()
        raise
    else:
        conn.commit()


def insert_if_absent(conn, table, values, key_cols):
    """INSERT a row unless one with the same key columns exists. Works on
    both engines and tolerates a concurrent insert of the same key.
    Returns a result whose rowcount is 1 if inserted (0 if it already existed)
    and whose lastrowid is the new id where the table has one. Call inside a
    transaction."""
    cols = list(values)
    where = " AND ".join(f"{k} IS NULL" if values[k] is None else f"{k} = ?" for k in key_cols)
    key_params = [values[k] for k in key_cols if values[k] is not None]
    sql = (f"INSERT INTO {table}({', '.join(cols)}) SELECT {', '.join('?' for _ in cols)} "
           f"WHERE NOT EXISTS (SELECT 1 FROM {table} WHERE {where})")
    try:
        res = conn.execute(sql, [values[c] for c in cols] + key_params)
    except IntegrityError:  # a concurrent session inserted the same key first
        return Result([], 0, None)
    res.rowcount = max(res.rowcount, 0)
    return res


# --------------------------------------------------------------- migrations
def _ensure_migration_table(conn):
    if conn.dialect == "mssql":
        conn.execute("""IF OBJECT_ID('hp_schema_migrations', 'U') IS NULL
            CREATE TABLE hp_schema_migrations (version NVARCHAR(20) PRIMARY KEY,
            name NVARCHAR(200) NOT NULL, applied_at NVARCHAR(40) NOT NULL)""")
    else:
        conn.execute("""CREATE TABLE IF NOT EXISTS hp_schema_migrations (
            version TEXT PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)""")


def _migration_files(dialect):
    out = []
    for up in sorted((config.MIGRATIONS_DIR / dialect).glob("*.up.sql")):
        stem = up.name[: -len(".up.sql")]
        version, _, name = stem.partition("_")
        if not (version.isdigit() and _SAFE_NAME.match(name)):
            raise RuntimeError(f"Invalid migration file name: {up.name}")
        out.append((version, name, up, up.with_name(f"{stem}.down.sql")))
    return out


def applied_versions(conn):
    _ensure_migration_table(conn)
    return {r["version"] for r in conn.execute("SELECT version FROM hp_schema_migrations").fetchall()}


def _apply(conn, script, bookkeeping_sql):
    """Run a migration script plus its bookkeeping statement atomically.
    Version and name come from validated file names, never user input."""
    if conn.dialect == "sqlite":
        # executescript() commits any open transaction, so wrap it ourselves.
        conn.raw.executescript(f"BEGIN;\n{script}\n;{bookkeeping_sql};\nCOMMIT;")
        return
    with transaction(conn):
        conn.run_script(script)
        conn.execute(bookkeeping_sql)


def migrate_up(conn):
    """Apply all pending migrations, each atomically. Returns applied versions."""
    done = applied_versions(conn)
    applied = []
    for version, name, up, _down in _migration_files(conn.dialect):
        if version in done:
            continue
        _apply(conn, up.read_text(encoding="utf-8"),
               "INSERT INTO hp_schema_migrations(version, name, applied_at) "
               f"VALUES ('{version}', '{name}', '{utcnow()}')")
        applied.append(version)
    return applied


def backup(conn):
    """Take a backup before destructive maintenance. Returns its location."""
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    if conn.dialect == "mssql":
        if not config.MSSQL_BACKUP_DIR:
            raise RuntimeError("Set HEYGEN_MSSQL_BACKUP_DIR (a folder on the SQL Server machine) "
                               "so a backup can be taken before rollback.")
        name = config.MSSQL_DATABASE
        if not _SAFE_NAME.match(name):
            raise RuntimeError("Unsafe database name.")
        target = f"{config.MSSQL_BACKUP_DIR.rstrip(chr(92) + '/')}{chr(92)}{name}-{stamp}.bak"
        cur = conn.raw.cursor()
        cur.execute(f"BACKUP DATABASE [{name}] TO DISK = ? WITH COPY_ONLY, INIT", target)
        while cur.nextset():  # drain informational messages so the backup completes
            pass
        cur.close()
        return target
    src = Path(conn.label)
    dst = src.with_name(f"{src.stem}.backup-{stamp}{src.suffix}")
    target = sqlite3.connect(str(dst))
    conn.raw.backup(target)
    target.close()
    return dst


def migrate_down(conn):
    """Roll back the most recent migration after taking a backup."""
    done = applied_versions(conn)
    files = [f for f in _migration_files(conn.dialect) if f[0] in done]
    if not files:
        return None, None
    version, _name, _up, down = files[-1]
    bak = backup(conn)
    _apply(conn, down.read_text(encoding="utf-8"),
           f"DELETE FROM hp_schema_migrations WHERE version = '{version}'")
    return version, bak


# ------------------------------------------------------------------ helpers
def rows(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def row(conn, sql, params=()):
    r = conn.execute(sql, params).fetchone()
    return dict(r) if r else None


def scalar(conn, sql, params=()):
    r = conn.execute(sql, params).fetchone()
    return r[0] if r else None


def wait_for_server(attempts=30, delay=2):
    """Used by scripts/tests: wait until SQL Server accepts connections."""
    last = None
    for _ in range(attempts):
        try:
            pyodbc.connect(mssql_connection_string("master"), timeout=5).close()
            return True
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(delay)
    raise RuntimeError(f"SQL Server not reachable: {last}")
