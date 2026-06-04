# backend/journal/parsers/kite.py
from datetime import date, datetime, time
from decimal import Decimal
from ..models import Trade
from ..symbol_parser import parse_symbol

class KiteParser:
    broker = "kite"

    def __init__(self, sdk):
        self._sdk = sdk

    async def fetch_today(self) -> list[Trade]:
        raw = await self._sdk.kite_get_trades()
        return self.parse_raw(raw, date.today())

    def parse_raw(self, raw: list[dict], trade_date: date) -> list[Trade]:
        trades = []
        for r in raw:
            sym = r.get("tradingsymbol", "")
            qty = int(r.get("quantity", 0))
            ps = parse_symbol(sym, broker="kite", quantity=qty)
            ts = r.get("order_execution_time") or r.get("fill_timestamp") or ""
            t = _parse_time(ts)
            trades.append(Trade(
                broker="kite", source="api", source_format="api", fill_grain="fill",
                order_no=r.get("order_id"),
                trade_id=r.get("trade_id"),
                trade_date=trade_date, trade_time=t,
                symbol=ps.symbol, raw_symbol=sym,
                underlying=ps.underlying,
                exchange=r.get("exchange", "NSE"),
                segment=_segment(r.get("segment", "FO")),
                trade_type=r.get("transaction_type", "BUY").upper(),
                quantity=qty, lot_size=ps.lot_size, lots=ps.lots,
                strike=ps.strike, option_type=ps.option_type,
                expiry=ps.expiry, instrument=ps.instrument,
                price=Decimal(str(r.get("average_price", 0))),
                brokerage=Decimal("20"),
                status="filled",
            ))
        return trades

def _parse_time(s: str) -> time | None:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M:%S"):
        try: return datetime.strptime(s, fmt).time()
        except: pass
    return None

def _segment(s: str) -> str:
    return "FO" if "FO" in s.upper() or "F&O" in s.upper() else "EQ"
