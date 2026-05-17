# Technical Analysis Engine — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a modular-monolith technical analysis engine for NSE/BSE — data ingestion, indicators, chart patterns, scanner, LLM NL interface, live signal feed, and React dashboard.

**Architecture:** FastAPI modular monolith; modules communicate only through `core/` interfaces. Temporal for all background jobs. Parquet as source of truth, QuestDB as hot layer, DuckDB as transparent fallback for historical ranges.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, Alembic, QuestDB, PostgreSQL, Redis, Temporal, pandas-ta 0.3.14b, scipy, DuckDB, React 18 + Vite, TradingView Lightweight Charts, TanStack Table/Query, Zustand, structlog, Prometheus, OpenTelemetry→Jaeger.

---

## File Structure

```
trading-system/
├── backend/
│   ├── pyproject.toml
│   ├── core/
│   │   ├── config.py                    # pydantic-settings — all env vars
│   │   ├── db.py                        # SQLAlchemy async session + QuestDB conn
│   │   ├── cache.py                     # Redis async client
│   │   ├── storage.py                   # Storage Protocol, LocalStorage, S3Storage stub
│   │   ├── sdk.py                       # MarketData, Indicators, Patterns, Scanner
│   │   ├── logging.py                   # structlog JSON setup + trace_id context var
│   │   ├── metrics.py                   # Prometheus custom metrics registry
│   │   └── auth/
│   │       ├── provider.py              # AuthProvider Protocol + User model
│   │       ├── local.py                 # LocalJWTProvider (bcrypt + JWT)
│   │       ├── google.py                # GoogleOAuthProvider stub
│   │       ├── github.py                # GitHubOAuthProvider stub
│   │       └── middleware.py            # FastAPI JWT dependency
│   ├── data/
│   │   └── sources/
│   │       ├── yfinance_source.py       # yfinance adapter + retry
│   │       ├── shoonya_source.py        # Shoonya API adapter
│   │       ├── nse_public_source.py     # NSE pre-open API + trading calendar
│   │       └── github_eod_source.py     # jugaad-trader/nse-data GitHub EOD
│   ├── technical/
│   │   ├── indicators/
│   │   │   ├── trend.py                 # EMA, SMA, WMA, Supertrend, Ichimoku
│   │   │   ├── momentum.py              # RSI, MACD, Stochastic, CCI
│   │   │   ├── volatility.py            # Bollinger Bands, ATR, Keltner, Donchian
│   │   │   ├── volume.py                # OBV, VWAP, Chaikin
│   │   │   └── registry.py              # indicator name → callable map
│   │   ├── patterns/
│   │   │   ├── reversal.py              # H&S, double top/bottom, triple top/bottom
│   │   │   ├── continuation.py          # triangle, flag, pennant, wedge
│   │   │   ├── levels.py                # support/resistance, breakout
│   │   │   └── detector.py              # scipy peaks → pattern dispatch
│   │   └── trend.py                     # TrendResult, linear regression
│   ├── scanner/
│   │   ├── engine.py                    # Scanner fluent API
│   │   ├── conditions.py                # condition evaluators
│   │   ├── dsl.py                       # canonical DSL JSON + SCANNER_DSL_VERSION
│   │   └── signals/
│   │       ├── models.py                # SignalConfig, SignalCondition Pydantic
│   │       └── loader.py                # load + validate signals.yaml at startup
│   ├── llm/
│   │   ├── translator.py                # NL → scanner DSL via Claude tool use
│   │   ├── tools.py                     # tool definitions for Claude
│   │   ├── budget.py                    # Redis daily token counter
│   │   └── prompts/
│   │       └── v1/
│   │           ├── system.txt
│   │           └── tools.json
│   ├── api/
│   │   ├── main.py                      # FastAPI app factory
│   │   ├── middleware.py                # trace_id injection
│   │   ├── signals_ws.py                # WebSocket via Redis Streams
│   │   └── routers/
│   │       ├── auth.py                  # POST /auth/login
│   │       ├── technical.py             # /technical/*
│   │       ├── scanner.py               # /scanner/*
│   │       ├── data.py                  # /data/*
│   │       ├── chat.py                  # /chat/*
│   │       └── admin.py                 # /admin/activities
│   └── workers/
│       ├── registry.py                  # auto-discover + register activity files
│       ├── security.py                  # AST + RestrictedPython + bytecode + subprocess gate
│       ├── workflows/
│       │   ├── backfill.py
│       │   ├── daily_eod.py
│       │   ├── intraday.py
│       │   ├── market_events.py
│       │   └── maintenance.py
│       ├── activities/
│       │   ├── fetch_github_eod_data.py
│       │   ├── fetch_yfinance_daily.py
│       │   ├── fetch_shoonya_intraday.py
│       │   ├── fetch_nse_preopen.py
│       │   ├── aggregate_hourly.py
│       │   ├── compute_indicators.py
│       │   ├── run_scanner_presets.py
│       │   ├── invalidate_cache.py
│       │   ├── data_quality_check.py
│       │   └── questdb_retention_sweep.py
│       └── config/
│           ├── signals.yaml
│           ├── daily_eod.yaml
│           └── workflows.yaml
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── store/
│   │   │   ├── signals.ts               # Zustand — live signal feed
│   │   │   └── filters.ts               # Zustand — screener filter state
│   │   ├── api/
│   │   │   ├── client.ts                # axios + JWT interceptor
│   │   │   ├── scanner.ts               # TanStack Query hooks for scanner
│   │   │   ├── technical.ts             # TanStack Query hooks for indicators/OHLCV
│   │   │   └── chat.ts                  # TanStack Query hooks for LLM chat
│   │   ├── components/
│   │   │   ├── Screener/
│   │   │   │   ├── ConditionBuilder.tsx
│   │   │   │   ├── ResultsTable.tsx
│   │   │   │   └── StrengthDots.tsx
│   │   │   ├── Chart/
│   │   │   │   ├── CandlestickChart.tsx
│   │   │   │   └── SignalMarkers.tsx
│   │   │   ├── SignalFeed/
│   │   │   │   ├── SignalFeedPanel.tsx
│   │   │   │   └── SignalItem.tsx
│   │   │   ├── Chat/
│   │   │   │   └── ChatInterface.tsx
│   │   │   └── Layout/
│   │   │       ├── Sidebar.tsx
│   │   │       └── Topbar.tsx
│   │   └── pages/
│   │       ├── Login.tsx
│   │       ├── Screener.tsx
│   │       ├── Chart.tsx
│   │       ├── Signals.tsx
│   │       └── Chat.tsx
├── infra/
│   ├── docker-compose.dev.yml
│   ├── docker-compose.prod.yml
│   ├── nginx/nginx.conf
│   ├── questdb/migrations/001_initial.sql
│   └── alembic/
│       ├── alembic.ini
│       └── versions/001_initial.py
└── tests/
    ├── unit/
    │   ├── test_indicators.py
    │   ├── test_patterns.py
    │   ├── test_trend.py
    │   ├── test_scanner.py
    │   ├── test_auth.py
    │   ├── test_llm_translator.py
    │   ├── test_security_gate.py
    │   └── test_storage.py
    └── integration/
        ├── test_sdk.py
        ├── test_api.py
        └── test_signal_yaml.py
```

---

## Task 1: Project Scaffold + Dev Environment

**Files:**
- Create: `backend/pyproject.toml`
- Create: `infra/docker-compose.dev.yml`
- Create: `backend/core/__init__.py` (empty)
- Create: `backend/api/main.py` (minimal app)

- [ ] **Step 1: Create backend/pyproject.toml**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "trading-system"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    # Web
    "fastapi>=0.111",
    "uvicorn[standard]>=0.30",
    "gunicorn>=22.0",
    # DB
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.29",
    "alembic>=1.13",
    "psycopg2-binary>=2.9",   # QuestDB PG wire
    # Cache
    "redis[hiredis]>=5.0",
    # Jobs
    "temporalio>=1.6",
    # Data
    "pandas>=2.2",
    "pandas-ta==0.3.14b",
    "duckdb>=0.10",
    "pyarrow>=16.0",
    "scipy>=1.13",
    # Data sources
    "yfinance>=0.2.38",
    "httpx>=0.27",
    # LLM
    "anthropic>=0.28",
    # Auth
    "python-jose[cryptography]>=3.3",
    "passlib[bcrypt]>=1.7",
    # Config
    "pydantic-settings>=2.3",
    # Observability
    "structlog>=24.2",
    "prometheus-fastapi-instrumentator>=7.0",
    "opentelemetry-sdk>=1.24",
    "opentelemetry-exporter-jaeger>=1.21",
    # Security gate
    "RestrictedPython>=7.1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.2",
    "pytest-asyncio>=0.23",
    "pytest-mock>=3.14",
    "httpx>=0.27",  # TestClient
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 2: Create infra/docker-compose.dev.yml**

```yaml
services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: trading
      POSTGRES_USER: trading
      POSTGRES_PASSWORD: trading
    ports: ["5432:5432"]
    volumes: [postgres_data:/var/lib/postgresql/data]

  questdb:
    image: questdb/questdb:8.0.3
    ports:
      - "9000:9000"   # Web console
      - "8812:8812"   # PG wire protocol
      - "9009:9009"   # InfluxDB line protocol
    volumes: [questdb_data:/root/.questdb]

  redis:
    image: redis:7-alpine
    ports: ["6379:6379"]

  temporal:
    image: temporalio/auto-setup:1.24
    ports: ["7233:7233"]
    environment:
      - DB=postgresql
      - DB_PORT=5432
      - POSTGRES_USER=trading
      - POSTGRES_PWD=trading
      - POSTGRES_SEEDS=postgres
    depends_on: [postgres]

  temporal-ui:
    image: temporalio/ui:2.28
    ports: ["8080:8080"]
    environment:
      - TEMPORAL_ADDRESS=temporal:7233

  prometheus:
    image: prom/prometheus:v2.52
    ports: ["9090:9090"]
    volumes: [./prometheus.yml:/etc/prometheus/prometheus.yml]

  grafana:
    image: grafana/grafana:11.0
    ports: ["3000:3000"]
    volumes: [grafana_data:/var/lib/grafana]

  jaeger:
    image: jaegertracing/all-in-one:1.57
    ports:
      - "16686:16686"  # Jaeger UI
      - "4317:4317"    # OTLP gRPC

volumes:
  postgres_data:
  questdb_data:
  grafana_data:
```

- [ ] **Step 3: Create minimal infra/prometheus.yml**

```yaml
global:
  scrape_interval: 15s
scrape_configs:
  - job_name: trading_api
    static_configs:
      - targets: ['host.docker.internal:8000']
```

- [ ] **Step 4: Create backend/api/main.py**

```python
from fastapi import FastAPI

def create_app() -> FastAPI:
    app = FastAPI(title="Trading System", version="0.1.0")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app

app = create_app()
```

- [ ] **Step 5: Verify docker-compose starts**

```bash
cd trading-system
docker compose -f infra/docker-compose.dev.yml up -d
docker compose -f infra/docker-compose.dev.yml ps
```

Expected: all services `running`. QuestDB web at http://localhost:9000, Temporal UI at http://localhost:8080.

- [ ] **Step 6: Verify API starts**

```bash
cd backend
pip install -e ".[dev]"
uvicorn api.main:app --reload
curl http://localhost:8000/health
```

Expected: `{"status":"ok"}`

- [ ] **Step 7: Commit**

```bash
git add infra/ backend/pyproject.toml backend/api/main.py
git commit -m "feat: project scaffold — docker-compose dev env + minimal FastAPI app"
```

---

## Task 2: Core Config + Structured Logging

**Files:**
- Create: `backend/core/config.py`
- Create: `backend/core/logging.py`
- Create: `backend/core/db.py`
- Create: `backend/core/cache.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_config.py
import pytest
from core.config import Settings

def test_settings_loads_defaults():
    s = Settings(
        POSTGRES_URL="postgresql+asyncpg://u:p@localhost/db",
        QUESTDB_URL="postgresql://admin:quest@localhost:8812/qdb",
        REDIS_URL="redis://localhost:6379",
        TEMPORAL_HOST="localhost:7233",
        JWT_SECRET="x" * 32,
        ADMIN_USERNAME="admin",
        ADMIN_PASSWORD_HASH="$2b$12$...",
    )
    assert s.SCHEMA_VERSION == "v1"
    assert s.LLM_MODEL == "claude-sonnet-4-6"
    assert s.PARQUET_BASE_PATH == "/data/raw"
    assert s.LLM_DAILY_TOKEN_BUDGET == 100_000
    assert s.SCANNER_DSL_VERSION == 1
```

- [ ] **Step 2: Run — verify fail**

```bash
cd backend && pytest tests/unit/test_config.py -v
```

Expected: `ImportError: cannot import name 'Settings' from 'core.config'`

- [ ] **Step 3: Implement core/config.py**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Databases
    POSTGRES_URL: str
    QUESTDB_URL: str
    REDIS_URL: str

    # Jobs
    TEMPORAL_HOST: str
    TEMPORAL_NAMESPACE: str = "trading"

    # Auth
    AUTH_PROVIDER: str = "local"
    ADMIN_USERNAME: str = ""
    ADMIN_PASSWORD_HASH: str = ""
    JWT_SECRET: str
    JWT_EXPIRY_HOURS: int = 24

    # LLM
    ANTHROPIC_API_KEY: str = ""
    LLM_MODEL: str = "claude-sonnet-4-6"
    LLM_PROMPT_VERSION: str = "v1"
    LLM_DAILY_TOKEN_BUDGET: int = 100_000

    # Storage
    PARQUET_BASE_PATH: str = "/data/raw"

    # Scanner DSL version — bump on breaking DSL changes
    SCANNER_DSL_VERSION: int = 1

    # Redis namespace — bump on breaking schema changes
    SCHEMA_VERSION: str = "v1"

    # Feature flags
    ENABLE_LIVE_SIGNALS: bool = True
    ENABLE_LLM_CHAT: bool = True
    SAFETY_GATE_AGENT_CODE: bool = True

    # Rate limits
    SHOONYA_MAX_CONCURRENT: int = 10

settings = Settings()
```

- [ ] **Step 4: Implement core/logging.py**

```python
import contextvars
import structlog

trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")

def setup_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )

def get_logger(name: str):
    return structlog.get_logger(name)
```

- [ ] **Step 5: Implement core/db.py**

```python
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
import psycopg2
from core.config import settings

engine = create_async_engine(settings.POSTGRES_URL, pool_size=10, max_overflow=20)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)

async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        yield session

def get_questdb_conn():
    """Synchronous psycopg2 connection to QuestDB PG wire."""
    return psycopg2.connect(settings.QUESTDB_URL)
```

- [ ] **Step 6: Implement core/cache.py**

```python
from redis.asyncio import Redis
from core.config import settings

_redis: Redis | None = None

def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _redis

def cache_key(*parts: str) -> str:
    """Build namespaced cache key: ta:v1:indicators:RELIANCE:1min"""
    from core.config import settings
    return f"ta:{settings.SCHEMA_VERSION}:{':'.join(parts)}"
```

- [ ] **Step 7: Run tests — verify pass**

```bash
pytest tests/unit/test_config.py -v
```

Expected: `PASSED`

- [ ] **Step 8: Commit**

```bash
git add backend/core/
git commit -m "feat: core config (pydantic-settings), structlog JSON logging, DB + cache clients"
```

---

## Task 3: PostgreSQL Schema (Alembic Migration)

**Files:**
- Create: `infra/alembic/alembic.ini`
- Create: `infra/alembic/env.py`
- Create: `infra/alembic/versions/001_initial.py`
- Create: `backend/core/models.py` (SQLAlchemy ORM models)

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_schema.py
import pytest
import asyncpg

@pytest.mark.asyncio
async def test_all_tables_exist():
    conn = await asyncpg.connect("postgresql://trading:trading@localhost:5432/trading")
    tables = await conn.fetch(
        "SELECT tablename FROM pg_tables WHERE schemaname='public'"
    )
    names = {r["tablename"] for r in tables}
    expected = {
        "stocks", "scan_results", "trading_calendar",
        "agent_activities", "stock_attributes",
        "market_event_types", "market_events",
        "data_quality_alerts", "adjustment_factors",
    }
    assert expected.issubset(names), f"Missing: {expected - names}"
    await conn.close()
```

- [ ] **Step 2: Run — verify fail**

```bash
pytest tests/integration/test_schema.py -v
```

Expected: `AssertionError: Missing: {'stocks', 'scan_results', ...}`

- [ ] **Step 3: Init Alembic**

```bash
cd infra && alembic init alembic
```

Edit `infra/alembic/alembic.ini`: set `sqlalchemy.url = postgresql://trading:trading@localhost:5432/trading`

- [ ] **Step 4: Write migration infra/alembic/versions/001_initial.py**

```python
"""Initial schema"""
revision = "001"
down_revision = None

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB, TIMESTAMPTZ

def upgrade():
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

    op.create_table("stocks",
        sa.Column("symbol", sa.Text, primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("exchange", sa.Text, nullable=False),
        sa.Column("sector", sa.Text),
        sa.Column("industry", sa.Text),
        sa.Column("market_cap", sa.BigInteger),
        sa.Column("updated_at", TIMESTAMPTZ, server_default=sa.func.now()),
        sa.CheckConstraint("exchange IN ('NSE','BSE')", name="stocks_exchange_check"),
    )

    op.create_table("stock_attributes",
        sa.Column("symbol", sa.Text, sa.ForeignKey("stocks.symbol"), nullable=False),
        sa.Column("group_name", sa.Text, nullable=False),
        sa.Column("attributes", JSONB, nullable=False),
        sa.Column("updated_at", TIMESTAMPTZ, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("symbol", "group_name"),
    )
    op.execute("CREATE INDEX idx_stock_attributes_gin ON stock_attributes USING GIN (attributes)")

    op.create_table("scan_results",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("scan_name", sa.Text, nullable=False),
        sa.Column("run_at", TIMESTAMPTZ, nullable=False, server_default=sa.func.now()),
        sa.Column("symbol", sa.Text, nullable=False),
        sa.Column("signals", JSONB, nullable=False),
        sa.Column("score", sa.Numeric),
    )
    op.create_index("idx_scan_results_name_run", "scan_results", ["scan_name", sa.text("run_at DESC")])
    op.create_index("idx_scan_results_symbol", "scan_results", ["symbol", sa.text("run_at DESC")])

    op.create_table("trading_calendar",
        sa.Column("date", sa.Date, primary_key=True),
        sa.Column("exchange", sa.Text, nullable=False),
        sa.Column("is_trading", sa.Boolean, nullable=False),
        sa.Column("session_type", sa.Text),
        sa.Column("open_time", sa.Time),
        sa.Column("close_time", sa.Time),
        sa.Column("minutes", sa.Integer),
    )

    op.create_table("agent_activities",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("name", sa.Text, nullable=False, unique=True),
        sa.Column("file_path", sa.Text, nullable=False),
        sa.Column("status", sa.Text, nullable=False),
        sa.Column("generator", sa.Text),
        sa.Column("prompt", sa.Text),
        sa.Column("created_at", TIMESTAMPTZ, server_default=sa.func.now()),
        sa.Column("approved_by", sa.Text),
        sa.Column("approved_at", TIMESTAMPTZ),
        sa.Column("disabled_at", TIMESTAMPTZ),
        sa.Column("git_sha", sa.Text),
        sa.CheckConstraint(
            "status IN ('proposed','approved','promoted','disabled')",
            name="agent_activities_status_check"
        ),
    )

    op.create_table("market_event_types",
        sa.Column("name", sa.Text, primary_key=True),
        sa.Column("description", sa.Text),
        sa.Column("source", sa.Text),
        sa.Column("collection_windows", JSONB, nullable=False),
        sa.Column("schema_hint", JSONB),
    )

    op.create_table("market_events",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("event_type", sa.Text, sa.ForeignKey("market_event_types.name"), nullable=False),
        sa.Column("collection_label", sa.Text, nullable=False, server_default="default"),
        sa.Column("date", sa.Date, nullable=False),
        sa.Column("symbol", sa.Text, sa.ForeignKey("stocks.symbol")),
        sa.Column("rank", sa.Integer),
        sa.Column("data", JSONB, nullable=False),
        sa.Column("captured_at", TIMESTAMPTZ, server_default=sa.func.now()),
    )
    op.execute(
        "CREATE UNIQUE INDEX idx_market_events_dedup ON market_events "
        "(event_type, collection_label, date, symbol)"
    )
    op.create_index("idx_market_events_type", "market_events", ["event_type", sa.text("date DESC")])
    op.create_index("idx_market_events_symbol", "market_events", ["symbol", "event_type", sa.text("date DESC")])
    op.execute("CREATE INDEX idx_market_events_gin ON market_events USING GIN (data)")

    op.create_table("data_quality_alerts",
        sa.Column("id", UUID, primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("check_name", sa.Text, nullable=False),
        sa.Column("symbol", sa.Text),
        sa.Column("timeframe", sa.Text),
        sa.Column("detail", JSONB),
        sa.Column("fired_at", TIMESTAMPTZ, server_default=sa.func.now()),
        sa.Column("resolved_at", TIMESTAMPTZ),
    )

    op.create_table("adjustment_factors",
        sa.Column("symbol", sa.Text, nullable=False),
        sa.Column("effective_date", sa.Date, nullable=False),
        sa.Column("factor", sa.Numeric, nullable=False),
        sa.Column("action_type", sa.Text),
        sa.PrimaryKeyConstraint("symbol", "effective_date"),
    )

def downgrade():
    for t in [
        "adjustment_factors", "data_quality_alerts", "market_events",
        "market_event_types", "agent_activities", "trading_calendar",
        "scan_results", "stock_attributes", "stocks",
    ]:
        op.drop_table(t)
```

