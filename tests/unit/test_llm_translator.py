import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from llm.translator import translate_nl_to_dsl
from llm.budget import check_budget, increment_budget


@pytest.mark.asyncio
async def test_translate_uses_cache_on_hit():
    mock_redis = AsyncMock()
    mock_redis.get.return_value = '{"version":1,"source":{"name":"nse_universe"},"filters":[]}'

    with patch("llm.translator.get_redis", return_value=mock_redis):
        result = await translate_nl_to_dsl("show me NSE stocks")

    assert result["source"]["name"] == "nse_universe"
    mock_redis.get.assert_called_once()


@pytest.mark.asyncio
async def test_budget_exceeded_raises():
    mock_redis = AsyncMock()
    mock_redis.get.return_value = "150000"  # over 100k budget

    with patch("llm.budget.get_redis", return_value=mock_redis):
        with pytest.raises(Exception, match="budget"):
            await check_budget(50000)


@pytest.mark.asyncio
async def test_translate_builds_valid_dsl(monkeypatch):
    mock_tool_result = {
        "source": {"name": "nse_universe"},
        "filters": [{"field": "exchange", "op": "eq", "value": "NSE"}],
        "indicators": ["rsi"],
        "sort": {"field": "rsi", "descending": False},
    }

    mock_redis = AsyncMock()
    mock_redis.get.return_value = None

    mock_content = MagicMock()
    mock_content.type = "tool_use"
    mock_content.name = "set_source"
    mock_content.input = {"source": "nse_universe"}

    with patch("llm.translator.get_redis", return_value=mock_redis), \
         patch("llm.translator._build_dsl_from_tool_calls", return_value=mock_tool_result), \
         patch("llm.translator._call_claude", return_value=[mock_content]), \
         patch("llm.budget.get_redis", return_value=mock_redis):
        result = await translate_nl_to_dsl("NSE stocks with RSI below 30")

    assert "source" in result
