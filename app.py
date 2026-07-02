"""
TradingAgents — Web UI (v4: generic, bring-your-own-key)
========================================================
A shareable research tool. Each user:
  • logs in (simple beta gate),
  • pastes THEIR OWN LLM API key (so the app owner pays nothing),
  • analyses ANY ticker(s) they choose.

No personal portfolio data is stored in this app.

LOGIN credentials live in Streamlit Secrets (Cloud) as:
    [credentials]
    tester1 = "password1"
    tester2 = "password2"

RESEARCH ONLY — NOT FINANCIAL ADVICE.
"""

import os
import time
import datetime as dt

import pandas as pd
import streamlit as st

st.set_page_config(page_title="TradingAgents", page_icon="📈", layout="wide")

BETA_BANNER = ("🧪 **Beta — research only. Not financial advice.** "
               "Outputs are one AI model's opinion and vary run to run.")

PROVIDER_KEY_ENV = {
    "google": "GOOGLE_API_KEY",
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}
KEY_HELP = {
    "google": "Get a free key at aistudio.google.com/apikey",
    "openai": "Get a key at platform.openai.com/api-keys",
    "anthropic": "Get a key at console.anthropic.com",
}
MODEL_HINTS = {
    "google": "e.g. gemini-2.5-flash-lite  ·  gemini-2.5-flash",
    "openai": "e.g. gpt-5.4-mini  ·  gpt-5.5",
    "anthropic": "e.g. claude-haiku-4-5  ·  claude-sonnet-5",
}
ANALYST_LABELS = {
    "market": "Market (technical)",
    "news": "News (macro / headlines)",
    "fundamentals": "Fundamentals",
    "social": "Sentiment (social media)",
}
SIGNAL_EMOJI = {"BUY": "🟢 BUY", "SELL": "🔴 SELL", "HOLD": "🟡 HOLD"}


# --- Login gate ----------------------------------------------------------
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
            st.warning("⚠️ No credentials configured — running in open demo mode. "
                       "Set a [credentials] block in Secrets before sharing.")
        if pw and creds.get(user) == pw:
            st.session_state["auth_ok"] = True
            st.session_state["user"] = user
            st.rerun()
        else:
            st.error("Invalid username or password.")
    st.stop()


require_login()

# Framework imported only after login (keeps the login page light).
from tradingagents.default_config import DEFAULT_CONFIG
from tradingagents.graph.trading_graph import TradingAgentsGraph


st.title("📈 TradingAgents — AI Stock Research")
st.info(BETA_BANNER)

with st.sidebar:
    st.header("⚙️ Settings")
    st.caption(f"Signed in as **{st.session_state.get('user','')}**")
    if st.button("Log out"):
        st.session_state.clear()
        st.rerun()

    st.divider()
    st.subheader("🔑 Your API key")
    provider = st.selectbox("LLM provider", ["google", "openai", "anthropic"], index=0)
    api_key = st.text_input("API key", type="password", help=KEY_HELP[provider])
    st.caption(f"🔒 {KEY_HELP[provider]}. Your key is used only for your session "
               "and is never stored.")
    fred_key = st.text_input("FRED key (optional, for macro)", type="password",
                             help="Free at fred.stlouisfed.org — improves the News analyst.")

    st.divider()
    st.caption(MODEL_HINTS[provider])
    default_model = "gemini-2.5-flash-lite" if provider == "google" else ""
    quick_model = st.text_input("Quick-thinking model", value=default_model).strip()
    deep_model = st.text_input("Deep-thinking model", value=default_model).strip()

    depth = st.select_slider("Research depth", ["Shallow", "Medium", "Deep"], "Shallow")
    rounds = {"Shallow": 1, "Medium": 2, "Deep": 3}[depth]

    analysts = st.multiselect(
        "Analysts to run",
        list(ANALYST_LABELS.keys()),
        default=["market", "news"],
        format_func=lambda k: ANALYST_LABELS[k],
        help="Fewer analysts = fewer API calls = cheaper and less likely to hit limits.",
    )

    today = dt.date.today()
    default_day = today - dt.timedelta(days=1)
    while default_day.weekday() >= 5:
        default_day -= dt.timedelta(days=1)
    analysis_date = st.date_input("Analysis date", value=default_day, max_value=today)

    mode = st.radio("Mode", ["Single ticker", "Batch (list of tickers)"])


