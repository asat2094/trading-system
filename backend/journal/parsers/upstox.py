# backend/journal/parsers/upstox.py
import httpx
from datetime import date, datetime, time
from decimal import Decimal
from ..models import Trade
from ..symbol_parser import parse_symbol

class UpstoxParser:
    broker = "upstox"
    _BASE = "https://api.upstox.com/v2"

    def __init__(self, access_token: str):
        self._headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }

    async def fetch_today(self) -> list[Trade]:
        async with httpx.AsyncClient() as c:
            r = await c.get(
                f"{self._BASE}/order/trades/get-trades-for-day",
                headers=self._headers,
            )
            r.raise_for_status()
        return self.parse_raw(r.json().get("data", []))

    async def fetch_history(self, segment: str, start: str, end: str) -> list[Trade]:
        trades = []
        page = 1
        async with httpx.AsyncClient() as c:
            while True:
                r = await c.get(
                    f"{self._BASE}/charges/historical-trades",
                    headers=self._headers,
                    params={"segment": segment, "start_date": start,
                            "end_date": end, "page_number": page, "page_size": 50},
                )
                r.raise_for_status()
                data = r.json().get("data", {})
                batch = data.get("trades", data.get("data", []))
                if not batch: break
                trades.extend(self.parse_raw(batch))
                page += 1
        return trades

    def parse_raw(self, raw: list[dict]) -> list[Trade]:
        trades = []
        for r in raw:
            sym = r.get("trading_symbol") or r.get("tradingsymbol", "")
            qty = int(r.get("quantity", 0))
            ps = parse_symbol(sym, broker="upstox", quantity=qty)
            t = _parse_time(r.get("order_execution_time", ""))
            td = _parse_date(r.get("trade_date", "")) or date.today()
            seg = r.get("segment", "")
            trades.append(Trade(
                broker="upstox", source="api", source_format="api", fill_grain="fill",
                order_no=r.get("order_id"),
                trade_id=r.get("trade_id"),
                trade_date=td, trade_time=t,
                symbol=ps.symbol, raw_symbol=sym,
                underlying=ps.underlying,
                exchange=r.get("exchange", "NSE"),
                segment="FO" if seg in ("FO", "NFO", "BFO") else "EQ",
                trade_type=(r.get("transaction_type") or "BUY").upper(),
                quantity=qty, lot_size=ps.lot_size, lots=ps.lots,
                strike=ps.strike, option_type=ps.option_type,
                expiry=ps.expiry, instrument=ps.instrument,
                price=Decimal(str(r.get("average_price") or r.get("trade_price", 0))),
                brokerage=Decimal("20"),
                status="filled",
            ))
        return trades

def _parse_time(s: str) -> time | None:
    for fmt in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
        try: return datetime.strptime(s.split("+")[0].split("Z")[0], fmt.rstrip("%z")).time()
        except: pass
    return None

def _parse_date(s: str) -> date | None:
    try: return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except: return None
