"""
M.E. Opinion Tracker
====================
Turns an analyst's public X posts into a daily research report: every stock
mention tagged bullish, bearish, neutral or background, with stance history,
price since first mention, source links, AI thesis summaries, and a track
record measured against a benchmark.

Run:  streamlit run tracker_app.py

KEYS (Streamlit Secrets or the sidebar):
    ANTHROPIC_API_KEY = "sk-ant-..."   # stance classification and Q&A
    X_BEARER_TOKEN    = "..."          # paid X API access, to pull posts

    [credentials]                      # optional login gate
    user1 = "password1"

Without keys the app still works: import posts from a CSV/JSON file, or load
the synthetic demo dataset, and stances fall back to keyword rules.

Research tool only. Not investment advice. Not affiliated with any account
it tracks.
"""

import datetime as dt
import html
import os

import altair as alt
import pandas as pd
import streamlit as st

from opinion_tracker import analytics, db, ingest, prices, qa
from opinion_tracker.classify import DEFAULT_MODEL, classify_posts

st.set_page_config(page_title="M.E. Opinion Tracker", layout="wide")

BRAND = "M.E. Opinion Tracker"
TAGLINE = "ANALYST STANCE RESEARCH"
DISCLAIMER = ("Research tool only. Not investment advice. Stance labels are "
              "AI-inferred from public posts and can be wrong. Always read the "
              "original post and verify independently.")
STANCE_COLORS = {"bullish": "#0E7C4A", "bearish": "#C0392B",
                 "neutral": "#B7791F", "background": "#8A94A6"}
MODELS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"]


def get_secret(name):
    try:
        return st.secrets.get(name, None)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------
def inject_style():
    st.markdown("""
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@500;600&display=swap');
      html, body, [class*="css"] { font-family:'Inter', system-ui, sans-serif; }
      .block-container { padding-top: 2.6rem; max-width: 1180px; }
      h1, h2, h3, h4 { color:#0F2A43; font-weight:700; letter-spacing:-0.01em; }
      .me-header { display:flex; align-items:center; gap:14px;
        padding:6px 0 16px; border-bottom:1px solid #E6E9EF; margin-bottom:18px; }
      .me-logo { width:44px; height:44px; border-radius:10px; background:#0F2A43;
        color:#fff; display:flex; align-items:center; justify-content:center;
        font-family:'IBM Plex Mono', monospace; font-weight:700; font-size:1rem; }
      .me-title { font-size:1.4rem; font-weight:700; color:#0F2A43; line-height:1.05; }
      .me-sub { font-size:0.74rem; color:#5B6675; font-weight:600;
        letter-spacing:0.14em; margin-top:2px; }
      [data-testid="stMetric"] { background:#F7F9FC; border:1px solid #E6E9EF;
        border-radius:10px; padding:12px 16px; }
      .note-card { padding:11px 15px; border-radius:8px; border:1px solid #E6E9EF;
        background:#F7F9FC; font-size:0.9rem; color:#26364B; }
      .rank-row { display:grid; grid-template-columns: 28px 90px 200px 1fr 80px 80px;
        gap:10px; align-items:center; padding:7px 0; border-bottom:1px solid #EEF1F5;
        font-size:0.88rem; }
      .rank-row .tk { font-family:'IBM Plex Mono', monospace; font-weight:600; }
      .mix { display:flex; height:12px; border-radius:3px; overflow:hidden;
        background:#EEF1F5; }
      .counts { font-family:'IBM Plex Mono', monospace; font-size:0.78rem; color:#5B6675; }
      .gain-pos { color:#0E7C4A; font-weight:600; } .gain-neg { color:#C0392B; font-weight:600; }
      .card { border:1px solid #E6E9EF; border-left:4px solid var(--c); border-radius:10px;
        padding:12px 14px; background:#fff; margin-bottom:10px; }
      .card .tk { font-family:'IBM Plex Mono', monospace; font-weight:700; font-size:1.1rem; }
      .badge { padding:2px 9px; border-radius:6px; font-weight:600; font-size:0.76rem;
        font-family:'IBM Plex Mono', monospace; }
      .chip { display:inline-block; padding:3px 9px; margin:3px; border-radius:6px;
        border:1px solid #D3D9E2; font-family:'IBM Plex Mono', monospace; font-size:0.78rem; }
      .dirbar { display:flex; height:16px; border-radius:4px; overflow:hidden; margin:6px 0 4px; }
      [data-testid="stSidebar"] { background:#FBFCFE; border-right:1px solid #E6E9EF; }
    </style>
    """, unsafe_allow_html=True)