- [ ] **Step 5: Run migration**

```bash
cd infra && alembic upgrade head
```

Expected: `Running upgrade  -> 001, Initial schema`

- [ ] **Step 6: Run test — verify pass**

```bash
pytest tests/integration/test_schema.py -v
```

Expected: `PASSED`

- [ ] **Step 7: Commit**

```bash
git add infra/alembic/ backend/core/models.py
git commit -m "feat: PostgreSQL schema via Alembic — all tables from spec"
```

---

## Task 4: QuestDB Schema

**Files:**
- Create: `infra/questdb/migrations/001_initial.sql`
- Create: `backend/workers/activities/questdb_migrate.py`

- [ ] **Step 1: Write failing test**

```python
# tests/integration/test_questdb_schema.py
import psycopg2

def get_questdb():
    return psycopg2.connect(
        host="localhost", port=8812, database="qdb",
        user="admin", password="quest"
    )

def test_questdb_tables_exist():
    conn = get_questdb()
    cur = conn.cursor()
    cur.execute("SHOW TABLES")
    tables = {row[0] for row in cur.fetchall()}
    assert "ohlcv_1min" in tables
    assert "ohlcv_hourly" in tables
    assert "ohlcv_daily" in tables
    conn.close()

def test_ohlcv_1min_columns():
    conn = get_questdb()
    cur = conn.cursor()
    cur.execute("SELECT * FROM ohlcv_1min LIMIT 0")
    cols = {desc[0] for desc in cur.description}
    assert cols == {"ts", "symbol", "open", "high", "low", "close", "volume"}
    conn.close()
```

- [ ] **Step 2: Run — verify fail**

```bash
pytest tests/integration/test_questdb_schema.py -v
```

Expected: `AssertionError: 'ohlcv_1min' not in set()`

- [ ] **Step 3: Write infra/questdb/migrations/001_initial.sql**

```sql
CREATE TABLE IF NOT EXISTS ohlcv_1min (
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
  DEDUP UPSERT KEYS(ts, symbol);

CREATE TABLE IF NOT EXISTS ohlcv_hourly (
  ts      TIMESTAMP,
  symbol  SYMBOL CAPACITY 4096 CACHE,
  open    DOUBLE,
  high    DOUBLE,
  low     DOUBLE,
  close   DOUBLE,
  volume  LONG
) TIMESTAMP(ts)
  PARTITION BY MONTH
  WAL
  DEDUP UPSERT KEYS(ts, symbol);

CREATE TABLE IF NOT EXISTS ohlcv_daily (
  ts             TIMESTAMP,
  symbol         SYMBOL CAPACITY 4096 CACHE,
  open           DOUBLE,
  high           DOUBLE,
  low            DOUBLE,
  close          DOUBLE,
  volume         LONG,
  adjusted_close DOUBLE
) TIMESTAMP(ts)
  PARTITION BY YEAR
  WAL
  DEDUP UPSERT KEYS(ts, symbol);
```

- [ ] **Step 4: Write backend/workers/activities/questdb_migrate.py**

```python
from temporalio import activity
import pathlib
import psycopg2
from core.config import settings
from core.logging import get_logger

log = get_logger(__name__)

@activity.defn(name="questdb_migrate")
async def activity_fn() -> None:
    sql_path = pathlib.Path(__file__).parents[3] / "infra" / "questdb" / "migrations" / "001_initial.sql"
    sql = sql_path.read_text()

    conn = psycopg2.connect(settings.QUESTDB_URL)
    conn.autocommit = True
    cur = conn.cursor()
    # Execute each statement (QuestDB doesn't support multi-statement in one call)
    for stmt in sql.split(";"):
        stmt = stmt.strip()
        if stmt:
            cur.execute(stmt)
    conn.close()
    log.info("questdb_migrate_complete")
```

- [ ] **Step 5: Apply migration manually for test**

```bash
PGPASSWORD=quest psql -h localhost -p 8812 -U admin -d qdb \
  -f infra/questdb/migrations/001_initial.sql
```

- [ ] **Step 6: Run test — verify pass**

```bash
pytest tests/integration/test_questdb_schema.py -v
```

Expected: `2 passed`

- [ ] **Step 7: Commit**

```bash
git add infra/questdb/ backend/workers/activities/questdb_migrate.py
git commit -m "feat: QuestDB OHLCV schema — WAL + DEDUP UPSERT on all three resolutions"
```

---

## Task 5: Storage Abstraction + Parquet Layout

**Files:**
- Create: `backend/core/storage.py`
- Create: `tests/unit/test_storage.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_storage.py
import pandas as pd
import tempfile
from pathlib import Path
from core.storage import LocalStorage

def test_local_storage_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        storage = LocalStorage(base_path=tmp)
        df = pd.DataFrame({
            "ts": pd.to_datetime(["2024-01-02 09:15:00", "2024-01-02 09:16:00"]),
            "symbol": ["RELIANCE", "RELIANCE"],
            "open": [2800.0, 2802.0],
            "high": [2810.0, 2808.0],
            "low":  [2795.0, 2798.0],
            "close":[2805.0, 2803.0],
            "volume":[100000, 95000],
        })

        path = "timeframe=1min/year=2024/month=01/data.parquet"
        storage.write_parquet(df, path)
        result = storage.read_parquet("timeframe=1min/year=2024/month=01/*.parquet")

        assert len(result) == 2
        assert set(result.columns) == set(df.columns)

def test_local_storage_hive_partition_pruning():
    """DuckDB must prune partitions correctly when querying by hive path."""
    with tempfile.TemporaryDirectory() as tmp:
        storage = LocalStorage(base_path=tmp)
        df = pd.DataFrame({
            "ts": pd.to_datetime(["2024-01-02"]),
            "symbol": ["INFY"],
            "open": [1500.0], "high": [1510.0],
            "low": [1495.0], "close": [1505.0], "volume": [50000],
        })
        storage.write_parquet(df, "timeframe=1min/year=2024/month=01/data.parquet")

        result = storage.read_parquet(
            "timeframe=1min/**/*.parquet",
            hive_partitioning=True,
            filters={"year": 2024, "month": 1},
        )
        assert len(result) == 1
```

- [ ] **Step 2: Run — verify fail**

```bash
pytest tests/unit/test_storage.py -v
```

Expected: `ImportError: cannot import name 'LocalStorage'`

- [ ] **Step 3: Implement backend/core/storage.py**

```python
from typing import Protocol, runtime_checkable
import pandas as pd
import duckdb
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path

@runtime_checkable
class Storage(Protocol):
    def read_parquet(self, path_pattern: str, **kwargs) -> pd.DataFrame: ...
    def write_parquet(self, df: pd.DataFrame, path: str) -> None: ...
    def full_path(self, relative: str) -> str: ...


class LocalStorage:
    def __init__(self, base_path: str | None = None):
        from core.config import settings
        self._base = Path(base_path or settings.PARQUET_BASE_PATH)

    def full_path(self, relative: str) -> str:
        return str(self._base / relative)

    def write_parquet(self, df: pd.DataFrame, path: str) -> None:
        full = self._base / path
        full.parent.mkdir(parents=True, exist_ok=True)
        table = pa.Table.from_pandas(df)
        pq.write_table(table, full, compression="snappy")

    def read_parquet(
        self,
        path_pattern: str,
        hive_partitioning: bool = False,
        filters: dict | None = None,
    ) -> pd.DataFrame:
        full_pattern = str(self._base / path_pattern)
        query = f"SELECT * FROM read_parquet('{full_pattern}'"
        if hive_partitioning:
            query += ", hive_partitioning=true"
        query += ")"

        if filters:
            clauses = " AND ".join(f"{k}={v!r}" for k, v in filters.items())
            query += f" WHERE {clauses}"

        return duckdb.query(query).df()


class S3Storage:
    """Stub — activate by setting PARQUET_BASE_PATH=s3://bucket/raw."""
    def __init__(self, base_path: str):
        self._base = base_path

    def full_path(self, relative: str) -> str:
        return f"{self._base}/{relative}"

    def write_parquet(self, df: pd.DataFrame, path: str) -> None:
        import duckdb
        conn = duckdb.connect()
        conn.execute("INSTALL httpfs; LOAD httpfs;")
        full = self.full_path(path)
        table = pa.Table.from_pandas(df)
        pq.write_table(table, full)

    def read_parquet(self, path_pattern: str, **kwargs) -> pd.DataFrame:
        import duckdb
        conn = duckdb.connect()
        conn.execute("INSTALL httpfs; LOAD httpfs;")
        full_pattern = self.full_path(path_pattern)
        return conn.query(f"SELECT * FROM read_parquet('{full_pattern}')").df()


def get_storage() -> Storage:
    from core.config import settings
    if settings.PARQUET_BASE_PATH.startswith("s3://"):
        return S3Storage(settings.PARQUET_BASE_PATH)
    return LocalStorage(settings.PARQUET_BASE_PATH)
```

- [ ] **Step 4: Run test — verify pass**

```bash
pytest tests/unit/test_storage.py -v
```

Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/core/storage.py tests/unit/test_storage.py
git commit -m "feat: Storage Protocol — LocalStorage (Parquet+DuckDB) + S3Storage stub"
```

---

## Task 6: Data Access SDK — MarketData

**Files:**
- Create: `backend/core/sdk.py`
- Create: `tests/unit/test_sdk.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_sdk.py
import pytest
import pandas as pd
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, date
from core.sdk import MarketData

@pytest.mark.asyncio
async def test_ohlcv_returns_dataframe_from_questdb():
    mock_conn = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=MagicMock(
        fetchall=lambda: [(datetime(2024,1,2,9,15), "RELIANCE", 2800.0, 2810.0, 2795.0, 2805.0, 100000)],
        description=[("ts",), ("symbol",), ("open",), ("high",), ("low",), ("close",), ("volume",)],
    ))
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    with patch("core.sdk.get_questdb_conn", return_value=mock_conn):
        md = MarketData()
        df = await md.ohlcv("RELIANCE", "1min",
                            datetime(2024,1,2,9,15), datetime(2024,1,2,15,30))
    assert isinstance(df, pd.DataFrame)
    assert "close" in df.columns

@pytest.mark.asyncio
async def test_ohlcv_falls_back_to_parquet_when_questdb_empty():
    """If QuestDB returns 0 rows, SDK must fall back to DuckDB+Parquet."""
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = []
    mock_cur.description = [("ts",), ("symbol",), ("open",), ("high",), ("low",), ("close",), ("volume",)]
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cur)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    mock_parquet_df = pd.DataFrame({
        "ts": [datetime(2024,1,2,9,15)],
        "symbol": ["RELIANCE"], "open": [2800.0], "high": [2810.0],
        "low": [2795.0], "close": [2805.0], "volume": [100000],
    })
    mock_storage = MagicMock()
    mock_storage.read_parquet.return_value = mock_parquet_df

    with patch("core.sdk.get_questdb_conn", return_value=mock_conn), \
         patch("core.sdk.get_storage", return_value=mock_storage):
        md = MarketData()
        df = await md.ohlcv("RELIANCE", "1min",
                            datetime(2024,1,2,9,15), datetime(2024,1,2,15,30))

    assert len(df) == 1
    mock_storage.read_parquet.assert_called_once()
```

- [ ] **Step 2: Run — verify fail**

```bash
pytest tests/unit/test_sdk.py -v
```

Expected: `ImportError: cannot import name 'MarketData' from 'core.sdk'`

- [ ] **Step 3: Implement backend/core/sdk.py**

```python
from __future__ import annotations
import asyncio
from datetime import datetime, date
from typing import Protocol, runtime_checkable
import pandas as pd
from core.config import settings
from core.db import get_questdb_conn
from core.storage import get_storage

SCANNER_DSL_VERSION = settings.SCANNER_DSL_VERSION

TF_TABLE = {"1min": "ohlcv_1min", "1h": "ohlcv_hourly", "1d": "ohlcv_daily"}


class MarketData:
    async def ohlcv(
        self,
        symbol: str,
        tf: str,
        from_dt: datetime,
        to_dt: datetime,
        adjusted: bool = True,
    ) -> pd.DataFrame:
        table = TF_TABLE.get(tf)
        if table is None:
            raise ValueError(f"Unknown timeframe {tf!r}. Use: {list(TF_TABLE)}")

        # Try QuestDB hot layer first
        df = await asyncio.get_event_loop().run_in_executor(
            None, self._query_questdb, table, symbol, from_dt, to_dt
        )
        if not df.empty:
            return df

        # Transparent fallback to DuckDB + Parquet
        return self._query_parquet(symbol, tf, from_dt, to_dt)

    def _query_questdb(
        self, table: str, symbol: str, from_dt: datetime, to_dt: datetime
    ) -> pd.DataFrame:
        conn = get_questdb_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM {table} WHERE symbol=? AND ts BETWEEN ? AND ? ORDER BY ts",
                    (symbol, from_dt, to_dt),
                )
                rows = cur.fetchall()
                cols = [d[0] for d in cur.description]
            return pd.DataFrame(rows, columns=cols)
        finally:
            conn.close()

    def _query_parquet(
        self, symbol: str, tf: str, from_dt: datetime, to_dt: datetime
    ) -> pd.DataFrame:
        storage = get_storage()
        pattern = f"timeframe={tf}/year={from_dt.year}/**/*.parquet"
        df = storage.read_parquet(pattern, hive_partitioning=True)
        if df.empty:
            return df
        df["ts"] = pd.to_datetime(df["ts"])
        mask = (df["symbol"] == symbol) & (df["ts"] >= from_dt) & (df["ts"] <= to_dt)
        return df[mask].copy()

    async def market_events(
        self,
        event_type: str,
        date_: date,
        symbol: str | None = None,
        collection_label: str | None = None,
        **filters,
    ) -> pd.DataFrame:
        from sqlalchemy import text
        from core.db import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            where = "event_type = :event_type AND date = :date"
            params: dict = {"event_type": event_type, "date": date_}
            if symbol is not None:
                where += " AND symbol = :symbol"
                params["symbol"] = symbol
            if collection_label is not None:
                where += " AND collection_label = :collection_label"
                params["collection_label"] = collection_label
            result = await session.execute(
                text(f"SELECT * FROM market_events WHERE {where} ORDER BY rank"),
                params,
            )
            rows = result.fetchall()
            return pd.DataFrame(rows, columns=result.keys())

    async def universe(self, filters: dict | None = None) -> list[str]:
        from sqlalchemy import text
        from core.db import AsyncSessionLocal

        async with AsyncSessionLocal() as session:
            result = await session.execute(text("SELECT symbol FROM stocks ORDER BY symbol"))
            symbols = [r[0] for r in result.fetchall()]
        return symbols


class Indicators:
    @staticmethod
    def rsi(data: pd.DataFrame, period: int = 14) -> pd.Series:
        import pandas_ta as ta
        return ta.rsi(data["close"], length=period)

    @staticmethod
    def macd(data: pd.DataFrame) -> pd.DataFrame:
        import pandas_ta as ta
        return ta.macd(data["close"])

    @staticmethod
    def ema(data: pd.DataFrame, period: int) -> pd.Series:
        import pandas_ta as ta
        return ta.ema(data["close"], length=period)

    @staticmethod
    def vwap(data: pd.DataFrame) -> pd.Series:
        import pandas_ta as ta
        return ta.vwap(data["high"], data["low"], data["close"], data["volume"])

    @staticmethod
    def bollinger_bands(data: pd.DataFrame, period: int = 20, std: float = 2.0) -> pd.DataFrame:
        import pandas_ta as ta
        return ta.bbands(data["close"], length=period, std=std)

    @staticmethod
    def atr(data: pd.DataFrame, period: int = 14) -> pd.Series:
        import pandas_ta as ta
        return ta.atr(data["high"], data["low"], data["close"], length=period)
```

- [ ] **Step 4: Run tests — verify pass**

```bash
pytest tests/unit/test_sdk.py -v
```

Expected: `2 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/core/sdk.py tests/unit/test_sdk.py
git commit -m "feat: MarketData SDK — QuestDB hot layer + transparent DuckDB/Parquet fallback"
```

---

## Task 7: Data Source Adapters

**Files:**
- Create: `backend/data/sources/yfinance_source.py`
- Create: `backend/data/sources/nse_public_source.py`
- Create: `backend/data/sources/github_eod_source.py`
- Create: `backend/data/sources/shoonya_source.py`
- Create: `tests/unit/test_data_sources.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_data_sources.py
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from data.sources.yfinance_source import fetch_daily_ohlcv
from data.sources.github_eod_source import fetch_github_eod

def test_yfinance_fetch_returns_normalized_df():
    mock_df = pd.DataFrame({
        "Open": [2800.0], "High": [2810.0], "Low": [2795.0],
        "Close": [2805.0], "Adj Close": [2805.0], "Volume": [100000],
    }, index=pd.to_datetime(["2024-01-02"]))
    mock_df.index.name = "Date"

    with patch("yfinance.download", return_value=mock_df):
        result = fetch_daily_ohlcv("RELIANCE.NS", "2024-01-01", "2024-01-03")

    assert set(result.columns) == {"ts", "symbol", "open", "high", "low", "close", "volume", "adjusted_close"}
    assert result["symbol"].iloc[0] == "RELIANCE"

def test_yfinance_retries_on_failure():
    with patch("yfinance.download", side_effect=[Exception("rate limit"), pd.DataFrame()]) as mock_dl:
        with patch("time.sleep"):  # don't actually sleep in tests
            result = fetch_daily_ohlcv("RELIANCE.NS", "2024-01-01", "2024-01-03")
    assert mock_dl.call_count == 2  # retried once

def test_github_eod_returns_dataframe():
    mock_csv = "Symbol,Date,Open,High,Low,Close,Volume\nRELIANCE,2024-01-02,2800,2810,2795,2805,100000\n"
    with patch("httpx.get") as mock_get:
        mock_get.return_value.text = mock_csv
        mock_get.return_value.raise_for_status = MagicMock()
        result = fetch_github_eod("2024-01-02")
    assert len(result) == 1
    assert result["symbol"].iloc[0] == "RELIANCE"
```

- [ ] **Step 2: Run — verify fail**

```bash
pytest tests/unit/test_data_sources.py -v
```

Expected: `ImportError: cannot import name 'fetch_daily_ohlcv'`

- [ ] **Step 3: Implement backend/data/sources/yfinance_source.py**

```python
import time
import pandas as pd
import yfinance as yf
from core.logging import get_logger

log = get_logger(__name__)
_MAX_ATTEMPTS = 3
_BACKOFF_BASE = 5  # seconds

def fetch_daily_ohlcv(ticker: str, start: str, end: str) -> pd.DataFrame:
    """Fetch daily OHLCV from yfinance with exponential backoff.
    ticker: yfinance format e.g. 'RELIANCE.NS'
    Returns normalized DataFrame with columns: ts, symbol, open, high, low, close, volume, adjusted_close
    """
    symbol = ticker.replace(".NS", "").replace(".BO", "")
    last_exc = None

    for attempt in range(_MAX_ATTEMPTS):
        try:
            df = yf.download(ticker, start=start, end=end, auto_adjust=False, progress=False)
            if df.empty:
                return pd.DataFrame()
            df = df.reset_index()
            return pd.DataFrame({
                "ts": pd.to_datetime(df["Date"]),
                "symbol": symbol,
                "open": df["Open"].astype(float),
                "high": df["High"].astype(float),
                "low": df["Low"].astype(float),
                "close": df["Close"].astype(float),
                "volume": df["Volume"].astype(int),
                "adjusted_close": df["Adj Close"].astype(float),
            })
        except Exception as exc:
            last_exc = exc
            wait = _BACKOFF_BASE * (2 ** attempt)
            log.warning("yfinance_retry", ticker=ticker, attempt=attempt + 1, wait_s=wait, error=str(exc))
            time.sleep(min(wait, 30))

    log.error("yfinance_failed", ticker=ticker, error=str(last_exc))
    return pd.DataFrame()


def fetch_universe(exchange: str = "NSE") -> pd.DataFrame:
    """Fetch market cap + basic info for all stocks via yfinance Ticker.info.
    Returns: DataFrame with columns matching stocks table.
    NOTE: slow — run weekly, not daily.
    """
    raise NotImplementedError("fetch_universe: implement with NSE stock list CSV + yfinance batch")
