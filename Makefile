.PHONY: up down purge api worker frontend seed migrate logs test dev install

PYTHON    := backend/.venv/bin/python
UVICORN   := backend/.venv/bin/uvicorn
PYTEST    := backend/.venv/bin/pytest
ALEMBIC   := backend/.venv/bin/alembic
COMPOSE   := docker compose -f infra/docker-compose.dev.yml

# Persistent data root — all stateful mounts live here.
# Override via: make up TRADING_DATA_DIR=/your/path
TRADING_DATA_DIR ?= $(HOME)/.trading-system/data
export TRADING_DATA_DIR

# Parquet files land on the host at the same root, not inside containers.
PARQUET_BASE_PATH := $(TRADING_DATA_DIR)/parquet
export PARQUET_BASE_PATH

# ── Infrastructure ─────────────────────────────────────────────────────────
up:
	@mkdir -p $(TRADING_DATA_DIR)/postgres $(TRADING_DATA_DIR)/questdb \
	           $(TRADING_DATA_DIR)/redis $(TRADING_DATA_DIR)/grafana \
	           $(TRADING_DATA_DIR)/prometheus $(TRADING_DATA_DIR)/parquet
	$(COMPOSE) up -d
	@echo "Waiting for Postgres to be ready..."
	@until $(COMPOSE) exec -T postgres pg_isready -U trading -d trading >/dev/null 2>&1; do sleep 1; done
	@echo "All services up. Data at: $(TRADING_DATA_DIR)"

down:
	# Stops containers, keeps all data intact at $(TRADING_DATA_DIR)
	$(COMPOSE) down

purge:
	# !! DESTRUCTIVE — wipes containers AND all persisted data !!
	@echo "WARNING: This will permanently delete all trading data at $(TRADING_DATA_DIR)"
	@read -p "Type YES to confirm: " ans && [ "$$ans" = "YES" ] || (echo "Aborted." && exit 1)
	$(COMPOSE) down
	rm -rf $(TRADING_DATA_DIR)
	@echo "All data purged."

logs:
	$(COMPOSE) logs -f

# ── Install ────────────────────────────────────────────────────────────────
install:
	python3.12 -m venv backend/.venv
	backend/.venv/bin/pip install -e backend/[dev] -q
	cd frontend && npm install

# ── Database ───────────────────────────────────────────────────────────────
migrate:
	cd infra && DATABASE_URL=postgresql://trading:trading@localhost:5432/trading \
		PYTHONPATH=../backend ../$(ALEMBIC) -c alembic.ini upgrade head

seed:
	@echo "Seeding NSE stocks + 2026 trading calendar..."
	cd backend && PYTHONPATH=. ../$(PYTHON) scripts/seed.py

# ── Backend ────────────────────────────────────────────────────────────────
api:
	cd backend && PYTHONPATH=. PARQUET_BASE_PATH=$(PARQUET_BASE_PATH) \
		../$(UVICORN) api.main:app --reload --host 0.0.0.0 --port 8000

worker:
	cd backend && PYTHONPATH=. PARQUET_BASE_PATH=$(PARQUET_BASE_PATH) \
		../$(PYTHON) -m workers.main

# ── Frontend ───────────────────────────────────────────────────────────────
frontend:
	cd frontend && npm run dev

# ── Tests ──────────────────────────────────────────────────────────────────
test:
	cd backend && PYTHONPATH=. ../$(PYTEST) tests/unit/ -q

# ── Full dev start ─────────────────────────────────────────────────────────
dev: up migrate seed
	@echo ""
	@echo "  API      → http://localhost:8000"
	@echo "  Docs     → http://localhost:8000/docs"
	@echo "  Frontend → http://localhost:5173  (run: make frontend)"
	@echo "  Temporal → http://localhost:8080"
	@echo "  Grafana  → http://localhost:3000"
	@echo "  Metrics  → http://localhost:9090"
	@echo "  Data     → $(TRADING_DATA_DIR)"
	@echo ""
	@echo "Starting API + worker (Ctrl-C to stop)..."
	@trap 'kill 0' INT; \
		make api & make worker & wait
