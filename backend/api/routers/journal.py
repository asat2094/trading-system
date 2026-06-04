# backend/api/routers/journal.py
from __future__ import annotations
import json
import logging
from datetime import date
from fastapi import APIRouter, HTTPException, UploadFile, File, Query
from pydantic import BaseModel
import asyncpg
from decimal import Decimal
from journal.db import get_pool

router = APIRouter(prefix="/journal", tags=["journal"])
log = logging.getLogger(__name__)


# ── Import ────────────────────────────────────────────────────────────────────

@router.post("/import/pdf")
async def import_pdf(
    file: UploadFile = File(...),
    broker: str = Query("auto"),
    password: str | None = Query(None),
):
    from journal.parsers.pdf import parse_pdf_contract_note
    content = await file.read()
    try:
        trades = await parse_pdf_contract_note(
            content, broker=broker,
            source_file=file.filename or "",
            password=password,
        )
    except ValueError as e:
        raise HTTPException(422, str(e))

    pool = await get_pool()
    inserted = await _upsert_trades(pool, trades)
    affected = list({t.trade_date for t in trades})
    for dt in affected:
        await _recompute_day(pool, dt)
    return {"imported": len(trades), "inserted": inserted,
            "filename": file.filename, "dates": [str(d) for d in affected]}


class ApiImportRequest(BaseModel):
    broker: str
    from_date: str
    to_date: str

@router.post("/import/api")
async def import_api(req: ApiImportRequest):
    trades = []
    if req.broker in ("kite", "zerodha"):
        from journal.parsers.kite import KiteParser
        from core.sdk import get_sdk
        trades = await KiteParser(await get_sdk()).fetch_today()
    elif req.broker == "upstox":
        from journal.parsers.upstox import UpstoxParser
        from brokers.upstox import _get_access_token
        token = _get_access_token()
        if not token: raise HTTPException(400, "Upstox not connected")
        p = UpstoxParser(token)
        trades = await p.fetch_history("FO", req.from_date, req.to_date)
    else:
        raise HTTPException(400, f"Unsupported broker: {req.broker}")

    pool = await get_pool()
    inserted = await _upsert_trades(pool, trades)
    for dt in {t.trade_date for t in trades}:
        await _recompute_day(pool, dt)
    return {"imported": len(trades), "inserted": inserted}


# ── Queries ───────────────────────────────────────────────────────────────────

@router.get("/trades")
async def list_trades(
    from_date: str | None = None, to_date: str | None = None,
    broker: str | None = None, symbol: str | None = None,
    status: str | None = None,
):
    conds, args = ["1=1"], []
    if from_date: args.append(date.fromisoformat(from_date)); conds.append(f"trade_date >= ${len(args)}")
    if to_date:   args.append(date.fromisoformat(to_date));   conds.append(f"trade_date <= ${len(args)}")
    if broker:    args.append(broker);    conds.append(f"broker = ${len(args)}")
    if status:    args.append(status);    conds.append(f"status = ${len(args)}")
    if symbol:    args.append(f"%{symbol}%"); conds.append(f"symbol ILIKE ${len(args)}")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM jrn_trades WHERE {' AND '.join(conds)} "
            f"ORDER BY trade_date DESC, trade_time DESC NULLS LAST LIMIT 1000", *args)
    return [_to_dict(r) for r in rows]


@router.get("/pairs")
async def list_pairs(
    from_date: str | None = None, to_date: str | None = None,
    broker: str | None = None, symbol: str | None = None,
):
    conds, args = ["1=1"], []
    if from_date: args.append(date.fromisoformat(from_date)); conds.append(f"open_date >= ${len(args)}")
    if to_date:   args.append(date.fromisoformat(to_date));   conds.append(f"open_date <= ${len(args)}")
    if broker:    args.append(broker);    conds.append(f"broker = ${len(args)}")
    if symbol:    args.append(f"%{symbol}%"); conds.append(f"symbol ILIKE ${len(args)}")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM jrn_trade_pairs WHERE {' AND '.join(conds)} "
            f"ORDER BY open_date DESC, open_time DESC NULLS LAST LIMIT 500", *args)
    return [_to_dict(r, jsonb=("charges",)) for r in rows]


