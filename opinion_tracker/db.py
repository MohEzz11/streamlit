"""SQLite storage for posts and the stock mentions extracted from them."""

import sqlite3
from contextlib import contextmanager

import pandas as pd

DB_FILE = "opinion_tracker.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
    id          TEXT PRIMARY KEY,
    handle      TEXT NOT NULL,
    created_at  TEXT NOT NULL,          -- ISO 8601, UTC
    text        TEXT NOT NULL,
    url         TEXT,
    classified  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_posts_handle_time ON posts(handle, created_at);

CREATE TABLE IF NOT EXISTS mentions (
    post_id     TEXT NOT NULL REFERENCES posts(id),
    ticker      TEXT NOT NULL,
    stance      TEXT NOT NULL,          -- bullish | bearish | neutral | background
    confidence  REAL,
    rationale   TEXT,
    risks       TEXT,                   -- risks raised in the post, '; ' joined
    method      TEXT,                   -- 'claude' or 'rules'
    PRIMARY KEY (post_id, ticker)
);
CREATE INDEX IF NOT EXISTS idx_mentions_ticker ON mentions(ticker);
"""


@contextmanager
def connect(path=DB_FILE):
    con = sqlite3.connect(path)
    try:
        con.executescript(SCHEMA)
        yield con
        con.commit()
    finally:
        con.close()


def upsert_posts(posts, path=DB_FILE):
    """Insert new posts; existing ids are left untouched. Returns # inserted."""
    rows = [(p["id"], p["handle"].lstrip("@").lower(), p["created_at"],
             p["text"], p.get("url")) for p in posts]
    with connect(path) as con:
        before = con.total_changes
        con.executemany(
            "INSERT OR IGNORE INTO posts (id, handle, created_at, text, url) "
            "VALUES (?, ?, ?, ?, ?)", rows)
        return con.total_changes - before


def unclassified_posts(handle=None, path=DB_FILE):
    q = "SELECT id, handle, created_at, text FROM posts WHERE classified = 0"
    args = []
    if handle:
        q += " AND handle = ?"
        args.append(handle.lstrip("@").lower())
    with connect(path) as con:
        return pd.read_sql_query(q + " ORDER BY created_at", con, params=args)


def save_mentions(post_id, mentions, path=DB_FILE):
    with connect(path) as con:
        con.execute("DELETE FROM mentions WHERE post_id = ?", (post_id,))
        con.executemany(
            "INSERT OR REPLACE INTO mentions (post_id, ticker, stance, confidence, "
            "rationale, risks, method) VALUES (?, ?, ?, ?, ?, ?, ?)",
            [(post_id, m["ticker"].upper(), m["stance"], m.get("confidence"),
              m.get("rationale"), "; ".join(m.get("risks") or []), m.get("method"))
             for m in mentions])
        con.execute("UPDATE posts SET classified = 1 WHERE id = ?", (post_id,))


def reset_classification(handle=None, path=DB_FILE):
    with connect(path) as con:
        if handle:
            h = handle.lstrip("@").lower()
            con.execute("DELETE FROM mentions WHERE post_id IN "
                        "(SELECT id FROM posts WHERE handle = ?)", (h,))
            con.execute("UPDATE posts SET classified = 0 WHERE handle = ?", (h,))
        else:
            con.execute("DELETE FROM mentions")
            con.execute("UPDATE posts SET classified = 0")


def handles(path=DB_FILE):
    with connect(path) as con:
        return [r[0] for r in con.execute(
            "SELECT DISTINCT handle FROM posts ORDER BY handle")]


def latest_post_id(handle, path=DB_FILE):
    """Newest post id for a handle (X ids are time-ordered), for since_id."""
    with connect(path) as con:
        row = con.execute(
            "SELECT id FROM posts WHERE handle = ? "
            "ORDER BY LENGTH(id) DESC, id DESC LIMIT 1",
            (handle.lstrip("@").lower(),)).fetchone()
    return row[0] if row else None


def mentions_frame(handle, path=DB_FILE):
    """One row per (post, ticker) with the post's time, text and link."""
    q = """
        SELECT m.ticker, m.stance, m.confidence, m.rationale, m.risks, m.method,
               p.id AS post_id, p.created_at, p.text, p.url
        FROM mentions m JOIN posts p ON p.id = m.post_id
        WHERE p.handle = ?
        ORDER BY p.created_at
    """
    with connect(path) as con:
        df = pd.read_sql_query(q, con, params=[handle.lstrip("@").lower()])
    df["created_at"] = pd.to_datetime(df["created_at"], utc=True, format="ISO8601")
    return df


def counts(handle, path=DB_FILE):
    h = handle.lstrip("@").lower()
    with connect(path) as con:
        posts = con.execute("SELECT COUNT(*), SUM(classified) FROM posts "
                            "WHERE handle = ?", (h,)).fetchone()
        ments = con.execute("SELECT COUNT(*), COUNT(DISTINCT ticker) FROM mentions m "
                            "JOIN posts p ON p.id = m.post_id WHERE p.handle = ?",
                            (h,)).fetchone()
    return {"posts": posts[0] or 0, "classified": posts[1] or 0,
            "mentions": ments[0] or 0, "tickers": ments[1] or 0}