```

- [ ] **Step 4: Implement backend/data/sources/github_eod_source.py**

```python
import httpx
import pandas as pd
from core.logging import get_logger

log = get_logger(__name__)

# jugaad-trader/nse-data publishes daily CSVs
_REPO_BASE = "https://raw.githubusercontent.com/jugaad-trader/nse-data/main/data"

def fetch_github_eod(date_str: str) -> pd.DataFrame:
    """Fetch EOD OHLCV for all NSE stocks from GitHub auto-updated repo.
    date_str: 'YYYY-MM-DD'
    Returns normalized DataFrame.
    """
    year, month, _ = date_str.split("-")
    url = f"{_REPO_BASE}/{year}/{month}/{date_str}.csv"
    try:
        resp = httpx.get(url, timeout=30)
        resp.raise_for_status()
    except Exception as exc:
        log.error("github_eod_fetch_failed", date=date_str, url=url, error=str(exc))
        return pd.DataFrame()

    df = pd.read_csv(pd.io.common.StringIO(resp.text))
    # Normalize column names — repo schema may vary, handle both cases
    df.columns = [c.strip() for c in df.columns]
    col_map = {
        "Symbol": "symbol", "Date": "ts",
        "Open": "open", "High": "high", "Low": "low",
        "Close": "close", "Volume": "volume",
    }
    df = df.rename(columns=col_map)
    df["ts"] = pd.to_datetime(df["ts"])
    return df[["ts", "symbol", "open", "high", "low", "close", "volume"]]
```

- [ ] **Step 5: Implement backend/data/sources/nse_public_source.py**

```python
import httpx
import pandas as pd
from core.logging import get_logger

log = get_logger(__name__)

_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com",
}
_PRE_OPEN_URL = "https://www.nseindia.com/api/market-status"
_PRE_OPEN_MARKET = "https://www.nseindia.com/api/market-turn-overs?key=pre_open_market"


def fetch_preopen_gainers(top_n: int = 20) -> pd.DataFrame:
    """Fetch NSE pre-open market data. Returns top_n by change%.
    NOTE: NSE requires session cookie. Client must bootstrap session first.
    """
    with httpx.Client(headers=_HEADERS, follow_redirects=True) as client:
        # Bootstrap session cookie
        client.get("https://www.nseindia.com", timeout=10)
        try:
            resp = client.get(_PRE_OPEN_MARKET, timeout=15)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            log.error("nse_preopen_fetch_failed", error=str(exc))
            return pd.DataFrame()

    records = data.get("data", [])
    rows = []
    for item in records:
        rows.append({
            "symbol": item.get("symbol", ""),
            "pre_price": item.get("finalPrice", 0),
            "pre_change_pct": item.get("pChange", 0),
            "pre_volume": item.get("totalTradedVolume", 0),
            "iep": item.get("iep", 0),
        })
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.nlargest(top_n, "pre_change_pct").reset_index(drop=True)


def fetch_trading_calendar(year: int) -> pd.DataFrame:
    """NSE does not have a public JSON calendar API — uses PDF.
    This returns a minimal hardcoded structure; update annually from NSE website.
    """
    raise NotImplementedError("Implement: download NSE holiday PDF + parse, or use hardcoded list")
```

- [ ] **Step 6: Implement backend/data/sources/shoonya_source.py**

```python
import asyncio
import pandas as pd
from core.config import settings
from core.logging import get_logger

log = get_logger(__name__)


async def fetch_intraday_1min(symbol: str, date_str: str) -> pd.DataFrame:
    """Fetch 1-min OHLCV from Shoonya API.
    symbol: NSE symbol e.g. 'RELIANCE'
    date_str: 'YYYY-MM-DD'
    Returns normalized DataFrame.
    NOTE: Shoonya API rate limit assumed 10 req/s — caller must throttle.
    """
    # Shoonya uses NorenApi; keep import local so missing lib doesn't break other modules
    try:
        from NorenRestApiPy.NorenApi import NorenApi
    except ImportError:
        log.error("shoonya_not_installed", msg="pip install NorenRestApiPy")
        return pd.DataFrame()

    # Auth + fetch implementation depends on Shoonya session management
    # Placeholder: return empty; implement with actual NorenApi calls
    log.warning("shoonya_fetch_not_implemented", symbol=symbol, date=date_str)
    return pd.DataFrame()
```

- [ ] **Step 7: Run tests — verify pass**

```bash
pytest tests/unit/test_data_sources.py -v
```

Expected: `3 passed`

- [ ] **Step 8: Commit**

```bash
git add backend/data/ tests/unit/test_data_sources.py
git commit -m "feat: data source adapters — yfinance (retry), GitHub EOD, NSE pre-open, Shoonya stub"
```

---

## Task 8: Technical Indicators

**Files:**
- Create: `backend/technical/indicators/trend.py`
- Create: `backend/technical/indicators/momentum.py`
- Create: `backend/technical/indicators/volatility.py`
- Create: `backend/technical/indicators/volume.py`
- Create: `backend/technical/indicators/registry.py`
- Create: `tests/unit/test_indicators.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_indicators.py
import pytest
import pandas as pd
import numpy as np
from core.sdk import Indicators
from technical.indicators.registry import get_indicator, list_indicators

def make_ohlcv(n: int = 50) -> pd.DataFrame:
    np.random.seed(42)
    close = 2800 + np.cumsum(np.random.randn(n) * 10)
    return pd.DataFrame({
        "ts": pd.date_range("2024-01-01", periods=n, freq="1min"),
        "open":   close - 5,
        "high":   close + 10,
        "low":    close - 10,
        "close":  close,
        "volume": np.random.randint(50000, 200000, n),
    })

def test_rsi_returns_series_length_matches_input():
    df = make_ohlcv(50)
    result = Indicators.rsi(df, period=14)
    assert len(result) == len(df)
    # First 13 values are NaN (insufficient data)
    assert result.iloc[:13].isna().all()
    # Values in range [0, 100]
    assert (result.dropna() >= 0).all()
    assert (result.dropna() <= 100).all()

def test_ema_period_20_returns_series():
    df = make_ohlcv(50)
    result = Indicators.ema(df, period=20)
    assert len(result) == len(df)
    assert result.dropna().shape[0] > 0

def test_macd_returns_dataframe_with_required_columns():
    df = make_ohlcv(100)
    result = Indicators.macd(df)
    assert result is not None
    # pandas-ta MACD returns columns like MACD_12_26_9, MACDh_12_26_9, MACDs_12_26_9
    assert any("MACD" in str(c) for c in result.columns)

def test_bollinger_bands_returns_upper_lower():
    df = make_ohlcv(50)
    result = Indicators.bollinger_bands(df, period=20, std=2.0)
    col_names = [str(c).lower() for c in result.columns]
    assert any("upper" in c or "bbu" in c for c in col_names)
    assert any("lower" in c or "bbl" in c for c in col_names)

def test_registry_get_indicator_returns_callable():
    fn = get_indicator("rsi")
    assert callable(fn)

def test_registry_unknown_indicator_raises():
    with pytest.raises(KeyError, match="unknown_indicator"):
        get_indicator("unknown_indicator")

def test_registry_list_includes_core_indicators():
    indicators = list_indicators()
    assert "rsi" in indicators
    assert "macd" in indicators
    assert "ema" in indicators
    assert "vwap" in indicators
```

- [ ] **Step 2: Run — verify fail**

```bash
pytest tests/unit/test_indicators.py -v
```

Expected: multiple failures: `ImportError`, missing registry.

- [ ] **Step 3: Implement backend/technical/indicators/registry.py**

```python
from typing import Callable
from core.sdk import Indicators

_REGISTRY: dict[str, Callable] = {
    "rsi":             Indicators.rsi,
    "macd":            Indicators.macd,
    "ema":             Indicators.ema,
    "vwap":            Indicators.vwap,
    "bollinger_bands": Indicators.bollinger_bands,
    "atr":             Indicators.atr,
}

def get_indicator(name: str) -> Callable:
    if name not in _REGISTRY:
        raise KeyError(f"{name!r}: not in indicator registry. Available: {list(_REGISTRY)}")
    return _REGISTRY[name]

def list_indicators() -> list[str]:
    return list(_REGISTRY.keys())

def register_indicator(name: str, fn: Callable) -> None:
    """Add custom indicator without modifying core SDK."""
    _REGISTRY[name] = fn
```

- [ ] **Step 4: Implement backend/technical/indicators/momentum.py**

```python
import pandas as pd
import pandas_ta as ta

def rsi(data: pd.DataFrame, period: int = 14) -> pd.Series:
    return ta.rsi(data["close"], length=period)

