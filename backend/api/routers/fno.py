"""FnO live analysis API endpoints."""
from __future__ import annotations

import asyncio

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth.middleware import get_current_user
from core.auth.provider import User

router = APIRouter(prefix="/fno", tags=["fno"])


@router.get("/expiries")
async def get_fno_expiries(
    symbol: str = Query("NIFTY", description="Underlying: NIFTY, BANKNIFTY, MIDCPNIFTY, SENSEX"),
    user: User = Depends(get_current_user),
):
    """Return available expiry dates for the given index symbol.

    Tries Kite MCP search_instruments; falls back to rule-based computation.
    Cached in Redis for 1 hour.
    """
    try:
        from workers.activities.fetch_fno_snapshot import run_expiries
        return await asyncio.to_thread(run_expiries, symbol)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/snapshot")
async def get_fno_snapshot(
    symbol:  str = Query("NIFTY", description="Underlying: NIFTY, BANKNIFTY, MIDCPNIFTY, SENSEX"),
    strikes: int = Query(15, ge=5, le=25, description="Number of strikes on each side of ATM"),
    expiry:  str | None = Query(None, description="Expiry date YYYY-MM-DD; omit for next expiry"),
    user: User = Depends(get_current_user),
):
    """
    Fetch live NIFTY FnO snapshot.

    Returns PCR, PCDR, PCD (put-call metrics) and per-strike CE/PE data
    including Open-High candle detection.

    Falls back to cached Redis data if Kite MCP session is expired.
    """
    try:
        from workers.activities.fetch_fno_snapshot import run_fno_snapshot
        result = await asyncio.to_thread(run_fno_snapshot, symbol, strikes, expiry)
        return result
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 400:
            raise HTTPException(
                status_code=503,
                detail="Kite MCP session expired. Run: cd backend && PYTHONPATH=. python scripts/backfill_1min_kitemcp.py --auth"
            ) from exc
        raise HTTPException(status_code=503, detail=f"Kite MCP error: {exc}") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"FnO fetch failed: {exc}") from exc
