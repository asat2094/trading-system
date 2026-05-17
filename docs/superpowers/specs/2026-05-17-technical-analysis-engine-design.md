# Technical Analysis Engine — Design Spec
**Date:** 2026-05-17  
**Scope:** Sub-project 1 of 3 (Technical Analysis Engine). Fundamental Analysis Engine and Backtesting System are separate specs to follow.  
**Use:** Personal, non-enterprise. Designed for pilot-to-production portability.

---

## 1. Goals

Build a technical analysis engine for Indian equity markets (NSE/BSE) that:
- Ingests and stores multi-resolution OHLCV data (1-min to daily, up to 10 years)
- Computes indicators, detects chart patterns, scores trend direction + accuracy
- Scans the NSE universe against configurable signal conditions
- Surfaces signals via a Chartink-style visual screener, a live signal feed, and an LLM natural language interface
- Supports agent-generated analysis activities sideloaded from config without workflow code changes

---

## 2. Architecture

### 2.1 Approach

Modular monolith — single FastAPI process with clean module boundaries. Each module owns its router, service layer, and DB models. No cross-module direct imports; modules communicate only through `core/` interfaces. Any module can be extracted to a separate service by changing transport, not logic.

### 2.2 System Structure

```
trading-system/
├── backend/
│   ├── core/              # Shared: DB sessions, cache client, config, base models, auth providers
│   ├── data/              # Data ingestion module
│   ├── technical/         # Indicators + chart patterns + trend analysis
│   ├── scanner/           # Universe scanner + query engine + signal registry
│   ├── llm/               # LLM interface — NL → scanner DSL
│   ├── api/               # FastAPI routers (one per module)
│   └── workers/           # Temporal workflows + activities
│       ├── workflows/      # Static orchestration logic
│       ├── activities/     # Sideloadable activity plugins
│       ├── registry.py    # Auto-discovers + registers activity files
│       └── config/        # YAML workflow + signal configs
├── frontend/              # React + Vite
├── data/
│   └── raw/               # Parquet files (base resolution storage)
├── infra/                 # Docker Compose, DB migrations (Alembic)
└── docs/
```

### 2.3 Runtime Components

```
Browser
  └─▶ Nginx (prod only)
        └─▶ Gunicorn + Uvicorn workers → FastAPI
                ├─▶ PostgreSQL (metadata, scan results, stock universe)
                ├─▶ QuestDB (OHLCV time-series — all resolutions)
                └─▶ Redis (hot cache — indicators, scan results)

Temporal Workers (background)
  ├─▶ QuestDB (write OHLCV)
  ├─▶ PostgreSQL (write scan results, market events)
  ├─▶ Parquet files (write raw base data)
  └─▶ Redis (invalidate cache after runs)
```

---

## 3. Data Layer

### 3.1 Storage Tiers

| Tier | Store | Content | Retention |
|------|-------|---------|-----------|
| Base | Parquet files | 1-min OHLCV, all symbols | Permanent |
| Hot time-series | QuestDB | 1-min (60d), hourly (2yr), daily (10yr) | Per retention |
| Operational | PostgreSQL | Stocks universe, scan results, pre-market, signal configs | Permanent |
| Cache | Redis | Computed indicators, scan output, market event snapshots | TTL-based |

**Write path: Parquet first, then QuestDB.**
1. Ingest activity writes to Parquet (durable, permanent)
2. On Parquet write success → write to QuestDB (hot layer)
3. If QuestDB write fails → data is safe in Parquet; QuestDB backfill activity re-runs on next cycle
4. If Parquet write fails → abort; no QuestDB write; Temporal retries the activity

**Read path:** SDK queries QuestDB for data within retention window. For data older than QuestDB retention (or any date range not found in QuestDB), SDK transparently falls back to DuckDB+Parquet — caller sees one unified `ohlcv()` API regardless of underlying store.

**Rule:** Parquet = source of truth. QuestDB = operational hot queries. DuckDB = transparent fallback for historical ranges.

**Agent-generated activities (commercial boundary):** For commercial product, agent-generated Temporal activities are **admin/owner tier only** — not exposed to regular users. Regular users get pre-built signal library + LLM NL→DSL only. Prevents cross-user data leakage from buggy agent code in shared worker process.

### 3.2 QuestDB Schema (OHLCV)

Full DDL with deduplication and partitioning:

```sql
CREATE TABLE ohlcv_1min (
  ts      TIMESTAMP,
  symbol  SYMBOL CAPACITY 4096 CACHE,
  open    DOUBLE,
  high    DOUBLE,
  low     DOUBLE,
  close   DOUBLE,
  volume  LONG
) TIMESTAMP(ts)
  PARTITION BY DAY
  WAL
  DEDUP UPSERT KEYS(ts, symbol);  -- idempotent re-ingestion

CREATE TABLE ohlcv_hourly (
  ts      TIMESTAMP,
  symbol  SYMBOL CAPACITY 4096 CACHE,
  open    DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume LONG
) TIMESTAMP(ts) PARTITION BY MONTH WAL DEDUP UPSERT KEYS(ts, symbol);

CREATE TABLE ohlcv_daily (
  ts      TIMESTAMP,
  symbol  SYMBOL CAPACITY 4096 CACHE,
  open    DOUBLE, high DOUBLE, low DOUBLE, close DOUBLE, volume LONG,
  adjusted_close DOUBLE  -- corporate-action adjusted close
) TIMESTAMP(ts) PARTITION BY YEAR WAL DEDUP UPSERT KEYS(ts, symbol);
```

QuestDB DDL migrations managed by versioned `.sql` files in `infra/questdb/migrations/` executed on startup via a one-shot Temporal activity.