def header():
    st.markdown(
        f'<div class="me-header"><div class="me-logo">ME</div>'
        f'<div><div class="me-title">{BRAND}</div>'
        f'<div class="me-sub">{TAGLINE}</div></div></div>',
        unsafe_allow_html=True)


def badge(stance):
    c = STANCE_COLORS.get(stance, "#455063")
    return (f'<span class="badge" style="background:{c}1A;color:{c};'
            f'border:1px solid {c}55">{stance}</span>')


def pct(x):
    if x is None or pd.isna(x):
        return '<span class="counts">n/a</span>'
    cls = "gain-pos" if x >= 0 else "gain-neg"
    return f'<span class="{cls}">{x:+.1%}</span>'


def require_login():
    try:
        creds = dict(st.secrets.get("credentials", {}))
    except Exception:
        creds = {}
    if not creds or st.session_state.get("auth_ok"):
        return
    inject_style()
    header()
    user = st.text_input("Username")
    pw = st.text_input("Password", type="password")
    if st.button("Sign in", type="primary"):
        if pw and creds.get(user) == pw:
            st.session_state["auth_ok"] = True
            st.rerun()
        st.error("Invalid username or password.")
    st.stop()


require_login()
inject_style()
header()


# ---------------------------------------------------------------------------
# Cached data access
# ---------------------------------------------------------------------------
def db_version():
    try:
        return os.path.getmtime(db.DB_FILE)
    except OSError:
        return 0


@st.cache_data(show_spinner=False)
def load_mentions(handle, _version):
    return db.mentions_frame(handle)


@st.cache_data(ttl=3600, show_spinner=False)
def load_prices(tickers, start, symbol_map_items):
    try:
        return prices.history(list(tickers), start, dict(symbol_map_items))
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=3600, show_spinner=False)
def load_performance(handle, _version, symbol_map_items, benchmark):
    df = db.mentions_frame(handle)
    try:
        return analytics.call_performance(df, dict(symbol_map_items), benchmark)
    except Exception as e:
        return pd.DataFrame({"note": [f"Price lookup failed: {e}"]})


def gains_since_first(df, tickers, symbol_map):
    """Price change from the first mention to the latest close."""
    if not len(tickers):
        return {}
    first = df[df["ticker"].isin(tickers)].groupby("ticker")["created_at"].min()
    hist = load_prices(tuple(sorted(tickers)), first.min() - pd.Timedelta(days=5),
                       tuple(sorted(symbol_map.items())))
    out = {}
    for t in tickers:
        if t in hist.columns:
            _, p0 = prices.close_on_or_after(hist[t], first[t])
            s = hist[t].dropna()
            if p0 and len(s):
                out[t] = float(s.iloc[-1]) / p0 - 1
    return out


# ---------------------------------------------------------------------------
# Sidebar: account, keys, settings
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### Tracked account")
    known = db.handles()
    default = "aleabitoreddit"
    options = sorted(set(known) | {default})
    handle = st.selectbox("Handle", options, index=options.index(default))
    new_h = st.text_input("Add another handle", placeholder="e.g. some_analyst")
    if new_h.strip():
        handle = new_h.strip().lstrip("@").lower()

    st.markdown("### Keys")
    anth_key = get_secret("ANTHROPIC_API_KEY") or st.text_input(
        "Anthropic API key", type="password",
        help="console.anthropic.com. Without it, stances use keyword rules.")
    x_token = get_secret("X_BEARER_TOKEN") or st.text_input(
        "X API bearer token", type="password",
        help="developer.x.com. Paid access is needed to read user timelines.")
    model = st.selectbox("Claude model", MODELS, index=MODELS.index(DEFAULT_MODEL),
                         help="Opus gives the best stance accuracy; Haiku is far "
                              "cheaper for large post histories.")

    st.markdown("### Prices")
    benchmark = st.text_input("Benchmark", "SMH",
                              help="SMH = semiconductor ETF. Use SPY for the S&P 500.")
    sym_text = st.text_area("Ticker to Yahoo symbol map",
                            prices.format_symbol_map(prices.DEFAULT_SYMBOL_MAP),
                            help="One per line, e.g. SIVE=SIVE.ST for non-US listings.")
    symbol_map = prices.parse_symbol_map(sym_text)
    st.markdown(f'<div class="note-card">{DISCLAIMER}</div>', unsafe_allow_html=True)


