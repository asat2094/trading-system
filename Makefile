.PHONY: up down api worker frontend seed migrate logs test dev install

PYTHON    := backend/.venv/bin/python
UVICORN   := backend/.venv/bin/uvicorn
PYTEST    := backend/.venv/bin/pytest
ALEMBIC   := backend/.venv/bin/alembic
COMPOSE   := docker compose -f infra/docker-compose.dev.yml

# ── Infrastructure ─────────────────────────────────────────────────────────
up:
	$(COMPOSE) up -d
	@echo "Waiting for Postgres to be ready..."
	@until $(COMPOSE) exec -T postgres pg_isready -U trading -d trading >/dev/null 2>&1; do sleep 1; done
	@echo "All services up."

down:
	$(COMPOSE) down -v

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
		PYTHONPATH=../backend $(ALEMBIC) -c alembic.ini upgrade head

seed:
	@echo "Seeding NSE stocks + 2026 trading calendar..."
	cd backend && PYTHONPATH=. $(PYTHON) scripts/seed.py

# ── Backend ────────────────────────────────────────────────────────────────
api:
	cd backend && PYTHONPATH=. $(UVICORN) api.main:app --reload --host 0.0.0.0 --port 8000

worker:
	cd backend && PYTHONPATH=. $(PYTHON) -m workers.main

# ── Frontend ───────────────────────────────────────────────────────────────
frontend:
	cd frontend && npm run dev

# ── Tests ──────────────────────────────────────────────────────────────────
test:
	cd backend && PYTHONPATH=. $(PYTEST) tests/unit/ -q

# ── Full dev start ─────────────────────────────────────────────────────────
dev: up migrate seed
	@echo ""
	@echo "  API      → http://localhost:8000"
	@echo "  Docs     → http://localhost:8000/docs"
	@echo "  Frontend → http://localhost:5173  (run: make frontend)"
	@echo "  Temporal → http://localhost:8080"
	@echo "  Grafana  → http://localhost:3000"
	@echo "  Metrics  → http://localhost:9090"
	@echo ""
	@echo "Starting API + worker (Ctrl-C to stop)..."
	@trap 'kill 0' INT; \
		make api & make worker & wait
