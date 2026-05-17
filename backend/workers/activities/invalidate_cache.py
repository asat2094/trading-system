from temporalio import activity
from core.logging import get_logger
from core.cache import get_redis

log = get_logger(__name__)


@activity.defn(name="invalidate_cache")
async def activity_fn(patterns: list[str] | None = None) -> dict:
    if patterns is None:
        patterns = ["ta:v1:indicators:*", "ta:v1:scan:*"]
    redis = get_redis()
    total_deleted = 0

    for pattern in patterns:
        cursor = 0
        while True:
            cursor, keys = await redis.scan(cursor, match=pattern, count=100)
            if keys:
                await redis.delete(*keys)
                total_deleted += len(keys)
            if cursor == 0:
                break

    log.info("cache_invalidated", keys_deleted=total_deleted, patterns=patterns)
    return {"deleted": total_deleted}
