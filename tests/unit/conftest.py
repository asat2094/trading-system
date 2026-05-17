import os

# Set required env vars before any module import so Settings() can be instantiated at module level.
_required_defaults = {
    "POSTGRES_URL": "postgresql+asyncpg://trading:trading@localhost:5432/trading",
    "QUESTDB_URL": "postgresql://admin:quest@localhost:8812/qdb",
    "REDIS_URL": "redis://localhost:6379",
    "TEMPORAL_HOST": "localhost:7233",
    "JWT_SECRET": "x" * 32,
}
for _key, _value in _required_defaults.items():
    os.environ.setdefault(_key, _value)
