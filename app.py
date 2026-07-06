"""
TradingAgents Research Platform (v5, trial)
=============================================
Two modes:
  • Standalone Stock — analyse any single ticker: price chart, quick stats,
                       and a full AI multi-agent report.
  • My Portfolio     — build a portfolio (add tickers + shares), see allocation
                       analytics, then run AI analysis across every holding.

TRIAL / KEY MODEL:
  • If GOOGLE_API_KEY is set in Streamlit Secrets, the app runs on the OWNER's
    key (trial mode) and users don't need to enter anything.
  • If it is NOT set, each user pastes their own key (bring-your-own).

LOGIN (Streamlit Secrets):
    GOOGLE_API_KEY = "AIza..."          # optional: enables trial mode

    [credentials]
    user1 = "password1"
    user2 = "password2"
    user3 = "password3"

NOTE: Portfolios are session-based in this trial (reset on logout).
RESEARCH ONLY — NOT FINANCIAL ADVICE.
"""

import os
import time
import datetime as dt

import pandas as pd
import streamlit as st

st.set_page_config(page_title="TradingAgents", page_icon="📈", layout="wide")

BETA_BANNER = ("🧪 **Beta — research only. Not financial advice.** "
               "AI output is one model's opinion and varies run to run.")

PROVIDER_KEY_ENV = {"google": "GOOGLE_API_KEY",
                    "openai": "OPENAI_API_KEY",
                    "anthropic": "ANTHROPIC_API_KEY"}
KEY_HELP = {"google": "aistudio.google.com/apikey",
            "openai": "platform.openai.com/api-keys",
            "anthropic": "console.anthropic.com"}
ANALYST_LABELS = {"market": "Market (technical)", "news": "News (macro)",
                  "fundamentals": "Fundamentals", "social": "Sentiment (social)"}
SIGNAL_EMOJI = {"BUY": "🟢 BUY", "SELL": "🔴 SELL", "HOLD": "🟡 HOLD"}


# --- detect trial (owner) key -------------------------------------------
def get_trial_key():
    try:
        return st.secrets.get("GOOGLE_API_KEY", None)
    except Exception:
        return None


TRIAL_KEY = get_trial_key()


# --- login gate ----------------------------------------------------------
def require_login():
    if st.session_state.get("auth_ok"):
        return
    st.title("🔒 TradingAgents — Beta Access")
    st.caption(BETA_BANNER)
    user = st.text_input("Username")
    pw = st.text_input("Password", type="password")
    if st.button("Log in", type="primary"):
        try:
            creds = dict(st.secrets.get("credentials", {}))
        except Exception:
            creds = {}
        if not creds:
            creds = {"demo": "demo"}
            st.warning("⚠️ No credentials configured — open demo mode. "
                       "Set a [credentials] block in Secrets before sharing.")
        if pw and creds.get(user) == pw:
            st.session_state["auth_ok"] = True
            st.session_state["user"] = user
            st.rerun()
        else:
            st.error("Invalid username or password.")
    st.stop()


require_login()

# Heavy imports only after login.
import yfinance as yf
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph


# --- market data helpers (free — no LLM cost) ---------------------------
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
    return {
        "price": last,
        "chg_pct": (last / prev - 1) * 100 if prev else 0,
        "hi_52": float(close.max()),
        "lo_52": float(close.min()),
        "history": df,
    }


# ----------------------------------------------------------------------
st.title("📈 TradingAgents — Research Platform")
st.info(BETA_BANNER)