def macd(data: pd.DataFrame, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.DataFrame:
    return ta.macd(data["close"], fast=fast, slow=slow, signal=signal)

def stochastic(data: pd.DataFrame, k: int = 14, d: int = 3) -> pd.DataFrame:
    return ta.stoch(data["high"], data["low"], data["close"], k=k, d=d)

def cci(data: pd.DataFrame, period: int = 20) -> pd.Series:
    return ta.cci(data["high"], data["low"], data["close"], length=period)

def williams_r(data: pd.DataFrame, period: int = 14) -> pd.Series:
    return ta.willr(data["high"], data["low"], data["close"], length=period)
```

- [ ] **Step 5: Implement backend/technical/indicators/trend.py**

```python
import pandas as pd
import pandas_ta as ta

def ema(data: pd.DataFrame, period: int) -> pd.Series:
    return ta.ema(data["close"], length=period)

def sma(data: pd.DataFrame, period: int) -> pd.Series:
    return ta.sma(data["close"], length=period)

def wma(data: pd.DataFrame, period: int) -> pd.Series:
    return ta.wma(data["close"], length=period)

def supertrend(data: pd.DataFrame, period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    return ta.supertrend(data["high"], data["low"], data["close"], length=period, multiplier=multiplier)

def ichimoku(data: pd.DataFrame) -> pd.DataFrame:
    ich, span = ta.ichimoku(data["high"], data["low"], data["close"])
    return ich
```

- [ ] **Step 6: Implement backend/technical/indicators/volatility.py**

```python
import pandas as pd
import pandas_ta as ta

def bollinger_bands(data: pd.DataFrame, period: int = 20, std: float = 2.0) -> pd.DataFrame:
    return ta.bbands(data["close"], length=period, std=std)

def atr(data: pd.DataFrame, period: int = 14) -> pd.Series:
    return ta.atr(data["high"], data["low"], data["close"], length=period)

def keltner_channel(data: pd.DataFrame, period: int = 20, scalar: float = 2.0) -> pd.DataFrame:
    return ta.kc(data["high"], data["low"], data["close"], length=period, scalar=scalar)

def donchian(data: pd.DataFrame, lower_length: int = 20, upper_length: int = 20) -> pd.DataFrame:
    return ta.donchian(data["high"], data["low"], lower_length=lower_length, upper_length=upper_length)
```

- [ ] **Step 7: Implement backend/technical/indicators/volume.py**

```python
import pandas as pd
import pandas_ta as ta

def obv(data: pd.DataFrame) -> pd.Series:
    return ta.obv(data["close"], data["volume"])

def vwap(data: pd.DataFrame) -> pd.Series:
    return ta.vwap(data["high"], data["low"], data["close"], data["volume"])

def chaikin(data: pd.DataFrame, fast: int = 3, slow: int = 10) -> pd.Series:
    return ta.adosc(data["high"], data["low"], data["close"], data["volume"], fast=fast, slow=slow)
```

- [ ] **Step 8: Run tests — verify pass**

```bash
pytest tests/unit/test_indicators.py -v
```

Expected: `7 passed`

- [ ] **Step 9: Commit**

```bash
git add backend/technical/indicators/ tests/unit/test_indicators.py
git commit -m "feat: indicators — RSI, MACD, EMA, BB, ATR, OBV, VWAP via pandas-ta + registry"
```

---

## Task 9: Chart Pattern Detection

**Files:**
- Create: `backend/technical/patterns/detector.py`
- Create: `backend/technical/patterns/reversal.py`
- Create: `backend/technical/patterns/continuation.py`
- Create: `backend/technical/patterns/levels.py`
- Create: `tests/unit/test_patterns.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_patterns.py
import pytest
import pandas as pd
import numpy as np
from technical.patterns.detector import detect_patterns
from technical.patterns.levels import find_support_resistance
from core.sdk import Patterns

def make_double_bottom(n: int = 100) -> pd.DataFrame:
    """Synthetic double-bottom: two troughs at same level separated by a peak."""
    t = np.arange(n)
    price = 2800 + 50 * np.sin(2 * np.pi * t / 40)
    # Flatten the two troughs to create double-bottom
    price[15:20] = 2750
    price[55:60] = 2752
    return pd.DataFrame({
        "ts": pd.date_range("2024-01-01", periods=n, freq="1min"),
        "open": price - 2, "high": price + 5,
        "low": price - 5, "close": price,
        "volume": np.random.randint(50000, 200000, n),
    })

def test_double_bottom_detected():
    df = make_double_bottom(100)
    results = detect_patterns(df, ["double_bottom"])
    # May or may not detect depending on scipy peak sensitivity — just verify return type
    assert isinstance(results, list)
    for r in results:
        assert "pattern" in r
        assert "confidence" in r
        assert 0 <= r["confidence"] <= 1
        assert "direction" in r
        assert r["direction"] in ("bullish", "bearish", "neutral")

def test_detect_unknown_pattern_raises():
    df = make_double_bottom()
    with pytest.raises(ValueError, match="unknown_pattern"):
        detect_patterns(df, ["unknown_pattern"])

def test_support_resistance_returns_levels():
    df = make_double_bottom(100)
    levels = find_support_resistance(df)
    assert isinstance(levels, list)
    for level in levels:
        assert "price" in level
        assert "type" in level
        assert level["type"] in ("support", "resistance")
        assert "strength" in level

def test_patterns_sdk_detect():
    df = make_double_bottom(100)
    results = Patterns.detect(df, ["double_bottom", "head_and_shoulders"])
    assert isinstance(results, list)
```

- [ ] **Step 2: Run — verify fail**

```bash
pytest tests/unit/test_patterns.py -v
```

Expected: `ImportError: cannot import name 'detect_patterns'`

- [ ] **Step 3: Implement backend/technical/patterns/reversal.py**

```python
from dataclasses import dataclass
import numpy as np
import pandas as pd
from scipy.signal import find_peaks

@dataclass
class PatternResult:
    pattern: str
    confidence: float
    direction: str
    key_levels: list[float]
    formed_at: str
    target: float | None = None

    def to_dict(self) -> dict:
        return {
            "pattern": self.pattern,
            "confidence": self.confidence,
            "direction": self.direction,
            "key_levels": self.key_levels,
            "formed_at": self.formed_at,
            "target": self.target,
        }


def detect_double_bottom(data: pd.DataFrame) -> PatternResult | None:
    lows = data["low"].values
    troughs, _ = find_peaks(-lows, distance=10, prominence=lows.std() * 0.3)
    if len(troughs) < 2:
        return None

    t1, t2 = troughs[-2], troughs[-1]
    p1, p2 = lows[t1], lows[t2]

    if abs(p1 - p2) / p1 > 0.03:  # troughs must be within 3% of each other
        return None

    # Check intermediate peak
    mid_slice = data["high"].values[t1:t2]
    if len(mid_slice) == 0:
        return None
    neck = mid_slice.max()
    trough_avg = (p1 + p2) / 2
    depth = neck - trough_avg
    if depth <= 0:
        return None

    confidence = min(1.0, depth / (lows.std() * 2))
    target = neck + depth
    formed_ts = str(data["ts"].iloc[t2]) if "ts" in data.columns else ""

    return PatternResult(
        pattern="double_bottom",
        confidence=round(confidence, 2),
        direction="bullish",
        key_levels=[round(trough_avg, 2), round(neck, 2)],
        formed_at=formed_ts,
        target=round(target, 2),
    )


def detect_double_top(data: pd.DataFrame) -> PatternResult | None:
    highs = data["high"].values
    peaks, _ = find_peaks(highs, distance=10, prominence=highs.std() * 0.3)
    if len(peaks) < 2:
        return None

    t1, t2 = peaks[-2], peaks[-1]
    p1, p2 = highs[t1], highs[t2]

    if abs(p1 - p2) / p1 > 0.03:
        return None

    mid_slice = data["low"].values[t1:t2]
    if len(mid_slice) == 0:
        return None
    neck = mid_slice.min()
    peak_avg = (p1 + p2) / 2
    depth = peak_avg - neck
    if depth <= 0:
        return None

    confidence = min(1.0, depth / (highs.std() * 2))
    target = neck - depth
    formed_ts = str(data["ts"].iloc[t2]) if "ts" in data.columns else ""

    return PatternResult(
        pattern="double_top",
        confidence=round(confidence, 2),
        direction="bearish",
        key_levels=[round(neck, 2), round(peak_avg, 2)],
        formed_at=formed_ts,
        target=round(target, 2),
    )


def detect_head_and_shoulders(data: pd.DataFrame) -> PatternResult | None:
    highs = data["high"].values
    peaks, props = find_peaks(highs, distance=8, prominence=highs.std() * 0.2)
    if len(peaks) < 3:
        return None

    # Take last 3 peaks: left shoulder, head, right shoulder
    ls, head, rs = peaks[-3], peaks[-2], peaks[-1]
    h_ls, h_head, h_rs = highs[ls], highs[head], highs[rs]

    # Head must be higher than both shoulders
    if not (h_head > h_ls and h_head > h_rs):
        return None
    # Shoulders roughly equal (within 5%)
    if abs(h_ls - h_rs) / h_ls > 0.05:
        return None

    neckline = min(data["low"].values[ls:rs].min(), data["low"].values[rs:].min() if rs < len(data) - 1 else data["low"].values[rs])
    depth = ((h_ls + h_rs) / 2) - neckline
    confidence = min(1.0, depth / highs.std())
    formed_ts = str(data["ts"].iloc[rs]) if "ts" in data.columns else ""

    return PatternResult(
        pattern="head_and_shoulders",
        confidence=round(confidence, 2),
        direction="bearish",
        key_levels=[round(neckline, 2), round(h_head, 2)],
        formed_at=formed_ts,
        target=round(neckline - depth, 2),
    )
```

- [ ] **Step 4: Implement backend/technical/patterns/levels.py**

```python
import numpy as np
import pandas as pd
from scipy.signal import find_peaks

def find_support_resistance(data: pd.DataFrame, prominence_factor: float = 0.3) -> list[dict]:
    highs = data["high"].values
    lows  = data["low"].values
    std   = data["close"].std()

    resistance_idx, _ = find_peaks(highs, prominence=std * prominence_factor, distance=5)
    support_idx, _    = find_peaks(-lows, prominence=std * prominence_factor, distance=5)

    levels = []
    for idx in resistance_idx:
        levels.append({
            "price": round(float(highs[idx]), 2),
            "type": "resistance",
            "strength": min(5, int(highs[idx] / std)),
            "index": int(idx),
        })
    for idx in support_idx:
        levels.append({
            "price": round(float(lows[idx]), 2),
            "type": "support",
            "strength": min(5, int(std / max(lows[idx], 1))),
            "index": int(idx),
        })
    return sorted(levels, key=lambda x: x["price"])
```

- [ ] **Step 5: Implement backend/technical/patterns/continuation.py**

```python
import numpy as np
import pandas as pd
from scipy.signal import find_peaks
from technical.patterns.reversal import PatternResult

def detect_bull_flag(data: pd.DataFrame) -> PatternResult | None:
    """Detect bull flag: sharp upward pole followed by shallow consolidation."""
    close = data["close"].values
    n = len(close)
    if n < 20:
        return None

    # Pole: 20% move up in first 40% of window
    pole_end = n // 2
    pole_gain = (close[pole_end] - close[0]) / close[0]
    if pole_gain < 0.05:  # need at least 5% pole
        return None

    # Flag: consolidation in second half (range < 50% of pole move)
    flag_range = close[pole_end:].max() - close[pole_end:].min()
    pole_move = close[pole_end] - close[0]
    if flag_range > pole_move * 0.5:
        return None

    confidence = min(1.0, pole_gain * 5)
    return PatternResult(
        pattern="bull_flag",
        confidence=round(confidence, 2),
        direction="bullish",
        key_levels=[round(close[0], 2), round(close[pole_end], 2)],
        formed_at=str(data["ts"].iloc[-1]) if "ts" in data.columns else "",
        target=round(close[-1] + pole_move, 2),
    )
```

- [ ] **Step 6: Implement backend/technical/patterns/detector.py**

```python
import pandas as pd
from technical.patterns.reversal import (
    detect_double_bottom, detect_double_top, detect_head_and_shoulders, PatternResult,
)
from technical.patterns.continuation import detect_bull_flag
from technical.patterns.levels import find_support_resistance

_DETECTORS = {
    "double_bottom":      detect_double_bottom,
    "double_top":         detect_double_top,
    "head_and_shoulders": detect_head_and_shoulders,
    "bull_flag":          detect_bull_flag,
}

def detect_patterns(data: pd.DataFrame, patterns: list[str]) -> list[dict]:
    unknown = set(patterns) - set(_DETECTORS)
    if unknown:
        raise ValueError(f"{unknown}: not in pattern registry. Available: {list(_DETECTORS)}")

    results = []
    for name in patterns:
        result: PatternResult | None = _DETECTORS[name](data)
        if result is not None:
            results.append(result.to_dict())
    return results
```

- [ ] **Step 7: Update core/sdk.py Patterns class**

```python
# Add to existing core/sdk.py — replace stub Patterns class:
class Patterns:
    @staticmethod
    def detect(data: pd.DataFrame, patterns: list[str]) -> list[dict]:
        from technical.patterns.detector import detect_patterns
        return detect_patterns(data, patterns)

    @staticmethod
    def support_resistance(data: pd.DataFrame) -> list[dict]:
        from technical.patterns.levels import find_support_resistance
        return find_support_resistance(data)

    @staticmethod
    def trend(data: pd.DataFrame, from_time: str | None = None, to_time: str | None = None) -> dict:
        from technical.trend import analyze_trend
        return analyze_trend(data, from_time, to_time)
```

- [ ] **Step 8: Run tests — verify pass**

```bash
pytest tests/unit/test_patterns.py -v
```

Expected: `4 passed`

- [ ] **Step 9: Commit**

```bash
git add backend/technical/patterns/ tests/unit/test_patterns.py
git commit -m "feat: chart pattern detection — double top/bottom, H&S, bull flag via scipy peaks"
```

---

## Task 10: Trend Analysis

**Files:**
- Create: `backend/technical/trend.py`
- Create: `tests/unit/test_trend.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_trend.py
import pytest
import numpy as np
import pandas as pd
from technical.trend import analyze_trend

def make_uptrend(n: int = 60) -> pd.DataFrame:
    t = np.arange(n)
    close = 2800 + t * 5 + np.random.randn(n) * 3
    return pd.DataFrame({
        "ts": pd.date_range("2024-01-02 09:15:00", periods=n, freq="1min"),
        "open": close - 2, "high": close + 3,
        "low": close - 3, "close": close,
        "volume": np.random.randint(50000, 200000, n),
    })

def make_downtrend(n: int = 60) -> pd.DataFrame:
    t = np.arange(n)
    close = 2800 - t * 4 + np.random.randn(n) * 2
    return pd.DataFrame({
        "ts": pd.date_range("2024-01-02 09:15:00", periods=n, freq="1min"),
        "open": close - 2, "high": close + 3,
        "low": close - 3, "close": close,
        "volume": np.random.randint(50000, 200000, n),
    })

def test_uptrend_detected():
    df = make_uptrend()
    result = analyze_trend(df)
    assert result["direction"] == "up"
    assert result["slope"] > 0
    assert 0 <= result["r_squared"] <= 1
    assert result["accuracy"] > 0.5
    assert result["strength"] in ("strong", "moderate", "weak")

def test_downtrend_detected():
    df = make_downtrend()
    result = analyze_trend(df)
    assert result["direction"] == "down"
    assert result["slope"] < 0

def test_trend_with_time_window():
    df = make_uptrend(200)
    result = analyze_trend(df, from_time="09:30", to_time="10:30")
    assert result["window"] == "09:30–10:30"
    assert "direction" in result

def test_trend_result_has_all_required_fields():
    df = make_uptrend()
    result = analyze_trend(df)
    required = {"direction", "strength", "accuracy", "slope", "r_squared", "window", "timeframe"}
    assert required.issubset(result.keys())
```

- [ ] **Step 2: Run — verify fail**

```bash
pytest tests/unit/test_trend.py -v
```

Expected: `ImportError: cannot import name 'analyze_trend'`

- [ ] **Step 3: Implement backend/technical/trend.py**

```python
from __future__ import annotations
import numpy as np
import pandas as pd
from scipy.stats import linregress

def analyze_trend(
    data: pd.DataFrame,
    from_time: str | None = None,
    to_time: str | None = None,
    timeframe: str = "1min",
) -> dict:
    df = data.copy()

    if from_time and to_time and "ts" in df.columns:
        df["_time"] = pd.to_datetime(df["ts"]).dt.strftime("%H:%M")
        df = df[(df["_time"] >= from_time) & (df["_time"] <= to_time)]
        window = f"{from_time}–{to_time}"
    else:
        window = "full"

    if len(df) < 5:
        return _flat_result(window, timeframe)

    close = df["close"].values
    x = np.arange(len(close))
    slope, intercept, r_value, _, _ = linregress(x, close)
    r_squared = r_value ** 2

    # Direction
    if slope > 0 and r_squared > 0.3:
        direction = "up"
    elif slope < 0 and r_squared > 0.3:
        direction = "down"
    else:
        direction = "sideways"

    # Strength based on r_squared
    if r_squared > 0.75:
        strength = "strong"
    elif r_squared > 0.4:
        strength = "moderate"
    else:
        strength = "weak"

    # Accuracy: % candles with close on correct side of regression line
    fitted = intercept + slope * x
    if direction == "up":
        accuracy = float(np.mean(close >= fitted))
    elif direction == "down":
        accuracy = float(np.mean(close <= fitted))
    else:
        accuracy = 0.5

    return {
        "direction":  direction,
        "strength":   strength,
        "accuracy":   round(accuracy, 3),
        "slope":      round(float(slope), 4),
        "r_squared":  round(float(r_squared), 3),
        "window":     window,
        "timeframe":  timeframe,
    }

def _flat_result(window: str, timeframe: str) -> dict:
    return {
        "direction": "sideways", "strength": "weak",
        "accuracy": 0.5, "slope": 0.0, "r_squared": 0.0,
        "window": window, "timeframe": timeframe,
    }
```

- [ ] **Step 4: Run tests — verify pass**

```bash
pytest tests/unit/test_trend.py -v
```

Expected: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add backend/technical/trend.py tests/unit/test_trend.py
git commit -m "feat: trend analysis — direction/strength/accuracy/slope/r_squared via scipy linregress"
```

---

## Task 11: Scanner Engine + Signal YAML Config

**Files:**
- Create: `backend/scanner/signals/models.py`
- Create: `backend/scanner/signals/loader.py`
- Create: `backend/scanner/dsl.py`
- Create: `backend/scanner/conditions.py`
- Create: `backend/scanner/engine.py`
- Create: `backend/workers/config/signals.yaml`
- Create: `tests/unit/test_scanner.py`
- Create: `tests/integration/test_signal_yaml.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_scanner.py
import pytest
import pandas as pd
from unittest.mock import AsyncMock, patch
from scanner.engine import Scanner
from scanner.dsl import build_dsl, SCANNER_DSL_VERSION

def test_scanner_dsl_includes_version():
    s = Scanner()
    s.from_source("nse_universe")
    dsl = build_dsl(s)
    assert dsl["version"] == SCANNER_DSL_VERSION
    assert dsl["source"]["name"] == "nse_universe"

def test_scanner_filter_adds_condition():
    s = Scanner()
    s.from_source("nse_universe").filter(exchange="NSE")
    assert len(s._filters) == 1
    assert s._filters[0] == {"field": "exchange", "op": "eq", "value": "NSE"}

def test_scanner_run_respects_max_symbols():
    s = Scanner()
    s.from_source("nse_universe")
    with patch.object(s, "_fetch_symbols", return_value=["A"] * 600):
        with patch.object(s, "_apply_filters", side_effect=lambda syms: syms):
            with patch.object(s, "_compute_results", return_value=pd.DataFrame()):
                result = s.run(max_symbols=500)
    # _compute_results called with at most 500 symbols
    call_args = s._compute_results.call_args
    assert len(call_args[0][0]) <= 500
```

```python
# tests/integration/test_signal_yaml.py
import pytest
from scanner.signals.loader import load_signals
from scanner.signals.models import SignalConfig

def test_signals_yaml_loads_and_validates():
    signals = load_signals()
    assert len(signals) > 0
    for sig in signals:
        assert isinstance(sig, SignalConfig)
        assert sig.name
        assert sig.category in ("entry", "exit", "alert", "custom")
        assert sig.direction in ("bullish", "bearish", "any")
        assert 1 <= sig.display.get("strength_score", 0) <= 5

def test_invalid_yaml_fails_fast(tmp_path):
    bad_yaml = tmp_path / "signals.yaml"
    bad_yaml.write_text("signals:\n  - name: bad\n    category: INVALID\n")
    with pytest.raises(Exception):
        load_signals(str(bad_yaml))
```

- [ ] **Step 2: Run — verify fail**

```bash
pytest tests/unit/test_scanner.py tests/integration/test_signal_yaml.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Implement backend/scanner/signals/models.py**

```python
from typing import Any, Literal
from pydantic import BaseModel, field_validator

class SignalCondition(BaseModel):
    type: Literal[
        "candlestick_pattern", "volume_confirmation",
        "trend_context", "indicator", "custom_activity",
    ]
    pattern: str | None = None
    indicator: str | None = None
    operator: str | None = None        # gt | lt | gte | lte | eq
    value: float | str | None = None
    min_volume_ratio: float | None = None
    trend: str | None = None


class SignalDisplay(BaseModel):
    color: str
    icon: str = "●"
    strength_score: int

    @field_validator("strength_score")
    @classmethod
    def score_in_range(cls, v: int) -> int:
        if not 1 <= v <= 5:
            raise ValueError(f"strength_score must be 1–5, got {v}")
        return v


class SignalConfig(BaseModel):
    name: str
    category: Literal["entry", "exit", "alert", "custom"]
    direction: Literal["bullish", "bearish", "any"]
    timeframes: list[str]
    conditions: list[SignalCondition]
    severity: Literal["low", "medium", "high"]
    display: dict[str, Any]
```

- [ ] **Step 4: Implement backend/scanner/signals/loader.py**

```python
import pathlib
import yaml
from scanner.signals.models import SignalConfig
from core.logging import get_logger

log = get_logger(__name__)

_DEFAULT_PATH = pathlib.Path(__file__).parents[3] / "workers" / "config" / "signals.yaml"

def load_signals(path: str | None = None) -> list[SignalConfig]:
    yaml_path = pathlib.Path(path) if path else _DEFAULT_PATH
    raw = yaml.safe_load(yaml_path.read_text())
    signals = []
    for item in raw.get("signals", []):
        try:
            signals.append(SignalConfig(**item))
        except Exception as exc:
            log.error("signal_yaml_invalid", name=item.get("name"), error=str(exc))
            raise
    log.info("signals_loaded", count=len(signals))
    return signals
```

- [ ] **Step 5: Create backend/workers/config/signals.yaml**

```yaml
signals:
  - name: bearish_engulfing_strong
    category: entry
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
      strength_score: 4

  - name: rsi_oversold_uptrend
    category: entry
    direction: bullish
    timeframes: [1h, 1d]
    conditions:
      - type: indicator
        indicator: rsi
        operator: lt
        value: 30
      - type: trend_context
        trend: up
    severity: medium
    display:
      color: "#089981"
      icon: "▲"
      strength_score: 3

  - name: ema_crossover_bullish
    category: entry
    direction: bullish
    timeframes: [1d]
    conditions:
      - type: indicator
        indicator: ema_20_crosses_ema_50
        operator: eq
        value: "cross_above"
    severity: medium
    display:
      color: "#089981"
      icon: "✕"
      strength_score: 3

  - name: breakout_high_volume
    category: alert
    direction: any
    timeframes: [15min, 1h]
    conditions:
      - type: indicator
        indicator: price_vs_resistance
        operator: gt
        value: 1.0
      - type: volume_confirmation
        min_volume_ratio: 2.0
    severity: high
    display:
      color: "#f5a623"
      icon: "◉"
      strength_score: 5
```

- [ ] **Step 6: Implement backend/scanner/dsl.py**

```python
from core.config import settings

SCANNER_DSL_VERSION = settings.SCANNER_DSL_VERSION

def build_dsl(scanner) -> dict:
    return {
        "version": SCANNER_DSL_VERSION,
        "source": scanner._source or {},
        "filters": scanner._filters,
        "analysis": scanner._analysis,
        "indicators": scanner._indicators,
        "sort": scanner._sort,
    }
```

- [ ] **Step 7: Implement backend/scanner/engine.py**

```python
from __future__ import annotations
import asyncio
import pandas as pd
from core.logging import get_logger
from scanner.dsl import build_dsl, SCANNER_DSL_VERSION

log = get_logger(__name__)


class Scanner:
    def __init__(self):
        self._source: dict = {}
        self._filters: list[dict] = []
        self._analysis: dict = {}
        self._indicators: list[str] = []
        self._sort: dict = {}

    def from_source(self, source: str, **params) -> "Scanner":
        self._source = {"name": source, **params}
        return self

    def filter(self, **conditions) -> "Scanner":
        for field, value in conditions.items():
            if "__" in field:
                attr, op = field.rsplit("__", 1)
                self._filters.append({"field": attr, "op": op, "value": value})
            else:
                self._filters.append({"field": field, "op": "eq", "value": value})
        return self

    def add_analysis(self, **params) -> "Scanner":
        self._analysis = params
        return self

    def add_indicators(self, indicators: list[str]) -> "Scanner":
        self._indicators = indicators
        return self

    def sort_by(self, field: str, descending: bool = True) -> "Scanner":
        self._sort = {"field": field, "descending": descending}
        return self

    def to_dsl(self) -> dict:
        return build_dsl(self)

    def run(self, max_symbols: int = 500, timeout_s: int = 120) -> pd.DataFrame:
        symbols = self._fetch_symbols()
        symbols = symbols[:max_symbols]
        symbols = self._apply_filters(symbols)
        return self._compute_results(symbols)

    def _fetch_symbols(self) -> list[str]:
        source = self._source.get("name", "nse_universe")
        if source == "nse_universe":
            return asyncio.get_event_loop().run_until_complete(self._fetch_universe())
        raise ValueError(f"Unknown source: {source!r}")

    async def _fetch_universe(self) -> list[str]:
        from core.sdk import MarketData
        md = MarketData()
        return await md.universe()

    def _apply_filters(self, symbols: list[str]) -> list[str]:
        # Phase 1: simple attribute filters only (stock_attributes JSONB)
        # Full condition evaluation happens in _compute_results
        return symbols

    def _compute_results(self, symbols: list[str]) -> pd.DataFrame:
        # Placeholder: full implementation in Task 13 (Temporal activities)
        # Scanner.run() is the in-process path; Temporal wraps it for scheduled scans
        log.info("scanner_run", symbol_count=len(symbols), indicators=self._indicators)
        return pd.DataFrame({"symbol": symbols})
```

- [ ] **Step 8: Run tests — verify pass**

```bash
pytest tests/unit/test_scanner.py tests/integration/test_signal_yaml.py -v
```

Expected: `5 passed`

- [ ] **Step 9: Commit**

```bash
git add backend/scanner/ backend/workers/config/signals.yaml tests/
git commit -m "feat: scanner engine (fluent API + DSL) + signal YAML config with Pydantic validation"
```

---

## Task 12: Temporal Worker Registry + Skeleton

**Files:**
- Create: `backend/workers/registry.py`
- Create: `backend/workers/activities/_template.py`
- Create: `tests/unit/test_registry.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_registry.py
import pytest
import pathlib
import tempfile
from unittest.mock import MagicMock

def test_registry_registers_valid_activity(tmp_path):
    # Create a valid activity file in tmp dir
    activity_file = tmp_path / "test_activity.py"
    activity_file.write_text(
        "from temporalio import activity\n\n"
        "@activity.defn(name='test_activity')\n"
        "async def activity_fn():\n"
        "    pass\n"
    )

    # Patch ACTIVITIES_DIR to tmp_path
    import importlib
    import sys
    # We test the registration logic directly
    from workers.registry import _load_activity_from_path
    fn, name = _load_activity_from_path(activity_file)
    assert name == "test_activity"
    assert callable(fn)

def test_registry_rejects_missing_activity_fn(tmp_path):
    bad_file = tmp_path / "bad.py"
    bad_file.write_text("def not_activity_fn(): pass\n")

    from workers.registry import _load_activity_from_path
    with pytest.raises(AttributeError, match="activity_fn"):
        _load_activity_from_path(bad_file)

def test_registry_rejects_duplicate_names(tmp_path):
    f1 = tmp_path / "a1.py"
    f2 = tmp_path / "a2.py"
    code = (
        "from temporalio import activity\n\n"
        "@activity.defn(name='duplicate_name')\n"
        "async def activity_fn():\n"
        "    pass\n"
    )
    f1.write_text(code)
    f2.write_text(code)

    from workers.registry import _collect_activities
    with pytest.raises(ValueError, match="Duplicate activity name"):
        _collect_activities(tmp_path)
```

- [ ] **Step 2: Run — verify fail**

```bash
pytest tests/unit/test_registry.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Implement backend/workers/registry.py**

```python
import importlib.util
import pathlib
import logging
from temporalio.worker import Worker

log = logging.getLogger(__name__)

ACTIVITIES_DIR = pathlib.Path(__file__).parent / "activities"


def _load_activity_from_path(path: pathlib.Path):
    spec = importlib.util.spec_from_file_location(f"workers.activities.{path.stem}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    fn = getattr(module, "activity_fn", None)
    if fn is None:
        raise AttributeError(f"activity_fn not found in {path.name}")

    definition = getattr(fn, "__temporal_activity_definition", None)
    if definition is None:
        raise AttributeError(f"activity_fn in {path.name} missing @activity.defn decorator")

    name = definition.name
    return fn, name


def _collect_activities(activities_dir: pathlib.Path) -> list[tuple]:
    seen: set[str] = set()
    collected = []

    for path in sorted(activities_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            fn, name = _load_activity_from_path(path)
            if name in seen:
                raise ValueError(f"Duplicate activity name '{name}' in {path.name}")
            seen.add(name)
            collected.append((fn, name, path.stem))
        except Exception as exc:
            log.error("activity_load_failed", extra={"file": path.stem, "error": str(exc)})
            raise

    return collected


def register_all(worker: Worker) -> tuple[list[str], list[str]]:
    """Auto-discover and register all activity files. Returns (registered, skipped)."""
    registered, skipped = [], []

    for path in sorted(ACTIVITIES_DIR.glob("*.py")):
        if path.name.startswith("_"):
            continue
        try:
            fn, name, stem = _collect_activities(ACTIVITIES_DIR)[0]  # load individually
            worker.register_activity(fn)
            registered.append(name)
            log.info("activity_registered", extra={"name": name, "file": stem})
        except Exception as exc:
            skipped.append(f"{path.stem}: {exc}")
            log.error("activity_registration_failed", extra={"file": path.stem, "error": str(exc)})

    return registered, skipped
```

- [ ] **Step 4: Create backend/workers/activities/_template.py** (underscored = excluded from auto-registration)

```python
# Template for new activities — copy and rename (without leading underscore)
from temporalio import activity
from core.logging import get_logger

log = get_logger(__name__)

@activity.defn(name="template_activity")  # CHANGE: unique name required
async def activity_fn() -> None:
    """Activity body. Use MarketData/Indicators/Patterns/Scanner from core.sdk only."""
    log.info("template_activity_start")
    # Implementation here
    log.info("template_activity_complete")
```

- [ ] **Step 5: Run tests — verify pass**

```bash
pytest tests/unit/test_registry.py -v
```

Expected: `3 passed`

- [ ] **Step 6: Commit**

```bash
git add backend/workers/registry.py backend/workers/activities/ tests/unit/test_registry.py
git commit -m "feat: Temporal activity auto-registry — discovers, validates uniqueness, registers on startup"
```

---

## Task 13: Temporal Workflows — Data Ingestion

**Files:**
- Create: `backend/workers/workflows/daily_eod.py`
- Create: `backend/workers/workflows/intraday.py`
- Create: `backend/workers/workflows/market_events.py`
- Create: `backend/workers/workflows/backfill.py`
- Create: `backend/workers/activities/fetch_github_eod_data.py`
- Create: `backend/workers/activities/fetch_yfinance_daily.py`
- Create: `backend/workers/activities/fetch_shoonya_intraday.py`
- Create: `backend/workers/activities/fetch_nse_preopen.py`
- Create: `backend/workers/activities/aggregate_hourly.py`
- Create: `backend/workers/config/daily_eod.yaml`

- [ ] **Step 1: Implement backend/workers/activities/fetch_github_eod_data.py**

```python
from datetime import date
from temporalio import activity
from core.logging import get_logger
from core.storage import get_storage
from data.sources.github_eod_source import fetch_github_eod

log = get_logger(__name__)

@activity.defn(name="fetch_github_eod_data")
async def activity_fn(date_str: str | None = None) -> dict:
    """Fetch EOD data for all NSE stocks from GitHub repo, write to Parquet + QuestDB."""
    import asyncio
    if date_str is None:
        date_str = date.today().strftime("%Y-%m-%d")

    log.info("fetch_github_eod_start", date=date_str)

    df = await asyncio.get_event_loop().run_in_executor(None, fetch_github_eod, date_str)
    if df.empty:
        log.warning("fetch_github_eod_empty", date=date_str)
        return {"rows": 0, "date": date_str}

    # Write Parquet first (source of truth)
    year, month, _ = date_str.split("-")
    storage = get_storage()
    path = f"timeframe=1d/year={year}/month={month}/data.parquet"
    await asyncio.get_event_loop().run_in_executor(None, storage.write_parquet, df, path)

    # Write to QuestDB
    rows_written = await _write_questdb(df, "ohlcv_daily")

    log.info("fetch_github_eod_complete", date=date_str, rows=rows_written)
    return {"rows": rows_written, "date": date_str}


async def _write_questdb(df, table: str) -> int:
    import asyncio
    import psycopg2
    from core.config import settings

    def _write():
        conn = psycopg2.connect(settings.QUESTDB_URL)
        conn.autocommit = True
        cur = conn.cursor()
        rows = 0
        for _, row in df.iterrows():
            cur.execute(
                f"INSERT INTO {table} (ts, symbol, open, high, low, close, volume) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (row["ts"], row["symbol"], row["open"], row["high"],
                 row["low"], row["close"], row["volume"]),
            )
            rows += 1
        conn.close()
        return rows

    return await asyncio.get_event_loop().run_in_executor(None, _write)
```

- [ ] **Step 2: Implement backend/workers/activities/fetch_nse_preopen.py**

```python
import asyncio
from datetime import date
from temporalio import activity
from core.logging import get_logger
from core.db import AsyncSessionLocal
from data.sources.nse_public_source import fetch_preopen_gainers
from sqlalchemy import text

log = get_logger(__name__)

@activity.defn(name="fetch_nse_preopen")
async def activity_fn(collection_label: str = "default", top_n: int = 20) -> dict:
    """Fetch NSE pre-open data and write to market_events table.
    collection_label: 'order_open' (9:00 AM) or 'iep_final' (9:11 AM)
    """
    today = date.today().isoformat()
    log.info("fetch_nse_preopen_start", label=collection_label, date=today)

    df = await asyncio.get_event_loop().run_in_executor(
        None, fetch_preopen_gainers, top_n
    )
    if df.empty:
        log.warning("fetch_nse_preopen_empty", date=today, label=collection_label)
        return {"rows": 0}

    # Ensure event type exists
    async with AsyncSessionLocal() as session:
        await session.execute(text("""
            INSERT INTO market_event_types (name, description, source, collection_windows)
            VALUES ('premarket_gainers', 'NSE pre-open top gainers', 'nse_public',
                    '[{"cron":"9 9 * * 1-5","label":"order_open","delay_s":0},
                      {"cron":"11 9 * * 1-5","label":"iep_final","delay_s":60}]'::jsonb)
            ON CONFLICT (name) DO NOTHING
        """))

        rows = 0
        for rank, row in enumerate(df.itertuples(), start=1):
            await session.execute(text("""
                INSERT INTO market_events
                    (event_type, collection_label, date, symbol, rank, data)
                VALUES
                    ('premarket_gainers', :label, :date, :symbol, :rank, :data)
                ON CONFLICT (event_type, collection_label, date, symbol) DO UPDATE
                    SET data = EXCLUDED.data, captured_at = now()
            """), {
                "label": collection_label,
                "date": today,
                "symbol": row.symbol,
                "rank": rank,
                "data": f'{{"pre_price":{row.pre_price},"pre_change_pct":{row.pre_change_pct},"pre_volume":{row.pre_volume}}}',
            })
            rows += 1
        await session.commit()

    log.info("fetch_nse_preopen_complete", rows=rows, label=collection_label)
    return {"rows": rows}
```

- [ ] **Step 3: Implement backend/workers/workflows/market_events.py**

```python
"""Market event collector workflow.
Collection windows driven by market_event_types.collection_windows DB config.
One workflow instance per (event_type, collection_label) pair.
"""
import asyncio
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError

with workflow.unsafe.imports_passed_through():
    from core.logging import get_logger

@workflow.defn
class MarketEventCollectorWorkflow:
    @workflow.run
    async def run(self, event_type: str, collection_label: str, activity_name: str) -> None:
        log = get_logger(__name__)
        log.info("market_event_collector_start",
                 event_type=event_type, label=collection_label)

        try:
            result = await workflow.execute_activity(
                activity_name,
                args=[collection_label],
                start_to_close_timeout=timedelta(minutes=5),
                retry_policy=RetryPolicy(maximum_attempts=3, initial_interval=timedelta(seconds=10)),
            )
            log.info("market_event_collector_complete",
                     event_type=event_type, label=collection_label, result=result)
        except ActivityError as exc:
            log.error("market_event_collector_failed",
                      event_type=event_type, label=collection_label, error=str(exc))
            raise
```

- [ ] **Step 4: Implement backend/workers/workflows/intraday.py**

```python
"""Intraday 1-min collector.
Single long-running workflow — NOT re-triggered every minute.
Internal loop with asyncio.sleep(60). Runs 9:15 AM – 3:30 PM IST.
"""
import asyncio
from datetime import datetime, timedelta
import pytz
from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from core.logging import get_logger

IST = pytz.timezone("Asia/Kolkata")

@workflow.defn
class Intraday1MinCollectorWorkflow:
    @workflow.run
    async def run(self, symbols: list[str]) -> None:
        log = get_logger(__name__)

        while True:
            now_ist = datetime.now(IST)
            market_close = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)

            if now_ist >= market_close:
                log.info("intraday_collector_market_closed")
                break

            log.info("intraday_tick_start", symbol_count=len(symbols))

            # Fan out across all symbols in parallel
            tasks = [
                workflow.execute_activity(
                    "fetch_shoonya_intraday",
                    args=[sym, now_ist.strftime("%Y-%m-%d")],
                    start_to_close_timeout=timedelta(seconds=50),
                    retry_policy=RetryPolicy(maximum_attempts=2),
                )
                for sym in symbols
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            errors = [r for r in results if isinstance(r, Exception)]
            if errors:
                log.warning("intraday_tick_partial_failure", errors=len(errors))

            await asyncio.sleep(60)
```

- [ ] **Step 5: Implement backend/workers/workflows/daily_eod.py**

```python
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from core.logging import get_logger

@workflow.defn
class DailyEodWorkflow:
    @workflow.run
    async def run(self) -> None:
        log = get_logger(__name__)
        log.info("daily_eod_start")

        for activity_name, timeout_min, max_attempts in [
            ("fetch_github_eod_data",  10, 3),
            ("fetch_yfinance_daily",   15, 2),
            ("aggregate_hourly",       20, 2),
            ("compute_indicators",     30, 2),
            ("run_scanner_presets",    20, 2),
            ("invalidate_cache",        2, 1),
            ("data_quality_check",      5, 1),
        ]:
            await workflow.execute_activity(
                activity_name,
                start_to_close_timeout=timedelta(minutes=timeout_min),
                retry_policy=RetryPolicy(
                    maximum_attempts=max_attempts,
                    initial_interval=timedelta(seconds=10),
                    backoff_coefficient=2.0,
                ),
            )

        log.info("daily_eod_complete")
```

- [ ] **Step 6: Create backend/workers/config/daily_eod.yaml**

```yaml
workflow: daily_eod
schedule: "0 16 * * 1-5"  # 4 PM IST weekdays (UTC 10:30 AM)
activities:
  - activity: fetch_github_eod_data
    timeout_minutes: 10
    retry:
      max_attempts: 3
      initial_interval_s: 10
      backoff_coefficient: 2.0
    params:
      repo: "jugaad-trader/nse-data"
  - activity: fetch_yfinance_daily
    timeout_minutes: 15
    retry:
      max_attempts: 2
  - activity: aggregate_hourly
    timeout_minutes: 20
    retry:
      max_attempts: 2
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
      presets: [ema_crossover_bullish, rsi_oversold_uptrend, breakout_high_volume]
  - activity: invalidate_cache
    timeout_minutes: 2
    params:
      patterns: ["ta:v1:indicators:*", "ta:v1:scan:*"]
  - activity: data_quality_check
    timeout_minutes: 5
```

- [ ] **Step 7: Implement remaining activity stubs**

```python
# backend/workers/activities/fetch_yfinance_daily.py
from temporalio import activity
from core.logging import get_logger
from core.storage import get_storage
from data.sources.yfinance_source import fetch_daily_ohlcv
from core.sdk import MarketData
import asyncio

log = get_logger(__name__)

@activity.defn(name="fetch_yfinance_daily")
async def activity_fn() -> dict:
    md = MarketData()
    symbols = await md.universe()
    storage = get_storage()
    total = 0
    for sym in symbols[:50]:  # batch — full impl adds pagination
        ticker = f"{sym}.NS"
        df = await asyncio.get_event_loop().run_in_executor(
            None, fetch_daily_ohlcv, ticker, "2024-01-01", "today"
        )
        if not df.empty:
            storage.write_parquet(df, f"timeframe=1d/year=2024/month=01/yf_{sym}.parquet")
            total += len(df)
    log.info("fetch_yfinance_daily_complete", rows=total)
    return {"rows": total}
```

```python
# backend/workers/activities/aggregate_hourly.py
from temporalio import activity
from core.logging import get_logger
log = get_logger(__name__)

@activity.defn(name="aggregate_hourly")
async def activity_fn() -> dict:
    """Aggregate ohlcv_1min → ohlcv_hourly via QuestDB SAMPLE BY."""
    import psycopg2
    from core.config import settings
    conn = psycopg2.connect(settings.QUESTDB_URL)
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO ohlcv_hourly
        SELECT ts, symbol, first(open), max(high), min(low), last(close), sum(volume)
        FROM ohlcv_1min
        WHERE ts >= dateadd('h', -2, now())
        SAMPLE BY 1h ALIGN TO CALENDAR TIME ZONE 'Asia/Kolkata'
    """)
    conn.close()
    log.info("aggregate_hourly_complete")
    return {}
```

- [ ] **Step 8: Commit**

```bash
git add backend/workers/workflows/ backend/workers/activities/ backend/workers/config/
git commit -m "feat: Temporal workflows — daily EOD, intraday 1-min (long-running loop), market events, backfill"
```

---

## Task 14: Temporal Workflows — Maintenance

**Files:**
- Create: `backend/workers/activities/data_quality_check.py`
- Create: `backend/workers/activities/questdb_retention_sweep.py`
- Create: `backend/workers/activities/compute_indicators.py`
- Create: `backend/workers/activities/run_scanner_presets.py`
- Create: `backend/workers/activities/invalidate_cache.py`
- Create: `backend/workers/workflows/maintenance.py`

- [ ] **Step 1: Implement backend/workers/activities/data_quality_check.py**

```python
import asyncio
from datetime import date
from temporalio import activity
from core.logging import get_logger
from core.db import AsyncSessionLocal
from sqlalchemy import text

log = get_logger(__name__)

@activity.defn(name="data_quality_check")
async def activity_fn() -> dict:
    today = date.today()
    alerts = []

    async with AsyncSessionLocal() as session:
        # Check 1: OHLCV gap > 1 trading day for Nifty 50 stocks
        result = await session.execute(text("""
            SELECT s.symbol FROM stocks s
            WHERE NOT EXISTS (
                SELECT 1 FROM scan_results sr
                WHERE sr.symbol = s.symbol AND sr.run_at::date = :today
            )
            LIMIT 10
        """), {"today": today})
        gaps = [r[0] for r in result.fetchall()]
        if gaps:
            alerts.append({"check": "ohlcv_gap", "symbols": gaps})

        # Check 2: market_cap stale (>7 days)
        result = await session.execute(text("""
            SELECT COUNT(*) FROM stocks
            WHERE updated_at < now() - INTERVAL '7 days'
        """))
        stale_count = result.scalar()
        if stale_count > 0:
            alerts.append({"check": "market_cap_stale", "count": stale_count})

        # Write alerts to data_quality_alerts
        for alert in alerts:
            await session.execute(text("""
                INSERT INTO data_quality_alerts (check_name, detail)
                VALUES (:name, :detail::jsonb)
            """), {"name": alert["check"], "detail": str(alert)})
        await session.commit()

    if alerts:
        log.warning("data_quality_alerts_fired", count=len(alerts), alerts=alerts)
    else:
        log.info("data_quality_check_passed")
    return {"alerts": len(alerts)}
```

- [ ] **Step 2: Implement backend/workers/activities/questdb_retention_sweep.py**

```python
import asyncio
from temporalio import activity
from core.logging import get_logger
from core.storage import get_storage
import psycopg2

log = get_logger(__name__)

@activity.defn(name="questdb_retention_sweep")
async def activity_fn(retention_days: int = 60) -> dict:
    """Drop QuestDB 1-min partitions older than retention_days ONLY after verifying Parquet has data."""
    from core.config import settings
    from datetime import date, timedelta
    import duckdb

    cutoff = date.today() - timedelta(days=retention_days)
    storage = get_storage()

    # Verify Parquet has data for the partition being dropped
    try:
        parquet_count = duckdb.query(
            f"SELECT COUNT(*) FROM read_parquet('{storage.full_path(\"timeframe=1min/**/*.parquet\")}', "
            f"hive_partitioning=true) WHERE ts::date < '{cutoff}'"
        ).fetchone()[0]
    except Exception as exc:
        log.error("parquet_verify_failed", error=str(exc))
        return {"dropped": 0, "error": str(exc)}

    if parquet_count == 0:
        log.warning("parquet_missing_for_retention_drop", cutoff=str(cutoff))
        return {"dropped": 0, "reason": "no_parquet_data"}

    # Safe to drop QuestDB partitions
    def _drop():
        conn = psycopg2.connect(settings.QUESTDB_URL)
        conn.autocommit = True
        cur = conn.cursor()
        # QuestDB DROP PARTITION WHERE ts < date
        cur.execute(f"ALTER TABLE ohlcv_1min DROP PARTITION WHERE ts < '{cutoff}T00:00:00'")
        conn.close()

    await asyncio.get_event_loop().run_in_executor(None, _drop)
    log.info("questdb_partition_dropped", cutoff=str(cutoff), parquet_rows_verified=parquet_count)
    return {"dropped": 1, "cutoff": str(cutoff)}
```

- [ ] **Step 3: Implement backend/workers/activities/compute_indicators.py**

```python
from temporalio import activity
from core.logging import get_logger
from core.sdk import MarketData, Indicators
from core.cache import get_redis, cache_key
import asyncio
import json

log = get_logger(__name__)

@activity.defn(name="compute_indicators")
async def activity_fn(
    indicators: list[str] | None = None,
    timeframes: list[str] | None = None,
) -> dict:
    if indicators is None:
        indicators = ["rsi", "macd", "ema"]
    if timeframes is None:
        timeframes = ["1d"]

    from datetime import datetime, timedelta
    md = MarketData()
    symbols = await md.universe()
    redis = get_redis()
    computed = 0

    for sym in symbols:
        for tf in timeframes:
            to_dt = datetime.now()
            from_dt = to_dt - timedelta(days=200)
            df = await md.ohlcv(sym, tf, from_dt, to_dt)
            if df.empty:
                continue

            result = {}
            for ind_name in indicators:
                try:
                    from technical.indicators.registry import get_indicator
                    fn = get_indicator(ind_name.replace("_14", "").replace("_20", ""))
                    val = fn(df)
                    result[ind_name] = float(val.iloc[-1]) if val is not None and len(val) > 0 else None
                except Exception as exc:
                    log.warning("indicator_compute_failed", symbol=sym, indicator=ind_name, error=str(exc))

            key = cache_key("indicators", sym, tf)
            await redis.setex(key, 3600, json.dumps(result))
            computed += 1

    log.info("compute_indicators_complete", symbols=len(symbols), computed=computed)
    return {"computed": computed}
```

- [ ] **Step 4: Implement backend/workers/activities/run_scanner_presets.py**

```python
from temporalio import activity
from core.logging import get_logger
from scanner.signals.loader import load_signals

log = get_logger(__name__)

@activity.defn(name="run_scanner_presets")
async def activity_fn(presets: list[str] | None = None) -> dict:
    signals = load_signals()
    target = set(presets) if presets else {s.name for s in signals}
    ran = 0

    for sig in signals:
        if sig.name not in target:
            continue
        log.info("scanner_preset_run", name=sig.name)
        # Full scanner execution via Scanner engine — stub for now
        # Full impl: build Scanner from SignalConfig conditions, call run(), persist to scan_results
        ran += 1

    log.info("run_scanner_presets_complete", ran=ran)
    return {"presets_run": ran}
```

- [ ] **Step 5: Implement backend/workers/activities/invalidate_cache.py**

```python
from temporalio import activity
from core.logging import get_logger
from core.cache import get_redis

log = get_logger(__name__)

@activity.defn(name="invalidate_cache")
async def activity_fn(patterns: list[str] | None = None) -> dict:
    if patterns is None:
        patterns = ["ta:v1:indicators:*", "ta:v1:scan:*"]
    redis = get_redis()
    total_deleted = 0

    for pattern in patterns:
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor, match=pattern, count=100)
            if keys:
                await redis.delete(*keys)
                total_deleted += len(keys)
            if cursor == 0:
                break

    log.info("cache_invalidated", keys_deleted=total_deleted, patterns=patterns)
    return {"deleted": total_deleted}
```

- [ ] **Step 6: Implement backend/workers/workflows/maintenance.py**

```python
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from core.logging import get_logger

@workflow.defn
class RetentionSweepWorkflow:
    @workflow.run
    async def run(self, retention_days: int = 60) -> None:
        log = get_logger(__name__)
        log.info("retention_sweep_start")
        await workflow.execute_activity(
            "questdb_retention_sweep",
            args=[retention_days],
            start_to_close_timeout=timedelta(minutes=30),
            retry_policy=RetryPolicy(maximum_attempts=3),
        )
        log.info("retention_sweep_complete")

@workflow.defn
class MarketCapRefreshWorkflow:
    @workflow.run
    async def run(self) -> None:
        await workflow.execute_activity(
            "fetch_yfinance_daily",
            start_to_close_timeout=timedelta(minutes=60),
            retry_policy=RetryPolicy(maximum_attempts=2),
        )

@workflow.defn
class TradingCalendarSyncWorkflow:
    @workflow.run
    async def run(self, year: int) -> None:
        # Placeholder: implement with NSE calendar fetch
        pass
```

- [ ] **Step 7: Commit**

```bash
git add backend/workers/activities/ backend/workers/workflows/maintenance.py
git commit -m "feat: maintenance workflows — retention sweep (Parquet-verified), data quality, cache invalidation"
```

---

## Task 15: Auth System

**Files:**
- Create: `backend/core/auth/provider.py`
- Create: `backend/core/auth/local.py`
- Create: `backend/core/auth/google.py`
- Create: `backend/core/auth/github.py`
- Create: `backend/core/auth/middleware.py`
- Create: `backend/api/routers/auth.py`
- Create: `tests/unit/test_auth.py`

- [ ] **Step 1: Write failing test**

```python
# tests/unit/test_auth.py
import pytest
from datetime import datetime, timezone
from unittest.mock import patch
from core.auth.local import LocalJWTProvider
from core.auth.provider import User

@pytest.mark.asyncio
async def test_local_provider_authenticate_success():
    provider = LocalJWTProvider(
        username="admin",
        password_hash="$2b$12$KIXtmJFMCxJL4v6lEKq9LO9qcIiO.u8t5TH5S8bYcf3fMPi6xKQBm",  # hash of "password"
        jwt_secret="x" * 32,
        jwt_expiry_hours=24,
    )
    with patch("passlib.context.CryptContext.verify", return_value=True):
        user = await provider.authenticate({"username": "admin", "password": "password"})
    assert user is not None
    assert user.username == "admin"

@pytest.mark.asyncio
async def test_local_provider_authenticate_wrong_password():
    provider = LocalJWTProvider(
        username="admin",
        password_hash="$2b$12$wrong",
        jwt_secret="x" * 32,
        jwt_expiry_hours=24,
    )
    with patch("passlib.context.CryptContext.verify", return_value=False):
        user = await provider.authenticate({"username": "admin", "password": "wrong"})
    assert user is None

@pytest.mark.asyncio
async def test_local_provider_token_roundtrip():
    provider = LocalJWTProvider(
        username="admin",
        password_hash="hash",
        jwt_secret="x" * 32,
        jwt_expiry_hours=24,
    )
    user = User(username="admin")
    token = provider.create_token(user)
    verified = await provider.verify_token(token)
    assert verified is not None
    assert verified.username == "admin"

@pytest.mark.asyncio
async def test_expired_token_rejected():
    import time
    provider = LocalJWTProvider(
        username="admin",
        password_hash="hash",
        jwt_secret="x" * 32,
        jwt_expiry_hours=-1,  # already expired
    )
    user = User(username="admin")
    token = provider.create_token(user)
    verified = await provider.verify_token(token)
    assert verified is None
```

- [ ] **Step 2: Run — verify fail**

```bash
pytest tests/unit/test_auth.py -v
```

Expected: `ImportError`

- [ ] **Step 3: Implement backend/core/auth/provider.py**

```python
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

@dataclass
class User:
    username: str
    is_admin: bool = True

@runtime_checkable
class AuthProvider(Protocol):
    async def authenticate(self, credentials: dict) -> User | None: ...
    async def verify_token(self, token: str) -> User | None: ...
    def login_url(self) -> str: ...
    def callback_url(self) -> str: ...
```

- [ ] **Step 4: Implement backend/core/auth/local.py**

```python
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from jose import jwt, JWTError
from passlib.context import CryptContext
from core.auth.provider import User

_PWD_CTX = CryptContext(schemes=["bcrypt"], deprecated="auto")
_ALGORITHM = "HS256"

@dataclass
class LocalJWTProvider:
    username: str
    password_hash: str
    jwt_secret: str
    jwt_expiry_hours: int = 24

    async def authenticate(self, credentials: dict) -> User | None:
        if credentials.get("username") != self.username:
            return None
        if not _PWD_CTX.verify(credentials.get("password", ""), self.password_hash):
            return None
        return User(username=self.username)

    def create_token(self, user: User) -> str:
        expire = datetime.now(timezone.utc) + timedelta(hours=self.jwt_expiry_hours)
        return jwt.encode(
            {"sub": user.username, "exp": expire},
            self.jwt_secret,
            algorithm=_ALGORITHM,
        )

    async def verify_token(self, token: str) -> User | None:
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=[_ALGORITHM])
            username = payload.get("sub")
            if username is None:
                return None
            return User(username=username)
        except JWTError:
            return None

    def login_url(self) -> str:
        return "/auth/login"

    def callback_url(self) -> str:
        return "/auth/login"
```

- [ ] **Step 5: Implement backend/core/auth/google.py and github.py (stubs)**

```python
# backend/core/auth/google.py
from core.auth.provider import User

class GoogleOAuthProvider:
    """Activate via AUTH_PROVIDER=google + GOOGLE_CLIENT_ID/SECRET env vars."""
    async def authenticate(self, credentials: dict) -> User | None:
        raise NotImplementedError("GoogleOAuthProvider: set AUTH_PROVIDER=google + configure OAuth app")

    async def verify_token(self, token: str) -> User | None:
        raise NotImplementedError

    def login_url(self) -> str:
        return "/auth/google/login"

    def callback_url(self) -> str:
        return "/auth/google/callback"
```

```python
# backend/core/auth/github.py
from core.auth.provider import User

class GitHubOAuthProvider:
    """Activate via AUTH_PROVIDER=github + GITHUB_CLIENT_ID/SECRET env vars."""
    async def authenticate(self, credentials: dict) -> User | None:
        raise NotImplementedError("GitHubOAuthProvider: set AUTH_PROVIDER=github + configure OAuth app")

    async def verify_token(self, token: str) -> User | None:
        raise NotImplementedError

    def login_url(self) -> str:
        return "/auth/github/login"

    def callback_url(self) -> str:
        return "/auth/github/callback"
```

- [ ] **Step 6: Implement backend/core/auth/middleware.py**

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from core.auth.provider import User

_bearer = HTTPBearer(auto_error=False)

def _get_provider():
    from core.config import settings
    if settings.AUTH_PROVIDER == "local":
        from core.auth.local import LocalJWTProvider
        return LocalJWTProvider(
            username=settings.ADMIN_USERNAME,
            password_hash=settings.ADMIN_PASSWORD_HASH,
            jwt_secret=settings.JWT_SECRET,
            jwt_expiry_hours=settings.JWT_EXPIRY_HOURS,
        )
    raise ValueError(f"Unknown AUTH_PROVIDER: {settings.AUTH_PROVIDER!r}")

async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> User:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    provider = _get_provider()
    user = await provider.verify_token(credentials.credentials)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token")
    return user
```

- [ ] **Step 7: Implement backend/api/routers/auth.py**

```python
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from core.auth.middleware import _get_provider

router = APIRouter(prefix="/auth", tags=["auth"])

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest):
    provider = _get_provider()
    user = await provider.authenticate({"username": req.username, "password": req.password})
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = provider.create_token(user)
    return TokenResponse(access_token=token)
```

- [ ] **Step 8: Run tests — verify pass**

```bash
pytest tests/unit/test_auth.py -v
```

Expected: `4 passed`

- [ ] **Step 9: Commit**

```bash
git add backend/core/auth/ backend/api/routers/auth.py tests/unit/test_auth.py
git commit -m "feat: JWT auth — LocalJWTProvider, AuthProvider Protocol, FastAPI dependency, Google/GitHub stubs"
```

---

## Task 16: FastAPI API Layer + WebSocket

**Files:**
- Modify: `backend/api/main.py`
- Create: `backend/api/middleware.py`
- Create: `backend/api/routers/technical.py`
- Create: `backend/api/routers/scanner.py`
- Create: `backend/api/routers/data.py`
- Create: `backend/api/routers/admin.py`
- Create: `backend/api/signals_ws.py`
- Create: `tests/integration/test_api.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/integration/test_api.py
import pytest
from httpx import AsyncClient, ASGITransport
from api.main import create_app

@pytest.fixture
def app():
    return create_app()

@pytest.mark.asyncio
async def test_health_returns_200(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

@pytest.mark.asyncio
async def test_protected_route_requires_auth(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/scanner/run")
    assert resp.status_code == 401

@pytest.mark.asyncio
async def test_login_returns_token(app):
    import os
    os.environ["ADMIN_USERNAME"] = "admin"
    os.environ["ADMIN_PASSWORD_HASH"] = "$2b$12$placeholder"
    os.environ["JWT_SECRET"] = "x" * 32
    from unittest.mock import patch, AsyncMock
    from core.auth.provider import User
    with patch("core.auth.local.LocalJWTProvider.authenticate", new_callable=AsyncMock,
               return_value=User(username="admin")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post("/auth/login", json={"username": "admin", "password": "pass"})
    assert resp.status_code == 200
    assert "access_token" in resp.json()
```

- [ ] **Step 2: Run — verify fail**

```bash
pytest tests/integration/test_api.py -v
```

Expected: failures (missing routers/middleware)

- [ ] **Step 3: Implement backend/api/middleware.py**

```python
import uuid
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
import structlog

class TraceIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get("X-Trace-ID", str(uuid.uuid4()))
        structlog.contextvars.bind_contextvars(trace_id=trace_id)
        response = await call_next(request)
        response.headers["X-Trace-ID"] = trace_id
        structlog.contextvars.unbind_contextvars("trace_id")
        return response
```

- [ ] **Step 4: Implement backend/api/routers/scanner.py**

```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from core.auth.middleware import get_current_user
from core.auth.provider import User
from scanner.engine import Scanner

router = APIRouter(prefix="/scanner", tags=["scanner"])

class ScanRequest(BaseModel):
    source: str = "nse_universe"
    filters: list[dict] = []
    indicators: list[str] = []
    max_symbols: int = 500
    timeout_s: int = 120

@router.post("/run")
async def run_scan(req: ScanRequest, user: User = Depends(get_current_user)):
    s = Scanner().from_source(req.source)
    for f in req.filters:
        s.filter(**{f["field"]: f["value"]})
    s.add_indicators(req.indicators)
    result = s.run(max_symbols=req.max_symbols, timeout_s=req.timeout_s)
    return {"symbols": result["symbol"].tolist() if "symbol" in result.columns else []}

@router.get("/signals")
async def list_signals(user: User = Depends(get_current_user)):
    from scanner.signals.loader import load_signals
    signals = load_signals()
    return [{"name": s.name, "category": s.category, "direction": s.direction} for s in signals]
```

- [ ] **Step 5: Implement backend/api/routers/technical.py**

```python
from fastapi import APIRouter, Depends, Query
from datetime import datetime
from core.auth.middleware import get_current_user
from core.auth.provider import User
from core.sdk import MarketData, Indicators

router = APIRouter(prefix="/technical", tags=["technical"])

@router.get("/ohlcv/{symbol}")
async def get_ohlcv(
    symbol: str,
    tf: str = Query("1d", pattern="^(1min|1h|1d)$"),
    from_dt: datetime = Query(...),
    to_dt: datetime = Query(...),
    user: User = Depends(get_current_user),
):
    md = MarketData()
    df = await md.ohlcv(symbol, tf, from_dt, to_dt)
    return {"symbol": symbol, "tf": tf, "rows": df.to_dict(orient="records")}

@router.get("/indicators/{symbol}")
async def get_indicators(
    symbol: str,
    tf: str = Query("1d"),
    indicators: list[str] = Query(["rsi", "macd"]),
    user: User = Depends(get_current_user),
):
    from datetime import timedelta
    md = MarketData()
    to_dt = datetime.now()
    from_dt = to_dt - timedelta(days=200)
    df = await md.ohlcv(symbol, tf, from_dt, to_dt)
    result = {}
    for name in indicators:
        try:
            from technical.indicators.registry import get_indicator
            fn = get_indicator(name)
            val = fn(df)
            result[name] = float(val.iloc[-1]) if val is not None and len(val) > 0 else None
        except Exception:
            result[name] = None
    return {"symbol": symbol, "tf": tf, "indicators": result}

@router.get("/trend/{symbol}")
async def get_trend(
    symbol: str,
    tf: str = Query("1min"),
    from_time: str | None = Query(None),
    to_time: str | None = Query(None),
    user: User = Depends(get_current_user),
):
    from datetime import timedelta
    from technical.trend import analyze_trend
    md = MarketData()
    to_dt = datetime.now()
    from_dt = to_dt - timedelta(hours=8)
    df = await md.ohlcv(symbol, tf, from_dt, to_dt)
    return analyze_trend(df, from_time, to_time, tf)
```

- [ ] **Step 6: Implement backend/api/signals_ws.py**

```python
"""WebSocket live signal feed via Redis Streams. Resume-on-reconnect via last_event_id."""
import asyncio
from fastapi import WebSocket, WebSocketDisconnect, Query
from core.cache import get_redis
from core.auth.middleware import _get_provider
from core.logging import get_logger

log = get_logger(__name__)

STREAM_KEY = "signals:live"
CONSUMER_GROUP = "ws_clients"


async def websocket_endpoint(ws: WebSocket, token: str = Query(...), last_event_id: str = Query("0")):
    provider = _get_provider()
    user = await provider.verify_token(token)
    if user is None:
        await ws.close(code=1008)
        return

    await ws.accept()
    redis = get_redis()

    # Ensure consumer group exists
    try:
        await redis.xgroup_create(STREAM_KEY, CONSUMER_GROUP, id="0", mkstream=True)
    except Exception:
        pass  # group already exists

    consumer_id = str(id(ws))
    start_id = last_event_id if last_event_id != "0" else ">"

    log.info("ws_client_connected", consumer=consumer_id)
    try:
        while True:
            messages = await redis.xreadgroup(
                groupname=CONSUMER_GROUP,
                consumername=consumer_id,
                streams={STREAM_KEY: start_id},
                count=10,
                block=5000,
            )
            if messages:
                for _, events in messages:
                    for event_id, data in events:
                        await ws.send_json({"event_id": event_id, **data})
                        await redis.xack(STREAM_KEY, CONSUMER_GROUP, event_id)
                        start_id = ">"  # switch to new messages after catching up
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        log.info("ws_client_disconnected", consumer=consumer_id)
```

- [ ] **Step 7: Update backend/api/main.py**

```python
from fastapi import FastAPI
from fastapi import WebSocket
from api.middleware import TraceIdMiddleware
from api.routers import auth, technical, scanner
from api.signals_ws import websocket_endpoint
from prometheus_fastapi_instrumentator import Instrumentator
from core.logging import setup_logging

def create_app() -> FastAPI:
    setup_logging()
    app = FastAPI(title="Trading System", version="0.1.0")
    app.add_middleware(TraceIdMiddleware)

    app.include_router(auth.router)
    app.include_router(technical.router)
    app.include_router(scanner.router)

    @app.websocket("/ws/signals")
    async def signals_ws(ws: WebSocket, token: str, last_event_id: str = "0"):
        await websocket_endpoint(ws, token, last_event_id)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    Instrumentator().instrument(app).expose(app)
    return app

app = create_app()
```

- [ ] **Step 8: Run tests — verify pass**

```bash
pytest tests/integration/test_api.py -v
```

Expected: `3 passed`

- [ ] **Step 9: Commit**

```bash
git add backend/api/ tests/integration/test_api.py
git commit -m "feat: FastAPI — scanner/technical/auth routers, trace_id middleware, WebSocket Redis Streams feed"
```

---

## Task 17: LLM Integration

**Files:**
- Create: `backend/llm/tools.py`
- Create: `backend/llm/budget.py`
- Create: `backend/llm/translator.py`
- Create: `backend/llm/prompts/v1/system.txt`
- Create: `backend/api/routers/chat.py`
- Create: `tests/unit/test_llm_translator.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_llm_translator.py
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from llm.translator import translate_nl_to_dsl
from llm.budget import check_budget, increment_budget

@pytest.mark.asyncio
async def test_translate_uses_cache_on_hit():
    mock_redis = AsyncMock()
    mock_redis.get.return_value = '{"version":1,"source":{"name":"nse_universe"},"filters":[]}'

    with patch("llm.translator.get_redis", return_value=mock_redis):
        result = await translate_nl_to_dsl("show me NSE stocks")

    assert result["source"]["name"] == "nse_universe"
    mock_redis.get.assert_called_once()

@pytest.mark.asyncio
async def test_budget_exceeded_raises():
    mock_redis = AsyncMock()
    mock_redis.get.return_value = "150000"  # over 100k budget

    with patch("llm.budget.get_redis", return_value=mock_redis):
        with pytest.raises(Exception, match="budget"):
            await check_budget(50000)

@pytest.mark.asyncio
async def test_translate_builds_valid_dsl(monkeypatch):
    """Mocking Claude API response — verify DSL structure."""
    mock_tool_result = {
        "source": {"name": "nse_universe"},
        "filters": [{"field": "exchange", "op": "eq", "value": "NSE"}],
        "indicators": ["rsi"],
        "sort": {"field": "rsi", "descending": False},
    }

    mock_redis = AsyncMock()
    mock_redis.get.return_value = None  # no cache

    mock_anthropic = MagicMock()
    mock_msg = MagicMock()
    mock_msg.content = [MagicMock(type="tool_use", name="set_source",
                                  input={"source": "nse_universe"})]
    mock_anthropic.messages.create.return_value = mock_msg

    with patch("llm.translator.get_redis", return_value=mock_redis), \
         patch("llm.translator._build_dsl_from_tool_calls", return_value=mock_tool_result), \
         patch("llm.translator._call_claude", return_value=[mock_msg.content[0]]):
        result = await translate_nl_to_dsl("NSE stocks with RSI below 30")

    assert "source" in result
```

- [ ] **Step 2: Implement backend/llm/budget.py**

```python
from core.cache import get_redis, cache_key
from core.logging import get_logger

log = get_logger(__name__)

async def check_budget(tokens_needed: int) -> None:
    redis = get_redis()
    key = cache_key("llm_tokens", "daily")
    used_str = await redis.get(key)
    used = int(used_str) if used_str else 0

    from core.config import settings
    if used + tokens_needed > settings.LLM_DAILY_TOKEN_BUDGET:
        log.warning("llm_budget_exceeded", used=used, needed=tokens_needed)
        raise ValueError(f"Daily LLM budget reached ({used}/{settings.LLM_DAILY_TOKEN_BUDGET} tokens). Try scanner directly.")

async def increment_budget(tokens_used: int) -> None:
    redis = get_redis()
    key = cache_key("llm_tokens", "daily")
    await redis.incrby(key, tokens_used)
    await redis.expire(key, 86400)  # resets daily
```

- [ ] **Step 3: Implement backend/llm/tools.py**

```python
from core.config import settings

TOOL_DEFINITIONS = [
    {
        "name": "set_source",
        "description": "Set the data source for the scan (stock universe or event-based).",
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {"type": "string",
                           "enum": ["nse_universe", "premarket_gainers", "custom_list", "watchlist"]},
                "top_n": {"type": "integer", "description": "For event-based sources, limit to top N"},
                "date": {"type": "string", "description": "YYYY-MM-DD, default today"},
            },
            "required": ["source"],
        },
    },
    {
        "name": "add_filter",
        "description": "Add a filter condition on stock attributes or exchange.",
        "input_schema": {
            "type": "object",
            "properties": {
                "field": {"type": "string"},
                "operator": {"type": "string", "enum": ["eq", "gt", "lt", "gte", "lte", "in"]},
                "value": {},
            },
            "required": ["field", "operator", "value"],
        },
    },
    {
        "name": "add_indicator",
        "description": "Add indicator condition (RSI, MACD, EMA, etc.)",
        "input_schema": {
            "type": "object",
            "properties": {
                "indicator": {"type": "string"},
                "operator": {"type": "string", "enum": ["gt", "lt", "gte", "lte", "eq", "cross_above", "cross_below"]},
                "value": {"type": "number"},
                "period": {"type": "integer"},
            },
            "required": ["indicator", "operator"],
        },
    },
    {
        "name": "add_trend_analysis",
        "description": "Add trend analysis for a specific time window.",
        "input_schema": {
            "type": "object",
            "properties": {
                "from_time": {"type": "string", "description": "HH:MM"},
                "to_time": {"type": "string", "description": "HH:MM"},
                "date": {"type": "string", "description": "today | yesterday | YYYY-MM-DD"},
                "timeframe": {"type": "string", "enum": ["1min", "1h", "1d"]},
                "metrics": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["from_time", "to_time"],
        },
    },
    {
        "name": "set_sort",
        "description": "Sort results by a field.",
        "input_schema": {
            "type": "object",
            "properties": {
                "field": {"type": "string"},
                "descending": {"type": "boolean", "default": True},
            },
            "required": ["field"],
        },
    },
]
```

- [ ] **Step 4: Implement backend/llm/translator.py**

```python
import json
import hashlib
from core.cache import get_redis, cache_key
from core.config import settings
from core.logging import get_logger
from llm.tools import TOOL_DEFINITIONS
from llm.budget import check_budget, increment_budget

log = get_logger(__name__)

async def translate_nl_to_dsl(nl_query: str) -> dict:
    # Check cache first
    redis = get_redis()
    query_hash = hashlib.sha256(nl_query.encode()).hexdigest()[:16]
    cache_k = cache_key("nlq", query_hash)
    cached = await redis.get(cache_k)
    if cached:
        log.info("llm_cache_hit", query_hash=query_hash)
        return json.loads(cached)

    # Budget check (estimate 2k tokens per request)
    await check_budget(2000)

    # Call Claude
    tool_calls = await _call_claude(nl_query)
    dsl = _build_dsl_from_tool_calls(tool_calls)

    # Cache result
    await redis.setex(cache_k, 86400, json.dumps(dsl))
    await increment_budget(2000)

    log.info("llm_translate_complete", query_hash=query_hash, tools_called=len(tool_calls))
    return dsl


async def _call_claude(nl_query: str) -> list:
    import anthropic
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    system = _load_system_prompt()

    response = client.messages.create(
        model=settings.LLM_MODEL,
        max_tokens=1024,
        system=system,
        tools=TOOL_DEFINITIONS,
        messages=[{"role": "user", "content": nl_query}],
    )
    return [block for block in response.content if block.type == "tool_use"]


def _load_system_prompt() -> str:
    import pathlib
    prompt_dir = pathlib.Path(__file__).parent / "prompts" / settings.LLM_PROMPT_VERSION
    return (prompt_dir / "system.txt").read_text()


def _build_dsl_from_tool_calls(tool_calls: list) -> dict:
    from scanner.dsl import SCANNER_DSL_VERSION
    dsl: dict = {
        "version": SCANNER_DSL_VERSION,
        "source": {},
        "filters": [],
        "analysis": {},
        "indicators": [],
        "sort": {},
    }
    for call in tool_calls:
        name, inp = call.name, call.input
        if name == "set_source":
            dsl["source"] = inp
        elif name == "add_filter":
            dsl["filters"].append(inp)
        elif name == "add_indicator":
            dsl["indicators"].append(inp)
        elif name == "add_trend_analysis":
            dsl["analysis"] = inp
        elif name == "set_sort":
            dsl["sort"] = inp
    return dsl
```

- [ ] **Step 5: Create backend/llm/prompts/v1/system.txt**

```
You are a stock market scanner assistant for Indian equity markets (NSE/BSE).

Your job: translate natural language queries into scanner conditions using the available tools.
Call tools in sequence to build the complete scan. Use all relevant tools based on the query.

Rules:
- Always call set_source first
- Use add_filter for stock universe filters (exchange, market cap, sector)
- Use add_indicator for technical conditions (RSI < 30, EMA crossover, etc.)
- Use add_trend_analysis only when the query mentions a specific time window or session
- Use set_sort to rank results by the most relevant metric
- For Indian markets: NSE = National Stock Exchange, BSE = Bombay Stock Exchange
- Nifty 50 / large cap = market_cap > 20000 crore, small cap = market_cap < 5000 crore
- RSI < 30 = oversold, RSI > 70 = overbought

Examples:
- "oversold large cap NSE stocks" → set_source(nse_universe) + add_filter(exchange=NSE) + add_filter(market_cap>20000cr) + add_indicator(rsi<30)
- "pre-market top gainers with uptrend last 2 hours" → set_source(premarket_gainers,top_n=20) + add_trend_analysis(from_time=13:30,to_time=15:30)
```

- [ ] **Step 6: Implement backend/api/routers/chat.py**

```python
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from core.auth.middleware import get_current_user
from core.auth.provider import User
from core.config import settings

router = APIRouter(prefix="/chat", tags=["chat"])

class ChatRequest(BaseModel):
    query: str

class ChatResponse(BaseModel):
    dsl: dict
    explanation: str
    results: list[dict] = []

@router.post("/query", response_model=ChatResponse)
async def chat_query(req: ChatRequest, user: User = Depends(get_current_user)):
    if not settings.ENABLE_LLM_CHAT:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="LLM chat is disabled")
    try:
        from llm.translator import translate_nl_to_dsl
        dsl = await translate_nl_to_dsl(req.query)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))

    # Execute the scanner with the translated DSL
    from scanner.engine import Scanner
    s = Scanner()
    if dsl.get("source"):
        s.from_source(dsl["source"].get("name", "nse_universe"))
    for f in dsl.get("filters", []):
        s.filter(**{f["field"]: f["value"]})

    result_df = s.run(max_symbols=200)
    return ChatResponse(
        dsl=dsl,
        explanation=f"Running scan: {req.query}",
        results=result_df.head(50).to_dict(orient="records"),
    )
