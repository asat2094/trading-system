# backend/journal/parsers/mstock.py
# Parses the per-fill annexure tables (pages 3+), NOT the WAP summary table (page 1).
# Annexure columns (14, merged cells — all fills for one symbol per table row):
#   Order No | Order Time | Trade No | Trade Time | Remark/Segment |
#   Contract Description | B/S | Qty | Gross Rate (foreign) | Gross Rate (Rs) |
#   Brokerage Per Unit | Net Rate Per Unit | Closing Rate | Net Total
import re
from datetime import date, time, datetime
from decimal import Decimal
from ..models import Trade
from ..symbol_parser import parse_symbol
from ..force_square import is_force_squared

_DATE_RE    = re.compile(r'TRADE\s+DATE[:\s]+([\w]+\s+\d{1,2}\s+\d{4})', re.IGNORECASE)
_NOTE_RE    = re.compile(r'CONTRACT\s+NOTE\s+NO[.\s:]+(\d+)', re.IGNORECASE)
_REVISED_RE = re.compile(r'REVISED|SUPPLEMENTARY', re.IGNORECASE)


def _clean(v: str | None) -> str:
    return (v or "").strip().replace(",", "")


def _decimal(v: str | None) -> Decimal:
    s = _clean(v).lstrip("(").rstrip(")")
    try: return Decimal(s) if s else Decimal(0)
    except: return Decimal(0)


def _split_cell(v: str | None) -> list[str]:
    return [x.strip() for x in (v or "").split("\n") if x.strip()]


def _t(s: str) -> time | None:
    try: return datetime.strptime(s.strip(), "%H:%M:%S").time()
    except: return None


def parse(rows: list[list[str | None]], text: str = "", source_file: str = "") -> list[Trade]:
    from datetime import datetime as dt
    d_m = _DATE_RE.search(text)
    if d_m:
        try: trade_date = dt.strptime(d_m.group(1).strip(), "%b %d %Y").date()
        except: trade_date = date.today()
    else:
        trade_date = date.today()
    n_m = _NOTE_RE.search(text)
    note_no = n_m.group(1) if n_m else None
    is_revised = bool(_REVISED_RE.search(text))

    trades: list[Trade] = []
    for row in rows:
        if len(row) < 10:
            continue
        # Detect annexure data row: col[5] has BSXOPT symbol, col[6] has B/S values
        contracts = _split_cell(row[5])
        if not contracts or not any(re.search(r'(BSXOPT|NSXOPT)', c, re.IGNORECASE) for c in contracts):
            continue

        # Get the symbol — first valid BSXOPT entry in the contract column
        symbol_raw = next((c for c in contracts if re.search(r'(BSXOPT|NSXOPT)', c, re.IGNORECASE)), "")
        if not symbol_raw:
            continue

        order_nos   = _split_cell(row[0])
        order_times = _split_cell(row[1])
        trade_nos   = _split_cell(row[2])
        trade_times = _split_cell(row[3])
        sides       = _split_cell(row[6])
        qtys        = _split_cell(row[7])
        prices      = _split_cell(row[9])   # Gross Rate (Rs) — col[8] is foreign currency
        broks       = _split_cell(row[10]) if len(row) > 10 else []
        remarks     = _split_cell(row[4])   # Remark/Segment

        for i, bs in enumerate(sides):
            bs = bs.upper()
            if bs not in ("BUY", "SELL", "B", "S"):
                continue
            side = "BUY" if bs.startswith("B") else "SELL"
            raw_qty = qtys[i] if i < len(qtys) else "0"
            qty = abs(int(raw_qty)) if raw_qty.lstrip("-").isdigit() else 0

            price      = _decimal(prices[i] if i < len(prices) else None)
            brok_unit  = _decimal(broks[i] if i < len(broks) else None)
            remark     = remarks[i] if i < len(remarks) else None
            order_no   = order_nos[i] if i < len(order_nos) else None
            order_time = _t(order_times[i]) if i < len(order_times) else None
            trade_no   = trade_nos[i] if i < len(trade_nos) else None
            trade_time = _t(trade_times[i]) if i < len(trade_times) else None

            # Rejected orders: qty=0, net_total=-5 (₹5 penalty charge)
            if qty == 0:
                ps = parse_symbol(symbol_raw.strip(), broker="mstock")
                trades.append(Trade(
                    broker="mstock", source="pdf", source_format="pdf", fill_grain="fill",
                    source_file=source_file, contract_note_no=note_no, is_revised=is_revised,
                    order_no=order_no, order_time=order_time,
                    trade_id=trade_no, trade_date=trade_date, trade_time=trade_time,
                    symbol=ps.symbol, raw_symbol=symbol_raw.strip(),
                    underlying=ps.underlying, exchange=ps.exchange, segment=ps.segment or "FO",
                    strike=ps.strike, option_type=ps.option_type, expiry=ps.expiry,
                    instrument=ps.instrument,
                    trade_type=side, quantity=0, price=Decimal("5"),
                    status="rejected", remark=remark,
                ))
                continue

            if brok_unit == 0:
                brok_unit = Decimal("0.25")
            brokerage = brok_unit * qty
            ps = parse_symbol(symbol_raw.strip(), broker="mstock", quantity=qty)
            fsq = is_force_squared(remark, "mstock")

            trades.append(Trade(
                broker="mstock", source="pdf", source_format="pdf", fill_grain="fill",
                source_file=source_file, contract_note_no=note_no, is_revised=is_revised,
                order_no=order_no, order_time=order_time,
                trade_id=trade_no, trade_date=trade_date, trade_time=trade_time,
                symbol=ps.symbol, raw_symbol=symbol_raw.strip(), underlying=ps.underlying,
                exchange=ps.exchange, segment=ps.segment,
                strike=ps.strike, option_type=ps.option_type, expiry=ps.expiry,
                instrument=ps.instrument,
                trade_type=side, quantity=qty, lot_size=ps.lot_size, lots=ps.lots,
                price=price, brokerage=brokerage,
                status="filled", remark=remark, is_force_squared=fsq,
            ))
    return trades