Derive 5-min/15-min/30-min on the fly — do NOT materialise separately:
```sql
SELECT ts, symbol, first(open), max(high), min(low), last(close), sum(volume)
FROM ohlcv_1min WHERE symbol = 'RELIANCE.NS'
SAMPLE BY 15m ALIGN TO CALENDAR TIME ZONE 'Asia/Kolkata';
```

`ohlcv_hourly` IS materialized (not derived) because 2-year hourly lookbacks on 1-min data would be too slow. Written by a dedicated aggregation activity, not independently ingested.

### 3.3 PostgreSQL Schema

```sql
CREATE TABLE stocks (
  symbol       TEXT PRIMARY KEY,
  name         TEXT NOT NULL,
  exchange     TEXT NOT NULL CHECK (exchange IN ('NSE','BSE')),
  sector       TEXT,
  industry     TEXT,
  market_cap   BIGINT,         -- INR (BIGINT fits up to ~9.2e18, safe for all Indian caps)
  updated_at   TIMESTAMPTZ DEFAULT now()
  -- NOTE: no classification columns (is_penny, cap_category etc.) — all in stock_attributes table
);

CREATE TABLE scan_results (
  id         UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  scan_name  TEXT        NOT NULL,
  run_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  symbol     TEXT        NOT NULL,
  signals    JSONB       NOT NULL,  -- {rsi: 32, pattern: "double_bottom", trend: "up", strength: 4}
  score      NUMERIC
);
CREATE INDEX idx_scan_results_name_run  ON scan_results (scan_name, run_at DESC);
CREATE INDEX idx_scan_results_symbol    ON scan_results (symbol, run_at DESC);
-- monthly partitioning for retention (add via pg_partman or manual partition DDL)

CREATE TABLE trading_calendar (
  date         DATE PRIMARY KEY,
  exchange     TEXT NOT NULL,   -- NSE | BSE
  is_trading   BOOLEAN NOT NULL,
  session_type TEXT,            -- full | half | muhurat
  open_time    TIME,
  close_time   TIME,
  minutes      INT              -- actual trading minutes (not hardcoded 375)
);

CREATE TABLE agent_activities (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name         TEXT NOT NULL UNIQUE,
  file_path    TEXT NOT NULL,
  status       TEXT NOT NULL CHECK (status IN ('proposed','approved','promoted','disabled')),
  generator    TEXT,            -- 'claude-sonnet-4-6' | 'human'
  prompt       TEXT,
  created_at   TIMESTAMPTZ DEFAULT now(),
  approved_by  TEXT,
  approved_at  TIMESTAMPTZ,
  disabled_at  TIMESTAMPTZ,
  git_sha      TEXT
);

-- Extensible stock attribute dimensions (replaces any hardcoded classification columns)
CREATE TABLE stock_attributes (
  symbol      TEXT NOT NULL REFERENCES stocks(symbol),
  group_name  TEXT NOT NULL,   -- "classification" | "index_membership" | "fundamentals" | "ownership"
  attributes  JSONB NOT NULL,
  updated_at  TIMESTAMPTZ DEFAULT now(),
  PRIMARY KEY (symbol, group_name)
);
CREATE INDEX idx_stock_attributes_gin ON stock_attributes USING GIN (attributes);
-- Examples:
-- ("RELIANCE","classification", {"cap_category":"mega","market_cap":1800000000000})
-- ("RELIANCE","index_membership",{"nifty50":true,"sensex":true,"nifty500":true})
-- ("RELIANCE","ownership",{"promoter_pct":50.3,"fii_pct":24.1,"dii_pct":13.2})
-- New dimension = new key in JSONB. Zero schema migration.

-- Generic market events (replaces hardcoded premarket_snapshot table)
CREATE TABLE market_event_types (
  name             TEXT PRIMARY KEY,
  description      TEXT,
  source           TEXT,
  collection_windows JSONB NOT NULL,
  -- array of {cron, label, delay_s} — multiple collection points per event type
  -- e.g. premarket_gainers:
  --   [{"cron":"9 9 * * 1-5","label":"order_open","delay_s":0},
  --    {"cron":"11 9 * * 1-5","label":"iep_final","delay_s":60}]
  -- delay_s: wait after cron fire before fetching (data may lag source)
  -- label: stored on each market_events row so queries can filter by collection point
  schema_hint      JSONB   -- documents expected keys in data{}
);
CREATE TABLE market_events (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  event_type       TEXT NOT NULL REFERENCES market_event_types(name),
  collection_label TEXT NOT NULL DEFAULT 'default',
  -- matches label in market_event_types.collection_windows
  -- e.g. "order_open" (9:00 AM) vs "iep_final" (9:11 AM)
  date             DATE NOT NULL,
  symbol           TEXT REFERENCES stocks(symbol),   -- nullable for market-wide events
  rank             INT,
  data             JSONB NOT NULL,
  captured_at      TIMESTAMPTZ DEFAULT now()
);
CREATE UNIQUE INDEX idx_market_events_dedup   ON market_events (event_type, collection_label, date, symbol);
CREATE INDEX        idx_market_events_type    ON market_events (event_type, date DESC);
CREATE INDEX        idx_market_events_symbol  ON market_events (symbol, event_type, date DESC);
CREATE INDEX        idx_market_events_gin     ON market_events USING GIN (data);
-- Examples:
-- event_type="premarket_gainers": data={"pre_price":2840,"pre_change_pct":2.3,"pre_volume":120000}
-- event_type="block_deals":       data={"quantity":500000,"price":1820,"buyer":"Morgan Stanley"}
-- event_type="fii_dii_daily":     symbol=NULL, data={"fii_buy":4200000000,"dii_buy":2100000000}
-- New event type = insert into market_event_types + write activity. Zero schema migration.

CREATE TABLE data_quality_alerts (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  check_name TEXT NOT NULL,
  symbol     TEXT,
  timeframe  TEXT,
  detail     JSONB,
  fired_at   TIMESTAMPTZ DEFAULT now(),
  resolved_at TIMESTAMPTZ
);
```

