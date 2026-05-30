from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncIterator, Protocol, runtime_checkable

@dataclass(frozen=True)
class Quote:
    """Represents a financial quote."""
    symbol: str
    ltp: float
    open: float
    high: float
    low: float
    close: float
    volume: float
    ts: datetime

    def to_dict(self) -> dict[str, str | float]:
        """Returns a dictionary representation of the quote, with ts as ISO format string."""
        return {
            "symbol": self.symbol,
            "ltp": self.ltp,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "ts": self.ts.isoformat(),
        }

def broker_prefix(symbol: str) -> str:
    """
    Extracts the exchange prefix from a market symbol (e.g., "NSE:RELIANCE" -> "NSE").
    Returns "" if no colon is found.
    """
    if ":" in symbol:
        return symbol.split(":")[0]
    return ""

@runtime_checkable
class BrokerAdapter(Protocol):
    """
    A protocol defining the interface for connecting to a financial market data source.
    """
    name: str
    prefixes: list[str]

    async def connect(self) -> None:
        """Establishes the connection to the broker."""
        ...

    async def subscribe(self, symbols: list[str]) -> None:
        """Subscribes to real-time updates for the given list of symbols."""
        ...

    async def unsubscribe(self, symbols: list[str]) -> None:
        """Unsubscribes from updates for the given list of symbols."""
        ...

    async def quotes(self) -> AsyncIterator[Quote]:
        """Asynchronously yields Quote objects as they become available."""
        ...

    async def disconnect(self) -> None:
        """Cleans up and closes the connection."""
        ...
