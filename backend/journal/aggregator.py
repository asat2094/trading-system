# backend/journal/aggregator.py
from collections import defaultdict
from decimal import Decimal
from .models import Trade, TradePair, DaySummary

def _fiscal_year(d) -> str:
    y, m = d.year, d.month
    if m >= 4: return f"{y}-{str(y+1)[2:]}"
    return f"{y-1}-{str(y)[2:]}"

def build_day_summary(
    trades: list[Trade],
    pairs: list[TradePair],
    broker: str | None = None,
) -> DaySummary:
    if not trades:
        raise ValueError("No trades")
    trade_date = trades[0].trade_date

    times = [t.trade_time for t in trades if t.trade_time and t.status == "filled"]
    first = min(times) if times else None
    last  = max(times) if times else None

    filled = [t for t in trades if t.status == "filled"]
    order_nos = {t.order_no for t in filled if t.order_no}

    buckets: dict[str, float] = defaultdict(float)
    for p in pairs:
        if p.net_pnl is not None and p.close_time:
            hh = p.close_time.hour
            mm = 0 if p.close_time.minute < 30 else 30
            buckets[f"{hh:02d}:{mm:02d}"] += float(p.net_pnl)

    holds = [p.hold_seconds for p in pairs if p.hold_seconds is not None]
    avg_hold = int(sum(holds) / len(holds)) if holds else None

    closed = [p for p in pairs if p.net_pnl is not None]
    gross_pnl = sum((p.gross_pnl or Decimal(0)) for p in closed)
    total_charges = sum((p.charges.total if p.charges else Decimal(0)) for p in closed)
    net_pnl = sum((p.net_pnl or Decimal(0)) for p in closed)
    total_brok = sum(t.brokerage for t in filled)
    total_lots = sum(t.lots or 0 for t in filled)

    return DaySummary(
        trade_date=trade_date,
        broker=broker,
        fiscal_year=_fiscal_year(trade_date),
        total_fills=len(filled),
        total_orders=len(order_nos),
        total_lots=total_lots,
        failed_order_count=sum(1 for t in trades if t.status == "rejected"),
        force_squared_count=sum(1 for t in filled if t.is_force_squared),
        first_trade_time=first,
        last_trade_time=last,
        avg_hold_seconds=avg_hold,
        time_bucket_pnl=dict(buckets),
        gross_pnl=Decimal(str(round(float(gross_pnl), 2))),
        total_brokerage=total_brok,
        total_charges=Decimal(str(round(float(total_charges), 2))),
        net_pnl=Decimal(str(round(float(net_pnl), 2))),
        win_pairs=sum(1 for p in closed if (p.net_pnl or 0) > 0),
        loss_pairs=sum(1 for p in closed if (p.net_pnl or 0) < 0),
        open_pairs=sum(1 for p in pairs if p.close_date is None),
    )
