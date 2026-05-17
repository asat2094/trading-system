from core.config import Settings


def test_settings_loads_defaults():
    s = Settings(
        _env_file=None,  # don't read .env file in tests
    )
    assert s.SCHEMA_VERSION == "v1"
    assert s.LLM_MODEL == "claude-sonnet-4-6"
    assert s.LLM_DAILY_TOKEN_BUDGET == 100_000
    assert s.SCANNER_DSL_VERSION == 1


def test_cache_key_format():
    from core.cache import cache_key
    key = cache_key("indicators", "RELIANCE", "1min")
    assert key == "ta:v1:indicators:RELIANCE:1min"


def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("SCHEMA_VERSION", "v2")
    s = Settings(_env_file=None)
    assert s.SCHEMA_VERSION == "v2"