def apply_keys():
    """Put the user's own keys into the environment for this run."""
    if api_key:
        os.environ[PROVIDER_KEY_ENV[provider]] = api_key.strip()
    if fred_key:
        os.environ["FRED_API_KEY"] = fred_key.strip()


def build_config():
    cfg = DEFAULT_CONFIG.copy()
    cfg["llm_provider"] = provider
    cfg["quick_think_llm"] = quick_model
    cfg["deep_think_llm"] = deep_model
    cfg["backend_url"] = None
    cfg["max_debate_rounds"] = rounds
    cfg["max_risk_discuss_rounds"] = rounds
    return cfg


def normalize_signal(decision) -> str:
    t = str(decision).upper()
    if "BUY" in t:
        return "BUY"
    if "SELL" in t:
        return "SELL"
    if "HOLD" in t:
        return "HOLD"
    return (t.strip()[:12] or "N/A")


def run_one(ticker, date_str, cfg, selected, retries=2):
    last_err = None
    for attempt in range(retries + 1):
        try:
            graph = TradingAgentsGraph(
                debug=False, config=cfg, selected_analysts=tuple(selected)
            )
            state, decision = graph.propagate(ticker, date_str)
            return state, decision, None
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            transient = any(x in last_err for x in
                            ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE"))
            if transient and attempt < retries:
                time.sleep(20 * (attempt + 1))
                continue
            return None, None, last_err
    return None, None, last_err


def combined_markdown(ticker, date, state, decision):
    def block(title, body):
        return f"\n\n## {title}\n\n{body or '_No report generated._'}"
    debate = state.get("investment_debate_state", {}) or {}
    risk = state.get("risk_debate_state", {}) or {}
    md = f"# TradingAgents Report — {ticker} ({date})\n\n**Final signal:** {decision}\n"
    md += block("Final Trade Decision", state.get("final_trade_decision"))
    md += block("Market Analyst (Technical)", state.get("market_report"))
    md += block("News Analyst (Macro)", state.get("news_report"))
    md += block("Fundamentals Analyst", state.get("fundamentals_report"))
    md += block("Sentiment Analyst", state.get("sentiment_report"))
    md += block("Bull Case", debate.get("bull_history"))
    md += block("Bear Case", debate.get("bear_history"))
    md += block("Research Manager Verdict", debate.get("judge_decision"))
    md += block("Trader Plan", state.get("trader_investment_plan"))
    md += block("Risk Panel Verdict", risk.get("judge_decision"))
    return md


def render_tabs(state, decision):
    debate = state.get("investment_debate_state", {}) or {}
    risk = state.get("risk_debate_state", {}) or {}
    tabs = st.tabs(["🏁 Final", "📊 Market", "🌍 News", "💰 Fundamentals",
                    "💬 Sentiment", "🐂🐻 Bull/Bear", "🧑‍💼 Trader", "⚖️ Risk"])
    tabs[0].markdown(state.get("final_trade_decision") or "_No decision text._")
    tabs[1].markdown(state.get("market_report") or "_Not run._")
    tabs[2].markdown(state.get("news_report") or "_Not run._")
    tabs[3].markdown(state.get("fundamentals_report") or "_Not run._")
    tabs[4].markdown(state.get("sentiment_report") or "_Not run._")
    with tabs[5]:
        st.subheader("Bull"); st.markdown(debate.get("bull_history") or "_n/a_")
        st.subheader("Bear"); st.markdown(debate.get("bear_history") or "_n/a_")
        st.subheader("Verdict"); st.markdown(debate.get("judge_decision") or "_n/a_")
    tabs[6].markdown(state.get("trader_investment_plan") or "_n/a_")
    tabs[7].markdown(risk.get("judge_decision") or "_n/a_")


def friendly_error(msg):
    if "API key" in msg or "API_KEY" in msg or "credential" in msg.lower():
        st.error("**API key problem.** Check the key you pasted is valid for the "
                 "selected provider and has access to the chosen model.")
    elif "RESOURCE_EXHAUSTED" in msg or "429" in msg:
        st.error("**Rate limit (429).** Your key's free-tier quota is used up. "
                 "Use gemini-2.5-flash-lite, run fewer analysts, wait for the daily "
                 "reset, or enable billing on your own account.")
    elif "503" in msg or "UNAVAILABLE" in msg:
        st.warning("**Provider busy (503).** Temporary — press Run again shortly.")
    else:
        st.error(msg)


def preflight():
    if not api_key:
        st.error("🔑 Paste your API key in the sidebar first."); return False
    if not analysts:
        st.error("Select at least one analyst."); return False
    if not quick_model or not deep_model:
        st.error("Fill in both model names."); return False
    return True


# ======================================================================
# MODE 1 — SINGLE TICKER
# ======================================================================
if mode == "Single ticker":
    ticker = st.text_input("Ticker symbol", value="", placeholder="e.g. AAPL").strip().upper()
    if st.button("🚀 Run Analysis", type="primary"):
        if not ticker:
            st.error("Enter a ticker symbol.")
        elif preflight():
            apply_keys()
            date_str = analysis_date.strftime("%Y-%m-%d")
            with st.status(f"Analysing {ticker}…", expanded=True) as s:
                st.write(f"Running {len(analysts)} analyst(s) + research + risk…")
                state, decision, err = run_one(ticker, date_str, build_config(), analysts)
                if err:
                    s.update(label="❌ Failed", state="error")
                    friendly_error(err)
                    st.stop()
                s.update(label=f"✅ Done — {ticker}", state="complete")
            st.session_state["single"] = (ticker, date_str, state, decision)

    if "single" in st.session_state:
        ticker, date_str, state, decision = st.session_state["single"]
        sig = normalize_signal(decision)
        st.success(f"**{ticker}** — signal: **{SIGNAL_EMOJI.get(sig, sig)}**")
        render_tabs(state, decision)
        st.download_button("⬇️ Download report (.md)",
                           combined_markdown(ticker, date_str, state, decision),
                           file_name=f"{ticker}_{date_str}_report.md",
                           mime="text/markdown")


# ======================================================================
# MODE 2 — BATCH
# ======================================================================
else:
    st.subheader("📋 Analyse a list of tickers")
    raw = st.text_input("Tickers (comma-separated)", value="",
                        placeholder="e.g. AAPL, MSFT, TSLA, NVDA")
    picks = [t.strip().upper() for t in raw.split(",") if t.strip()]
    pace = st.slider("Pause between tickers (seconds)", 0, 30, 5,
                     help="Spacing calls out reduces rate-limit errors on free tiers.")

    if picks:
        est = len(picks) * (len(analysts) + 6)
        st.caption(f"{len(picks)} tickers → ≈ {est} model calls total.")

    if st.button("🚀 Run Batch", type="primary"):
        if not picks:
            st.error("Enter at least one ticker.")
        elif preflight():
            apply_keys()
            date_str = analysis_date.strftime("%Y-%m-%d")
            cfg = build_config()
            prog = st.progress(0.0, text="Starting…")
            rows, results = [], {}
            for i, tk in enumerate(picks):
                prog.progress(i / len(picks), text=f"Analysing {tk} ({i+1}/{len(picks)})…")
                state, decision, err = run_one(tk, date_str, cfg, analysts)
                if err:
                    rows.append({"Ticker": tk, "Signal": "⚠️ ERROR", "Detail": err[:70]})
                    continue
                sig = normalize_signal(decision)
                rows.append({"Ticker": tk, "Signal": SIGNAL_EMOJI.get(sig, sig), "Detail": ""})
                results[tk] = (state, decision)
                if pace and i < len(picks) - 1:
                    time.sleep(pace)
            prog.progress(1.0, text="Done.")
            st.session_state["batch"] = {"dash": pd.DataFrame(rows),
                                        "results": results, "date": date_str}

    if "batch" in st.session_state:
        b = st.session_state["batch"]
        st.markdown("### 🧭 Signal summary")
        st.dataframe(b["dash"], hide_index=True, use_container_width=True)
        st.markdown("### 📄 Detail")
        for tk, (state, decision) in b["results"].items():
            sig = normalize_signal(decision)
            with st.expander(f"{tk} — {SIGNAL_EMOJI.get(sig, sig)}"):
                render_tabs(state, decision)
                st.download_button("⬇️ Download", combined_markdown(tk, b["date"], state, decision),
                                   file_name=f"{tk}_{b['date']}_report.md",
                                   mime="text/markdown", key=f"dl_{tk}")

    st.caption("Each signal is one model's opinion on one date, analysed in isolation. "
               "Not financial advice.")
