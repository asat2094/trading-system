"""Fetch 1-min OHLCV from Kite MCP for an index symbol, load into QuestDB.

Index symbols differ from equity in three ways:
  1. QuestDB symbol: "NSE_NIFTY_50" (not the Kite tradingsymbol "NIFTY 50")
  2. Token lookup: segment=="INDICES", not instrument_type=="EQ"
  3. Token cache: .kitemcp_index_tokens.json (separate from equity cache)

Shares the global _kite_limiter (180 RPM) with fetch_kitemcp_1min so both
activity types count against the same rate budget.
"""
from workers.activities.fetch_kitemcp_1min import (
    _kite_limiter,
    SESSION_FILE,
    MCP_URL,
    IST_OFFSET,
    _session_id,
    _to_utc,
    _bulk_import_questdb,
    _missing_dates_for_symbol,
)

import asyncio
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
from temporalio import activity

from core.logging import get_logger
from core.metrics import ingestion_rows, ingestion_failures
from core.universe import questdb_to_index

log = get_logger(__name__)

INDEX_TOKEN_FILE = Path(__file__).parent.parent.parent / "scripts" / ".kitemcp_index_tokens.json"


def _index_token_cache() -> dict:
    return json.loads(INDEX_TOKEN_FILE.read_text()) if INDEX_TOKEN_FILE.exists() else {}


def _resolve_index_token(session_id: str, questdb_symbol: str, cache: dict) -> int | None:
    """Resolve instrument token for an index symbol (segment=INDICES)."""
    pair = questdb_to_index(questdb_symbol)
    if pair is None:
        return None
    tradingsymbol, exchange = pair
    cache_key = f"{exchange}:{tradingsymbol}"

    if cache_key in cache:
        return cache[cache_key]

    _kite_limiter.acquire()
    with httpx.Client(timeout=30) as client:
        resp = client.post(MCP_URL, json={
            "jsonrpc": "2.0", "method": "tools/call",
            "params": {"name": "search_instruments",
                       "arguments": {"query": f"{exchange}:{tradingsymbol}"}},
            "id": 1,
        }, headers={"Content-Type": "application/json", "mcp-session-id": session_id},
        timeout=30)
        resp.raise_for_status()
        data = resp.json()
        text = data.get("result", {}).get("content", [{}])[0].get("text", "[]")
        instruments = json.loads(text)
        for inst in instruments:
            if (inst.get("tradingsymbol") == tradingsymbol
                    and inst.get("exchange") == exchange
                    and inst.get("segment") == "INDICES"):
                token = inst["instrument_token"]
                cache[cache_key] = token
                INDEX_TOKEN_FILE.write_text(json.dumps(cache, indent=2))
                return token
    return None


def _fetch_index_candles(session_id: str, token: int, from_date: str, to_date: str) -> list:
    """Fetch 1-min candles for an index. Same as equity but uses the shared limiter."""
    _kite_limiter.acquire()
    with httpx.Client(timeout=30) as client:
        resp = client.post(MCP_URL, json={
            "jsonrpc": "2.0", "method": "tools/call",
            "params": {"name": "get_historical_data", "arguments": {
                "instrument_token": token,
                "interval": "minute",
                "from_date": f"{from_date} 09:00:00",
                "to_date":   f"{to_date} 15:30:00",
            }},
            "id": 1,
        }, headers={"Content-Type": "application/json", "mcp-session-id": session_id},
        timeout=30)
        resp.raise_for_status()
        data = resp.json()
        text = data.get("result", {}).get("content", [{}])[0].get("text", "")
        if "error" in text.lower() or "failed" in text.lower():
            raise RuntimeError(f"Kite MCP error: {text[:200]}")
        return json.loads(text)


@activity.defn(name="fetch_kitemcp_index_1min")
async def activity_fn(
    questdb_symbol: str,
    from_date: str,
    to_date: str,
    skip_existing: bool = True,
) -> dict:
    """
    Fetch 1-min OHLCV from Kite MCP for an index symbol and write to QuestDB.

    Args:
        questdb_symbol: QuestDB symbol name e.g. "NSE_NIFTY_50", "BSE_SENSEX"
        from_date:      YYYY-MM-DD
        to_date:        YYYY-MM-DD
        skip_existing:  if True, skip date ranges already in QuestDB
    """
    loop = asyncio.get_event_loop()

    session_id = await loop.run_in_executor(None, _session_id)
    cache      = await loop.run_in_executor(None, _index_token_cache)
    token      = await loop.run_in_executor(
        None, _resolve_index_token, session_id, questdb_symbol, cache
    )

    if token is None:
        log.warning("kitemcp_index_token_not_found", symbol=questdb_symbol)
        ingestion_failures.labels(source="kitemcp_index_1min").inc()
        return {"symbol": questdb_symbol, "rows": 0, "error": "token_not_found"}

    # Find missing dates
    if skip_existing:
        missing = await loop.run_in_executor(
            None, _missing_dates_for_symbol, questdb_symbol, from_date, to_date
        )
        if not missing:
            log.info("kitemcp_index_already_complete", symbol=questdb_symbol,
                     from_date=from_date, to_date=to_date)
            return {"symbol": questdb_symbol, "rows": 0, "skipped": True}
        from_dt = date.fromisoformat(missing[0])
        to_dt   = date.fromisoformat(missing[-1])
    else:
        from_dt = date.fromisoformat(from_date)
        to_dt   = date.fromisoformat(to_date)

    # Chunk into 7-day windows
    chunks = []
    d = to_dt
    while d >= from_dt:
        start = max(d - timedelta(days=6), from_dt)
        chunks.append((start.isoformat(), d.isoformat()))
        d = start - timedelta(days=1)

    total_rows = 0
    for chunk_from, chunk_to in chunks:
        try:
            candles = await loop.run_in_executor(
                None, _fetch_index_candles, session_id, token, chunk_from, chunk_to
            )
            rows = await loop.run_in_executor(
                None, _bulk_import_questdb, candles, questdb_symbol
            )
            total_rows += rows
            log.info("kitemcp_index_chunk_ok",
                     symbol=questdb_symbol, from_date=chunk_from, to_date=chunk_to, rows=rows)
        except Exception as exc:
            log.warning("kitemcp_index_chunk_fail",
                        symbol=questdb_symbol, from_date=chunk_from, error=str(exc))
            ingestion_failures.labels(source="kitemcp_index_1min").inc()

    ingestion_rows.labels(source="kitemcp_index_1min", timeframe="1min").inc(total_rows)
    log.info("kitemcp_index_done", symbol=questdb_symbol, rows=total_rows)
    return {"symbol": questdb_symbol, "rows": total_rows}