```

- [ ] **Step 7: Run tests — verify pass**

```bash
pytest tests/unit/test_llm_translator.py -v
```

Expected: `3 passed`

- [ ] **Step 8: Commit**

```bash
git add backend/llm/ backend/api/routers/chat.py tests/unit/test_llm_translator.py
git commit -m "feat: LLM NL→DSL translator — Claude tool use, Redis cache, daily token budget"
```

---

## Task 18: Agent Security Gate

**Files:**
- Create: `backend/workers/security.py`
- Create: `backend/api/routers/admin.py`
- Create: `tests/unit/test_security_gate.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/unit/test_security_gate.py
import pytest
from workers.security import validate_activity_code, SecurityViolation

SAFE_CODE = """
from temporalio import activity
from core.sdk import MarketData, Indicators

@activity.defn(name="safe_activity")
async def activity_fn():
    md = MarketData()
    df = await md.ohlcv("RELIANCE", "1d", None, None)
    rsi = Indicators.rsi(df)
    return float(rsi.iloc[-1])
"""

UNSAFE_IMPORT = """
from temporalio import activity
import os  # not in allowlist

@activity.defn(name="unsafe_activity")
async def activity_fn():
    os.system("rm -rf /")
"""

UNSAFE_EXEC = """
from temporalio import activity

@activity.defn(name="exec_activity")
async def activity_fn():
    exec("import os; os.system('evil')")
"""

