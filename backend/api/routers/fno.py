"""FnO live analysis API endpoints."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Query

from core.auth.middleware import get_current_user
from core.auth.provider import User

router = APIRouter(prefix="/fno", tags=["fno"])


@router.get("/snapshot")
async def get_fno_snapshot(
    symbol: str = Query("NIFTY", description="Underlying symbol (NIFTY only for v1)"),
    strikes: int = Query(10, ge=5, le=20, description="Number of strikes on each side of ATM"),
    user: User = Depends(get_current_user),
):
    """
    Fetch live NIFTY FnO snapshot.

    Returns PCR, PCDR, PCD (put-call metrics) and per-strike CE/PE data
    including Open-High candle detection.  Triggers exactly 2 Kite MCP calls.

    Rate constraint: Kite MCP is limited to 180 RPM.  The endpoint will block
    for the duration of the fetch (~1–3 s).  A 30-second Redis cache is NOT
    applied here — the caller (UI) controls refresh frequency via a button.
    """
    try:
        from workers.activities.fetch_fno_snapshot import run_fno_snapshot
        result = await asyncio.to_thread(run_fno_snapshot, symbol, strikes)
        return result
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"FnO fetch failed: {exc}") from exc
