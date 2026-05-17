import os
import pytest

# Must be set before any module imports Settings
os.environ.setdefault("POSTGRES_URL", "postgresql+asyncpg://test:test@localhost/test")
os.environ.setdefault("QUESTDB_URL", "postgresql://test:test@localhost:8812/qdb")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("TEMPORAL_HOST", "localhost:7233")
os.environ.setdefault("JWT_SECRET", "x" * 32)
os.environ.setdefault("ADMIN_USERNAME", "admin")
os.environ.setdefault("ADMIN_PASSWORD_HASH", "$2b$12$placeholder")
os.environ.setdefault("PARQUET_BASE_PATH", "/data/raw")
