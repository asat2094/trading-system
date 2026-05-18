from pathlib import Path
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env from repo root regardless of working directory
_ENV_FILE = Path(__file__).parent.parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

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
    ADMIN_PASSWORD_HASH: SecretStr = SecretStr("")
    JWT_SECRET: str
    JWT_EXPIRY_HOURS: int = 24

    # LLM
    ANTHROPIC_API_KEY: SecretStr = SecretStr("")
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

    @field_validator("JWT_SECRET")
    @classmethod
    def jwt_secret_min_length(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("JWT_SECRET must be at least 32 characters")
        return v


settings = Settings()
