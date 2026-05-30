from datetime import datetime, timezone
from brokers.base import Quote, broker_prefix
import pytest

@pytest.fixture
def sample_quote():
    """Provides a fully initialized Quote object for testing."""
    symbol = "NSE:RELIANCE"
    ltp = 2847.5
    open_price = 2831
    high_price = 2860
    low_price = 2820
    close_price = 2847
    volume = 1000000
    ts = datetime(2026, 5, 30, 9, 30, tzinfo=timezone.utc)
    
    return Quote(
        symbol=symbol,
        ltp=ltp,
        open=open_price,
        high=high_price,
        low=low_price,
        close=close_price,
        volume=volume,
        ts=ts
    )

def test_quote_fields(sample_quote: Quote):
    """Tests if the Quote object is correctly initialized with symbol and ltp."""
    assert sample_quote.symbol == "NSE:RELIANCE"
    assert sample_quote.ltp == 2847.5

def test_quote_to_dict(sample_quote: Quote):
    """Tests if the to_dict method correctly converts the timestamp to a string."""
    result = sample_quote.to_dict()
    # Assert that the 'ts' key exists and its value is a string
    assert "ts" in result
    assert isinstance(result["ts"], str)

def test_broker_prefix_nse():
    """Tests broker_prefix with a standard exchange prefix (NSE)."""
    assert broker_prefix("NSE:RELIANCE") == "NSE"

def test_broker_prefix_no_colon():
    """Tests broker_prefix when no exchange prefix is present."""
    assert broker_prefix("RELIANCE") == ""
