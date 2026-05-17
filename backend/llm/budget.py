from core.cache import get_redis, cache_key
from core.logging import get_logger

log = get_logger(__name__)


async def check_budget(tokens_needed: int) -> None:
    redis = get_redis()
    key = cache_key("llm_tokens", "daily")
    used_str = await redis.get(key)
    used = int(used_str) if used_str else 0

    from core.config import settings
    if used + tokens_needed > settings.LLM_DAILY_TOKEN_BUDGET:
        log.warning("llm_budget_exceeded", used=used, needed=tokens_needed)
        raise ValueError(
            f"Daily LLM budget reached ({used}/{settings.LLM_DAILY_TOKEN_BUDGET} tokens). "
            "Try scanner directly."
        )


async def increment_budget(tokens_used: int) -> None:
    redis = get_redis()
    key = cache_key("llm_tokens", "daily")
    await redis.incrby(key, tokens_used)
    await redis.expire(key, 86400)