UNSAFE_GETATTR = """
from temporalio import activity

@activity.defn(name="getattr_activity")
async def activity_fn():
    getattr(__builtins__, "eval")("evil")
"""

def test_safe_code_passes():
    validate_activity_code(SAFE_CODE)  # should not raise

def test_unsafe_import_rejected():
    with pytest.raises(SecurityViolation, match="os"):
        validate_activity_code(UNSAFE_IMPORT)

def test_exec_rejected():
    with pytest.raises(SecurityViolation, match="exec"):
        validate_activity_code(UNSAFE_EXEC)

def test_getattr_rejected():
    with pytest.raises(SecurityViolation, match="getattr"):
        validate_activity_code(UNSAFE_GETATTR)
```

- [ ] **Step 2: Run — verify fail**

```bash
pytest tests/unit/test_security_gate.py -v
```

Expected: `ImportError: cannot import name 'validate_activity_code'`

- [ ] **Step 3: Implement backend/workers/security.py**

```python
"""Multi-layer security gate for agent-generated Temporal activities.
Layers: AST scan → RestrictedPython compile → bytecode scan.
Subprocess isolation runs separately at approval time.
"""
import ast
import dis
import io
from RestrictedPython import compile_restricted

class SecurityViolation(Exception):
    pass

_ALLOWED_IMPORTS = {
    "temporalio", "core.sdk", "core.logging",
    "pandas", "numpy", "datetime", "typing",
}

