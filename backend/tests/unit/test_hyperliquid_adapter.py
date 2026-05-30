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
