from core.config import Settings


def test_settings_loads_defaults():
    s = Settings(
        _env_file=None,  # don't read .env file in tests
        POSTGRES_URL="postgresql+asyncpg://trading:trading@localhost:5432/trading",
        QUESTDB_URL="postgresql://admin:quest@localhost:8812/qdb",
        REDIS_URL="redis://localhost:6379",
        TEMPORAL_HOST="localhost:7233",
        JWT_SECRET="x" * 32,
    )
    assert s.SCHEMA_VERSION == "v1"
    assert s.LLM_MODEL == "claude-sonnet-4-6"
    assert s.LLM_DAILY_TOKEN_BUDGET == 100_000
    assert s.SCANNER_DSL_VERSION == 1
    assert s.PARQUET_BASE_PATH == "/data/raw"


def test_cache_key_format():
    from core.cache import cache_key
    key = cache_key("indicators", "RELIANCE", "1min")
    assert key == "ta:v1:indicators:RELIANCE:1min"


def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("SCHEMA_VERSION", "v2")
    monkeypatch.setenv("POSTGRES_URL", "postgresql+asyncpg://trading:trading@localhost:5432/trading")
    monkeypatch.setenv("QUESTDB_URL", "postgresql://admin:quest@localhost:8812/qdb")
    monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
    monkeypatch.setenv("TEMPORAL_HOST", "localhost:7233")
    monkeypatch.setenv("JWT_SECRET", "x" * 32)
    s = Settings(_env_file=None)
    assert s.SCHEMA_VERSION == "v2"