**`indicator_cache` removed** — Redis is the sole indicator cache. Postgres would duplicate it with no eviction mechanism.

### 3.4 Redis Cache Keys

Namespaced with schema version to prevent stale reads after deploys:

```
ta:v1:indicators:{symbol}:{timeframe}   TTL 1h
ta:v1:scan:{scan_name}:latest           TTL 6h
ta:v1:market_events:{event_type}:{date} TTL 24h   -- any event type, not just pre-market
ta:v1:universe:list                     TTL 7d
ta:v1:nlq:{hash(nl_query)}              TTL 24h   -- cached NL→DSL translations
```

`SCHEMA_VERSION=v1` env var controls prefix. Bump on breaking schema change to auto-invalidate.

### 3.5 Parquet Layout

Hive-partitioned for DuckDB partition pruning on cross-symbol scans:

```
data/raw/
  timeframe=1min/
    year=2024/
      month=01/
        data.parquet      -- all symbols, that month, columnar
```

DuckDB cross-symbol scan (partition pruning applies):
```sql
SELECT * FROM read_parquet('data/raw/timeframe=1min/year=2024/**/*.parquet', hive_partitioning=true)
WHERE year=2024 AND month BETWEEN 1 AND 3;
```

### 3.6 Storage Abstraction

Parquet access goes through a `Storage` interface so local → S3 is a config swap, not a code change:

```python
class Storage(Protocol):
    def read_parquet(self, path_pattern: str) -> DataFrame: ...
    def write_parquet(self, df: DataFrame, path: str) -> None: ...

# Implementations:
class LocalStorage(Storage): ...        # PARQUET_BASE_PATH=/data/raw
class S3Storage(Storage): ...           # PARQUET_BASE_PATH=s3://bucket/raw + httpfs
```

### 3.7 Retention + Rehydration

```
QuestDB 1-min retention: 60 days rolling
Temporal workflow: questdb_retention_sweep (runs nightly)
  1. Verify Parquet has all data for partitions being dropped
  2. DROP PARTITION from QuestDB
  3. Log partition confirmed in Parquet

On-demand rehydration (for queries needing >60d 1-min):
  API request → detect data not in QuestDB → read from Parquet via DuckDB
  → return result (does NOT write back to QuestDB — keeps hot layer clean)
```

### 3.8 Corporate Actions

**Convention: store both raw and adjusted.**

```sql
-- ohlcv_daily has adjusted_close column (corporate-action adjusted via yfinance)
-- ohlcv_1min and ohlcv_hourly store RAW prices only

-- Adjustment factors table
CREATE TABLE adjustment_factors (
  symbol      TEXT NOT NULL,
  effective_date DATE NOT NULL,
  factor      NUMERIC NOT NULL,  -- multiply historical raw prices by this
  action_type TEXT,              -- split | bonus | dividend
  PRIMARY KEY (symbol, effective_date)
);
```

yfinance returns adjusted prices for daily; raw for intraday. Convention enforced at ingestion. Signals computed on adjusted daily, raw intraday — documented per-indicator.

---

## 4. Data Sources

| Data | Primary Source | Fallback | Frequency |
|------|---------------|---------|-----------|
| 10yr daily backfill | Kaggle NSE datasets | NSE/BSE CSV downloads | One-time |
| 2yr hourly backfill | yfinance | Shoonya historical | One-time |
| 30d 1-min backfill | Shoonya API | Upstox API | One-time |
| Auto-updated daily EOD | GitHub auto-updated repos | yfinance | Daily 4 PM |
| 1-min rolling collect | Shoonya API | Upstox API | Market hours |
| Pre-market gainers/losers | NSE public pre-open API endpoint | NSE website scrape | 9:00–9:15 AM |
| Market cap + stock universe | yfinance `ticker.info` | NSE stock list CSV | Weekly |
| Live chart data | TradingView MCP | — | On demand |
| Trading calendar | NSE official calendar API | Hardcoded known holidays | Annual |

**yfinance resilience:** rate-limit aware retry with exponential backoff (max 3 attempts, 30s cap). On persistent failure, fall to GitHub repo for daily data, Shoonya for intraday.

**NSE pre-open:** use `https://www.nseindia.com/api/market-status` + pre-open endpoint (JSON API, more stable than scraping). Bootstrap with session cookie + headers (NSE requires browser-like UA). If blocked, fallback to Moneycontrol pre-open scrape.

---

## 5. Technical Analysis Module

### 5.1 Indicators

Library: `pandas-ta` (pure Python, 130+ indicators, no C compilation). **Note:** pandas-ta is largely unmaintained since 2021 — pin to `0.3.14b`, monitor for pandas compatibility breaks. Evaluate migration to `ta` (talipp) or `finta` if issues arise.

```
technical/indicators/
  trend.py       # EMA, SMA, WMA, Supertrend, Ichimoku
  momentum.py    # RSI, MACD, Stochastic, CCI, MFI, Williams %R
  volatility.py  # Bollinger Bands, ATR, Keltner Channel, Donchian
  volume.py      # OBV, VWAP, Volume Profile, Chaikin
  registry.py    # Add new indicators without touching core
```

