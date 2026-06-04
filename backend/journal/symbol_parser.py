# backend/journal/symbol_parser.py
import re, calendar
from dataclasses import dataclass
from datetime import date
from typing import Optional
from .config import get_lot_size

_MON3 = {"JAN":1,"FEB":2,"MAR":3,"APR":4,"MAY":5,"JUN":6,
          "JUL":7,"AUG":8,"SEP":9,"OCT":10,"NOV":11,"DEC":12}
_KITE_MON = {**{str(i):i for i in range(1,10)}, "O":10,"N":11,"D":12}

@dataclass
class ParsedSymbol:
    underlying: str; exchange: str; segment: str; instrument: str
    symbol: str; raw: str
    strike: Optional[int] = None; option_type: Optional[str] = None
    expiry: Optional[date] = None
    lot_size: Optional[int] = None; lots: Optional[int] = None


def parse_symbol(raw: str, broker: str = "unknown", quantity: int = 0) -> ParsedSymbol:
    s = raw.strip().upper()
    # Strip mStock prefixes: "BSXOPT SENSEX2660473600CE 1127872 (BT)"
    s = re.sub(r'^(BSXOPT|BSXFUT|NSXOPT|NSXFUT)\s+', '', s)
    s = re.sub(r'\s+\d+\s*\(BT\)\s*$', '', s).strip()

    # Lemonn verbose: "OPTIDX SENSEX 14MAY2026 74200 PE-BSE"
    m = re.match(
        r'^(OPTIDX|FUTIDX|OPTSTK|FUTSTK)\s+(\w+)\s+'
        r'(\d{2}(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{4})\s+'
        r'(\d+)\s+(CE|PE)(?:-(NSE|BSE|MCX))?$', s)
    if m:
        inst, und, exp_str, strike, opt, exch = m.groups()
        expiry = _ddmonyyyy(exp_str)
        exchange = exch or ("BSE" if und in ("SENSEX","BANKEX") else "NSE")
        return _make(raw, und, exchange, inst, expiry, int(strike), opt, quantity)

    # Zerodha annexure with date suffix: "NIFTY2660923200PE / 09 JUNE 2026"
    m = re.match(r'^(\S+)\s*/\s*(\d{2}\s+\w+\s+\d{4})$', s)
    if m:
        compact, date_str = m.groups()
        p = _compact(compact, broker, quantity)
        if p:
            p.expiry = _dd_mon_yyyy(date_str.strip())
            p.symbol = _canonical(p.underlying, p.strike, p.option_type, p.expiry)
            return p

    # Compact with exchange suffix: "NIFTY2660923200PE - NSE"
    m = re.match(r'^(\S+)\s*-\s*(NSE|BSE|MCX)$', s)
    if m:
        compact, exch = m.groups()
        p = _compact(compact, broker, quantity)
        if p: p.exchange = exch; return p

    # Pure compact (mStock bare symbol)
    p = _compact(s, broker, quantity)
    if p: return p

    # Equity fallback
    if re.match(r'^[A-Z&]+$', s):
        return ParsedSymbol(underlying=s, exchange="NSE", segment="EQ",
                            instrument="EQ", symbol=s, raw=raw, lot_size=1, lots=quantity)

    return ParsedSymbol(underlying=s, exchange="NSE", segment="EQ",
                        instrument="EQ", symbol=s, raw=raw)


def _compact(s: str, broker: str, qty: int) -> Optional["ParsedSymbol"]:
    # IMPORTANT: Try single-char-month FIRST (before YYMMDD).
    # YYMMDD regex would parse month=60 from "2660..." which is invalid.
    # Single-char-month: NIFTY2660923200PE → yy=26, M=6=June, dd=09, strike=23200, PE
    m = re.match(r'^([A-Z&]+?)(\d{2})([A-Z1-9])(\d{2})(\d+)(CE|PE)$', s)
    if m:
        und, yy, mon_c, dd, strike, opt = m.groups()
        month = _KITE_MON.get(mon_c)
        if month:
            try:
                expiry = date(2000+int(yy), month, int(dd))
                exch = "BSE" if und in ("SENSEX","BANKEX") else "NSE"
                return _make(s, und, exch, "OPTIDX", expiry, int(strike), opt, qty)
            except ValueError: pass

    # YYMMDD weekly (fallback): only if month digit is valid (1-12)
    m = re.match(r'^([A-Z&]+?)(\d{2})(\d{2})(\d{2})(\d+)(CE|PE)$', s)
    if m:
        und, yy, mm, dd, strike, opt = m.groups()
        try:
            expiry = date(2000+int(yy), int(mm), int(dd))
            exch = "BSE" if und in ("SENSEX","BANKEX") else "NSE"
            return _make(s, und, exch, "OPTIDX", expiry, int(strike), opt, qty)
        except ValueError: pass

    # Monthly: NIFTY26JUN23200PE
    m = re.match(r'^([A-Z&]+?)(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d+)(CE|PE)$', s)
    if m:
        und, yy, mon3, strike, opt = m.groups()
        expiry = _last_thu(2000+int(yy), _MON3[mon3])
        return _make(s, und, "NSE", "OPTIDX", expiry, int(strike), opt, qty)

    # Futures
    m = re.match(r'^([A-Z&]+?)(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)FUT$', s)
    if m:
        und, yy, mon3 = m.groups()
        expiry = _last_thu(2000+int(yy), _MON3[mon3])
        ls = get_lot_size(und)
        return ParsedSymbol(underlying=und, exchange="NSE", segment="FO",
                            instrument="FUTIDX", raw=s, expiry=expiry,
                            symbol=f"{und} FUT {expiry}", lot_size=ls,
                            lots=qty//ls if ls else None)
    return None


def _make(raw, und, exch, inst, expiry, strike, opt, qty) -> "ParsedSymbol":
    ls = get_lot_size(und)
    return ParsedSymbol(underlying=und, exchange=exch, segment="FO", instrument=inst,
                        raw=raw, symbol=_canonical(und, strike, opt, expiry),
                        strike=strike, option_type=opt, expiry=expiry,
                        lot_size=ls, lots=qty//ls if ls else None)

def _canonical(und, strike, opt, expiry) -> str:
    if opt:    return f"{und} {strike} {opt} {expiry}"
    if expiry: return f"{und} FUT {expiry}"
    return und

def _ddmonyyyy(s: str) -> date:
    m = re.match(r'^(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{4})$', s)
    if m: dd, mon, yyyy = m.groups(); return date(int(yyyy), _MON3[mon], int(dd))
    raise ValueError(s)

def _dd_mon_yyyy(s: str) -> date:
    parts = s.upper().split()
    if len(parts) == 3:
        dd, mon_name, yyyy = parts
        for i, name in enumerate(calendar.month_name):
            if name and name.upper().startswith(mon_name[:3]):
                return date(int(yyyy), i, int(dd))
    raise ValueError(s)

def _last_thu(year: int, month: int) -> date:
    last = calendar.monthrange(year, month)[1]
    d = date(year, month, last)
    while d.weekday() != 3: d = date(year, month, d.day - 1)
    return d
