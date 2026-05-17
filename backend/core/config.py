from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Databases
    POSTGRES_URL: str = "postgresql+asyncpg://trading:trading@localhost:5432/trading"
    QUESTDB_URL: str = "postgresql://admin:quest@localhost:8812/qdb"
    REDIS_URL: str = "redis://localhost:6379"

    # Jobs
    TEMPORAL_HOST: str = "localhost:7233"
    TEMPORAL_NAMESPACE: str = "trading"

    # Auth
    AUTH_PROVIDER: str = "local"
    ADMIN_USERNAME: str = ""
    ADMIN_PASSWORD_HASH: str = ""
    JWT_SECRET: str = "dev-secret-change-in-production"
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

    # Redis namespace — bump on breaking schema changes to auto-invalidate
    SCHEMA_VERSION: str = "v1"

    # Feature flags
    ENABLE_LIVE_SIGNALS: bool = True
    ENABLE_LLM_CHAT: bool = True
    SAFETY_GATE_AGENT_CODE: bool = True

    # Rate limits
    SHOONYA_MAX_CONCURRENT: int = 10


settings = Settings()
