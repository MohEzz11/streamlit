"""Storage for posts and the stock mentions extracted from them.

Uses Postgres (Supabase) when a connection string is configured, otherwise a
local SQLite file. The SQL below runs unchanged on both.

Connection string, first match wins:
  configure(url) call, then env DATABASE_URL, then env SUPABASE_DB_URL.
On Streamlit Cloud use Supabase's pooler URL (Connect > Session pooler); the
direct db.<ref>.supabase.co host is IPv6 only and will not connect.
"""

import os
from contextlib import contextmanager

import pandas as pd
from sqlalchemy import create_engine, text

DB_FILE = "opinion_tracker.db"

SCHEMA = [
    """CREATE TABLE IF NOT EXISTS posts (
        id          TEXT PRIMARY KEY,
        handle      TEXT NOT NULL,
        created_at  TEXT NOT NULL,          -- ISO 8601, UTC
        text        TEXT NOT NULL,
        url         TEXT,
        classified  INTEGER NOT NULL DEFAULT 0
    )""",
    "CREATE INDEX IF NOT EXISTS idx_posts_handle_time ON posts(handle, created_at)",
    """CREATE TABLE IF NOT EXISTS mentions (
        post_id     TEXT NOT NULL REFERENCES posts(id),
        ticker      TEXT NOT NULL,
        stance      TEXT NOT NULL,          -- bullish | bearish | neutral | background
        confidence  REAL,
        rationale   TEXT,
        risks       TEXT,                   -- risks raised in the post, '; ' joined
        method      TEXT,                   -- 'claude' or 'rules'
        PRIMARY KEY (post_id, ticker)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_mentions_ticker ON mentions(ticker)",
]

_engine = None
_url = None


def normalize_url(url):
    """Accept the postgresql:// string Supabase shows and point it at psycopg 3."""
    url = url.strip()
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+psycopg://" + url[len(prefix):]
    if url.startswith("postgresql+psycopg://") and "sslmode=" not in url:
        url += ("&" if "?" in url else "?") + "sslmode=require"
    return url


def configure(url=None):
    """Select the database. Safe to call on every Streamlit rerun."""
    global _engine, _url
    url = url or os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL")
    url = normalize_url(url) if url else f"sqlite:///{DB_FILE}"
    if _engine is not None and url == _url:
        return _engine
    kwargs = {"pool_pre_ping": True}
    if url.startswith("postgresql"):
        # prepare_threshold=None keeps Supabase's transaction pooler (port
        # 6543) working too, since it cannot hold prepared statements.
        kwargs.update(pool_size=2, max_overflow=2, pool_recycle=300,
                      connect_args={"prepare_threshold": None})
    engine = create_engine(url, **kwargs)
    with engine.begin() as con:
        for stmt in SCHEMA:
            con.execute(text(stmt))
        if url.startswith("postgresql"):
            # Supabase serves the public schema over its REST API. Row level
            # security with no policies blocks that path; this app connects
            # as the table owner, which RLS does not restrict.
            for table in ("posts", "mentions"):
                con.execute(text(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY"))
    _engine, _url = engine, url
    return engine


def backend():
    if _engine is None:
        configure()
    return "Postgres" if _url.startswith("postgresql") else "SQLite"


@contextmanager
def connect():
    engine = _engine or configure()
    with engine.begin() as con:
        yield con


def _count_posts(con):
    return con.execute(text("SELECT COUNT(*) FROM posts")).scalar()


def upsert_posts(posts):
    """Insert new posts; existing ids are left untouched. Returns # inserted."""
    rows = [{"id": str(p["id"]), "handle": p["handle"].lstrip("@").lower(),
             "created_at": p["created_at"], "text": p["text"], "url": p.get("url")}
            for p in posts]
    if not rows:
        return 0
    with connect() as con:
        before = _count_posts(con)
        con.execute(text(
            "INSERT INTO posts (id, handle, created_at, text, url) "
            "VALUES (:id, :handle, :created_at, :text, :url) "
            "ON CONFLICT (id) DO NOTHING"), rows)
        return _count_posts(con) - before


def unclassified_posts(handle=None):
    q = "SELECT id, handle, created_at, text FROM posts WHERE classified = 0"
    params = {}
    if handle:
        q += " AND handle = :handle"
        params["handle"] = handle.lstrip("@").lower()
    with connect() as con:
        return pd.read_sql_query(text(q + " ORDER BY created_at"), con, params=params)


def save_mentions(post_id, mentions):
    rows = {}
    for m in mentions:  # one row per ticker; a post may name a ticker twice
        t = m["ticker"].upper()
        rows[t] = {"post_id": str(post_id), "ticker": t, "stance": m["stance"],
                   "confidence": m.get("confidence"), "rationale": m.get("rationale"),
                   "risks": "; ".join(m.get("risks") or []), "method": m.get("method")}
    with connect() as con:
        con.execute(text("DELETE FROM mentions WHERE post_id = :p"), {"p": str(post_id)})
        if rows:
            con.execute(text(
                "INSERT INTO mentions (post_id, ticker, stance, confidence, "
                "rationale, risks, method) VALUES (:post_id, :ticker, :stance, "
                ":confidence, :rationale, :risks, :method)"), list(rows.values()))
        con.execute(text("UPDATE posts SET classified = 1 WHERE id = :p"),
                    {"p": str(post_id)})


def reset_classification(handle=None):
    with connect() as con:
        if handle:
            h = {"h": handle.lstrip("@").lower()}
            con.execute(text("DELETE FROM mentions WHERE post_id IN "
                             "(SELECT id FROM posts WHERE handle = :h)"), h)
            con.execute(text("UPDATE posts SET classified = 0 WHERE handle = :h"), h)
        else:
            con.execute(text("DELETE FROM mentions"))
            con.execute(text("UPDATE posts SET classified = 0"))


def handles():
    with connect() as con:
        return [r[0] for r in con.execute(
            text("SELECT DISTINCT handle FROM posts ORDER BY handle"))]


def latest_post_id(handle):
    """Newest post id for a handle (X ids are time-ordered), for since_id."""
    with connect() as con:
        row = con.execute(text(
            "SELECT id FROM posts WHERE handle = :h "
            "ORDER BY LENGTH(id) DESC, id DESC LIMIT 1"),
            {"h": handle.lstrip("@").lower()}).fetchone()
    return row[0] if row else None


def mentions_frame(handle):
    """One row per (post, ticker) with the post's time, text and link."""
    q = """
        SELECT m.ticker, m.stance, m.confidence, m.rationale, m.risks, m.method,
               p.id AS post_id, p.created_at, p.text, p.url
        FROM mentions m JOIN posts p ON p.id = m.post_id
        WHERE p.handle = :h
        ORDER BY p.created_at
    """
    with connect() as con:
        df = pd.read_sql_query(text(q), con, params={"h": handle.lstrip("@").lower()})
    df["created_at"] = pd.to_datetime(df["created_at"], utc=True, format="ISO8601")
    return df


def counts(handle):
    h = {"h": handle.lstrip("@").lower()}
    with connect() as con:
        posts = con.execute(text("SELECT COUNT(*), SUM(classified) FROM posts "
                                 "WHERE handle = :h"), h).fetchone()
        ments = con.execute(text(
            "SELECT COUNT(*), COUNT(DISTINCT ticker) FROM mentions m "
            "JOIN posts p ON p.id = m.post_id WHERE p.handle = :h"), h).fetchone()
    return {"posts": posts[0] or 0, "classified": int(posts[1] or 0),
            "mentions": ments[0] or 0, "tickers": ments[1] or 0}


def data_version():
    """Cheap fingerprint that changes whenever posts or mentions change, so
    cached views refresh after a scheduled refresh from another process."""
    with connect() as con:
        return tuple(con.execute(text(
            "SELECT (SELECT COUNT(*) FROM posts), (SELECT SUM(classified) FROM posts), "
            "(SELECT COUNT(*) FROM mentions), "
            "(SELECT MAX(created_at) FROM posts)")).fetchone())


def copy_all(src_url, dst_url):
    """Copy every post and mention from one database to another (used to move
    a local SQLite history into Supabase). Existing rows are kept."""
    src = create_engine(normalize_url(src_url) if "://" in src_url else f"sqlite:///{src_url}")
    with src.connect() as con:
        posts = pd.read_sql_query(text("SELECT * FROM posts"), con)
        ments = pd.read_sql_query(text("SELECT * FROM mentions"), con)
    configure(dst_url)
    with connect() as con:
        if len(posts):
            con.execute(text(
                "INSERT INTO posts (id, handle, created_at, text, url, classified) "
                "VALUES (:id, :handle, :created_at, :text, :url, :classified) "
                "ON CONFLICT (id) DO NOTHING"), posts.to_dict("records"))
        if len(ments):
            con.execute(text(
                "INSERT INTO mentions (post_id, ticker, stance, confidence, rationale, "
                "risks, method) VALUES (:post_id, :ticker, :stance, :confidence, "
                ":rationale, :risks, :method) ON CONFLICT (post_id, ticker) DO NOTHING"),
                ments.astype(object).where(ments.notna(), None).to_dict("records"))
    return len(posts), len(ments)