### 5.2 Chart Pattern Detection

Peak/trough analysis via `scipy.signal.find_peaks`.

**Phase 1 patterns:**

| Category | Patterns |
|----------|---------|
| Reversal | Head & Shoulders, Inverse H&S, Double Top/Bottom, Triple Top/Bottom |
| Continuation | Ascending/Descending/Symmetric Triangle, Bull/Bear Flag, Pennant, Wedge |
| Levels | Support/Resistance (pivot + volume-weighted), Breakout detection |

Each pattern returns:
```python
{
  "pattern": "double_bottom",
  "confidence": 0.82,       # 0–1
  "direction": "bullish",
  "key_levels": [2800, 2820],
  "formed_at": "2026-05-15T14:30:00",
  "target": 2950            # projected move
}
```

### 5.3 Trend Analysis

```python
TrendResult:
  direction:  "up" | "down" | "sideways"
  strength:   "strong" | "moderate" | "weak"
  accuracy:   float       # 0–1, % candles confirming direction
  slope:      float       # linear regression slope
  r_squared:  float       # trend fit quality
  window:     str         # "14:00–15:30"
  timeframe:  str         # "1min"
```

### 5.4 Data Access SDK

All modules — including LLM-generated activities — access data only through this SDK. No raw DB or QuestDB access outside `core/`. Version is `SCANNER_DSL_VERSION=1` — bump on breaking changes; LLM tool schemas include this version.

**Async boundary:** `MarketData` is fully async (I/O bound). `Indicators` and `Patterns` are sync (CPU bound, operate on in-memory DataFrames). Temporal activities call `MarketData` with `await`, then pass result to sync compute functions. Never call sync compute inside `asyncio.get_event_loop().run_in_executor` — Temporal handles thread isolation.

```python
# core/sdk.py  (SCANNER_DSL_VERSION = 1)

class MarketData:
    async def ohlcv(symbol: str, tf: str, from_dt: datetime, to_dt: datetime,
                    adjusted: bool = True) -> DataFrame: ...
    async def market_events(event_type: str, date: date, symbol: str | None = None,
                            **filters) -> DataFrame: ...
    # event_type: any value registered in market_event_types table
    # e.g. "premarket_gainers", "block_deals", "circuit_breakers", "fii_dii_daily"
    # filters: any key present in the event's data{} JSONB, e.g. rank__lte=20
    async def universe(filters: dict) -> list[str]: ...
    # tf: "1min" | "1h" | "1d" — returns from QuestDB hot layer;
    # falls back to DuckDB+Parquet for data older than QuestDB retention

class Indicators:  # all sync, pure functions on DataFrame
    @staticmethod def rsi(data: DataFrame, period: int = 14) -> Series: ...
    @staticmethod def macd(data: DataFrame) -> DataFrame: ...
    @staticmethod def ema(data: DataFrame, period: int) -> Series: ...
    @staticmethod def vwap(data: DataFrame) -> Series: ...

class Patterns:    # all sync
    @staticmethod def detect(data: DataFrame, patterns: list[str]) -> list[PatternResult]: ...
    @staticmethod def support_resistance(data: DataFrame) -> list[Level]: ...
    @staticmethod def trend(data: DataFrame, from_time: str, to_time: str) -> TrendResult: ...

class Scanner:
    def from_source(self, source: str, **params) -> Scanner: ...  # aligned with §6.1
    def filter(self, **conditions) -> Scanner: ...
    def add_analysis(self, **params) -> Scanner: ...
    def add_indicators(self, indicators: list[str]) -> Scanner: ...
    def sort_by(self, field: str, descending: bool = True) -> Scanner: ...
    def run(self, max_symbols: int = 500, timeout_s: int = 120) -> DataFrame: ...
    # max_symbols + timeout_s enforce resource caps on every scan
```

Cross-module interface: `scanner/` calls `technical/` via the SDK `Indicators`/`Patterns` classes — never direct module imports. `core/contracts/` contains Protocol definitions enforced at startup via `isinstance` checks.

---

## 6. Scanner Engine

### 6.1 Composable Conditions

All parameters are configurable — the scanner is not tied to any specific use case.

```python
# Example: pre-market event + prior-day time-window trend analysis
# Any source, any filters, any time window, any indicators, any sort field
scan = Scanner()
  .from_source("premarket_gainers", date=today, top_n=20)
  # source: any value in market_event_types, or "nse_universe", "custom_list", "watchlist:{id}"

  .filter(attribute_group="classification", cap_category__in=["large","mega"])
  # filter: any stock_attributes group + any JSONB key, any operator

  .filter(exchange="NSE")

  .add_analysis(
      trend_window=("14:00", "15:30"),   # any time window, any date
      date="yesterday",                  # "today" | "yesterday" | "YYYY-MM-DD"
      timeframe="1min",                  # any resolution
      metrics=["direction","accuracy","volume_pattern"]  # configurable metric set
  )

  .add_indicators(["rsi_14","macd","vwap"])
  # any indicator from indicators registry

  .sort_by("trend_accuracy", descending=True)
  # any metric or indicator value as sort key
```

### 6.2 Signal Configuration

Signals defined in YAML — not hardcoded. Add new signals without code changes. Schema validated by Pydantic at app startup — invalid YAML fails fast with a clear error, not at scan time.

```yaml
# workers/config/signals.yaml
signals:
  - name: bearish_engulfing_strong
    category: entry           # entry | exit | alert | custom
    direction: bearish
    timeframes: [15min, 1h, 1d]
    conditions:
      - type: candlestick_pattern
        pattern: bearish_engulfing
      - type: volume_confirmation
        min_volume_ratio: 1.5
      - type: trend_context
        trend: up
    severity: high
    display:
      color: "#f23645"
      icon: "▼"
      strength_score: 4       # 1–5, shown as dots in screener results table
```

