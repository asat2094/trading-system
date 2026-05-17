import json
import hashlib
from core.cache import get_redis, cache_key
from core.config import settings
from core.logging import get_logger
from llm.tools import TOOL_DEFINITIONS
from llm.budget import check_budget, increment_budget

log = get_logger(__name__)


async def translate_nl_to_dsl(nl_query: str) -> dict:
    redis = get_redis()
    query_hash = hashlib.sha256(nl_query.encode()).hexdigest()[:16]
    cache_k = cache_key("nlq", query_hash)
    cached = await redis.get(cache_k)
    if cached:
        log.info("llm_cache_hit", query_hash=query_hash)
        return json.loads(cached)

    await check_budget(2000)

    tool_calls = await _call_claude(nl_query)
    dsl = _build_dsl_from_tool_calls(tool_calls)

    await redis.setex(cache_k, 86400, json.dumps(dsl))
    await increment_budget(2000)

    log.info("llm_translate_complete", query_hash=query_hash, tools_called=len(tool_calls))
    return dsl


async def _call_claude(nl_query: str) -> list:
    import anthropic
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY.get_secret_value())
    system = _load_system_prompt()

    response = client.messages.create(
        model=settings.LLM_MODEL,
        max_tokens=1024,
        system=system,
        tools=TOOL_DEFINITIONS,
        messages=[{"role": "user", "content": nl_query}],
    )
    return [block for block in response.content if block.type == "tool_use"]


def _load_system_prompt() -> str:
    import pathlib
    prompt_dir = pathlib.Path(__file__).parent / "prompts" / settings.LLM_PROMPT_VERSION
    return (prompt_dir / "system.txt").read_text()


def _build_dsl_from_tool_calls(tool_calls: list) -> dict:
    from scanner.dsl import SCANNER_DSL_VERSION
    dsl: dict = {
        "version": SCANNER_DSL_VERSION,
        "source": {},
        "filters": [],
        "analysis": {},
        "indicators": [],
        "sort": {},
    }
    for call in tool_calls:
        name, inp = call.name, call.input
        if name == "set_source":
            dsl["source"] = inp
        elif name == "add_filter":
            dsl["filters"].append(inp)
        elif name == "add_indicator":
            dsl["indicators"].append(inp)
        elif name == "add_trend_analysis":
            dsl["analysis"] = inp
        elif name == "set_sort":
            dsl["sort"] = inp
    return dsl