with st.sidebar:
    st.header("⚙️ Settings")
    st.caption(f"Signed in as **{st.session_state.get('user','')}**")
    if st.button("Log out"):
        st.session_state.clear()
        st.rerun()

    st.divider()
    if TRIAL_KEY:
        provider = "google"
        st.success("✅ Trial mode — AI analyses run on the provider's key. "
                   "No key needed.")
        api_key = None
    else:
        st.subheader("🔑 Your API key")
        provider = st.selectbox("Provider", ["google", "openai", "anthropic"])
        api_key = st.text_input("API key", type="password",
                                help=f"Get one at {KEY_HELP[provider]}")
        st.caption(f"🔒 Free key at {KEY_HELP[provider]}. Used only for your "
                   "session, never stored.")

    fred_key = st.text_input("FRED key (optional macro)", type="password")

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
    if fred_key:
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
            if any(x in last for x in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE")) and attempt < retries:
                time.sleep(20 * (attempt + 1)); continue
            return None, None, last
    return None, None, last


def combined_markdown(ticker, date, state, decision):
    def b(t, body):
        return f"\n\n## {t}\n\n{body or '_n/a_'}"
    deb = state.get("investment_debate_state", {}) or {}
    rk = state.get("risk_debate_state", {}) or {}
    md = f"# {ticker} ({date})\n\n**Signal:** {decision}\n"
    md += b("Final Decision", state.get("final_trade_decision"))
    md += b("Market", state.get("market_report"))
    md += b("News", state.get("news_report"))
    md += b("Fundamentals", state.get("fundamentals_report"))
    md += b("Sentiment", state.get("sentiment_report"))
    md += b("Bull", deb.get("bull_history"))
    md += b("Bear", deb.get("bear_history"))
    md += b("Research Verdict", deb.get("judge_decision"))
    md += b("Trader Plan", state.get("trader_investment_plan"))
    md += b("Risk Verdict", rk.get("judge_decision"))
    return md


def render_report(state, decision):
    deb = state.get("investment_debate_state", {}) or {}
    rk = state.get("risk_debate_state", {}) or {}
    tabs = st.tabs(["🏁 Final", "📊 Market", "🌍 News", "💰 Fundamentals",
                    "💬 Sentiment", "🐂🐻 Bull/Bear", "🧑‍💼 Trader", "⚖️ Risk"])
    tabs[0].markdown(state.get("final_trade_decision") or "_n/a_")
    tabs[1].markdown(state.get("market_report") or "_Not run._")
    tabs[2].markdown(state.get("news_report") or "_Not run._")
    tabs[3].markdown(state.get("fundamentals_report") or "_Not run._")
    tabs[4].markdown(state.get("sentiment_report") or "_Not run._")
    with tabs[5]:
        st.subheader("Bull"); st.markdown(deb.get("bull_history") or "_n/a_")
        st.subheader("Bear"); st.markdown(deb.get("bear_history") or "_n/a_")
        st.subheader("Verdict"); st.markdown(deb.get("judge_decision") or "_n/a_")
    tabs[6].markdown(state.get("trader_investment_plan") or "_n/a_")
    tabs[7].markdown(rk.get("judge_decision") or "_n/a_")


def friendly_error(msg):
    if "RESOURCE_EXHAUSTED" in msg or "429" in msg:
        st.error("**Rate limit (429).** The AI key's quota is used up for now. "
                 "Try again later or use gemini-2.5-flash-lite.")
    elif "503" in msg or "UNAVAILABLE" in msg:
        st.warning("**Provider busy (503).** Try again shortly.")
    elif "API key" in msg or "API_KEY" in msg:
        st.error("**API key problem.** Check the key is valid for this provider/model.")
    else:
        st.error(msg)


def preflight():
    if not key_ready():
        st.error("🔑 Enter your API key in the sidebar first."); return False
    if not analysts:
        st.error("Select at least one analyst."); return False
    if not quick_model or not deep_model:
        st.error("Fill in both model names."); return False
    return True


def show_chart_and_stats(ticker):
    q = get_quote(ticker)
    if not q:
        st.warning(f"Couldn't load price data for {ticker}. Check the symbol.")
        return
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Price", f"${q['price']:.2f}", f"{q['chg_pct']:+.2f}%")
    c2.metric("52-wk high", f"${q['hi_52']:.2f}")
    c3.metric("52-wk low", f"${q['lo_52']:.2f}")
    rng = (q['price'] - q['lo_52']) / (q['hi_52'] - q['lo_52']) * 100 if q['hi_52'] > q['lo_52'] else 0
    c4.metric("In 52-wk range", f"{rng:.0f}%")
    st.line_chart(q["history"]["Close"], height=260)


# ======================================================================
mode = st.radio("Choose a mode", ["📊 Standalone Stock", "💼 My Portfolio"],
                horizontal=True)

# ----------------------------------------------------------------------
# MODE A — STANDALONE STOCK
# ----------------------------------------------------------------------
if mode == "📊 Standalone Stock":
    ticker = st.text_input("Ticker", value="", placeholder="e.g. AAPL").strip().upper()
    if ticker:
        st.subheader(f"{ticker} — price & stats")
        show_chart_and_stats(ticker)

    if st.button("🤖 Run AI Analysis", type="primary"):
        if not ticker:
            st.error("Enter a ticker.")
        elif preflight():
            apply_keys()
            ds = analysis_date.strftime("%Y-%m-%d")
            with st.status(f"Analysing {ticker}…", expanded=True) as s:
                st.write(f"{len(analysts)} analyst(s) + research + risk…")
                state, decision, err = run_one(ticker, ds, build_config(), analysts)
                if err:
                    s.update(label="❌ Failed", state="error"); friendly_error(err); st.stop()
                s.update(label=f"✅ Done — {ticker}", state="complete")
            st.session_state["a_result"] = (ticker, ds, state, decision)

    if "a_result" in st.session_state:
        tk, ds, state, decision = st.session_state["a_result"]
        sig = normalize_signal(decision)
        st.success(f"**{tk}** — AI signal: **{SIGNAL_EMOJI.get(sig, sig)}**")
        render_report(state, decision)
        st.download_button("⬇️ Download report", combined_markdown(tk, ds, state, decision),
                           file_name=f"{tk}_{ds}.md", mime="text/markdown")

# ----------------------------------------------------------------------
# MODE B — MY PORTFOLIO
# ----------------------------------------------------------------------
else:
    st.caption("ℹ️ Trial: your portfolio is saved for this session and resets when "
               "you log out.")
    st.session_state.setdefault("pf", [])  # list of {ticker, shares}

    with st.form("add_holding", clear_on_submit=True):
        c1, c2, c3 = st.columns([2, 1, 1])
        new_tk = c1.text_input("Ticker").strip().upper()
        new_sh = c2.number_input("Shares", min_value=0.0, value=1.0, step=1.0)
        add = c3.form_submit_button("➕ Add")
        if add and new_tk:
            st.session_state["pf"] = [h for h in st.session_state["pf"] if h["ticker"] != new_tk]
            st.session_state["pf"].append({"ticker": new_tk, "shares": new_sh})

    pf = st.session_state["pf"]
    if not pf:
        st.info("Add a few holdings above to build your portfolio.")
    else:
        # Build analytics table
        rows = []
        for h in pf:
            q = get_quote(h["ticker"])
            price = q["price"] if q else 0.0
            rows.append({"Ticker": h["ticker"], "Shares": h["shares"],
                         "Price": round(price, 2), "Value": round(price * h["shares"], 2)})
        adf = pd.DataFrame(rows)
        total = adf["Value"].sum()
        adf["Weight %"] = (adf["Value"] / total * 100).round(1) if total else 0

        st.subheader("💼 Holdings")
        st.dataframe(adf, hide_index=True, use_container_width=True)
        m1, m2 = st.columns(2)
        m1.metric("Total value", f"${total:,.0f}")
        m2.metric("Positions", len(pf))

        st.subheader("📊 Allocation")
        st.bar_chart(adf.set_index("Ticker")["Weight %"], height=240)

        rm = st.selectbox("Remove a holding", ["—"] + [h["ticker"] for h in pf])
        if rm != "—" and st.button(f"Remove {rm}"):
            st.session_state["pf"] = [h for h in pf if h["ticker"] != rm]
            st.rerun()

        st.divider()
        pace = st.slider("Pause between tickers (sec)", 0, 30, 5)
        if st.button("🤖 Analyse Whole Portfolio with AI", type="primary"):
            if preflight():
                apply_keys()
                ds = analysis_date.strftime("%Y-%m-%d")
                cfg = build_config()
                wt = {r["Ticker"]: r["Weight %"] for r in rows}
                prog = st.progress(0.0, text="Starting…")
                dash, results = [], {}
                tickers = [h["ticker"] for h in pf]
                for i, tk in enumerate(tickers):
                    prog.progress(i / len(tickers), text=f"Analysing {tk} ({i+1}/{len(tickers)})…")
                    state, decision, err = run_one(tk, ds, cfg, analysts)
                    if err:
                        dash.append({"Ticker": tk, "Weight %": wt.get(tk, 0),
                                     "Signal": "⚠️ ERROR", "Detail": err[:50]}); continue
                    sig = normalize_signal(decision)
                    flag = "High weight" if (sig in ("SELL", "HOLD") and wt.get(tk, 0) >= 15) else ""
                    dash.append({"Ticker": tk, "Weight %": wt.get(tk, 0),
                                 "Signal": SIGNAL_EMOJI.get(sig, sig), "Note": flag})
                    results[tk] = (state, decision)
                    if pace and i < len(tickers) - 1:
                        time.sleep(pace)
                prog.progress(1.0, text="Done.")
                st.session_state["pf_result"] = {"dash": pd.DataFrame(dash),
                                                 "results": results, "date": ds}

        if "pf_result" in st.session_state:
            r = st.session_state["pf_result"]
            st.subheader("🧭 Portfolio signal dashboard")
            st.dataframe(r["dash"], hide_index=True, use_container_width=True)
            d = r["dash"]
            buys = d[d["Signal"].str.contains("BUY")]["Weight %"].sum()
            sells = d[d["Signal"].str.contains("SELL")]["Weight %"].sum()
            x1, x2 = st.columns(2)
            x1.metric("Weight rated BUY", f"{buys:.1f}%")
            x2.metric("Weight rated SELL", f"{sells:.1f}%")
            for tk, (state, decision) in r["results"].items():
                sig = normalize_signal(decision)
                with st.expander(f"{tk} — {SIGNAL_EMOJI.get(sig, sig)}"):
                    render_report(state, decision)
            st.warning("⚠️ Each signal is judged per-stock in isolation — it does NOT "
                       "assess concentration across your portfolio. Not financial advice.")