@router.get("/summary")
async def list_summaries(
    from_date: str | None = None, to_date: str | None = None,
    broker: str | None = None,
):
    conds, args = ["1=1"], []
    if from_date: args.append(date.fromisoformat(from_date)); conds.append(f"trade_date >= ${len(args)}")
    if to_date:   args.append(date.fromisoformat(to_date));   conds.append(f"trade_date <= ${len(args)}")
    if broker:    args.append(broker);    conds.append(f"broker = ${len(args)}")
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM jrn_day_summary WHERE {' AND '.join(conds)} "
            f"ORDER BY trade_date DESC", *args)
    return [_to_dict(r, jsonb=("time_bucket_pnl",)) for r in rows]


@router.post("/recompute")
async def recompute(trade_date: str):
    pool = await get_pool()
    await _recompute_day(pool, date.fromisoformat(trade_date))
    return {"recomputed": trade_date}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _to_dict(r, jsonb: tuple = ()) -> dict:
    d = dict(r)
    for f in jsonb:
        if d.get(f) and isinstance(d[f], str):
            try:
                d[f] = json.loads(d[f])
            except Exception:
                d[f] = None
    return d

async def _upsert_trades(pool: asyncpg.Pool, trades) -> int:
    inserted = 0
    async with pool.acquire() as conn:
        for t in trades:
            try:
                await conn.execute("""
                    INSERT INTO jrn_trades
                    (broker,source,source_format,fill_grain,source_file,
                     contract_note_no,is_revised,order_no,order_time,trade_id,
                     trade_date,trade_time,symbol,raw_symbol,underlying,
                     strike,option_type,expiry,instrument,exchange,segment,
                     product_type,trade_type,quantity,lot_size,lots,
                     price,brokerage,gross_amount,status,remark,is_force_squared)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,
                            $16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28,$29,$30,$31,$32)
                """,
                t.broker, t.source, t.source_format, t.fill_grain, t.source_file,
                t.contract_note_no, t.is_revised, t.order_no, t.order_time,
                t.trade_id, t.trade_date, t.trade_time,
                t.symbol, t.raw_symbol, t.underlying,
                t.strike, t.option_type, t.expiry, t.instrument,
                t.exchange, t.segment, t.product_type,
                t.trade_type, t.quantity, t.lot_size, t.lots,
                float(t.price), float(t.brokerage),
                float(t.gross_amount) if t.gross_amount else None,
                t.status, t.remark, t.is_force_squared)
                inserted += 1
            except asyncpg.UniqueViolationError:
                pass
            except Exception as e:
                log.debug("upsert skip: %s", e)
    return inserted