df = load_mentions(handle, db_version())
stats = db.counts(handle)

tab_dash, tab_stock, tab_ask, tab_track, tab_data = st.tabs(
    ["Dashboard", "Stock detail", "Ask about a stock", "Track record", "Data & refresh"])


# ---------------------------------------------------------------------------
# Data & refresh
# ---------------------------------------------------------------------------
def run_classification():
    todo = db.unclassified_posts(handle)
    if todo.empty:
        st.info("Every stored post is already classified.")
        return
    bar = st.progress(0.0, text=f"Classifying {len(todo)} posts")
    errors = []

    def progress(done, total, err):
        if err:
            errors.append(err)
        bar.progress(done / total, text=f"Classified {done} of {total} posts")

    known_t = set(df["ticker"]) if not df.empty else set()
    for pid, ments in classify_posts(todo, anth_key, model, known_t, progress):
        db.save_mentions(pid, ments)
    if errors:
        st.warning(f"{len(errors)} batch(es) fell back to keyword rules. "
                   f"First error: {errors[0][:300]}")
    st.success("Classification complete.")
    st.cache_data.clear()


with tab_data:
    st.subheader(f"@{handle}")
    c = st.columns(4)
    c[0].metric("Posts stored", f"{stats['posts']:,}")
    c[1].metric("Classified", f"{stats['classified']:,}")
    c[2].metric("Stock mentions", f"{stats['mentions']:,}")
    c[3].metric("Distinct tickers", f"{stats['tickers']:,}")

    st.markdown("#### 1. Get posts")
    src = st.radio("Source", ["X API", "Upload CSV / JSON", "Synthetic demo data"],
                   horizontal=True)
    if src == "X API":
        st.caption("Pulls original posts and replies (not reposts) newer than the "
                   "last stored post. Each page is 100 posts.")
        pages = st.slider("Max pages per refresh", 1, 32, 5)
        if st.button("Fetch new posts", type="primary", disabled=not x_token):
            try:
                posts = ingest.fetch_x_posts(handle, x_token, db.latest_post_id(handle), pages)
                st.success(f"Fetched {len(posts)} posts, {db.upsert_posts(posts)} new.")
                st.cache_data.clear()
            except ingest.XApiError as e:
                st.error(str(e))
        if not x_token:
            st.info("Add an X API bearer token in the sidebar or Secrets to fetch.")
    elif src == "Upload CSV / JSON":
        st.caption("Columns: created_at (or date) and text (or full_text). "
                   "Optional: id, url. X archive tweets.js converted to JSON also works.")
        up = st.file_uploader("Posts file", type=["csv", "json"])
        if up is not None and st.button("Import", type="primary"):
            try:
                posts = ingest.parse_upload(up.name, up.getvalue(), handle)
                st.success(f"Read {len(posts)} posts, {db.upsert_posts(posts)} new.")
                st.cache_data.clear()
            except ValueError as e:
                st.error(str(e))
    else:
        st.caption(f"Loads about 350 invented posts under @{ingest.DEMO_HANDLE} so you "
                   "can explore every view. Nothing in it is a real person's opinion.")
        if st.button("Load demo data", type="primary"):
            n = db.upsert_posts(ingest.demo_posts())
            st.success(f"Loaded {n} demo posts. Select @{ingest.DEMO_HANDLE} in the "
                       "sidebar, then classify below.")
            st.cache_data.clear()

    st.markdown("#### 2. Classify stances")
    pending = stats["posts"] - stats["classified"]
    st.caption(f"{pending:,} posts waiting. Method: "
               + (f"Claude ({model})" if anth_key else "keyword rules (no API key)"))
    b1, b2 = st.columns([1, 1])
    if b1.button("Classify new posts", type="primary", disabled=pending == 0):
        run_classification()
    if b2.button("Re-classify everything"):
        db.reset_classification(handle)
        run_classification()

    st.markdown("#### Hourly updates")
    st.code(f"X_BEARER_TOKEN=... ANTHROPIC_API_KEY=... "
            f"python -m opinion_tracker.refresh {handle}", language="bash")
    st.caption("Schedule this with cron or a GitHub Actions workflow to refresh "
               "every hour. Hosted Streamlit apps do not run background jobs.")


