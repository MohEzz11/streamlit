# streamlit
Trading agents GitHub repository

## Apps

| App | Run | What it does |
|---|---|---|
| M.E. Portfolio Ai Agent | `streamlit run app.py` | Multi-agent AI research on single stocks and saved portfolios (TradingAgents) |
| M.E. Opinion Tracker | `streamlit run tracker_app.py` | Turns an analyst's public X posts into a stance dashboard with a track record |

## M.E. Opinion Tracker

Reads an analyst's public posts (for example `@aleabitoreddit`), tags every
stock mention bullish, bearish, neutral or background, and builds:

- **Dashboard** with Daily, Weekly (7d), Monthly (28d) and Quarterly (90d) views:
  most discussed names with stance mix, price change since first mention,
  bearish names and stance shifts, new names, and a sortable table.
- **Stock detail**: price chart with bullish and bearish posts marked, risks
  raised, and every post with its stance, confidence and source link.
- **Ask about a stock**: Claude summarises the latest opinion, how the thesis
  evolved, the 3 key posts, risks raised, and what the posts leave out.
- **Track record**: each ticker's first call priced at the next close and
  compared with a benchmark (SMH by default), with hit rate and excess return.

### Setup

1. Add keys in Streamlit Secrets (or paste them in the sidebar):
   ```toml
   ANTHROPIC_API_KEY = "sk-ant-..."   # stance classification and Q&A
   X_BEARER_TOKEN    = "..."          # paid X API access to read timelines
   ```
2. Open **Data & refresh**, then fetch from the X API, upload a CSV/JSON of
   posts, or load the synthetic demo dataset.
3. Click **Classify new posts**.

Without an Anthropic key, stances fall back to keyword rules (cashtags only,
much less accurate). Without an X token, use file upload.

### Hourly refresh

Hosted Streamlit apps do not run background jobs. Schedule this instead:

```bash
SUPABASE_DB_URL=... X_BEARER_TOKEN=... ANTHROPIC_API_KEY=... python -m opinion_tracker.refresh aleabitoreddit
```

### Persistent storage (Supabase)

Without a database URL the app uses a local SQLite file, which Streamlit
Community Cloud wipes on every reboot or redeploy. To keep data:

1. Create a free project at [supabase.com](https://supabase.com) and save the
   database password.
2. Click **Connect** at the top of the project, choose **Session pooler**, and
   copy the URI. Streamlit Cloud cannot reach the direct
   `db.<ref>.supabase.co` host because it is IPv6 only.
3. Add it to Streamlit Secrets with your password filled in:
   ```toml
   SUPABASE_DB_URL = "postgresql://postgres.<ref>:<password>@aws-0-<region>.pooler.supabase.com:5432/postgres"
   ```
   If the password contains `@`, `:`, `/` or `#`, URL-encode it (for example `@` becomes `%40`).
4. Reboot the app. Tables are created automatically, and the Data & refresh
   tab shows "Storage: Supabase Postgres".

To move an existing local history into Supabase:

```bash
SUPABASE_DB_URL="postgresql://..." python -m opinion_tracker.migrate opinion_tracker.db
```

### Notes

- Non-US tickers need a Yahoo symbol in the sidebar map (`SIVE=SIVE.ST`).
- The app turns on row level security for its tables, with no policies, so
  Supabase's public REST API key cannot read or change them. Only the
  connection string (which holds your database password) can. Keep it in
  Secrets, never in the repo.
- Research tool only. Not investment advice. Not affiliated with any account
  it tracks. Check X's developer terms before publishing or selling data
  derived from someone's posts.