async def _recompute_day(pool: asyncpg.Pool, dt: date) -> None:
    from journal.matcher import match_all_symbols
    from journal.aggregator import build_day_summary
    from journal.models import Trade
    from decimal import Decimal

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM jrn_trades WHERE trade_date=$1 ORDER BY trade_time NULLS LAST, id", dt)
    if not rows: return

    trades = [_row_to_trade(r) for r in rows]
    pairs  = match_all_symbols([t for t in trades if t.status == "filled"])

    async with pool.acquire() as conn:
        await conn.execute(
            "DELETE FROM jrn_trade_pairs WHERE open_date=$1 OR close_date=$1", dt)
        for p in pairs:
            await conn.execute("""
                INSERT INTO jrn_trade_pairs
                (broker,symbol,underlying,strike,option_type,expiry,exchange,segment,
                 product_type,side,quantity,lots,lot_size,open_date,open_time,
                 entry_price,entry_trade_ids,close_date,close_time,exit_price,
                 exit_trade_ids,gross_pnl,charges,net_pnl,hold_seconds,is_intraday,force_squared)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,
                        $18,$19,$20,$21,$22,$23,$24,$25,$26,$27)
            """,
            p.broker, p.symbol, p.underlying, p.strike, p.option_type, p.expiry,
            p.exchange, p.segment, p.product_type,
            p.side, p.quantity, p.lots, p.lot_size,
            p.open_date, p.open_time, float(p.entry_price),
            p.entry_trade_ids,
            p.close_date, p.close_time,
            float(p.exit_price) if p.exit_price else None,
            p.exit_trade_ids,
            float(p.gross_pnl) if p.gross_pnl else None,
            json.dumps(p.charges.to_dict()) if p.charges else None,
            float(p.net_pnl) if p.net_pnl else None,
            p.hold_seconds, p.is_intraday, p.force_squared)

        # Build per-broker summaries + one combined (broker=None)
        brokers = list({t.broker for t in trades if t.status == "filled"})
        summaries_to_write = []
        for broker_name in brokers:
            broker_trades = [t for t in trades if t.broker == broker_name]
            broker_pairs  = [p for p in pairs if p.broker == broker_name]
            try:
                s = build_day_summary(broker_trades, broker_pairs, broker=broker_name)
                summaries_to_write.append(s)
            except ValueError:
                pass
        # Combined (broker=None) only when multiple brokers
        if len(brokers) > 1:
            try:
                summaries_to_write.append(build_day_summary(trades, pairs, broker=None))
            except ValueError:
                pass
        elif len(brokers) == 1 and summaries_to_write:
            # Single broker — combined IS per-broker, skip duplicate
            pass

        await conn.execute("DELETE FROM jrn_day_summary WHERE trade_date=$1", dt)
        for summary in summaries_to_write:
            await conn.execute("""
                INSERT INTO jrn_day_summary
                (trade_date,broker,fiscal_year,total_fills,total_orders,total_lots,
                 failed_order_count,force_squared_count,first_trade_time,last_trade_time,
                 avg_hold_seconds,time_bucket_pnl,gross_pnl,total_brokerage,total_charges,
                 net_pnl,win_pairs,loss_pairs,open_pairs)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19)
            """,
            summary.trade_date, summary.broker, summary.fiscal_year,
            summary.total_fills, summary.total_orders, summary.total_lots,
            summary.failed_order_count, summary.force_squared_count,
            summary.first_trade_time, summary.last_trade_time,
            summary.avg_hold_seconds,
            json.dumps(summary.time_bucket_pnl),
            float(summary.gross_pnl), float(summary.total_brokerage),
            float(summary.total_charges), float(summary.net_pnl),
            summary.win_pairs, summary.loss_pairs, summary.open_pairs)


def _row_to_trade(r) -> "Trade":
    from journal.models import Trade
    return Trade(
        id=r["id"], broker=r["broker"], source=r["source"],
        source_format=r.get("source_format", "pdf"),
        fill_grain=r.get("fill_grain", "wap"),
        source_file=r["source_file"], contract_note_no=r["contract_note_no"],
        order_no=r["order_no"], order_time=r["order_time"],
        trade_id=r["trade_id"], trade_date=r["trade_date"], trade_time=r["trade_time"],
        symbol=r["symbol"], raw_symbol=r["raw_symbol"], underlying=r["underlying"],
        exchange=r["exchange"], segment=r["segment"],
        product_type=r.get("product_type"),
        trade_type=r["trade_type"], quantity=r["quantity"],
        lot_size=r["lot_size"], lots=r["lots"],
        strike=r["strike"], option_type=r["option_type"], expiry=r["expiry"],
        instrument=r["instrument"],
        price=Decimal(str(r["price"])), brokerage=Decimal(str(r["brokerage"])),
        status=r["status"] or "filled", remark=r["remark"],
        is_force_squared=r["is_force_squared"] or False,
    )
