"""Daily closes via yfinance, with exchange suffixes for non-US listings."""

import pandas as pd
import yfinance as yf

# Ticker as the analyst writes it -> Yahoo Finance symbol. Edit in the app
# sidebar; anything not listed is looked up as a US ticker.
DEFAULT_SYMBOL_MAP = {
    "SIVE": "SIVE.ST",     # Sivers Semiconductors, Stockholm
    "SOI": "SOI.PA",       # Soitec, Paris
    "XFAB": "XFAB.PA",     # X-FAB, Paris
    "TSEM": "TSEM",
    "3374": "3374.TWO",
    "8147": "8147.T",
}


def parse_symbol_map(text):
    m = {}
    for line in text.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            if k.strip() and v.strip():
                m[k.strip().upper()] = v.strip()
    return m


def format_symbol_map(m):
    return "\n".join(f"{k}={v}" for k, v in sorted(m.items()))


def history(tickers, start, symbol_map=None):
    """Close prices, one column per (unmapped) ticker, indexed by date."""
    symbol_map = symbol_map or {}
    sym = {t: symbol_map.get(t, t) for t in tickers}
    if not sym:
        return pd.DataFrame()
    raw = yf.download(sorted(set(sym.values())), start=pd.Timestamp(start).date(),
                      auto_adjust=True, progress=False, threads=True)
    if raw is None or raw.empty:
        return pd.DataFrame()
    close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
    if not isinstance(raw.columns, pd.MultiIndex):
        close.columns = [next(iter(sym.values()))]
    out = pd.DataFrame(index=close.index)
    for t, s in sym.items():
        if s in close.columns:
            out[t] = close[s]
    out.index = pd.to_datetime(out.index).tz_localize(None)
    return out.dropna(how="all", axis=1)


def close_on_or_after(series, when):
    """First close on or after a timestamp (the price a reader could act on)."""
    s = series.dropna()
    s = s[s.index >= pd.Timestamp(when).tz_localize(None).normalize()]
    return (s.index[0], float(s.iloc[0])) if len(s) else (None, None)
