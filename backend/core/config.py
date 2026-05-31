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
    JWT_EXPIRY_HOURS: int = 168  # 7 days

    # LLM
    ANTHROPIC_API_KEY: SecretStr = SecretStr("")
    LLM_MODEL: str = "claude-sonnet-4-6"

    # Upstox market data feed
    UPSTOX_API_KEY: str = ""
    UPSTOX_API_SECRET: str = ""
    LLM_PROMPT_VERSION: str = "v1"
    LLM_DAILY_TOKEN_BUDGET: int = 100_000

    # Storage
    PARQUET_BASE_PATH: str = "/data/raw"

    # Scanner DSL version — bump on breaking DSL changes
    SCANNER_DSL_VERSION: int = 1

    # ── Locale / market ──────────────────────────────────────────────────────
    # All time comparisons, schedule specs, and display must use these values.
    # Never hardcode "Asia/Kolkata", "+05:30", or "09:15" anywhere else.
    TIMEZONE: str = "Asia/Kolkata"          # IANA timezone for IST
    MARKET_OPEN_IST: str = "09:15"          # NSE session open (HH:MM, IST)
    MARKET_CLOSE_IST: str = "15:30"         # NSE session close (HH:MM, IST)

    # ── Daily refresh schedule ────────────────────────────────────────────────
    # Cron expressed in TIMEZONE (IST).  16:45 = 45 min after market close.
    DAILY_REFRESH_CRON: str = "45 16 * * 1-5"   # Mon–Fri 4:45 PM IST
    DAILY_REFRESH_GAP_DAYS: int = 30             # how many days back to scan for gaps
    DAILY_REFRESH_CONCURRENCY: int = 8           # parallel symbol fetches
    DAILY_REFRESH_CATCHUP_HOURS: int = 36        # catch up missed runs within this window

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
