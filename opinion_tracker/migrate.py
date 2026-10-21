"""Copy a local SQLite history into Supabase (or any Postgres).

    SUPABASE_DB_URL="postgresql://..." python -m opinion_tracker.migrate opinion_tracker.db

Rows already in the destination are kept, so it is safe to run twice.
"""

import argparse
import os
import sys

from . import db


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("source", help="SQLite file path or database URL to copy from")
    ap.add_argument("--to", default=os.getenv("DATABASE_URL") or os.getenv("SUPABASE_DB_URL"),
                    help="destination URL (default: DATABASE_URL or SUPABASE_DB_URL)")
    a = ap.parse_args()
    if not a.to:
        sys.exit("Set SUPABASE_DB_URL or pass --to.")
    posts, ments = db.copy_all(a.source, a.to)
    print(f"Copied {posts} posts and {ments} mentions to {db.backend()}.")


if __name__ == "__main__":
    main()
