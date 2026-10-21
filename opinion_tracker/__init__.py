"""
Opinion Tracker
===============
Turns an analyst's public X posts into a structured, searchable record of
stock opinions: every ticker mention tagged bullish, bearish, neutral or
background, with stance history, source links, price since first mention,
and a track record measured against a benchmark.

Modules:
  db         SQLite storage (posts, mentions)
  ingest     X API v2 fetch, CSV/JSON import, demo data
  classify   Claude stance classification, with a rule-based fallback
  prices     Price history via yfinance (with exchange suffix mapping)
  analytics  Day / week / month / quarter windows and call performance
  qa         Per-ticker thesis narrative via Claude

Research tool only. Not investment advice.
"""