if df.empty:
    for t in (tab_dash, tab_stock, tab_ask, tab_track):
        with t:
            st.info("No classified posts yet for this handle. Open **Data & refresh** "
                    "to fetch, upload, or load demo data, then classify.")
    st.stop()


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
def mix_bar(bull, bear, neu):
    tot = max(bull + bear + neu, 1)
    seg = "".join(
        f'<div style="width:{n / tot * 100:.1f}%;background:{STANCE_COLORS[s]}"></div>'
        for n, s in ((bull, "bullish"), (bear, "bearish"), (neu, "neutral")) if n)
    return f'<div class="mix">{seg}</div>'


with tab_dash:
    view = st.radio("View", list(analytics.WINDOWS), horizontal=True, index=2,
                    label_visibility="collapsed")
    days = analytics.WINDOWS[view]
    end = pd.Timestamp.now(tz="UTC")
    if view == "Daily":  # anchor to the latest day with posts, like a daily report
        end = df["created_at"].max()
    table = analytics.ticker_table(df, days, end)
    w = analytics.window_slice(df, days, end)
    start = end - pd.Timedelta(days=days)
    st.markdown(f"### {view} &nbsp;<span class='counts'>{start:%Y-%m-%d} to "
                f"{end:%Y-%m-%d} UTC</span>", unsafe_allow_html=True)

    if table.empty:
        st.info("No mentions in this window.")
    else:
        net_bull = int((table["net"] > 0).sum())
        net_bear = int((table["net"] < 0).sum())
        c = st.columns(4)
        c[0].metric("Names mentioned", len(table))
        c[1].metric("Mentions", int(table["mentions"].sum()))
        c[2].metric("Net-bullish names", net_bull)
        c[3].metric("Net-bearish names", net_bear)
        tot = max(net_bull + net_bear, 1)
        st.markdown(
            f'<div class="dirbar"><div style="width:{net_bull / tot * 100:.1f}%;'
            f'background:{STANCE_COLORS["bullish"]}"></div><div style="width:'
            f'{net_bear / tot * 100:.1f}%;background:{STANCE_COLORS["bearish"]}"></div></div>'
            f'<div class="counts">Direction is judged by number of names, not number of '
            f'posts, so a few heavily discussed names do not dominate. Stances are views '
            f'expressed in posts, not actual holdings.</div>', unsafe_allow_html=True)

        st.markdown("#### Most discussed")
        top = table.head(10)
        gains = gains_since_first(df, list(top.index), symbol_map)
        rows = []
        for i, (t, r) in enumerate(top.iterrows(), 1):
            new = " <span class='badge' style='background:#EEF4FF;color:#1F4FB8'>NEW</span>" if r["new"] else ""
            rows.append(
                f'<div class="rank-row"><div class="counts">{i}</div>'
                f'<div class="tk">{html.escape(t)}{new}</div>'
                f'<div class="counts">{r.bull} bull · {r.bear} bear · {r.neu} neu</div>'
                f'{mix_bar(r.bull, r.bear, r.neu)}'
                f'<div class="counts">{r.mentions} posts</div>'
                f'<div title="Price change since first mention">{pct(gains.get(t))}</div></div>')
        st.markdown("".join(rows), unsafe_allow_html=True)
        st.caption("Gain = price change from the first close after the first mention "
                   "to the latest close. It is not the author's return and ignores timing.")

        left, right = st.columns(2)
        with left:
            st.markdown("#### Notable: bearish or stance shift")
            shifts = analytics.stance_shifts(df, days, end)
            bears = table[table["bear"] > 0]
            notable = sorted(set(shifts.index) | set(bears.index))
            if not notable:
                st.caption("No bearish or stance-shift names this period.")
            for t in notable[:8]:
                if t in shifts.index:
                    s = shifts.loc[t]
                    note = f"Shift: {badge(s['before'])} to {badge(s['now'])}"
                    col = STANCE_COLORS[s["now"]]
                else:
                    note = f"{badge('bearish')} {int(table.loc[t, 'bear'])} bearish posts"
                    col = STANCE_COLORS["bearish"]
                st.markdown(f'<div class="card" style="--c:{col}"><span class="tk">'
                            f'{html.escape(t)}</span><br>{note}</div>', unsafe_allow_html=True)
        with right:
            min_new = 1 if days <= 7 else 3
            st.markdown(f"#### New names (first seen, {min_new}+ mentions)")
            new = table[table["new"] & (table["mentions"] >= min_new)]
            if new.empty:
                st.caption("No new names this period.")
            for t, r in new.head(8).iterrows():
                col = STANCE_COLORS.get(r["direction"], "#8A94A6")
                st.markdown(
                    f'<div class="card" style="--c:{col}"><span class="tk">{html.escape(t)}'
                    f'</span> &nbsp;{badge(r["direction"]) if r["direction"] in STANCE_COLORS else ""}'
                    f'<div class="counts">{r.mentions} mentions · {r.bull} bull · {r.bear} bear'
                    f' · first {r.first_mention:%Y-%m-%d}</div></div>', unsafe_allow_html=True)

        rest = table.iloc[10:]
        if len(rest):
            st.markdown(f"#### Other mentions ({len(rest)})")
            st.markdown("".join(f'<span class="chip">{html.escape(t)} · {n}</span>'
                                for t, n in rest["mentions"].items()), unsafe_allow_html=True)

        with st.expander("All names in this window (sortable)"):
            show = table.reset_index()[["ticker", "mentions", "bull", "bear", "neu",
                                        "direction", "first_mention", "latest_mention"]]
            show["first_mention"] = show["first_mention"].dt.date
            show["latest_mention"] = show["latest_mention"].dt.date
            st.dataframe(show, hide_index=True, use_container_width=True)


