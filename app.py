"""


M.E. Portfolio Ai Agent
=======================
A professional AI equity research tool built on the TradingAgents framework.

Modes:
  1. Standalone Stock : analyse any single ticker with a price chart, key
     statistics, and a full multi-agent AI report.
  2. My Portfolio     : build and SAVE a portfolio (tickers + shares), view
     allocation analytics, then run the AI across every holding.

Also includes a Head-to-Head Probability tool (Elo expected-score model).

KEY MODEL (Streamlit Secrets):
    GOOGLE_API_KEY = "AQ..."   # optional, enables trial mode (owner pays)
    FRED_API_KEY   = "..."       # optional, enables macro data for everyone

    [credentials]
    user1 = "password1"
    user2 = "password2"
    user3 = "password3"

Saved portfolios persist while the app is running. On a redeploy or reboot of
the hosting container the store is reset (see notes for a durable database option).

Research and educational tool only. Not financial advice.
"""

import os
import json
import time
import datetime as dt

import pandas as pd
import streamlit as st

st.set_page_config(page_title="M.E. Portfolio Ai Agent", layout="wide")

BRAND = "M.E. Portfolio Ai Agent"
TAGLINE = "AI-POWERED INVESTMENT RESEARCH"
DISCLAIMER = ("Research and educational tool only. Not financial, investment, "
              "or trading advice. AI output is one model's opinion, can be "
              "wrong, and varies between runs.")
PF_FILE = "portfolios.json"

PROVIDER_KEY_ENV = {"google": "GOOGLE_API_KEY",
                    "openai": "OPENAI_API_KEY",
                    "anthropic": "ANTHROPIC_API_KEY"}
KEY_HELP = {"google": "aistudio.google.com/apikey",
            "openai": "platform.openai.com/api-keys",
            "anthropic": "console.anthropic.com"}
ANALYST_LABELS = {"market": "Market (technical)", "news": "News (macro)",
                  "fundamentals": "Fundamentals", "social": "Sentiment (social)"}
SIGNAL_COLORS = {"BUY": "#0E7C4A", "SELL": "#C0392B", "HOLD": "#B7791F",
                 "ERROR": "#8A94A6"}


# ---------------------------------------------------------------------------
# Secrets helpers
# ---------------------------------------------------------------------------
def get_secret(name):
    try:
        return st.secrets.get(name, None)
    except Exception:
        return None


TRIAL_KEY = get_secret("GOOGLE_API_KEY")
TRIAL_FRED = get_secret("FRED_API_KEY")


