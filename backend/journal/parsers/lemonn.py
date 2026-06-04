# backend/journal/parsers/lemonn.py
import re
from datetime import date
from decimal import Decimal
from ..models import Trade
from ..symbol_parser import parse_symbol
from ..force_square import is_force_squared

_DATE_RE    = re.compile(r'Trade\s+Date\s*:\s*(\d{2}/\d{2}/\d{4})', re.IGNORECASE)
_NOTE_RE    = re.compile(r'CONTRACT\s+NOTE\s+NO\s*:\s*(\d+)', re.IGNORECASE)
_REVISED_RE = re.compile(r'REVISED|SUPPLEMENTARY', re.IGNORECASE)

_SKIP_HEADERS = {"security", "description", "b/s", "qty", "quantity", "net total",
                 "brokerage", "wap", "closing", "remarks", "particulars", ""}

def _clean(v: str | None) -> str:
    return (v or "").strip().replace("\n", " ").replace(",", "")

def _decimal(v: str | None) -> Decimal:
    s = _clean(v).lstrip("(").rstrip(")")
    try: return Decimal(s) if s else Decimal(0)
    except: return Decimal(0)

def parse(rows: list[list[str | None]], text: str = "", source_file: str = "") -> list[Trade]:
    d_m = _DATE_RE.search(text)
    from datetime import datetime
    trade_date = datetime.strptime(d_m.group(1), "%d/%m/%Y").date() if d_m else date.today()
    n_m = _NOTE_RE.search(text)
    note_no = n_m.group(1) if n_m else None
    is_revised = bool(_REVISED_RE.search(text))
    global_fsq = bool(re.search(r'squaring off|non-compliance of margin', text, re.IGNORECASE))

    trades = []
    for row in rows:
        if len(row) < 4:
            continue
        contract = _clean(row[0])
        if not contract or contract.lower() in _SKIP_HEADERS:
            continue
        if not re.match(r'^(OPTIDX|FUTIDX|OPTSTK|FUTSTK)', contract, re.IGNORECASE):
            continue
        bs = _clean(row[1]).upper()
        if bs not in ("B", "S", "BUY", "SELL"):
            continue
        side = "BUY" if bs.startswith("B") else "SELL"
        raw_qty = _clean(row[2])
        qty = abs(int(raw_qty)) if raw_qty.lstrip("-").isdigit() else 0
        if qty == 0:
            continue
        price = _decimal(row[4])   # col[4] = WAP Per Unit (Rs); col[3] = foreign currency WAP
        # Lemonn flat ₹20 brokerage per order
        brokerage = Decimal("20")
        remark_col = _clean(row[9]) if len(row) > 9 else None
        fsq = global_fsq or is_force_squared(remark_col, "lemonn")

        ps = parse_symbol(contract, broker="lemonn", quantity=qty)

        trades.append(Trade(
            broker="lemonn", source="pdf", source_format="pdf", fill_grain="wap",
            source_file=source_file, contract_note_no=note_no, is_revised=is_revised,
            trade_date=trade_date, trade_time=None, trade_id=None,
            order_no=None, order_time=None,
            symbol=ps.symbol, raw_symbol=contract, underlying=ps.underlying,
            exchange=ps.exchange, segment=ps.segment,
            strike=ps.strike, option_type=ps.option_type, expiry=ps.expiry,
            instrument=ps.instrument,
            trade_type=side, quantity=qty, lot_size=ps.lot_size, lots=ps.lots,
            price=price, brokerage=brokerage,
            status="filled", remark=remark_col, is_force_squared=fsq,
        ))
    return trades