`strength_score` (1–5) is defined per signal in YAML. Scanner output includes it in `signals` JSONB. Frontend maps 1–5 → dot display.

Signal YAML Pydantic model validated at startup:
```python
class SignalCondition(BaseModel):
    type: Literal["candlestick_pattern","volume_confirmation","trend_context","indicator","custom_activity"]
    ...

class SignalConfig(BaseModel):
    name: str
    category: Literal["entry","exit","alert","custom"]
    direction: Literal["bullish","bearish","any"]
    timeframes: list[str]
    conditions: list[SignalCondition]
    severity: Literal["low","medium","high"]
    display: dict
```

---

## 7. Temporal Workflows (Job System)

### 7.1 Design Principle

**Workflows are static** — orchestration logic only, never changes.  
**Activities are dynamic** — sideloaded from `workers/activities/`, auto-registered, config-driven.

### 7.2 Auto-Registration

```python
# workers/registry.py
import importlib, pathlib, logging
from temporalio.worker import Worker

ACTIVITIES_DIR = pathlib.Path(__file__).parent / "activities"  # absolute, not relative

def register_all(worker: Worker) -> list[str]:
    registered, skipped = [], []
    seen_names: set[str] = set()

    for path in sorted(ACTIVITIES_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            module = importlib.import_module(f"workers.activities.{path.stem}")
            fn = getattr(module, "activity_fn", None)
            if fn is None:
                skipped.append(f"{path.stem}: no activity_fn exported")
                continue
            activity_name = getattr(fn, "__temporal_activity_definition", {}).get("name", path.stem)
            if activity_name in seen_names:
                raise ValueError(f"Duplicate activity name '{activity_name}' in {path.stem}")
            seen_names.add(activity_name)
            worker.register_activity(fn)
            registered.append(activity_name)
        except Exception as e:
            logging.error("activity_registration_failed", extra={"file": path.stem, "error": str(e)})
            skipped.append(f"{path.stem}: {e}")

    # expose via /healthz — skipped activities visible without digging logs
    return registered, skipped
```

Each activity MUST use `@activity.defn(name="unique_name")` — registry asserts uniqueness and rejects collisions.

### 7.3 Workflow Config (YAML)

```yaml
# workers/config/daily_eod.yaml
workflow: daily_eod
schedule: "0 16 * * 1-5"
activities:
  - activity: fetch_github_eod_data
    timeout_minutes: 10
    retry:
      max_attempts: 3
      initial_interval_s: 10
      backoff_coefficient: 2.0
    params:
      repo: "jugaad-trader/nse-data"
  - activity: compute_indicators
    timeout_minutes: 30
    retry:
      max_attempts: 2
    params:
      indicators: [rsi_14, macd, ema_20, bb_20, atr_14]
      timeframes: [1d, 1h]
  - activity: run_scanner_presets
    timeout_minutes: 20
    retry:
      max_attempts: 2
    params:
      presets: [ema_crossover, rsi_oversold_uptrend, breakout_candidates]
  - activity: invalidate_cache
    timeout_minutes: 2
    params:
      patterns: ["ta:v1:indicators:*", "ta:v1:scan:*"]
```

Add new activity: create `workers/activities/my_activity.py` + add to YAML. Zero workflow code change.

### 7.4 Scheduled Workflows

| Workflow | Schedule (IST) | Purpose |
|----------|---------------|---------|
| `backfill_historical` | One-time | Kaggle + yfinance + Shoonya historical load |
| `market_event_collector` | Driven by `market_event_types.collection_windows` | One workflow per event_type + collection_label. Reads cron + delay_s from DB config. `premarket_gainers` fires twice: `order_open` at 9:00 AM and `iep_final` at 9:11 AM (after 60s delay for data propagation). New collection windows = update DB row only. |
| `intraday_1min_collector` | Starts 9:15 AM, runs until 3:30 PM | Single long-running workflow, internal loop with `asyncio.sleep(60)`, parallel fan-out across all symbols per tick. NOT re-triggered every minute — that would create 750k workflow starts/day. |
| `hourly_aggregator` | Every hour, 9:15 AM–4 PM weekdays | Aggregate 1-min → ohlcv_hourly |
| `questdb_retention_sweep` | 11:00 PM daily | Drop QuestDB 1-min partitions >60d after Parquet verify |
| `daily_eod_ingestion` | 4:00 PM weekdays | EOD data + indicator compute |
| `universe_scanner` | 4:30 PM weekdays | Full universe signal scan |
| `market_cap_refresh` | Monday 8:00 AM | Update stocks table |
| `trading_calendar_sync` | Jan 1 annually | Sync NSE trading calendar for the year |

---

## 8. LLM Integration

### 8.1 Pattern

```
User natural language query
  → hash(query) → Redis cache hit? → return cached DSL + results
  → Claude API (tool use, SCANNER_DSL_VERSION=1)
  → Structured scanner condition JSON (canonical DSL form)
  → Scanner engine executes
  → Results + plain-English explanation
  → Cache NL→DSL mapping in Redis (TTL 24h)
```

**Cost controls:** `LLM_DAILY_TOKEN_BUDGET=100000` env var. Counter in Redis incremented per request. Requests exceeding budget return HTTP 429 with "daily LLM budget reached" — scanner still available without LLM.