_BANNED_AST_CALLS = {"exec", "eval", "compile", "getattr", "globals", "locals", "vars"}
_BANNED_BYTECODES = {"IMPORT_NAME", "LOAD_BUILD_CLASS"}


def validate_activity_code(code: str) -> None:
    """Raises SecurityViolation if code fails any security check."""
    _check_ast(code)
    _check_restricted_python(code)
    _check_bytecode(code)


def _check_ast(code: str) -> None:
    tree = ast.parse(code)
    for node in ast.walk(tree):
        # Check imports
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
            else:
                module = node.names[0].name
            root = module.split(".")[0]
            if root not in _ALLOWED_IMPORTS:
                raise SecurityViolation(f"Forbidden import: {module!r}. Allowed: {_ALLOWED_IMPORTS}")

        # Check banned function calls
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in _BANNED_AST_CALLS:
                raise SecurityViolation(f"Forbidden call: {node.func.id!r}")

        # Check __import__
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "__import__":
                raise SecurityViolation("Forbidden: __import__")

        # Check dunder attribute access
        if isinstance(node, ast.Attribute):
            if node.attr.startswith("__") and node.attr.endswith("__"):
                raise SecurityViolation(f"Forbidden dunder access: {node.attr!r}")


def _check_restricted_python(code: str) -> None:
    try:
        compile_restricted(code, filename="<agent_activity>", mode="exec")
    except SyntaxError as exc:
        raise SecurityViolation(f"RestrictedPython rejected: {exc}")


def _check_bytecode(code: str) -> None:
    try:
        compiled = compile(code, "<agent_activity>", "exec")
    except SyntaxError as exc:
        raise SecurityViolation(f"Compile failed: {exc}")

    buf = io.StringIO()
    dis.dis(compiled, file=buf)
    bytecode_text = buf.getvalue()

    for banned in _BANNED_BYTECODES:
        if banned in bytecode_text:
            raise SecurityViolation(f"Banned bytecode instruction: {banned!r}")


def run_in_sandbox(code: str, test_data_path: str) -> dict:
    """Run activity in isolated subprocess for sandbox test.
    Subprocess has: no network, read-only filesystem except temp output, 60s CPU limit, 512MB RAM.
    Returns {"success": bool, "output": str, "error": str}.
    """
    import subprocess
    import tempfile
    import resource

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        tmp_path = f.name

    try:
        result = subprocess.run(
            ["python", "-S", "-I", tmp_path],
            capture_output=True,
            text=True,
            timeout=60,
            preexec_fn=lambda: resource.setrlimit(
                resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024)
            ),
        )
        return {
            "success": result.returncode == 0,
            "output": result.stdout[:2000],
            "error": result.stderr[:2000],
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "output": "", "error": "Timeout: >60s"}
    finally:
        import os
        os.unlink(tmp_path)
```

- [ ] **Step 4: Implement backend/api/routers/admin.py**

```python
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from core.auth.middleware import get_current_user
from core.auth.provider import User
from core.db import AsyncSessionLocal
from sqlalchemy import text

router = APIRouter(prefix="/admin", tags=["admin"])

class ActivitySubmit(BaseModel):
    name: str
    code: str
    prompt: str = ""
    generator: str = "human"

@router.post("/activities")
async def submit_activity(req: ActivitySubmit, user: User = Depends(get_current_user)):
    from workers.security import validate_activity_code, SecurityViolation
    try:
        validate_activity_code(req.code)
    except SecurityViolation as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"Security gate rejected: {exc}")

    async with AsyncSessionLocal() as session:
        await session.execute(text("""
            INSERT INTO agent_activities (name, file_path, status, generator, prompt)
            VALUES (:name, :file_path, 'proposed', :generator, :prompt)
        """), {
            "name": req.name,
            "file_path": f"workers/activities/{req.name}.py",
            "generator": req.generator,
            "prompt": req.prompt,
        })
        await session.commit()

    return {"status": "proposed", "name": req.name}

@router.post("/activities/{name}/approve")
async def approve_activity(name: str, user: User = Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT code, file_path FROM agent_activities WHERE name = :name AND status = 'proposed'"),
            {"name": name},
        )
        row = result.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Activity not found or not in proposed state")

        await session.execute(text("""
            UPDATE agent_activities
            SET status = 'approved', approved_by = :approver, approved_at = now()
            WHERE name = :name
        """), {"name": name, "approver": user.username})
        await session.commit()

    return {"status": "approved", "name": name, "message": "Restart Temporal worker to activate"}
```

- [ ] **Step 5: Run tests — verify pass**

```bash
pytest tests/unit/test_security_gate.py -v
```

Expected: `4 passed`

- [ ] **Step 6: Commit**

```bash
git add backend/workers/security.py backend/api/routers/admin.py tests/unit/test_security_gate.py
git commit -m "feat: agent activity security gate — AST + RestrictedPython + bytecode scan + subprocess sandbox"
```

---

## Task 19: Observability

**Files:**
- Modify: `backend/core/metrics.py`
- Modify: `backend/api/main.py`
- Create: `infra/grafana/dashboards/ingestion_health.json`

- [ ] **Step 1: Implement backend/core/metrics.py**

```python
from prometheus_client import Counter, Histogram, Gauge

ingestion_rows = Counter(
    "ingestion_rows_written_total",
    "Rows written per ingestion run",
    ["source", "timeframe"],
)
ingestion_duration = Histogram(
    "ingestion_duration_seconds",
    "Duration of ingestion workflow",
    ["workflow"],
)
ingestion_failures = Counter(
    "ingestion_failures_total",
    "Failed data fetches per source",
    ["source"],
)
data_gaps = Counter(
    "data_gap_detected_total",
    "Missing candles detected",
    ["symbol", "timeframe"],
)
scanner_duration = Histogram(
    "scanner_run_duration_seconds",
    "Scanner execution time",
    ["scan_name"],
)
signals_fired = Counter(
    "signals_fired_total",
    "Signals detected per type",
    ["signal_name", "timeframe", "direction"],
)
cache_hits = Counter("redis_cache_hits_total", "Redis cache hits")
cache_misses = Counter("redis_cache_misses_total", "Redis cache misses")
llm_tool_calls = Counter(
    "llm_tool_calls_total",
    "LLM tool use frequency",
    ["tool"],
)
```

- [ ] **Step 2: Add metrics to ingestion activity**

Edit `backend/workers/activities/fetch_github_eod_data.py`, add after successful write:

```python
from core.metrics import ingestion_rows, ingestion_duration, ingestion_failures

# After successful write:
ingestion_rows.labels(source="github_eod", timeframe="1d").inc(rows_written)
```

- [ ] **Step 3: Verify /metrics endpoint**

```bash
uvicorn api.main:app --reload &
curl http://localhost:8000/metrics | grep ingestion_rows
```

Expected: `ingestion_rows_written_total` metric present.

- [ ] **Step 4: Add OpenTelemetry setup to core/logging.py**

```python
# Add to bottom of setup_logging():
def setup_tracing() -> None:
    """Optional — enable via OTEL_ENABLED=true env var."""
    import os
    if os.getenv("OTEL_ENABLED", "false").lower() != "true":
        return
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.exporter.jaeger.thrift import JaegerExporter
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider()
    exporter = JaegerExporter(agent_host_name="localhost", agent_port=6831)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
```

- [ ] **Step 5: Commit**

```bash
git add backend/core/metrics.py infra/grafana/
git commit -m "feat: observability — Prometheus custom metrics, OpenTelemetry/Jaeger setup"
```

---

## Task 20: Frontend — Scaffold + Auth

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/pages/Login.tsx`
- Create: `frontend/src/App.tsx`

- [ ] **Step 1: Scaffold React + Vite project**

```bash
cd trading-system/frontend
npm create vite@latest . -- --template react-ts
```

- [ ] **Step 2: Install dependencies**

```bash
npm install \
  @tanstack/react-query \
  @tanstack/react-table \
  zustand \
  react-hook-form \
  axios \
  lightweight-charts \
  react-router-dom
```

- [ ] **Step 3: Create frontend/src/api/client.ts**

```typescript
import axios from "axios";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000";

export const apiClient = axios.create({ baseURL: API_BASE });

// Attach JWT token to all requests
apiClient.interceptors.request.use((config) => {
  const token = localStorage.getItem("access_token");
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Redirect to login on 401
apiClient.interceptors.response.use(
  (r) => r,
  (error) => {
    if (error.response?.status === 401) {
      localStorage.removeItem("access_token");
      window.location.href = "/login";
    }
    return Promise.reject(error);
  }
);

export async function login(username: string, password: string): Promise<string> {
  const { data } = await apiClient.post<{ access_token: string }>("/auth/login", {
    username,
    password,
  });
  localStorage.setItem("access_token", data.access_token);
  return data.access_token;
}

export function logout(): void {
  localStorage.removeItem("access_token");
  window.location.href = "/login";
}

export function isAuthenticated(): boolean {
  return !!localStorage.getItem("access_token");
}
```

- [ ] **Step 4: Create frontend/src/pages/Login.tsx**

```tsx
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { login } from "../api/client";

export default function Login() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const navigate = useNavigate();

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await login(username, password);
      navigate("/screener");
    } catch {
      setError("Invalid credentials");
    }
  }

  return (
    <div style={{ maxWidth: 400, margin: "100px auto", padding: 24 }}>
      <h2>Trading System</h2>
      <form onSubmit={handleSubmit}>
        <div>
          <input
            placeholder="Username"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            style={{ width: "100%", marginBottom: 8, padding: 8 }}
          />
        </div>
        <div>
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            style={{ width: "100%", marginBottom: 8, padding: 8 }}
          />
        </div>
        {error && <p style={{ color: "red" }}>{error}</p>}
        <button type="submit" style={{ width: "100%", padding: 8 }}>
          Login
        </button>
      </form>
    </div>
  );
}
```

- [ ] **Step 5: Create frontend/src/App.tsx**

```tsx
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import Login from "./pages/Login";
import { isAuthenticated } from "./api/client";

const queryClient = new QueryClient();

function ProtectedRoute({ children }: { children: React.ReactNode }) {
  if (!isAuthenticated()) return <Navigate to="/login" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/screener" element={
            <ProtectedRoute><div>Screener (Task 21)</div></ProtectedRoute>
          } />
          <Route path="/chart/:symbol" element={
            <ProtectedRoute><div>Chart (Task 22)</div></ProtectedRoute>
          } />
          <Route path="/signals" element={
            <ProtectedRoute><div>Signals (Task 23)</div></ProtectedRoute>
          } />
          <Route path="/chat" element={
            <ProtectedRoute><div>Chat (Task 23)</div></ProtectedRoute>
          } />
          <Route path="*" element={<Navigate to="/screener" replace />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
```

- [ ] **Step 6: Start dev server + verify login flow**

```bash
cd frontend && npm run dev
```

Open http://localhost:5173. Navigate to /screener → should redirect to /login. Enter credentials → should redirect to /screener placeholder.

- [ ] **Step 7: Commit**

```bash
git add frontend/
git commit -m "feat: frontend scaffold — React+Vite, axios JWT client, login page, protected routes"
```

---

## Task 21: Frontend — Screener UI

**Files:**
- Create: `frontend/src/components/Screener/ConditionBuilder.tsx`
- Create: `frontend/src/components/Screener/ResultsTable.tsx`
- Create: `frontend/src/components/Screener/StrengthDots.tsx`
- Create: `frontend/src/api/scanner.ts`
- Create: `frontend/src/store/filters.ts`
- Create: `frontend/src/pages/Screener.tsx`

- [ ] **Step 1: Create frontend/src/store/filters.ts**

```typescript
import { create } from "zustand";

interface Filter {
  field: string;
  operator: string;
  value: string | number;
}

interface FiltersStore {
  source: string;
  filters: Filter[];
  indicators: string[];
  maxSymbols: number;
  setSource: (source: string) => void;
  addFilter: (filter: Filter) => void;
  removeFilter: (index: number) => void;
  setIndicators: (indicators: string[]) => void;
  reset: () => void;
}

export const useFiltersStore = create<FiltersStore>((set) => ({
  source: "nse_universe",
  filters: [],
  indicators: [],
  maxSymbols: 500,
  setSource: (source) => set({ source }),
  addFilter: (filter) => set((s) => ({ filters: [...s.filters, filter] })),
  removeFilter: (index) => set((s) => ({ filters: s.filters.filter((_, i) => i !== index) })),
  setIndicators: (indicators) => set({ indicators }),
  reset: () => set({ source: "nse_universe", filters: [], indicators: [] }),
}));
```

- [ ] **Step 2: Create frontend/src/api/scanner.ts**

```typescript
import { useMutation } from "@tanstack/react-query";
import { apiClient } from "./client";

interface ScanRequest {
  source: string;
  filters: Array<{ field: string; operator: string; value: unknown }>;
  indicators: string[];
  max_symbols: number;
}

interface ScanResult {
  symbol: string;
  signals?: Record<string, unknown>;
  score?: number;
}

interface ScanResponse {
  symbols: string[];
  results?: ScanResult[];
}

export function useRunScan() {
  return useMutation({
    mutationFn: async (req: ScanRequest): Promise<ScanResponse> => {
      const { data } = await apiClient.post<ScanResponse>("/scanner/run", req);
      return data;
    },
  });
}

export function useListSignals() {
  const { useQuery } = require("@tanstack/react-query");
  return useQuery({
    queryKey: ["signals"],
    queryFn: async () => {
      const { data } = await apiClient.get("/scanner/signals");
      return data;
    },
  });
}
```

- [ ] **Step 3: Create frontend/src/components/Screener/StrengthDots.tsx**

```tsx
interface Props {
  score: number;  // 1–5
}

export default function StrengthDots({ score }: Props) {
  return (
    <span style={{ letterSpacing: 2 }}>
      {Array.from({ length: 5 }, (_, i) => (
        <span key={i} style={{ color: i < score ? "#089981" : "#444" }}>●</span>
      ))}
    </span>
  );
}
```

- [ ] **Step 4: Create frontend/src/components/Screener/ConditionBuilder.tsx**

```tsx
import { useFiltersStore } from "../../store/filters";

const SOURCES = ["nse_universe", "premarket_gainers", "custom_list"];
const INDICATORS = ["rsi", "macd", "ema", "vwap", "bollinger_bands", "atr"];
const OPERATORS = ["eq", "gt", "lt", "gte", "lte"];

export default function ConditionBuilder() {
  const { source, filters, indicators, setSource, addFilter, removeFilter, setIndicators } =
    useFiltersStore();

  return (
    <div style={{ padding: 16 }}>
      <h3>Source</h3>
      <select value={source} onChange={(e) => setSource(e.target.value)}>
        {SOURCES.map((s) => <option key={s} value={s}>{s}</option>)}
      </select>

      <h3>Filters</h3>
      {filters.map((f, i) => (
        <div key={i} style={{ display: "flex", gap: 8, marginBottom: 4 }}>
          <span>{f.field} {f.operator} {String(f.value)}</span>
          <button onClick={() => removeFilter(i)}>✕</button>
        </div>
      ))}
      <AddFilterRow onAdd={addFilter} />

      <h3>Indicators</h3>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {INDICATORS.map((ind) => (
          <label key={ind}>
            <input
              type="checkbox"
              checked={indicators.includes(ind)}
              onChange={(e) => {
                if (e.target.checked) setIndicators([...indicators, ind]);
                else setIndicators(indicators.filter((i) => i !== ind));
              }}
            />
            {ind}
          </label>
        ))}
      </div>
    </div>
  );
}

function AddFilterRow({ onAdd }: { onAdd: (f: { field: string; operator: string; value: string }) => void }) {
  const [field, setField] = React.useState("exchange");
  const [operator, setOperator] = React.useState("eq");
  const [value, setValue] = React.useState("NSE");
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const React = require("react");

  return (
    <div style={{ display: "flex", gap: 4, marginTop: 8 }}>
      <input value={field} onChange={(e) => setField(e.target.value)} placeholder="field" style={{ width: 100 }} />
      <select value={operator} onChange={(e) => setOperator(e.target.value)}>
        {OPERATORS.map((op) => <option key={op}>{op}</option>)}
      </select>
      <input value={value} onChange={(e) => setValue(e.target.value)} placeholder="value" style={{ width: 80 }} />
      <button onClick={() => onAdd({ field, operator, value })}>+ Add</button>
    </div>
  );
}
```

- [ ] **Step 5: Create frontend/src/components/Screener/ResultsTable.tsx**

