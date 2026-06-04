# backend/journal/parsers/mstock_api.py
import httpx
from datetime import date, datetime, time
from decimal import Decimal
from ..models import Trade
from ..symbol_parser import parse_symbol

class MStockApiParser:
    broker = "mstock"
    _BASE = "https://api.mstock.trade/openapi/typeb"

    def __init__(self, jwt_token: str, api_key: str):
        self._headers = {
            "X-Mirae-Version": "1",
            "Authorization": f"Bearer {jwt_token}",
            "X-PrivateKey": api_key,
        }

    async def fetch_today(self) -> list[Trade]:
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{self._BASE}/tradebook", headers=self._headers)
            r.raise_for_status()
        return self.parse_raw(r.json().get("data", {}).get("tradebook", []))

    async def fetch_orders(self) -> list[Trade]:
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{self._BASE}/orderbook", headers=self._headers)
            r.raise_for_status()
        orders = r.json().get("data", {}).get("orderbook", [])
        trades = []
        for o in orders:
            if o.get("status", "").lower() not in ("rejected", "cancelled"):
                continue
            ps = parse_symbol(o.get("tradingsymbol", ""), broker="mstock")
            trades.append(Trade(
                broker="mstock", source="api", source_format="api", fill_grain="fill",
                order_no=o.get("order_id"),
                trade_date=date.today(),
                symbol=ps.symbol, raw_symbol=o.get("tradingsymbol", ""),
                underlying=ps.underlying,
                exchange=o.get("exchange", "BSE"),
                segment="FO",
                trade_type=(o.get("transaction_type") or "BUY").upper(),
                quantity=0, price=Decimal("5"),
                status="rejected",
                remark=o.get("status_message"),
            ))
        return trades

    def parse_raw(self, raw: list[dict]) -> list[Trade]:
        trades = []
        for r in raw:
            sym = r.get("tradingsymbol", "")
            qty = int(r.get("quantity", 0))
            ps = parse_symbol(sym, broker="mstock", quantity=qty)
            t = _parse_time(r.get("trade_time") or r.get("fill_timestamp", ""))
            brok = Decimal("0.25") * qty
            trades.append(Trade(
                broker="mstock", source="api", source_format="api", fill_grain="fill",
                order_no=r.get("order_id"),
                trade_id=r.get("trade_id"),
                trade_date=date.today(), trade_time=t,
                symbol=ps.symbol, raw_symbol=sym,
                underlying=ps.underlying,
                exchange=r.get("exchange", "BSE"),
                segment="FO",
                trade_type=(r.get("transaction_type") or "BUY").upper(),
                quantity=qty, lot_size=ps.lot_size, lots=ps.lots,
                strike=ps.strike, option_type=ps.option_type,
                expiry=ps.expiry, instrument=ps.instrument,
                price=Decimal(str(r.get("average_price", 0))),
                brokerage=brok,
                status="filled",
            ))
        return trades

def _parse_time(s: str) -> time | None:
    for fmt in ("%H:%M:%S", "%d-%m-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try: return datetime.strptime(s, fmt).time()
        except: pass
    return None
