from brokers.hyperliquid import HyperliquidAdapter
import pytest

def test_to_hl_coin():
    """Tests converting a standard coin string to the Hyperliquid format."""
    assert HyperliquidAdapter._to_hl_coin("CRYPTO:BTC") == "BTC"

def test_from_hl_coin():
    """Tests converting a Hyperliquid coin format back to a standard coin string."""
    assert HyperliquidAdapter._from_hl_coin("BTC") == "CRYPTO:BTC"

def test_to_hl_coin_eth():
    """Tests conversion for ETH."""
    assert HyperliquidAdapter._to_hl_coin("CRYPTO:ETH") == "ETH"

def test_from_hl_coin_sol():
    """Tests conversion for SOL."""
    assert HyperliquidAdapter._from_hl_coin("SOL") == "CRYPTO:SOL"


@pytest.mark.asyncio
async def test_recv_loop_parses_nested_mids():
    """Verify _recv_loop extracts mids from data.mids (not top-level mids)."""
    import asyncio
    import json

    adapter = HyperliquidAdapter()
    adapter._running = True
    adapter._subscribed = {"BTC"}

    msg = json.dumps({
        "channel": "allMids",
        "data": {"mids": {"BTC": "107500.5", "ETH": "2500.0"}}
    })

    class FakeWS:
        def __init__(self, messages):
            self._msgs = iter(messages)
        def __aiter__(self):
            return self
        async def __anext__(self):
            try:
                return next(self._msgs)
            except StopIteration:
                raise StopAsyncIteration

    adapter._ws = FakeWS([msg])
    task = asyncio.create_task(adapter._recv_loop())
    await asyncio.sleep(0.05)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass

    assert not adapter._queue.empty()
    quote = adapter._queue.get_nowait()
    assert quote.symbol == "CRYPTO:BTC"
    assert quote.ltp == 107500.5