# ---------------------------------------------------------------------------
# Stock detail
# ---------------------------------------------------------------------------
ranked = df.groupby("ticker").size().sort_values(ascending=False)

with tab_stock:
    t = st.selectbox("Ticker", list(ranked.index),
                     format_func=lambda x: f"{x}  ({ranked[x]} mentions)")
    m = df[df["ticker"] == t].sort_values("created_at")
    latest = m[m["stance"].isin(analytics.OPINION)].tail(1)
    c = st.columns(4)
    c[0].metric("Mentions", len(m))
    c[1].metric("First mention", f"{m['created_at'].min():%d %b %y}")
    c[2].metric("Latest stance", latest["stance"].iloc[0] if len(latest) else "none")
    gain = gains_since_first(df, [t], symbol_map).get(t)
    c[3].metric("Price since first mention", "n/a" if gain is None else f"{gain:+.1%}")

    hist = load_prices((t,), m["created_at"].min() - pd.Timedelta(days=10),
                       tuple(sorted(symbol_map.items())))
    if t in hist.columns:
        price = hist[[t]].reset_index()
        price.columns = ["date", "close"]
        marks = m[m["stance"].isin(["bullish", "bearish"])].copy()
        marks["date"] = marks["created_at"].dt.tz_localize(None).dt.normalize()
        marks = marks.merge(price, on="date", how="inner") if len(marks) else marks
        line = alt.Chart(price).mark_line(color="#0F2A43").encode(
            x=alt.X("date:T", title=None), y=alt.Y("close:Q", title="Close", scale=alt.Scale(zero=False)))
        chart = line
        if len(marks) and "close" in marks:
            pts = alt.Chart(marks).mark_circle(size=60, opacity=0.8).encode(
                x="date:T", y="close:Q",
                color=alt.Color("stance:N", scale=alt.Scale(
                    domain=["bullish", "bearish"],
                    range=[STANCE_COLORS["bullish"], STANCE_COLORS["bearish"]])),
                tooltip=["date:T", "stance:N", "text:N"])
            chart = line + pts
        st.altair_chart(chart.properties(height=320), use_container_width=True)
        st.caption("Dots mark bullish and bearish posts on trading days.")
    else:
        st.info(f"No price data for {t}. If it trades outside the US, add a line "
                f"such as {t}=SYMBOL.EXCHANGE to the symbol map in the sidebar.")

    risks = [r for r in m["risks"].dropna() if r]
    if risks:
        with st.expander(f"Risks raised in posts ({len(risks)})"):
            for r in dict.fromkeys(risks):
                st.markdown(f"- {r}")

    st.markdown(f"#### All posts ({len(m)})")
    posts = m.sort_values("created_at", ascending=False)[
        ["created_at", "stance", "confidence", "text", "url"]].copy()
    posts["created_at"] = posts["created_at"].dt.strftime("%Y-%m-%d %H:%M")
    st.dataframe(posts, hide_index=True, use_container_width=True, column_config={
        "url": st.column_config.LinkColumn("Source", display_text="open"),
        "confidence": st.column_config.ProgressColumn("Conf.", min_value=0, max_value=1),
        "text": st.column_config.TextColumn("Post", width="large")})