**DSL canonical form:** the JSON produced by LLM tool calls is the canonical representation persisted in `scan_results.signals`. The fluent Python API (§6.1) and YAML presets (§7.3) are alternative representations that serialize to the same JSON. `SCANNER_DSL_VERSION` is included in every persisted JSON for forward compatibility.

**LLM prompt management:** system prompts and tool schemas stored as versioned files in `backend/llm/prompts/v{N}/`. Version controlled in git. Active version set via `LLM_PROMPT_VERSION` env var — no code deploy needed to update prompts.

### 8.2 LLM Tools (scanner primitives exposed as tools)

- `set_source` — universe source (premarket_gainers, nse_universe, custom_list)
- `add_filter` — market cap, exchange, sector, volume thresholds
- `add_trend_analysis` — time window, date, timeframe
- `add_indicator` — indicator + condition + value
- `set_sort` — field + order

### 8.3 Agent-Generated Activities

LLMs and coding agents can write new Temporal activities against the Data Access SDK:

1. Agent writes activity Python file (uses `MarketData`, `Indicators`, `Patterns`, `Scanner` only)
2. **Security gate — multi-layer (AST alone is insufficient):**
   - AST scan: ban `Import`/`ImportFrom` nodes except SDK allowlist, ban `Exec`, `Eval`, `Call` to `__import__`/`getattr`/`globals`/`compile`
   - `RestrictedPython` compile: restricts builtins, prevents dunder access
   - Bytecode scan: reject `IMPORT_NAME`, `LOAD_BUILD_CLASS` opcodes
   - Run in **isolated subprocess** (`python -S -I`) with:
     - Network egress blocked (no outbound connections)
     - Read-only filesystem except a temp output dir
     - CPU time limit: 60s wall-clock
     - Memory cap: 512MB
     - No access to prod DBs — separate read-only Postgres schema + read-only Parquet mount
3. Sandboxed test run on last 2 days of data (isolated subprocess, see above)
4. Human approval gate when `SAFETY_GATE_AGENT_CODE=true` — approval recorded in `agent_activities` table with approver + timestamp
5. Promoted to `workers/activities/` + config updated
6. Git commit with metadata: generator model, prompt hash, approver, timestamp, git SHA stored in `agent_activities`
7. Auto-registered on next worker restart

**Revocation:** set `agent_activities.status = 'disabled'` → registry skips the file → takes effect on next worker restart. No file deletion needed. Kill-switch env var `DISABLE_ACTIVITY=name1,name2` for emergency bypass without restart.

---

## 9. Frontend

### 9.1 Stack

| Library | Purpose |
|---------|---------|
| React + Vite | Framework + dev server |
| TradingView Lightweight Charts | Candlestick charts |
| TanStack Table | Screener results, sortable/filterable |
| TanStack Query | API data fetching + caching |
| Zustand | Global state (signal feed, active filters) |
| React Hook Form | Screener condition builder |
| WebSocket (native) | Live signal feed |

### 9.2 Routes

| Route | Page |
|-------|------|
| `/screener` | Visual condition builder (Chartink-style) + results table |
| `/signals` | Live signal feed dashboard |
| `/chart/:symbol` | Chart + overlaid signals + indicator panel |
| `/scanner/:id` | Saved scanner run results |
| `/chat` | LLM natural language interface |
| `/watchlist` | Saved watchlists |

### 9.3 Layout

Persistent sidebar: live signal feed (WebSocket), always visible.  
Topbar: stock search, date/timeframe picker, market status indicator.  
Main area: route-based content.

**WebSocket event source:** signals pushed via **Redis Streams** (`XADD signals:live`). FastAPI maintains one Redis Streams consumer group. Each connected browser WebSocket client receives events via a per-connection async generator. On disconnect + reconnect, client sends last `event_id` to resume from that position (no missed signals).

### 9.4 Screener UI

Chartink-style condition builder:
- Dropdowns for indicator/pattern selection
- AND/OR logic between conditions
- Inline LLM input: plain English → auto-populates condition form
- Results table: symbol, price, change%, signal type, strength (1–5 dots), volume ratio
- Click row → opens `/chart/:symbol`

---

## 10. Deployment

### 10.1 Dev

```bash
docker compose -f docker-compose.dev.yml up
# API:          http://localhost:8000 (uvicorn --reload)
# Frontend:     http://localhost:5173 (vite HMR)
# Temporal UI:  http://localhost:8080
# QuestDB UI:   http://localhost:9000
# PostgreSQL:   localhost:5432
# Redis:        localhost:6379
# Prometheus:   http://localhost:9090
# Grafana:      http://localhost:3000
# Jaeger UI:    http://localhost:16686
```

### 10.2 Production

```bash
docker compose -f docker-compose.prod.yml up -d
# Nginx → Gunicorn (4 uvicorn workers) → FastAPI
# Vite build → Nginx static
# All services behind nginx on 80/443
```

### 10.3 Environment Config

```bash
# Data sources
SHOONYA_API_KEY=
SHOONYA_USER=

# Databases
POSTGRES_URL=postgresql://user:pass@postgres:5432/trading
QUESTDB_URL=postgresql://admin:quest@questdb:8812/qdb
REDIS_URL=redis://redis:6379

# Jobs
TEMPORAL_HOST=temporal:7233
TEMPORAL_NAMESPACE=trading

# LLM
ANTHROPIC_API_KEY=
LLM_MODEL=claude-sonnet-4-6

# Storage
PARQUET_BASE_PATH=/data/raw     # local | s3://bucket/raw for prod

# Auth
AUTH_PROVIDER=local              # local | google | github
ADMIN_USERNAME=
ADMIN_PASSWORD_HASH=             # bcrypt hash
JWT_SECRET=                      # 256-bit random
JWT_EXPIRY_HOURS=24
# Future OAuth (when AUTH_PROVIDER=google):
# GOOGLE_CLIENT_ID=
# GOOGLE_CLIENT_SECRET=
# GOOGLE_ALLOWED_EMAILS=

# Feature flags
ENABLE_LIVE_SIGNALS=true
ENABLE_LLM_CHAT=true
SAFETY_GATE_AGENT_CODE=true
```

