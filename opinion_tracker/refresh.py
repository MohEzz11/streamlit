"""Command-line refresh for scheduled runs (cron, GitHub Actions, etc.).

    SUPABASE_DB_URL=... X_BEARER_TOKEN=... ANTHROPIC_API_KEY=... \\
        python -m opinion_tracker.refresh aleabitoreddit [more_handles ...]

Pulls new posts since the last stored one, then classifies anything not yet
classified. Run it hourly to mirror an hourly-updated tracker.
"""

import argparse
import os
import sys

from . import db, ingest
from .classify import DEFAULT_MODEL, classify_posts


def run(handle, x_token, api_key, model=DEFAULT_MODEL, log=print):
    handle = handle.lstrip("@").lower()
    if x_token:
        try:
            posts = ingest.fetch_x_posts(handle, x_token, since_id=db.latest_post_id(handle))
            log(f"@{handle}: fetched {len(posts)} posts, "
                f"{db.upsert_posts(posts)} new")
        except ingest.XApiError as e:
            if "rate limit" not in str(e):
                raise
            # Try again next hour; still classify what is already stored.
            log(f"::warning::@{handle}: {e}")
    todo = db.unclassified_posts(handle)
    if todo.empty:
        log(f"@{handle}: nothing to classify.")
        return
    known = set(db.mentions_frame(handle)["ticker"])

    def progress(done, total, err):
        log(f"classified {done}/{total}" + (f" (batch fell back to rules: {err})" if err else ""))

    for pid, ments in classify_posts(todo, api_key, model, known, progress):
        db.save_mentions(pid, ments)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("handles", nargs="+", help="X handles, with or without @")
    ap.add_argument("--model", default=os.getenv("TRACKER_MODEL") or DEFAULT_MODEL)
    ap.add_argument("--require-db", action="store_true",
                    help="fail instead of writing to a throwaway local SQLite file")
    a = ap.parse_args()
    if a.require_db and db.backend() != "Postgres":
        sys.exit("No database URL set (SUPABASE_DB_URL or DATABASE_URL).")
    x_token, key = os.getenv("X_BEARER_TOKEN"), os.getenv("ANTHROPIC_API_KEY")
    if not x_token:
        print("X_BEARER_TOKEN not set: only classifying stored posts.", file=sys.stderr)
    if not key:
        print("ANTHROPIC_API_KEY not set: using keyword rules.", file=sys.stderr)
    print(f"Storage: {db.backend()}, model: {a.model if key else 'keyword rules'}")
    for h in a.handles:
        run(h, x_token, key, a.model)


if __name__ == "__main__":
    main()
