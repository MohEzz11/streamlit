"""Command-line refresh for scheduled runs (cron, GitHub Actions, etc.).

    X_BEARER_TOKEN=... ANTHROPIC_API_KEY=... python -m opinion_tracker.refresh aleabitoreddit

Pulls new posts since the last stored one, then classifies anything not yet
classified. Run it hourly to mirror an hourly-updated tracker.
"""

import argparse
import os
import sys

from . import db, ingest
from .classify import DEFAULT_MODEL, classify_posts


def run(handle, x_token, api_key, model=DEFAULT_MODEL, log=print):
    if x_token:
        posts = ingest.fetch_x_posts(handle, x_token, since_id=db.latest_post_id(handle))
        log(f"@{handle}: fetched {len(posts)} posts, "
            f"{db.upsert_posts(posts)} new")
    todo = db.unclassified_posts(handle)
    if todo.empty:
        log("Nothing to classify.")
        return
    known = set(db.mentions_frame(handle)["ticker"])

    def progress(done, total, err):
        log(f"classified {done}/{total}" + (f" (batch fell back to rules: {err})" if err else ""))

    for pid, ments in classify_posts(todo, api_key, model, known, progress):
        db.save_mentions(pid, ments)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("handle")
    ap.add_argument("--model", default=os.getenv("TRACKER_MODEL", DEFAULT_MODEL))
    a = ap.parse_args()
    x_token, key = os.getenv("X_BEARER_TOKEN"), os.getenv("ANTHROPIC_API_KEY")
    if not x_token:
        print("X_BEARER_TOKEN not set: only classifying stored posts.", file=sys.stderr)
    if not key:
        print("ANTHROPIC_API_KEY not set: using keyword rules.", file=sys.stderr)
    run(a.handle, x_token, key, a.model)


if __name__ == "__main__":
    main()