### 10.4 Production Scale Path

All components containerized with env-var config. Migration path:

| Component | Personal (now) | Production (future) |
|-----------|---------------|-------------------|
| QuestDB | Single node | QuestDB cluster / ClickHouse |
| PostgreSQL | Single node | Read replicas / Aurora |
| Redis | Single node | Redis Cluster |
| Temporal | Self-hosted | Temporal Cloud (config + mTLS cert change — not URL-only) |
| Parquet | Local disk | S3 / GCS via `Storage` abstraction (§3.6) |
| Docker Compose | Local | Kubernetes / ECS |

No application business logic changes required. `Storage` abstraction (§3.6) ensures Parquet→S3 is config-only.

---

## 11. Observability

### 11.1 Stack

| Concern | Tool | Notes |
|---------|------|-------|
| Structured logging | `structlog` | JSON logs, every service. Fields: timestamp, level, module, symbol, duration_ms, error |
| Metrics | Prometheus + Grafana | FastAPI exposes `/metrics`. Grafana dashboards for all key metrics |
| Tracing | OpenTelemetry → Jaeger | Trace API request → service → QuestDB/Postgres. Optional in pilot, on in prod |
| Workflow observability | Temporal UI (built-in) | Workflow run history, activity failures, retries — already included in Docker Compose |
| Data quality | Custom health checks | Detect OHLCV gaps, stale data, failed scrapes |

### 11.2 Key Metrics to Instrument

**Data ingestion:**
- `ingestion_rows_written_total{source, symbol, timeframe}` — rows written per run
- `ingestion_duration_seconds{workflow}` — how long each workflow takes
- `ingestion_failures_total{source}` — failed fetches per source
- `data_gap_detected_total{symbol, timeframe}` — missing candles detected

**API:**
- `http_request_duration_seconds{route, method, status}` — latency per endpoint
- `scanner_run_duration_seconds{scan_name}` — scanner execution time
- `llm_tool_calls_total{tool}` — LLM tool use frequency

**Signal engine:**
- `signals_fired_total{signal_name, timeframe, direction}` — signals per type
- `pattern_detection_duration_seconds{pattern}` — pattern compute time

**Cache:**
- `redis_cache_hits_total` / `redis_cache_misses_total` — cache effectiveness
- `indicator_cache_staleness_seconds{symbol}` — age of cached indicators

### 11.3 Logging Strategy

Every log entry is structured JSON with correlation ID propagated from API → Temporal workflow → activity → DB:

```json
{
  "ts": "2026-05-17T09:01:23Z",
  "level": "info",
  "module": "workers.activities.fetch_github_eod_data",
  "event": "ingestion_complete",
  "trace_id": "abc123",          -- OpenTelemetry trace ID, same across API request + all downstream work
  "workflow_run_id": "xyz789",   -- Temporal workflow run ID for correlation
  "symbols_count": 1842,
  "rows_written": 1842,
  "duration_ms": 4200
}
```

`trace_id` propagated via Temporal workflow headers (`workflow.get_external_workflow_handle` memo) and FastAPI middleware (`X-Trace-ID` header → context var → all log calls in that request).

Log levels:
- `DEBUG` — SDK calls, indicator compute steps (dev only)
- `INFO` — workflow start/end, ingestion counts, scan results count
- `WARNING` — data gaps detected, cache miss rate > 50%, slow query > 5s
- `ERROR` — ingestion failure, DB write failure, LLM API error
- `CRITICAL` — Temporal worker down, QuestDB unreachable

### 11.4 Data Quality Monitoring

Temporal activity runs after each ingestion:

```python
# activities/data_quality_check.py
# Runs after daily_eod_ingestion
checks:
  - No OHLCV gap > 1 trading day for Nifty 50 stocks
  - market_cap updated within last 7 days for all stocks
  - each market_event_type with refresh_schedule="daily" has at least one event row for today
  - ohlcv_1min rows for today match expected count:
      expected = trading_calendar.minutes_for_date(today) × active_symbols
      # Uses trading_calendar table — NOT hardcoded 375
      # Handles half-days (Diwali Muhurat, Budget day early close, etc.)
```

Failures write to `data_quality_alerts` Postgres table + log at ERROR level.

### 11.5 Alerting

Personal use: Temporal UI + log tailing sufficient for pilot.  
Production path: Prometheus Alertmanager → Telegram/email on:
- Any `CRITICAL` log event
- Ingestion failure 2 consecutive days
- Scanner run duration > 10 minutes
- Data gap detected in Nifty 50 stocks

### 11.6 Grafana Dashboards (pre-built)

- **Ingestion health** — rows/day per source, failure rates, data freshness
- **API performance** — latency percentiles, scanner run times, error rates
- **Signal activity** — signals fired per type per day, pattern distribution
- **Cache efficiency** — hit/miss rates, TTL expiry patterns

---

## 12. Authentication

### 12.1 Current Implementation (Pilot)

Single-user JWT auth. No user database — credentials in `.env`.

```bash
ADMIN_USERNAME=you
ADMIN_PASSWORD_HASH=bcrypt_hash_of_password
JWT_SECRET=random_256_bit_key
JWT_EXPIRY_HOURS=24
AUTH_PROVIDER=local   # switches auth provider
```

