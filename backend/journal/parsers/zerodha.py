# backend/journal/parsers/zerodha.py
# Parses the per-fill annexure table (page 5+), NOT the WAP summary table (page 2).
# Annexure columns (13): Order No | Order Time | Trade No | Trade Time |
#   Contract / Expiry Date | B/S | Exchange | Qty | Brokerage (₹) |
#   Net Rate per Unit (₹) | Closing Rate | Net Total | Remarks
import re
from datetime import date, time, datetime
from decimal import Decimal
from ..models import Trade
from ..symbol_parser import parse_symbol
from ..force_square import is_force_squared

_DATE_RE    = re.compile(r'Trade\s+Date[:\s]+(\d{2}/\d{2}/\d{4})', re.IGNORECASE)
_NOTE_RE    = re.compile(r'Contract\s+Note\s+No[:\s]+(CNT-[\d/\-]+|\d+)', re.IGNORECASE)
_REVISED_RE = re.compile(r'REVISED|SUPPLEMENTARY', re.IGNORECASE)
_ORDER_NO   = re.compile(r'^\d{10,20}$')
_TIME_RE    = re.compile(r'^\d{2}:\d{2}:\d{2}$')


def _clean(v: str | None) -> str:
    return (v or "").strip().replace("\n", " ").replace(",", "")


def _decimal(v: str | None) -> Decimal:
    s = _clean(v).lstrip("(").rstrip(")")
    try: return Decimal(s) if s else Decimal(0)
    except: return Decimal(0)


def _t(s: str) -> time | None:
    try: return datetime.strptime(s.strip(), "%H:%M:%S").time()
    except: return None


def parse(rows: list[list[str | None]], text: str = "", source_file: str = "") -> list[Trade]:
    d_m = _DATE_RE.search(text)
    trade_date = datetime.strptime(d_m.group(1), "%d/%m/%Y").date() if d_m else date.today()
    n_m = _NOTE_RE.search(text)
    note_no = n_m.group(1) if n_m else None
    is_revised = bool(_REVISED_RE.search(text))

    trades: list[Trade] = []
    for row in rows:
        if len(row) < 10:
            continue
        order_no = _clean(row[0])
        if not _ORDER_NO.match(order_no):
            continue
        order_time_s = _clean(row[1])
        if not _TIME_RE.match(order_time_s):
            continue

        trade_no   = _clean(row[2])
        trade_time_s = _clean(row[3])
        contract   = _clean(row[4])
        bs         = _clean(row[5]).upper()
        exch       = _clean(row[6])
        qty_s      = _clean(row[7])
        brok_s     = _clean(row[8])
        price_s    = _clean(row[9])
        remark     = _clean(row[12]) if len(row) > 12 else None

        if bs not in ("B", "S"):
            continue
        side  = "BUY" if bs == "B" else "SELL"
        qty   = int(qty_s) if qty_s.isdigit() else 0
        if qty == 0:
            continue

        ps       = parse_symbol(contract, broker="zerodha", quantity=qty)
        if exch in ("NSE", "BSE", "MCX"):
            ps.exchange = exch
        brokerage = _decimal(brok_s)
        price     = _decimal(price_s)
        fsq       = is_force_squared(remark, "zerodha")

        trades.append(Trade(
            broker="zerodha", source="pdf", source_format="pdf", fill_grain="fill",
            source_file=source_file, contract_note_no=note_no, is_revised=is_revised,
            order_no=order_no, order_time=_t(order_time_s),
            trade_id=trade_no,
            trade_date=trade_date, trade_time=_t(trade_time_s),
            symbol=ps.symbol, raw_symbol=contract, underlying=ps.underlying,
            exchange=ps.exchange, segment=ps.segment,
            strike=ps.strike, option_type=ps.option_type, expiry=ps.expiry,
            instrument=ps.instrument,
            trade_type=side, quantity=qty, lot_size=ps.lot_size, lots=ps.lots,
            price=price, brokerage=brokerage,
            status="filled", remark=remark, is_force_squared=fsq,
        ))
    return trades
