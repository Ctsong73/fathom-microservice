# fathom — Mining Stocks Microservice

A small Flask microservice that tracks US & Canadian mining stocks and provides a
"snapshot analysis" for each one: momentum indicators, valuation ratios (P/E, P/B,
P/S), a price-history chart, and key company snapshot fields (market cap, 52-week
range, volume).

Live instance: <https://fathom-microservice.onrender.com>

## Features

- **Universe** — 122 validated mining stocks (US & Canada) in `data/mining_stocks.csv`,
  grouped by sector (Precious Metals, Base Metals, Lithium, Coal, Iron Ore, ...).
- **Directory** — searchable, sortable home page (by Sector, Market Cap, Gainers,
  Losers, Country) with a per-stock 6-month momentum badge.
- **Stock page** — for each symbol:
  - Momentum panel: 6M / 3M / 1M change, trend strength
  - Price levels: current price, price ~6 months ago, SMA 20/50
  - Valuation panel: P/E, P/B, P/S
  - Snapshot panel: market cap, 52-week range, volume, average volume
  - SVG price chart rendered server-side (no charting library)
- **No caching** — data is fetched on demand from Yahoo Finance and stored in a
  local SQLite database; stale stocks are refreshed in the background.

## Stack

- Flask 2.3 + Jinja templates
- SQLite (`sqlite3` stdlib, WAL mode)
- `yfinance` (chart fallback, market caps, valuation/snapshot data)
- `yahooquery` (primary price-history source)
- Deploys as a single Web Service on Render (or any Docker host)

## Project layout

```
├── Dockerfile              # python:3.9-slim, copies src/ + universe CSV
├── requirements.txt
├── docker-compose.yml
├── .env.example            # documented environment variables
├── data/
│   └── mining_stocks.csv   # the tracked universe (symbol,name,exchange,country,sector)
├── scripts/
│   └── build_universe.py   # (re)generate + validate mining_stocks.csv
└── src/
    ├── app.py              # Flask routes, background boot sync, chart builder
    ├── database.py         # SQLite schema, migrations, access helpers
    ├── fetcher.py          # Yahoo fetch, momentum/market-cap persistence, snapshot
    ├── models.py           # MomentumCalculator (indicators from stored prices)
    ├── static/
    │   ├── favicon.svg
    │   └── style.css
    └── templates/
        ├── base.html       # nav/footer shell
        ├── index.html      # directory (search + sort + country filter)
        └── stock.html      # per-stock snapshot analysis page
```

## Local development

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# run from the repo root so data/mining_stocks.csv resolves
python src/app.py
# -> http://localhost:5000
```

Environment variables (all optional — see `.env.example`):

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_PATH` | `data/stocks.db` | SQLite file location |
| `UNIVERSE_CSV` | `data/mining_stocks.csv` | Universe file |
| `FRESH_HOURS` | `6` | Age after which a stock is stale and refreshed |
| `PORT` | `5000` | Web server port |
| `FLASK_ENV` | `production` | `development` enables the Flask debug server |

On startup the app syncs the universe and kicks off a background fetch of every
stock so the first page loads are fast.

## Docker

```bash
docker compose up --build     # docker-compose.yml
# or
docker build -t fathom .
docker run -p 5000:5000 fathom
```

## Deploying on Render (Web Service)

1. Push this repo to GitHub.
2. In Render, **New → Web Service → Connect** the repo.
3. Use the **Docker** runtime (a `Dockerfile` is included) — Render builds it.
4. Optionally set env vars (`FRESH_HOURS`, etc.); Render injects `PORT` for you.
5. Deploy. The build installs dependencies and copies `data/mining_stocks.csv`
   into the image; SQLite lives in `/app/data/stocks.db`.

Notes:

- Render cold-starts cost ~1–2 minutes for the initial background sync of the full
  universe; the `/health` endpoint is available immediately.
- Data is stored on the service's local disk — it resets on a fresh deploy.
  Persistent storage requires a Render Disk mounted at `/app/data` (map
  `DATABASE_PATH` there).
- Free-tier instances sleep; **a free MySQL/other DB plan is not required** —
  SQLite works for single-instance reads.

## API

| Endpoint | Description |
| --- | --- |
| `/` | Home directory (HTML) |
| `/stock/<symbol>` | Stock snapshot page (HTML) |
| `/api/stocks/<symbol>/momentum` | Momentums, valuation & snapshot JSON |
| `/api/fetch/<symbol>` | Force-refresh one symbol's price data |
| `/api/fetch/all` | Force-refresh the whole universe (slow) |
| `/health` | Status + universe/storage counts |
| `/debug/db/<symbol>` | Raw stored prices (debug) |
| `/debug/valuation/<symbol>` | Raw Yahoo valuation payload (debug) |
| `/debug/universe` | Universe grouped by sector (debug) |

## Troubleshooting

- **Valuation/snapshot returns nulls right after a deploy** — Yahoo throttles the
  quote endpoints for the service IP during the boot sync. The fetcher retries with
  backoff; wait ~2 minutes and refresh.
- **`YFDataException` about curl_cffi** — yfinance ≥ 1.2 requires `curl_cffi`; it is
  installed via `requirements.txt`. Make sure requirements resolve (Redis, caching
  endpoints are intentionally absent).
- **A symbol has no data** — it was likely delisted/rename; `scripts/build_universe.py`
  validates the universe against Yahoo before regenerating the CSV.
- **Rate limiting** — the sync uses a per-symbol delay and a throttled market-cap
  sweep; avoid hammering `/api/fetch/all` repeatedly.