# ---------------------------------------------------------------------------
# Saved-portfolio storage (per user)
# ---------------------------------------------------------------------------
def _load_all():
    try:
        with open(PF_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_all(data):
    try:
        with open(PF_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return True
    except Exception:
        return False


def load_portfolio(user):
    return _load_all().get(user, [])


def save_portfolio(user, holdings):
    data = _load_all()
    data[user] = holdings
    return _save_all(data)


# ---------------------------------------------------------------------------
# Elo expected-score model (relative ranking, not a return forecast)
# ---------------------------------------------------------------------------
def elo_expected(rating_a, rating_b):
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


# Maps the AI signal to an Elo rating. These gaps are assumptions, not
# empirically calibrated values, and can be edited here.
SIGNAL_RATING = {"BUY": 1600, "HOLD": 1500, "SELL": 1400}


def signal_to_rating(sig):
    return SIGNAL_RATING.get(str(sig).upper(), 1500)


# ---------------------------------------------------------------------------
# Styling
# ---------------------------------------------------------------------------
def inject_style():
    st.markdown("""
    <style>
      @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=IBM+Plex+Mono:wght@500;600&display=swap');
      html, body, [class*="css"] { font-family:'Inter', system-ui, sans-serif; }
      .block-container { padding-top: 1.2rem; max-width: 1120px; }
      h1, h2, h3, h4 { color:#0F2A43; font-weight:700; letter-spacing:-0.01em; }
      .me-header { display:flex; align-items:center; gap:14px;
        padding:6px 0 16px; border-bottom:1px solid #E6E9EF; margin-bottom:18px; }
      .me-logo { width:44px; height:44px; border-radius:10px; background:#0F2A43;
        color:#fff; display:flex; align-items:center; justify-content:center;
        font-family:'IBM Plex Mono', monospace; font-weight:700; font-size:1rem; }
      .me-title { font-size:1.4rem; font-weight:700; color:#0F2A43; line-height:1.05; }
      .me-sub { font-size:0.74rem; color:#5B6675; font-weight:600;
        letter-spacing:0.14em; margin-top:2px; }
      .stButton>button { border-radius:8px; font-weight:600; padding:0.5rem 1.1rem;
        border:1px solid #D3D9E2; transition:0.15s; }
      .stButton>button[kind="primary"] { background:#0F2A43; border-color:#0F2A43; color:#fff; }
      .stButton>button[kind="primary"]:hover { background:#173e63; border-color:#173e63; }
      [data-testid="stMetric"] { background:#F7F9FC; border:1px solid #E6E9EF;
        border-radius:10px; padding:12px 16px; }
      .stTabs [data-baseweb="tab-list"] { gap:2px; }
      .sig-badge { padding:3px 11px; border-radius:6px; font-weight:600;
        font-size:0.8rem; font-family:'IBM Plex Mono', monospace; }
      .note-card { padding:11px 15px; border-radius:8px; border:1px solid #E6E9EF;
        background:#F7F9FC; font-size:0.9rem; color:#26364B; }
      [data-testid="stSidebar"] { background:#FBFCFE; border-right:1px solid #E6E9EF; }
    </style>
    """, unsafe_allow_html=True)


def signal_badge(sig):
    c = SIGNAL_COLORS.get(sig, "#455063")
    return (f'<span class="sig-badge" style="background:{c}1A;color:{c};'
            f'border:1px solid {c}55">{sig}</span>')


def header():
    st.markdown(
        f'<div class="me-header"><div class="me-logo">ME</div>'
        f'<div><div class="me-title">{BRAND}</div>'
        f'<div class="me-sub">{TAGLINE}</div></div></div>',
        unsafe_allow_html=True)


# ---------------------------------------------------------------------------
def require_login():
    if st.session_state.get("auth_ok"):
        return
    inject_style()
    header()
    st.subheader("Sign in")
    st.markdown(f'<div class="note-card">{DISCLAIMER}</div>', unsafe_allow_html=True)
    st.write("")
    user = st.text_input("Username")
    pw = st.text_input("Password", type="password")
    if st.button("Sign in", type="primary"):
        try:
            creds = dict(st.secrets.get("credentials", {}))
        except Exception:
            creds = {}
        if not creds:
            creds = {"demo": "demo"}
            st.warning("No credentials configured. Running in open demo mode. "
                       "Set a [credentials] block in Secrets before sharing.")
        if pw and creds.get(user) == pw:
            st.session_state["auth_ok"] = True
            st.session_state["user"] = user
            st.rerun()
        else:
            st.error("Invalid username or password.")
    st.stop()


require_login()

import yfinance as yf
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph


@st.cache_data(ttl=900, show_spinner=False)
def get_history(ticker, period="6mo"):
    try:
        df = yf.Ticker(ticker).history(period=period)
        return df if not df.empty else None
    except Exception:
        return None


@st.cache_data(ttl=900, show_spinner=False)
def get_quote(ticker):
    df = get_history(ticker, "1y")
    if df is None or df.empty:
        return None
    close = df["Close"]
    last = float(close.iloc[-1])
    prev = float(close.iloc[-2]) if len(close) > 1 else last
    return {"price": last, "chg_pct": (last / prev - 1) * 100 if prev else 0,
            "hi_52": float(close.max()), "lo_52": float(close.min()), "history": df}


# ---------------------------------------------------------------------------
inject_style()
header()
USER = st.session_state.get("user", "")

with st.sidebar:
    st.markdown("#### Settings")
    st.caption(f"Signed in as {USER}")
    if st.button("Sign out"):
        st.session_state.clear()
        st.rerun()

    st.divider()
    if TRIAL_KEY:
        provider = "google"
        st.markdown('<div class="note-card">Trial mode active. AI analyses run '
                    'on the provider key. No key required.</div>',
                    unsafe_allow_html=True)
        api_key = None
    else:
        st.markdown("**API key**")
        provider = st.selectbox("Provider", ["google", "openai", "anthropic"])
        api_key = st.text_input("API key", type="password",
                                help=f"Get one at {KEY_HELP[provider]}")
        st.caption(f"Free key at {KEY_HELP[provider]}. Used only for your "
                   "session, never stored.")

    # FRED / macro key
    if TRIAL_FRED:
        fred_key = None
        st.caption("Macro data (FRED) is enabled for this app.")
    else:
        fred_key = st.text_input("FRED key (optional, macro)", type="password",
                                 help="Free at fred.stlouisfed.org. Adds Fed rates, "
                                      "inflation and jobs data to the News analyst.")

    st.divider()
    default_model = "gemini-2.5-flash-lite" if provider == "google" else ""
    quick_model = st.text_input("Quick model", value=default_model).strip()
    deep_model = st.text_input("Deep model", value=default_model).strip()
    depth = st.select_slider("Research depth", ["Shallow", "Medium", "Deep"], "Shallow")
    rounds = {"Shallow": 1, "Medium": 2, "Deep": 3}[depth]
    analysts = st.multiselect("Analysts", list(ANALYST_LABELS.keys()),
                              default=["market", "news"],
                              format_func=lambda k: ANALYST_LABELS[k])
    today = dt.date.today()
    d = today - dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    analysis_date = st.date_input("Analysis date", value=d, max_value=today)


def apply_keys():
    if TRIAL_KEY:
        os.environ["GOOGLE_API_KEY"] = str(TRIAL_KEY)
    elif api_key:
        os.environ[PROVIDER_KEY_ENV[provider]] = api_key.strip()
    if TRIAL_FRED:
        os.environ["FRED_API_KEY"] = str(TRIAL_FRED)
    elif fred_key:
        os.environ["FRED_API_KEY"] = fred_key.strip()


def key_ready():
    return bool(TRIAL_KEY or api_key)


def build_config():
    cfg = DEFAULT_CONFIG.copy()
    cfg.update(llm_provider=provider, quick_think_llm=quick_model,
               deep_think_llm=deep_model, backend_url=None,
               max_debate_rounds=rounds, max_risk_discuss_rounds=rounds)
    return cfg


def normalize_signal(decision):
    t = str(decision).upper()
    for s in ("BUY", "SELL", "HOLD"):
        if s in t:
            return s
    return (t.strip()[:12] or "N/A")


def run_one(ticker, date_str, cfg, selected, retries=2):
    last = None
    for attempt in range(retries + 1):
        try:
            g = TradingAgentsGraph(debug=False, config=cfg,
                                   selected_analysts=tuple(selected))
            state, decision = g.propagate(ticker, date_str)
            return state, decision, None
        except Exception as e:  # noqa: BLE001
            last = str(e)
            transient = any(x in last for x in
                            ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE"))
            if transient and attempt < retries:
                time.sleep(20 * (attempt + 1))
                continue
            return None, None, last
    return None, None, last


def combined_markdown(ticker, date, state, decision):
    def b(t, body):
        return f"\n\n## {t}\n\n{body or '_Not available._'}"
    deb = state.get("investment_debate_state", {}) or {}
    rk = state.get("risk_debate_state", {}) or {}
    md = f"# {ticker} ({date})\n\nSignal: {decision}\n"
    md += b("Final Decision", state.get("final_trade_decision"))
    md += b("Market", state.get("market_report"))
    md += b("News", state.get("news_report"))
    md += b("Fundamentals", state.get("fundamentals_report"))
    md += b("Sentiment", state.get("sentiment_report"))
    md += b("Bull Case", deb.get("bull_history"))
    md += b("Bear Case", deb.get("bear_history"))
    md += b("Research Verdict", deb.get("judge_decision"))
    md += b("Trader Plan", state.get("trader_investment_plan"))
    md += b("Risk Verdict", rk.get("judge_decision"))
    return md


def render_report(state, decision):
    deb = state.get("investment_debate_state", {}) or {}
    rk = state.get("risk_debate_state", {}) or {}
    tabs = st.tabs(["Final Decision", "Market", "News", "Fundamentals",
                    "Sentiment", "Bull vs Bear", "Trader", "Risk"])
    tabs[0].markdown(state.get("final_trade_decision") or "_Not available._")
    tabs[1].markdown(state.get("market_report") or "_Not run._")
    tabs[2].markdown(state.get("news_report") or "_Not run._")
    tabs[3].markdown(state.get("fundamentals_report") or "_Not run._")
    tabs[4].markdown(state.get("sentiment_report") or "_Not run._")
    with tabs[5]:
        st.markdown("**Bull case**"); st.markdown(deb.get("bull_history") or "_n/a_")
        st.markdown("**Bear case**"); st.markdown(deb.get("bear_history") or "_n/a_")
        st.markdown("**Research verdict**"); st.markdown(deb.get("judge_decision") or "_n/a_")
    tabs[6].markdown(state.get("trader_investment_plan") or "_n/a_")
    tabs[7].markdown(rk.get("judge_decision") or "_n/a_")


def friendly_error(msg):
    if "RESOURCE_EXHAUSTED" in msg or "429" in msg:
        st.error("Rate limit reached (429). The AI key quota is used up for now. "
                 "Try again later or use gemini-2.5-flash-lite.")
    elif "503" in msg or "UNAVAILABLE" in msg:
        st.warning("Provider busy (503). Please try again shortly.")
    elif "API key" in msg or "API_KEY" in msg:
        st.error("API key problem. Check the key is valid for this provider and model.")
    else:
        st.error(msg)


def preflight():
    if not key_ready():
        st.error("Enter your API key in the sidebar first."); return False
    if not analysts:
        st.error("Select at least one analyst."); return False
    if not quick_model or not deep_model:
        st.error("Fill in both model names."); return False
    return True


def signal_style(df):
    def color(v):
        for s, c in SIGNAL_COLORS.items():
            if s in str(v):
                return f"color:{c}; font-weight:600"
        return ""
    return df.style.map(color, subset=["Signal"])


def show_chart_and_stats(ticker):
    q = get_quote(ticker)
    if not q:
        st.warning(f"Could not load price data for {ticker}. Check the symbol.")
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Price", f"${q['price']:.2f}", f"{q['chg_pct']:+.2f}%")
    c2.metric("52-week high", f"${q['hi_52']:.2f}")
    c3.metric("52-week low", f"${q['lo_52']:.2f}")
    rng = ((q['price'] - q['lo_52']) / (q['hi_52'] - q['lo_52']) * 100
           if q['hi_52'] > q['lo_52'] else 0)
    c4.metric("Position in range", f"{rng:.0f}%")
    st.line_chart(q["history"]["Close"], height=260)


def head_to_head_tool():
    with st.expander("Head-to-Head Probability (Elo model)"):
        st.caption("Estimates the probability that one stock outperforms another, "
                   "given each one's rating, using the Elo expected-score formula. "
                   "This is a relative ranking tool, not a return forecast or a "
                   "valuation. Ratings are inputs you assign (for example, a "
                   "conviction or momentum score); the model turns a rating gap "
                   "into a probability.")
        st.latex(r"E_A = \frac{1}{1 + 10^{(R_B - R_A)/400}}")
        c1, c2 = st.columns(2)
        na = c1.text_input("Stock A label", value="Stock A")
        ra = c1.number_input("Rating A", value=1500, step=10)
        nb = c2.text_input("Stock B label", value="Stock B")
        rb = c2.number_input("Rating B", value=1500, step=10)
        ea = elo_expected(ra, rb)
        r1, r2 = st.columns(2)
        r1.metric(f"P({na} outperforms {nb})", f"{ea * 100:.1f}%")
        r2.metric(f"P({nb} outperforms {na})", f"{(1 - ea) * 100:.1f}%")


# ===========================================================================
mode = st.radio("Mode", ["Standalone Stock", "My Portfolio"], horizontal=True)

# ---------------------------------------------------------------------------
# STANDALONE STOCK
# ---------------------------------------------------------------------------
if mode == "Standalone Stock":
    ticker = st.text_input("Ticker", value="", placeholder="e.g. AAPL").strip().upper()
    if ticker:
        st.markdown(f"#### {ticker}")
        show_chart_and_stats(ticker)

    if st.button("Run AI Analysis", type="primary"):
        if not ticker:
            st.error("Enter a ticker.")
        elif preflight():
            apply_keys()
            ds = analysis_date.strftime("%Y-%m-%d")
            with st.status(f"Analysing {ticker} ...", expanded=True) as s:
                st.write(f"{len(analysts)} analyst(s) plus research and risk review.")
                state, decision, err = run_one(ticker, ds, build_config(), analysts)
                if err:
                    s.update(label="Failed", state="error"); friendly_error(err); st.stop()
                s.update(label=f"Completed: {ticker}", state="complete")
            st.session_state["a_result"] = (ticker, ds, state, decision)

    if "a_result" in st.session_state:
        tk, ds, state, decision = st.session_state["a_result"]
        sig = normalize_signal(decision)
        st.markdown(
            f'<div class="note-card">{tk} analysis complete. Signal: '
            f'{signal_badge(sig)}</div>', unsafe_allow_html=True)
        st.write("")
        render_report(state, decision)
        st.download_button("Download report", combined_markdown(tk, ds, state, decision),
                           file_name=f"{tk}_{ds}.md", mime="text/markdown")

    st.write("")
    head_to_head_tool()

# ---------------------------------------------------------------------------
# MY PORTFOLIO
# ---------------------------------------------------------------------------
else:
    # Load this user's saved portfolio once per session.
    if not st.session_state.get("pf_loaded"):
        st.session_state["pf"] = load_portfolio(USER)
        st.session_state["pf_loaded"] = True
    st.session_state.setdefault("pf", [])

    st.markdown('<div class="note-card">Your portfolio is saved to your account. '
                'It loads automatically when you sign in.</div>',
                unsafe_allow_html=True)
    st.write("")

    with st.form("add_holding", clear_on_submit=True):
        c1, c2, c3 = st.columns([2, 1, 1])
        new_tk = c1.text_input("Ticker").strip().upper()
        new_sh = c2.number_input("Shares", min_value=0.0, value=1.0, step=1.0)
        if c3.form_submit_button("Add holding") and new_tk:
            st.session_state["pf"] = [h for h in st.session_state["pf"] if h["ticker"] != new_tk]
            st.session_state["pf"].append({"ticker": new_tk, "shares": new_sh})
            save_portfolio(USER, st.session_state["pf"])

    pf = st.session_state["pf"]
    if not pf:
        st.info("Add a few holdings above to build and save your portfolio.")
    else:
        rows = []
        for h in pf:
            q = get_quote(h["ticker"])
            price = q["price"] if q else 0.0
            rows.append({"Ticker": h["ticker"], "Shares": h["shares"],
                         "Price": round(price, 2), "Value": round(price * h["shares"], 2)})
        adf = pd.DataFrame(rows)
        total = adf["Value"].sum()
        adf["Weight %"] = (adf["Value"] / total * 100).round(1) if total else 0

        st.markdown("#### Holdings")
        st.dataframe(adf, hide_index=True, use_container_width=True)
        m1, m2 = st.columns(2)
        m1.metric("Total value", f"${total:,.0f}")
        m2.metric("Positions", len(pf))

        st.markdown("#### Allocation")
        st.bar_chart(adf.set_index("Ticker")["Weight %"], height=240)

        rm = st.selectbox("Remove a holding", ["None"] + [h["ticker"] for h in pf])
        if rm != "None" and st.button(f"Remove {rm}"):
            st.session_state["pf"] = [h for h in pf if h["ticker"] != rm]
            save_portfolio(USER, st.session_state["pf"])
            st.rerun()

        st.divider()
        pace = st.slider("Pause between tickers (seconds)", 0, 30, 5)
        if st.button("Analyse Whole Portfolio", type="primary"):
            if preflight():
                apply_keys()
                ds = analysis_date.strftime("%Y-%m-%d")
                cfg = build_config()
                wt = {r["Ticker"]: r["Weight %"] for r in rows}
                prog = st.progress(0.0, text="Starting ...")
                dash, results = [], {}
                tickers = [h["ticker"] for h in pf]
                for i, tk in enumerate(tickers):
                    prog.progress(i / len(tickers), text=f"Analysing {tk} ({i+1}/{len(tickers)}) ...")
                    state, decision, err = run_one(tk, ds, cfg, analysts)
                    if err:
                        dash.append({"Ticker": tk, "Weight %": wt.get(tk, 0),
                                     "Signal": "ERROR", "Note": err[:50]}); continue
                    sig = normalize_signal(decision)
                    flag = "High weight" if (sig in ("SELL", "HOLD") and wt.get(tk, 0) >= 15) else ""
                    dash.append({"Ticker": tk, "Weight %": wt.get(tk, 0),
                                 "Signal": sig, "Note": flag})
                    results[tk] = (state, decision)
                    if pace and i < len(tickers) - 1:
                        time.sleep(pace)
                prog.progress(1.0, text="Complete.")
                st.session_state["pf_result"] = {"dash": pd.DataFrame(dash),
                                                 "results": results, "date": ds}

        if "pf_result" in st.session_state:
            r = st.session_state["pf_result"]
            st.markdown("#### Portfolio signal dashboard")
            st.dataframe(signal_style(r["dash"]), hide_index=True, use_container_width=True)
            d = r["dash"]
            buys = d[d["Signal"] == "BUY"]["Weight %"].sum()
            sells = d[d["Signal"] == "SELL"]["Weight %"].sum()
            x1, x2 = st.columns(2)
            x1.metric("Weight rated BUY", f"{buys:.1f}%")
            x2.metric("Weight rated SELL", f"{sells:.1f}%")

            # Elo ranking derived from the AI signals
            sig_map = {tk: normalize_signal(dec) for tk, (stt, dec) in r["results"].items()}
            if len(sig_map) >= 2:
                st.markdown("#### AI signal ranking (Elo model)")
                st.caption("Relative ranking of your holdings, derived from each "
                           "stock's AI signal (BUY=1600, HOLD=1500, SELL=1400 - "
                           "assumptions, editable in code). The score is the average "
                           "probability each stock outperforms the others. "
                           "Illustrative relative ranking only, not an empirical "
                           "probability or a return forecast.")
                names = list(sig_map.keys())
                ratings = {t: signal_to_rating(sig_map[t]) for t in names}
                rank_rows = []
                for t in names:
                    others = [o for o in names if o != t]
                    avg = (sum(elo_expected(ratings[t], ratings[o]) for o in others)
                           / len(others)) if others else 0.5
                    rank_rows.append({"Ticker": t, "Signal": sig_map[t],
                                      "Rating": ratings[t],
                                      "Avg win-prob vs peers %": round(avg * 100, 1)})
                rank_df = pd.DataFrame(rank_rows).sort_values(
                    "Avg win-prob vs peers %", ascending=False)
                st.dataframe(signal_style(rank_df), hide_index=True,
                             use_container_width=True)

                st.markdown("**Head-to-head from AI signals**")
                h1, h2 = st.columns(2)
                a = h1.selectbox("Stock A", names, index=0, key="h2h_a")
                b = h2.selectbox("Stock B", names,
                                 index=min(1, len(names) - 1), key="h2h_b")
                if a != b:
                    ea = elo_expected(ratings[a], ratings[b])
                    q1, q2 = st.columns(2)
                    q1.metric(f"P({a} outperforms {b})", f"{ea * 100:.1f}%")
                    q2.metric(f"P({b} outperforms {a})", f"{(1 - ea) * 100:.1f}%")

            for tk, (state, decision) in r["results"].items():
                sig = normalize_signal(decision)
                with st.expander(f"{tk}  -  {sig}"):
                    render_report(state, decision)
            st.markdown('<div class="note-card">Each signal is judged per stock in '
                        'isolation and does not assess concentration across the '
                        'portfolio. Not financial advice.</div>', unsafe_allow_html=True)

st.write("")
st.caption(DISCLAIMER)