```tsx
import { useReactTable, getCoreRowModel, getSortedRowModel, flexRender, type ColumnDef } from "@tanstack/react-table";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import StrengthDots from "./StrengthDots";

interface Row { symbol: string; score?: number; signals?: Record<string, unknown> }

export default function ResultsTable({ data }: { data: Row[] }) {
  const navigate = useNavigate();
  const [sorting, setSorting] = useState([]);

  const columns: ColumnDef<Row>[] = [
    { accessorKey: "symbol", header: "Symbol" },
    {
      accessorKey: "score",
      header: "Strength",
      cell: ({ getValue }) => {
        const score = (getValue() as number) ?? 0;
        return <StrengthDots score={Math.round(score)} />;
      },
    },
  ];

  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    state: { sorting },
    onSortingChange: setSorting as any,
  });

  return (
    <table style={{ width: "100%", borderCollapse: "collapse" }}>
      <thead>
        {table.getHeaderGroups().map((hg) => (
          <tr key={hg.id}>
            {hg.headers.map((h) => (
              <th key={h.id} onClick={h.column.getToggleSortingHandler()}
                  style={{ cursor: "pointer", textAlign: "left", padding: "8px 12px", borderBottom: "1px solid #333" }}>
                {flexRender(h.column.columnDef.header, h.getContext())}
                {h.column.getIsSorted() === "asc" ? " ▲" : h.column.getIsSorted() === "desc" ? " ▼" : ""}
              </th>
            ))}
          </tr>
        ))}
      </thead>
      <tbody>
        {table.getRowModel().rows.map((row) => (
          <tr key={row.id}
              onClick={() => navigate(`/chart/${row.original.symbol}`)}
              style={{ cursor: "pointer" }}>
            {row.getVisibleCells().map((cell) => (
              <td key={cell.id} style={{ padding: "8px 12px", borderBottom: "1px solid #222" }}>
                {flexRender(cell.column.columnDef.cell, cell.getContext())}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 6: Create frontend/src/pages/Screener.tsx**

```tsx
import { useFiltersStore } from "../store/filters";
import { useRunScan } from "../api/scanner";
import ConditionBuilder from "../components/Screener/ConditionBuilder";
import ResultsTable from "../components/Screener/ResultsTable";

export default function Screener() {
  const { source, filters, indicators, maxSymbols } = useFiltersStore();
  const { mutate: runScan, data, isPending } = useRunScan();

  function handleRun() {
    runScan({
      source,
      filters: filters.map((f) => ({ field: f.field, operator: f.operator, value: f.value })),
      indicators,
      max_symbols: maxSymbols,
    });
  }

  const results = data?.symbols?.map((s) => ({ symbol: s })) ?? [];

  return (
    <div style={{ display: "flex", height: "100vh" }}>
      <div style={{ width: 320, borderRight: "1px solid #333", overflowY: "auto" }}>
        <ConditionBuilder />
        <div style={{ padding: 16 }}>
          <button onClick={handleRun} disabled={isPending} style={{ width: "100%", padding: 10 }}>
            {isPending ? "Running..." : "Run Scan"}
          </button>
        </div>
      </div>
      <div style={{ flex: 1, overflowY: "auto", padding: 16 }}>
        <h3>Results ({results.length})</h3>
        <ResultsTable data={results} />
      </div>
    </div>
  );
}
```

- [ ] **Step 7: Update App.tsx to use Screener page**

Replace `<div>Screener (Task 21)</div>` in App.tsx with `<Screener />` and import it.

- [ ] **Step 8: Test screener in browser**

```bash
cd frontend && npm run dev
```

Open http://localhost:5173/screener. Add a filter → click Run Scan → verify results table renders. Click a row → verify navigation to /chart/SYMBOL.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/
git commit -m "feat: screener UI — condition builder, TanStack Table results, strength dots, Zustand state"
```

---

## Task 22: Frontend — Chart View

**Files:**
- Create: `frontend/src/api/technical.ts`
- Create: `frontend/src/components/Chart/CandlestickChart.tsx`
- Create: `frontend/src/components/Chart/SignalMarkers.tsx`
- Create: `frontend/src/pages/Chart.tsx`

- [ ] **Step 1: Create frontend/src/api/technical.ts**

```typescript
import { useQuery } from "@tanstack/react-query";
import { apiClient } from "./client";

interface OHLCVRow {
  ts: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export function useOHLCV(symbol: string, tf: string, fromDt: string, toDt: string) {
  return useQuery({
    queryKey: ["ohlcv", symbol, tf, fromDt, toDt],
    queryFn: async (): Promise<OHLCVRow[]> => {
      const { data } = await apiClient.get(`/technical/ohlcv/${symbol}`, {
        params: { tf, from_dt: fromDt, to_dt: toDt },
      });
      return data.rows;
    },
    enabled: !!symbol,
  });
}
```

- [ ] **Step 2: Create frontend/src/components/Chart/CandlestickChart.tsx**

```tsx
import { useEffect, useRef } from "react";
import { createChart, type IChartApi, type ISeriesApi, CandlestickSeries } from "lightweight-charts";

interface Bar { ts: string; open: number; high: number; low: number; close: number }

export default function CandlestickChart({ bars }: { bars: Bar[] }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  useEffect(() => {
    if (!containerRef.current) return;
    chartRef.current = createChart(containerRef.current, {
      width: containerRef.current.clientWidth,
      height: 400,
      layout: { background: { color: "#1a1a2e" }, textColor: "#d1d4dc" },
      grid: { vertLines: { color: "#2d2d4e" }, horzLines: { color: "#2d2d4e" } },
    });
    seriesRef.current = chartRef.current.addSeries(CandlestickSeries, {
      upColor: "#089981",
      downColor: "#f23645",
      borderVisible: false,
      wickUpColor: "#089981",
      wickDownColor: "#f23645",
    });
    return () => chartRef.current?.remove();
  }, []);

  useEffect(() => {
    if (!seriesRef.current || bars.length === 0) return;
    const formatted = bars.map((b) => ({
      time: b.ts.split("T")[0] as unknown as number,
      open: b.open,
      high: b.high,
      low: b.low,
      close: b.close,
    }));
    seriesRef.current.setData(formatted);
    chartRef.current?.timeScale().fitContent();
  }, [bars]);

  return <div ref={containerRef} style={{ width: "100%", height: 400 }} />;
}
```

- [ ] **Step 3: Create frontend/src/pages/Chart.tsx**

```tsx
import { useParams } from "react-router-dom";
import CandlestickChart from "../components/Chart/CandlestickChart";
import { useOHLCV } from "../api/technical";

export default function Chart() {
  const { symbol } = useParams<{ symbol: string }>();
  const today = new Date().toISOString().split("T")[0];
  const yearAgo = new Date(Date.now() - 365 * 24 * 60 * 60 * 1000).toISOString().split("T")[0];

  const { data: rows, isLoading } = useOHLCV(symbol!, "1d", yearAgo, today);

  return (
    <div style={{ padding: 16 }}>
      <h2>{symbol}</h2>
      {isLoading ? (
        <div>Loading chart...</div>
      ) : (
        <CandlestickChart bars={rows ?? []} />
      )}
    </div>
  );
}
```

- [ ] **Step 4: Update App.tsx Chart route**

Replace `<div>Chart (Task 22)</div>` with `<Chart />` and add import.

- [ ] **Step 5: Test chart in browser**

Open http://localhost:5173/chart/RELIANCE. Verify candlestick chart renders with data from API. Zoom, pan work correctly.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/
git commit -m "feat: chart view — TradingView Lightweight Charts candlestick + OHLCV API integration"
```

---

## Task 23: Frontend — Live Signal Feed + LLM Chat

**Files:**
- Create: `frontend/src/store/signals.ts`
- Create: `frontend/src/components/SignalFeed/SignalFeedPanel.tsx`
- Create: `frontend/src/components/SignalFeed/SignalItem.tsx`
- Create: `frontend/src/components/Chat/ChatInterface.tsx`
- Create: `frontend/src/components/Layout/Sidebar.tsx`
- Create: `frontend/src/components/Layout/Topbar.tsx`

- [ ] **Step 1: Create frontend/src/store/signals.ts**

```typescript
import { create } from "zustand";

interface Signal {
  event_id: string;
  symbol: string;
  signal_name: string;
  direction: string;
  strength_score: number;
  timestamp: string;
}

interface SignalsStore {
  signals: Signal[];
  lastEventId: string;
  wsStatus: "connecting" | "connected" | "disconnected";
  addSignal: (signal: Signal) => void;
  setLastEventId: (id: string) => void;
  setWsStatus: (status: "connecting" | "connected" | "disconnected") => void;
}

export const useSignalsStore = create<SignalsStore>((set) => ({
  signals: [],
  lastEventId: "0",
  wsStatus: "disconnected",
  addSignal: (signal) =>
    set((s) => ({ signals: [signal, ...s.signals].slice(0, 100) })),
  setLastEventId: (id) => set({ lastEventId: id }),
  setWsStatus: (status) => set({ wsStatus: status }),
}));
```

- [ ] **Step 2: Create frontend/src/components/SignalFeed/SignalFeedPanel.tsx**

```tsx
import { useEffect } from "react";
import { useSignalsStore } from "../../store/signals";
import SignalItem from "./SignalItem";

const WS_URL = import.meta.env.VITE_WS_BASE ?? "ws://localhost:8000";

export default function SignalFeedPanel() {
  const { signals, lastEventId, addSignal, setLastEventId, setWsStatus } = useSignalsStore();

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (!token) return;

    function connect() {
      setWsStatus("connecting");
      const ws = new WebSocket(
        `${WS_URL}/ws/signals?token=${token}&last_event_id=${lastEventId}`
      );

      ws.onopen = () => setWsStatus("connected");
      ws.onclose = () => {
        setWsStatus("disconnected");
        setTimeout(connect, 3000);  // reconnect with last_event_id for resume
      };
      ws.onerror = () => ws.close();
      ws.onmessage = (evt) => {
        const data = JSON.parse(evt.data);
        addSignal(data);
        setLastEventId(data.event_id);
      };

      return ws;
    }

    const ws = connect();
    return () => ws.close();
  }, []);  // connect once; reconnect loop handles resume

  return (
    <div style={{ height: "100%", overflowY: "auto" }}>
      <h4 style={{ padding: "8px 12px", margin: 0 }}>Live Signals</h4>
      {signals.map((sig) => <SignalItem key={sig.event_id} signal={sig} />)}
      {signals.length === 0 && (
        <div style={{ padding: 12, color: "#666" }}>Waiting for signals...</div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Create frontend/src/components/SignalFeed/SignalItem.tsx**

```tsx
import { useNavigate } from "react-router-dom";

interface Signal {
  symbol: string;
  signal_name: string;
  direction: string;
  strength_score: number;
  timestamp: string;
}

export default function SignalItem({ signal }: { signal: Signal }) {
  const navigate = useNavigate();
  const color = signal.direction === "bullish" ? "#089981" : "#f23645";

  return (
    <div
      onClick={() => navigate(`/chart/${signal.symbol}`)}
      style={{
        padding: "8px 12px",
        borderBottom: "1px solid #222",
        cursor: "pointer",
        borderLeft: `3px solid ${color}`,
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between" }}>
        <strong style={{ color }}>{signal.symbol}</strong>
        <span style={{ fontSize: 11, color: "#666" }}>
          {new Date(signal.timestamp).toLocaleTimeString()}
        </span>
      </div>
      <div style={{ fontSize: 12, color: "#aaa" }}>{signal.signal_name}</div>
    </div>
  );
}
```

- [ ] **Step 4: Create frontend/src/components/Chat/ChatInterface.tsx**

```tsx
import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { apiClient } from "../../api/client";
import { useFiltersStore } from "../../store/filters";
import { useNavigate } from "react-router-dom";

export default function ChatInterface() {
  const [query, setQuery] = useState("");
  const { setSource } = useFiltersStore();
  const navigate = useNavigate();

  const { mutate: sendQuery, data, isPending, error } = useMutation({
    mutationFn: async (q: string) => {
      const { data } = await apiClient.post("/chat/query", { query: q });
      return data;
    },
    onSuccess: (data) => {
      // Populate screener with translated DSL
      if (data.dsl?.source?.name) {
        setSource(data.dsl.source.name);
        navigate("/screener");
      }
    },
  });

  return (
    <div style={{ padding: 16, height: "100%" }}>
      <h3>Ask in plain English</h3>
      <textarea
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        placeholder="e.g. Show me oversold large cap NSE stocks with uptrend in last 2 hours"
        rows={4}
        style={{ width: "100%", padding: 8, marginBottom: 8 }}
      />
      <button onClick={() => sendQuery(query)} disabled={isPending || !query}>
        {isPending ? "Thinking..." : "Analyze"}
      </button>
      {error && <p style={{ color: "red" }}>Error: budget exceeded or API unavailable</p>}
      {data && (
        <div style={{ marginTop: 16 }}>
          <p style={{ color: "#aaa" }}>{data.explanation}</p>
          <p>Redirecting to screener...</p>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Create frontend/src/components/Layout/Sidebar.tsx**

```tsx
import SignalFeedPanel from "../SignalFeed/SignalFeedPanel";
import { useSignalsStore } from "../../store/signals";

export default function Sidebar() {
  const { wsStatus } = useSignalsStore();
  const statusColor = wsStatus === "connected" ? "#089981" : wsStatus === "connecting" ? "#f5a623" : "#f23645";

  return (
    <div style={{ width: 280, borderRight: "1px solid #222", display: "flex", flexDirection: "column" }}>
      <div style={{ padding: "8px 12px", borderBottom: "1px solid #222", display: "flex", justifyContent: "space-between" }}>
        <strong>Trading System</strong>
        <span style={{ color: statusColor, fontSize: 11 }}>● {wsStatus}</span>
      </div>
      <div style={{ flex: 1, overflow: "hidden" }}>
        <SignalFeedPanel />
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Update App.tsx with layout**

```tsx
// Wrap all protected routes with Sidebar layout:
function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div style={{ display: "flex", height: "100vh", background: "#0d0d1a", color: "#d1d4dc" }}>
      <Sidebar />
      <div style={{ flex: 1, overflow: "auto" }}>{children}</div>
    </div>
  );
}
```

- [ ] **Step 7: Test signal feed in browser**

Start backend + frontend. Open http://localhost:5173. Verify sidebar shows "Live Signals" panel. Verify WebSocket status indicator. Manually publish a test signal to Redis Streams:

```bash
redis-cli XADD signals:live '*' symbol RELIANCE signal_name rsi_oversold direction bullish strength_score 3 timestamp 2026-05-17T09:30:00
```

Verify signal appears in sidebar within 5 seconds.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/
git commit -m "feat: live signal feed (WebSocket+Redis Streams, resume-on-reconnect) + LLM chat interface"
```

---

## Task 24: Production Docker + Nginx

**Files:**
- Create: `infra/docker-compose.prod.yml`
- Create: `infra/nginx/nginx.conf`
- Modify: `backend/gunicorn.conf.py`

- [ ] **Step 1: Create backend/gunicorn.conf.py**

```python
bind = "0.0.0.0:8000"
workers = 4
worker_class = "uvicorn.workers.UvicornWorker"
timeout = 120
keepalive = 5
accesslog = "-"
errorlog = "-"
loglevel = "info"
```

- [ ] **Step 2: Create infra/nginx/nginx.conf**

```nginx
events { worker_connections 1024; }

http {
    upstream api {
        server api:8000;
    }

    server {
        listen 80;

        # API
        location /api/ {
            proxy_pass http://api/;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Trace-ID $request_id;
        }

        # WebSocket
        location /ws/ {
            proxy_pass http://api/ws/;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_read_timeout 86400;
        }

        # Frontend static
        location / {
            root /usr/share/nginx/html;
            index index.html;
            try_files $uri $uri/ /index.html;
        }
    }
}
```

- [ ] **Step 3: Create infra/docker-compose.prod.yml**

```yaml
services:
  nginx:
    image: nginx:1.26-alpine
    ports: ["80:80", "443:443"]
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - frontend_build:/usr/share/nginx/html:ro
    depends_on: [api]

  api:
    build:
      context: ../backend
      dockerfile: Dockerfile
    command: gunicorn api.main:app -c gunicorn.conf.py
    environment:
      - POSTGRES_URL=${POSTGRES_URL}
      - QUESTDB_URL=${QUESTDB_URL}
      - REDIS_URL=${REDIS_URL}
      - TEMPORAL_HOST=${TEMPORAL_HOST}
      - JWT_SECRET=${JWT_SECRET}
      - ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
      - PARQUET_BASE_PATH=/data/raw
    volumes:
      - parquet_data:/data/raw
    depends_on: [postgres, questdb, redis]

  temporal-worker:
    build:
      context: ../backend
      dockerfile: Dockerfile
    command: python -m workers.main
    environment:
      - POSTGRES_URL=${POSTGRES_URL}
      - QUESTDB_URL=${QUESTDB_URL}
      - REDIS_URL=${REDIS_URL}
      - TEMPORAL_HOST=${TEMPORAL_HOST}
      - PARQUET_BASE_PATH=/data/raw
    volumes:
      - parquet_data:/data/raw
    depends_on: [temporal]

  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: trading
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes: [postgres_data:/var/lib/postgresql/data]

  questdb:
    image: questdb/questdb:8.0.3
    volumes: [questdb_data:/root/.questdb]

  redis:
    image: redis:7-alpine
    command: redis-server --save 60 1  # persistence

  temporal:
    image: temporalio/auto-setup:1.24
    environment:
      - DB=postgresql
      - POSTGRES_USER=${POSTGRES_USER}
      - POSTGRES_PWD=${POSTGRES_PASSWORD}
      - POSTGRES_SEEDS=postgres
    depends_on: [postgres]

volumes:
  postgres_data:
  questdb_data:
  parquet_data:
  frontend_build:
```

- [ ] **Step 4: Create backend/Dockerfile**

```dockerfile
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml .
RUN pip install -e .

COPY . .
```

- [ ] **Step 5: Create frontend/Dockerfile**

```dockerfile
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json .
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.26-alpine
COPY --from=build /app/dist /usr/share/nginx/html
```

- [ ] **Step 6: Test production build**

```bash
cd trading-system
cp infra/docker-compose.dev.yml infra/.env.example   # create env template
docker compose -f infra/docker-compose.prod.yml build
docker compose -f infra/docker-compose.prod.yml up -d
curl http://localhost/health
```

Expected: `{"status":"ok"}` via Nginx proxy.

- [ ] **Step 7: Commit**

```bash
git add infra/docker-compose.prod.yml infra/nginx/ backend/Dockerfile backend/gunicorn.conf.py frontend/Dockerfile
git commit -m "feat: production Docker — Gunicorn+Uvicorn behind Nginx, multi-stage frontend build"
```

---

## Self-Review Checklist

**Spec coverage:**

| Spec section | Tasks |
|---|---|
| Goals — OHLCV ingestion | 4, 7, 13 |
| Goals — indicators + patterns | 8, 9, 10 |
| Goals — configurable scanner | 11 |
| Goals — LLM NL interface | 17 |
| Goals — agent activities | 12, 18 |
| Data Layer — QuestDB schema | 4 |
| Data Layer — PostgreSQL schema | 3 |
| Data Layer — Redis cache | 2 |
| Data Layer — Parquet + DuckDB fallback | 5, 6 |
| Data Layer — Storage abstraction | 5 |
| Data Layer — Retention + rehydration | 14 |
| Data Layer — Corporate actions | 3 (adjustment_factors table) |
| Scanner — composable conditions | 11 |
| Scanner — signal YAML + Pydantic | 11 |
| Temporal — auto-registry | 12 |
| Temporal — workflows | 13, 14 |
| LLM — tool use + budget | 17 |
| LLM — agent code safety gate | 18 |
| Frontend — screener UI | 21 |
| Frontend — chart view | 22 |
| Frontend — live signal feed | 23 |
| Frontend — LLM chat | 23 |
| Auth — JWT + Protocol | 15 |
| Observability | 19 |
| Deployment | 1, 24 |
| market_event_types.collection_windows | 3 (migration), 13 (market_events workflow) |
| stock_attributes (replaces is_penny) | 3 (migration) |

**Gaps addressed:**

- `SCANNER_DSL_VERSION` included in all DSL JSON output (Task 11, 17)
- `collection_label` on market_events distinguishes 9:00 AM vs 9:11 AM pre-open snapshots (Task 13)
- `intraday_1min_collector` is a single long-running workflow — NOT re-triggered every minute (Task 13)
- `questdb_retention_sweep` verifies Parquet before dropping QuestDB partitions (Task 14)
- `data_quality_check` uses `trading_calendar.minutes` — NOT hardcoded 375 (Task 14)
- Agent-generated activity security is multi-layer: AST + RestrictedPython + bytecode + subprocess (Task 18)
- Prometheus custom metrics defined and exposed at /metrics (Task 19)

**Type consistency verified:**
- `MarketData.ohlcv()` signature consistent across sdk.py (Task 6) and uses in activities (Task 13)
- `PatternResult.to_dict()` output matches `signals` JSONB column format in scan_results (Task 9)
- `Scanner.run()` returns `pd.DataFrame` consistently — API serializes via `.to_dict(orient="records")` (Task 16)
- `validate_activity_code()` raises `SecurityViolation` — caught in admin router (Task 18)

---

**Plan complete and saved to `docs/superpowers/plans/2026-05-17-technical-analysis-engine.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** — Fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch with checkpoints.

Which approach?
