# backend/journal/matcher.py
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, time, datetime
from decimal import Decimal
from .models import Trade, TradePair, Charges
from .charges import compute_pair_charges

@dataclass
class _Lot:
    trade_ids: list[int]
    qty: int
    price: Decimal
    open_date: date
    open_time: time | None
    brokerage: Decimal
    broker: str
    force_squared: bool = False

def match_all_symbols(trades: list[Trade]) -> list[TradePair]:
    by_key: dict[tuple, list[Trade]] = defaultdict(list)
    for t in trades:
        by_key[(t.broker, t.symbol)].append(t)
    return [p for ts in by_key.values() for p in _match(ts)]

def _match(trades: list[Trade]) -> list[TradePair]:
    trades = sorted(trades, key=lambda t: (
        t.trade_date, t.trade_time or time(0, 0, 0), t.id or 0))
    long_q: deque[_Lot] = deque()
    short_q: deque[_Lot] = deque()
    pairs: list[TradePair] = []

    for t in trades:
        if t.status != "filled": continue
        lot = _Lot(
            trade_ids=[t.id] if t.id else [],
            qty=t.quantity, price=t.price,
            open_date=t.trade_date, open_time=t.trade_time,
            brokerage=t.brokerage, broker=t.broker,
            force_squared=t.is_force_squared,
        )
        rem = t.quantity
        if t.trade_type == "BUY":
            while rem > 0 and short_q:
                e = short_q[0]; fill = min(rem, e.qty)
                pairs.append(_close(e, t, fill, "SHORT"))
                e.qty -= fill; rem -= fill
                if e.qty == 0: short_q.popleft()
            if rem > 0:
                lot.qty = rem; long_q.append(lot)
        else:
            while rem > 0 and long_q:
                e = long_q[0]; fill = min(rem, e.qty)
                pairs.append(_close(e, t, fill, "LONG"))
                e.qty -= fill; rem -= fill
                if e.qty == 0: long_q.popleft()
            if rem > 0:
                lot.qty = rem; short_q.append(lot)

    t0 = trades[0] if trades else None
    for side, q in [("LONG", long_q), ("SHORT", short_q)]:
        for lot in q:
            pairs.append(TradePair(
                broker=lot.broker,
                symbol=t0.symbol, underlying=t0.underlying,
                exchange=t0.exchange, segment=t0.segment,
                side=side, quantity=lot.qty,
                lot_size=t0.lot_size,
                lots=(lot.qty // t0.lot_size) if t0.lot_size else None,
                open_date=lot.open_date, open_time=lot.open_time,
                entry_price=lot.price, entry_trade_ids=lot.trade_ids,
                force_squared=lot.force_squared,
            ))
    return pairs

def _close(entry: _Lot, exit_t: Trade, qty: int, side: str) -> TradePair:
    ep = entry.price if side == "LONG" else exit_t.price
    xp = exit_t.price if side == "LONG" else entry.price
    gross = (xp - ep) * qty
    intraday = entry.open_date == exit_t.trade_date
    charges = compute_pair_charges(
        exit_t.segment, exit_t.exchange, qty, ep, xp,
        entry.brokerage, exit_t.brokerage, intraday,
        is_option=(exit_t.option_type is not None),
    )
    hold_s = None
    if entry.open_time and exit_t.trade_time:
        e_dt = datetime.combine(entry.open_date, entry.open_time)
        x_dt = datetime.combine(exit_t.trade_date, exit_t.trade_time)
        hold_s = int((x_dt - e_dt).total_seconds())
    return TradePair(
        broker=entry.broker,
        symbol=exit_t.symbol, underlying=exit_t.underlying,
        strike=exit_t.strike, option_type=exit_t.option_type, expiry=exit_t.expiry,
        exchange=exit_t.exchange, segment=exit_t.segment,
        product_type=exit_t.product_type,
        side=side, quantity=qty, lot_size=exit_t.lot_size,
        lots=(qty // exit_t.lot_size) if exit_t.lot_size else None,
        open_date=entry.open_date, open_time=entry.open_time, entry_price=ep,
        entry_trade_ids=entry.trade_ids,
        close_date=exit_t.trade_date, close_time=exit_t.trade_time, exit_price=xp,
        exit_trade_ids=[exit_t.id] if exit_t.id else [],
        gross_pnl=gross, charges=charges, net_pnl=gross - charges.total,
        hold_seconds=hold_s, is_intraday=intraday,
        force_squared=(entry.force_squared or exit_t.is_force_squared),
    )
