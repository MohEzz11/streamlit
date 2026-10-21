"""Window summaries (day / week / month / quarter) and call performance."""

import pandas as pd

from . import prices as px

WINDOWS = {"Daily": 1, "Weekly": 7, "Monthly": 28, "Quarterly": 90}
OPINION = ["bullish", "bearish", "neutral"]


def window_slice(df, days, end=None):
    end = end or pd.Timestamp.now(tz="UTC")
    return df[(df["created_at"] > end - pd.Timedelta(days=days)) &
              (df["created_at"] <= end)]


def ticker_table(df, days, end=None):
    """Per-ticker mention and stance counts inside the window, plus history."""
    w = window_slice(df, days, end)
    if w.empty:
        return pd.DataFrame()
    first = df.groupby("ticker")["created_at"].min().rename("first_mention")
    g = w.groupby("ticker")
    t = pd.DataFrame({
        "mentions": g.size(),
        "bull": g["stance"].apply(lambda s: (s == "bullish").sum()),
        "bear": g["stance"].apply(lambda s: (s == "bearish").sum()),
        "neu": g["stance"].apply(lambda s: (s == "neutral").sum()),
        "latest_mention": g["created_at"].max(),
    }).join(first)
    t["net"] = t["bull"] - t["bear"]
    t["direction"] = t["net"].apply(
        lambda n: "bullish" if n > 0 else "bearish" if n < 0 else "no stance")
    t["new"] = t["first_mention"] > (end or pd.Timestamp.now(tz="UTC")) - pd.Timedelta(days=days)
    return t.sort_values("mentions", ascending=False)


def latest_stance(df):
    """Most recent explicit (non-background) stance per ticker."""
    op = df[df["stance"].isin(OPINION)].sort_values("created_at")
    return op.groupby("ticker").tail(1).set_index("ticker")


def stance_shifts(df, days, end=None):
    """Tickers whose latest explicit stance in the window differs from the
    explicit stance before the window started."""
    end = end or pd.Timestamp.now(tz="UTC")
    start = end - pd.Timedelta(days=days)
    op = df[df["stance"].isin(["bullish", "bearish"])].sort_values("created_at")
    before = op[op["created_at"] <= start].groupby("ticker")["stance"].last()
    inside = op[(op["created_at"] > start) & (op["created_at"] <= end)]
    now = inside.groupby("ticker")["stance"].last()
    both = pd.concat([before.rename("before"), now.rename("now")], axis=1).dropna()
    return both[both["before"] != both["now"]]


def call_performance(df, symbol_map, benchmark="SMH"):
    """For each ticker: price at the first bullish (or bearish) call vs now,
    compared with the benchmark over the same dates.

    Return is measured from the first close on or after the post, so it is
    what a reader could have captured, not the author's own entry.
    """
    op = df[df["stance"].isin(["bullish", "bearish"])]
    if op.empty:
        return pd.DataFrame()
    first_call = op.sort_values("created_at").groupby("ticker").first()
    start = first_call["created_at"].min() - pd.Timedelta(days=5)
    hist = px.history(list(first_call.index) + [benchmark], start, symbol_map)
    if hist.empty:
        return pd.DataFrame()

    rows = []
    for t, r in first_call.iterrows():
        if t not in hist.columns:
            rows.append({"ticker": t, "first_call": r["created_at"].date(),
                         "call": r["stance"], "note": "no price data"})
            continue
        d0, p0 = px.close_on_or_after(hist[t], r["created_at"])
        if p0 is None:
            continue
        p1 = float(hist[t].dropna().iloc[-1])
        ret = p1 / p0 - 1
        bret = None
        if benchmark in hist.columns:
            _, b0 = px.close_on_or_after(hist[benchmark], r["created_at"])
            if b0:
                bret = float(hist[benchmark].dropna().iloc[-1]) / b0 - 1
        signed = ret if r["stance"] == "bullish" else -ret
        rows.append({
            "ticker": t, "first_call": d0.date(), "call": r["stance"],
            "price_then": round(p0, 2), "price_now": round(p1, 2),
            "return": ret, "benchmark": bret,
            "excess": None if bret is None else signed - (bret if r["stance"] == "bullish" else -bret),
            "call_correct": signed > 0,
            "note": "",
        })
    return pd.DataFrame(rows).sort_values("first_call")


def performance_summary(perf):
    p = perf.dropna(subset=["return"]) if "return" in perf else perf
    if p.empty:
        return {}
    ex = p["excess"].dropna()
    return {
        "calls": len(p),
        "hit_rate": float(p["call_correct"].mean()),
        "beat_benchmark": float((ex > 0).mean()) if len(ex) else None,
        "median_excess": float(ex.median()) if len(ex) else None,
        "mean_excess": float(ex.mean()) if len(ex) else None,
    }
