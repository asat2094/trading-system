# backend/journal/db.py
import asyncpg
from pathlib import Path
from core.config import settings

_SCHEMA_SQL = (Path(__file__).parent / "schema.sql").read_text()

_DEFAULT_RULES = [
    {"name": "max_loss_per_day",   "rule_type": "risk",      "config": {"limit": 5000}},
    {"name": "max_trades_per_day", "rule_type": "risk",      "config": {"limit": 30}},
    {"name": "no_force_square",    "rule_type": "discipline", "config": {}},
]

_pool: asyncpg.Pool | None = None

async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        dsn = settings.POSTGRES_URL.replace("postgresql+asyncpg://", "postgresql://")
        _pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
    return _pool

async def init_journal_tables() -> None:
    pool = await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(_SCHEMA_SQL)

async def seed_default_rules() -> None:
    import json
    pool = await get_pool()
    async with pool.acquire() as conn:
        for r in _DEFAULT_RULES:
            await conn.execute(
                """INSERT INTO jrn_rules (name, rule_type, enabled, config)
                   VALUES ($1, $2, $3, $4)
                   ON CONFLICT (name) DO NOTHING""",
                r["name"], r["rule_type"], False, json.dumps(r["config"]),
            )
