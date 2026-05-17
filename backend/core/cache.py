from redis.asyncio import Redis
from core.config import settings

_redis: Redis | None = None


def get_redis() -> Redis:
    global _redis
    if _redis is None:
        _redis = Redis.from_url(settings.REDIS_URL, decode_responses=True, health_check_interval=30)
    return _redis


def cache_key(*parts: object) -> str:
    """Build versioned cache key: ta:v1:indicators:RELIANCE:1min"""
    return f"ta:{settings.SCHEMA_VERSION}:{':'.join(str(p) for p in parts)}"
