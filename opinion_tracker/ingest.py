"""Getting posts in: X API v2, CSV/JSON import, and synthetic demo data."""

import datetime as dt
import io
import json
import random

import pandas as pd
import requests

X_API = "https://api.x.com/2"


class XApiError(RuntimeError):
    pass


def _x_get(path, token, params=None):
    r = requests.get(f"{X_API}{path}", params=params or {}, timeout=30,
                     headers={"Authorization": f"Bearer {token}"})
    if r.status_code == 429:
        reset = r.headers.get("x-rate-limit-reset")
        raise XApiError(f"X API rate limit hit. Resets at unix time {reset}.")
    if r.status_code >= 400:
        raise XApiError(f"X API error {r.status_code}: {r.text[:300]}")
    return r.json()


def fetch_x_posts(handle, token, since_id=None, max_pages=5):
    """Fetch a user's recent original posts and replies (no retweets).

    Requires a paid X API plan with read access to the user timeline
    endpoint. Each page is up to 100 posts; since_id makes refreshes
    incremental so only new posts are pulled.
    """
    handle = handle.lstrip("@")
    user = _x_get(f"/users/by/username/{handle}", token)
    if "data" not in user:
        raise XApiError(f"User @{handle} not found: {user.get('errors')}")
    uid = user["data"]["id"]

    params = {"max_results": 100, "exclude": "retweets",
              "tweet.fields": "created_at,note_tweet"}
    if since_id:
        params["since_id"] = since_id

    posts = []
    for _ in range(max_pages):
        page = _x_get(f"/users/{uid}/tweets", token, params)
        for t in page.get("data", []):
            text = (t.get("note_tweet") or {}).get("text") or t["text"]
            posts.append({"id": t["id"], "handle": handle,
                          "created_at": t["created_at"], "text": text,
                          "url": f"https://x.com/{handle}/status/{t['id']}"})
        nxt = page.get("meta", {}).get("next_token")
        if not nxt:
            break
        params["pagination_token"] = nxt
    return posts


# Accepted column names for file imports (X archive exports, scrapers, etc.)
_ID_COLS = ["id", "tweet_id", "id_str", "post_id"]
_TIME_COLS = ["created_at", "date", "timestamp", "time"]
_TEXT_COLS = ["text", "full_text", "content", "tweet"]
_URL_COLS = ["url", "link", "permalink"]


def _pick(cols, options):
    low = {c.lower(): c for c in cols}
    for o in options:
        if o in low:
            return low[o]
    return None


def parse_upload(name, data, handle):
    """Parse an uploaded CSV or JSON of posts into the standard post dicts."""
    if name.lower().endswith(".json"):
        raw = json.loads(data.decode("utf-8"))
        if isinstance(raw, dict):
            raw = raw.get("data") or raw.get("tweets") or [raw]
        # X archive format wraps each item as {"tweet": {...}}
        raw = [r.get("tweet", r) for r in raw]
        df = pd.DataFrame(raw)
    else:
        df = pd.read_csv(io.BytesIO(data))

    id_c, time_c = _pick(df.columns, _ID_COLS), _pick(df.columns, _TIME_COLS)
    text_c, url_c = _pick(df.columns, _TEXT_COLS), _pick(df.columns, _URL_COLS)
    if not (time_c and text_c):
        raise ValueError("File needs a date column (created_at/date) and a text "
                         f"column (text/full_text). Found: {list(df.columns)}")

    handle = handle.lstrip("@")
    posts = []
    for i, r in df.iterrows():
        ts = pd.to_datetime(r[time_c], utc=True, errors="coerce")
        if pd.isna(ts) or not str(r[text_c]).strip():
            continue
        pid = str(r[id_c]) if id_c and pd.notna(r[id_c]) else f"{handle}-{ts.value}-{i}"
        url = r[url_c] if url_c and pd.notna(r[url_c]) else (
            f"https://x.com/{handle}/status/{pid}" if pid.isdigit() else None)
        posts.append({"id": pid, "handle": handle, "text": str(r[text_c]),
                      "created_at": ts.isoformat(), "url": url})
    return posts


# ---------------------------------------------------------------------------
# Synthetic demo data. The handle and every post below are invented so the
# dashboard can be explored without an X API key. Nothing here is a real
# person's opinion.
# ---------------------------------------------------------------------------
DEMO_HANDLE = "demo_analyst"

_DEMO_TEMPLATES = {
    "bullish": [
        "${t} is still my top pick in {theme}. Supply is tight and orders keep growing.",
        "Added more ${t} on the dip. {theme} demand is nowhere near priced in.",
        "${t} looks like the bottleneck for {theme}. Very bullish into next quarter.",
        "Long ${t}. Capacity expansion confirms the {theme} thesis.",
    ],
    "bearish": [
        "Not a fan of ${t} here. Margins are getting squeezed in {theme}.",
        "${t} is overvalued vs peers. Expect downside as {theme} share shifts away.",
        "Trimmed ${t}. Risk: customer concentration and weak {theme} guidance.",
    ],
    "neutral": [
        "Watching ${t} earnings next week for {theme} commentary.",
        "Interesting note on ${t} today. Need more data on {theme} before deciding.",
    ],
}
_DEMO_BOOK = [  # ticker, theme, base stance weights (bull, bear, neutral)
    ("LITE", "optical comms", (0.75, 0.05, 0.20)),
    ("AAOI", "optical modules", (0.70, 0.10, 0.20)),
    ("COHR", "optical comms", (0.60, 0.10, 0.30)),
    ("MRVL", "AI networking", (0.55, 0.15, 0.30)),
    ("NVDA", "AI accelerators", (0.30, 0.10, 0.60)),
    ("AXTI", "InP substrates", (0.70, 0.10, 0.20)),
    ("JBL", "module manufacturing", (0.60, 0.05, 0.35)),
    ("IREN", "neocloud", (0.10, 0.75, 0.15)),
    ("INTC", "foundry", (0.15, 0.55, 0.30)),
    ("MU", "HBM memory", (0.50, 0.15, 0.35)),
]


def demo_posts(days=120, per_day=(1, 5), seed=7):
    rng = random.Random(seed)
    now = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
    posts, n = [], 0
    for d in range(days, -1, -1):
        day = now - dt.timedelta(days=d)
        for _ in range(rng.randint(*per_day)):
            t, theme, w = rng.choice(_DEMO_BOOK)
            stance = rng.choices(["bullish", "bearish", "neutral"], weights=w)[0]
            text = rng.choice(_DEMO_TEMPLATES[stance]).format(t=t, theme=theme)
            if rng.random() < 0.25:  # some posts name a second ticker in passing
                t2 = rng.choice(_DEMO_BOOK)[0]
                if t2 != t:
                    text += f" Also keeping an eye on ${t2}."
            ts = day - dt.timedelta(minutes=rng.randint(0, 600))
            n += 1
            posts.append({"id": f"demo-{n:05d}", "handle": DEMO_HANDLE,
                          "created_at": ts.isoformat(), "text": text, "url": None})
    return posts