Flow:
```
POST /auth/login {username, password}
  → bcrypt verify against ADMIN_PASSWORD_HASH
  → return JWT {sub: username, exp: now+24h, signed with JWT_SECRET}

All routes: FastAPI dependency → verify JWT → 401 if invalid/expired
WebSocket:  ws://...?token=<jwt>  → verified on connect
```

Protected endpoints:
- All API routes (`/technical/*`, `/scanner/*`, `/chat/*`, `/data/*`)
- WebSocket signal feed
- `/admin/activities` (agent approval — especially sensitive)

Public endpoints:
- `POST /auth/login`
- `GET /health`

### 12.2 Auth Provider Abstraction (extensible)

`AUTH_PROVIDER` env var switches implementation. No application route changes needed.

```python
# core/auth/provider.py
class AuthProvider(Protocol):
    async def authenticate(self, credentials: dict) -> User | None: ...
    async def verify_token(self, token: str) -> User | None: ...
    def login_url(self) -> str: ...        # for OAuth redirect flows
    def callback_url(self) -> str: ...     # for OAuth callback

# Implementations — register by name, activated via AUTH_PROVIDER env var
class LocalJWTProvider(AuthProvider): ...     # AUTH_PROVIDER=local (now)
class GoogleOAuthProvider(AuthProvider): ...  # AUTH_PROVIDER=google (future)
class GitHubOAuthProvider(AuthProvider): ...  # AUTH_PROVIDER=github (future)
```

Adding Google login in future:
```bash
AUTH_PROVIDER=google
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_ALLOWED_EMAILS=you@gmail.com  # allowlist for personal use
```

Zero application code change — only `.env` update + `GoogleOAuthProvider` implementation.

### 12.3 Future Multi-Provider

When multiple providers needed (e.g., local fallback + Google):
```bash
AUTH_PROVIDERS=local,google   # try in order
```

`core/auth/` also owns: session management, token refresh, logout (token blacklist in Redis).

---

## 13. What This Spec Does NOT Cover

- Fundamental Analysis Engine (separate spec)
- Backtesting System (separate spec) — owns its own DuckDB query layer; this spec owns the Parquet layout and `Storage` abstraction as the shared foundation. However, the following requirements are pre-decided here and must be honoured in the backtesting spec:

  **Cost model (all fields required — no silent defaults):**
  ```python
  BacktestConfig:
    brokerage_per_trade:   float   # flat or % e.g. 0.0003
    stt_pct:               float   # 0.001 delivery / 0.00025 intraday sell
    exchange_fees_pct:     float   # NSE: 0.0000325
    gst_on_charges_pct:    float   # 18% on brokerage + exchange fees
    slippage_model:        Literal["fixed", "volume_based", "atr_based"]
    slippage_pct:          float   # for fixed model
  ```
  Results always show: gross PnL, net PnL after all costs, cost drag %.

  **Bias prevention:**
  ```python
  universe_mode: Literal["point_in_time", "current_only"]
  # point_in_time = includes delisted stocks; uses only data available AT signal time (no look-ahead)
  # current_only  = survivorship bias present; results page shows a hard warning banner
  ```
  Look-ahead bias prevention is an architectural requirement: backtesting engine must enforce that any signal computation at time T only accesses data with timestamp < T.
- Trade execution / broker integration
- Automated trading bots
- Authentication / multi-user — deployment is LAN/personal network only for pilot; auth added before any public exposure

---

## 14. Open Questions (require answers before implementation)

1. **Data write path:** Does ingestion go `source → Parquet first, then QuestDB` (Parquet primary) or `source → both in parallel` (dual-write)? If dual-write, what's the consistency guarantee if one write fails?

2. **QuestDB → Parquet rehydration:** When a query needs 1-min data older than QuestDB's 60d retention, should the SDK transparently fall back to DuckDB+Parquet, or return an explicit error for the caller to handle? Transparent fallback is better UX but couples the SDK to two storage engines.

3. **intraday_1min_collector rate limits:** What is Shoonya's API rate limit for historical/streaming 1-min pulls? Determines how many symbols can realistically be collected per minute.

4. ~~**Agent approval UI**~~ — **Resolved:** both dashboard page (`/admin/activities`) and Telegram bot notification. Dashboard shows pending activities with code diff + Approve/Reject buttons. Telegram sends notification when a new activity is pending. Either channel can approve.

5. ~~**Authentication scope**~~ — **Resolved:** local machine only for pilot (localhost). No auth layer needed. Note for future: before exposing to LAN or remote, add Tailscale + basic app-level auth.

6. **Shoonya rate limits:** Exact rate limit for 1-min data pulls TBD during implementation. Default assumption: 10 req/s. `intraday_1min_collector` fans out with configurable concurrency (`SHOONYA_MAX_CONCURRENT=10`), respects rate limit via token bucket. Tune after first run.

---

## 15. Success Criteria for Pilot

- [ ] Historical backfill complete: 10yr daily + 60d 1-min for NSE top 500 stocks
- [ ] `market_event_collector` fires at all configured `collection_windows` per event type, including both 9:00 AM and 9:11 AM windows for pre-open data
- [ ] Screener can run any configurable scan (arbitrary source + filters + time-window analysis + indicators) and return results < 30s for up to 500 symbols
- [ ] LLM chat correctly translates a natural language query into scanner conditions and executes it end-to-end
- [ ] Signal feed shows live signals during market hours
- [ ] Chart view displays OHLCV with signal markers for any NSE stock
- [ ] Adding a new agent-generated activity works end-to-end without touching workflow code