# ---------------------------------------------------------------------------
# Ask about a stock
# ---------------------------------------------------------------------------
with tab_ask:
    st.caption("Claude reads every stored post about one ticker and writes the latest "
               "opinion, thesis arc, three key posts, risks raised, and what the posts "
               "leave out. It only uses the posts, never outside data.")
    q1, q2 = st.columns([1, 2])
    tq = q1.selectbox("Ticker ", list(ranked.index), key="ask_t")
    question = q2.text_input("Optional question", placeholder="e.g. What would make the author turn bearish?")
    if st.button("Analyse", type="primary", disabled=not anth_key):
        with st.spinner(f"Reading {ranked[tq]} posts about {tq}"):
            try:
                text, used = qa.ticker_brief(tq, df[df["ticker"] == tq], anth_key, model,
                                             question or None)
                st.markdown(text)
                with st.expander("Posts referenced by [n]"):
                    for i, r in enumerate(used.itertuples(), 1):
                        link = f" [source]({r.url})" if r.url else ""
                        st.markdown(f"**[{i}]** {r.created_at:%Y-%m-%d} *{r.stance}*: "
                                    f"{r.text}{link}")
            except Exception as e:
                st.error(f"Analysis failed: {e}")
    if not anth_key:
        st.info("Add an Anthropic API key to use Q&A.")
    st.markdown("#### Current bullish and bearish names")
    ls = analytics.latest_stance(df)
    b1, b2 = st.columns(2)
    for col, s in ((b1, "bullish"), (b2, "bearish")):
        names = ls[ls["stance"] == s].sort_values("created_at", ascending=False)
        col.markdown(f"{badge(s)} &nbsp;{len(names)} names, by latest explicit stance",
                     unsafe_allow_html=True)
        col.markdown("".join(f'<span class="chip">{html.escape(t)}</span>'
                             for t in names.index), unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Track record
# ---------------------------------------------------------------------------
with tab_track:
    st.caption(f"Did the calls work? For each ticker, the first bullish or bearish "
               f"post is treated as a call, priced at the next close, and compared "
               f"with {benchmark} over the same dates. A bearish call is correct when "
               f"the price fell.")
    perf = load_performance(handle, db_version(), tuple(sorted(symbol_map.items())),
                            benchmark)
    if perf.empty or "return" not in perf:
        st.info("No price data available for these calls yet."
                if "note" not in perf else perf["note"].iloc[0])
    else:
        s = analytics.performance_summary(perf)
        c = st.columns(4)
        c[0].metric("Calls priced", s["calls"])
        c[1].metric("Direction right", f"{s['hit_rate']:.0%}")
        c[2].metric(f"Beat {benchmark}", "n/a" if s["beat_benchmark"] is None
                    else f"{s['beat_benchmark']:.0%}")
        c[3].metric("Median excess return", "n/a" if s["median_excess"] is None
                    else f"{s['median_excess']:+.1%}")
        st.dataframe(perf, hide_index=True, use_container_width=True, column_config={
            "return": st.column_config.NumberColumn("Return", format="percent"),
            "benchmark": st.column_config.NumberColumn(benchmark, format="percent"),
            "excess": st.column_config.NumberColumn("Excess", format="percent")})
        st.markdown(
            '<div class="note-card"><b>Read with care.</b> This measures one entry '
            'point per ticker and ignores position size, later exits, and trading '
            'costs. Small caps the author promotes can move on the post itself, so '
            'early followers capture gains later readers do not. A short window or a '
            'strong sector rally can make any stock picker look skilled. Treat this as '
            'evidence to investigate, not proof of edge.</div>', unsafe_allow_html=True)

st.caption(f"{DISCLAIMER} Data last loaded {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC.")
