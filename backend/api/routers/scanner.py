# backend/api/routers/scanner.py
import time
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from core.auth.middleware import get_current_user
from core.auth.provider import User
from core.logging import get_logger
from scanner.engine import Scanner
from scanner.evaluator import ConditionNode, ConditionEvaluator, DataContext

log = get_logger(__name__)
router = APIRouter(prefix="/scanner", tags=["scanner"])


# ── request/response models ───────────────────────────────────────────────────

class ScanRequest(BaseModel):
    universe: list[str] | str = "nse_all"
    max_symbols: int = 500
    default_timeframe: str = "1d"
    signals: list[str] = []
    custom_conditions: dict | None = None
    match_mode: str = "any_signal"
    lookback_days: int = 200


class EvaluateRequest(BaseModel):
    symbol: str
    default_timeframe: str = "1d"
    conditions: dict
    lookback_days: int = 200


# ── helpers ───────────────────────────────────────────────────────────────────

def _result_to_dict(scan_result) -> dict:
    """Convert ScanResult dataclass to JSON-serialisable dict."""
    signal_details = {}
    for name, sr in scan_result.signal_details.items():
        signal_details[name] = {
            "passed": sr.passed,
            "score": sr.score,
            "conditions_passed": sr.conditions_passed,
            "conditions_total": sr.conditions_total,
            "details": sr.details,
            "display": sr.display,
        }
    return {
        "symbol": scan_result.symbol,
        "overall_score": scan_result.overall_score,
        "matched_signals": scan_result.matched_signals,
        "signal_details": signal_details,
        "custom_passed": scan_result.custom_passed,
    }


async def _resolve_universe(universe) -> list[str]:
    if isinstance(universe, list):
        return universe
    from core.sdk import MarketData
    md = MarketData()
    return await md.universe()


def _make_fetch_fn(lookback_days: int):
    from core.sdk import MarketData
    from datetime import datetime, timedelta
    md = MarketData()
    TF_LOOKBACK_CAP = {
        "1min": 5, "3min": 10, "5min": 15, "15min": 30,
        "30min": 60, "1h": 120, "1d": lookback_days,
        "1w": lookback_days, "1M": lookback_days,
    }

    async def fetch(symbol: str, tf: str):
        cap = TF_LOOKBACK_CAP.get(tf, lookback_days)
        effective = min(lookback_days, cap)
        to_dt = datetime.now()
        from_dt = to_dt - timedelta(days=effective)
        return await md.ohlcv(symbol, tf, from_dt, to_dt)

    return fetch


# ── endpoints ─────────────────────────────────────────────────────────────────

@router.post("/run")
async def run_scan(req: ScanRequest, user: User = Depends(get_current_user)):
    t0 = time.monotonic()
    universe = await _resolve_universe(req.universe)
    scanner = Scanner()
    results = await scanner.run_async(
        universe=universe,
        signals=req.signals,
        custom_conditions=req.custom_conditions,
        default_timeframe=req.default_timeframe,
        match_mode=req.match_mode,
        max_symbols=req.max_symbols,
        lookback_days=req.lookback_days,
    )
    duration_ms = int((time.monotonic() - t0) * 1000)
    matched_symbols = [r.symbol for r in results]
    return {
        "symbols": matched_symbols,
        "results": [_result_to_dict(r) for r in results],
        "total_scanned": min(len(universe), req.max_symbols),
        "matched": len(results),
        "duration_ms": duration_ms,
    }


def _sanitize(obj):
    """Recursively convert numpy scalars to native Python types for JSON serialization."""
    import numpy as np
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    return obj


@router.post("/evaluate")
async def evaluate_symbol(req: EvaluateRequest, user: User = Depends(get_current_user)):
    """Evaluate a single symbol against a custom condition tree."""
    node = ConditionNode.from_dict(req.conditions)
    ctx = DataContext(
        symbol=req.symbol,
        default_tf=req.default_timeframe,
        fetch_fn=_make_fetch_fn(req.lookback_days),
    )
    evaluator = ConditionEvaluator()
    result = await evaluator.evaluate(node, ctx)
    return {
        "symbol": req.symbol,
        "passed": bool(result.passed),
        "score": float(result.score),
        "details": _sanitize(result.details),
    }


@router.get("/signals")
async def list_signals(user: User = Depends(get_current_user)):
    from scanner.signals.loader import load_signals
    signals = load_signals()
    return [
        {
            "name": s.name,
            "category": s.category,
            "direction": s.direction,
            "timeframes": s.timeframes,
            "display": s.display,
            "severity": s.severity,
        }
        for s in signals
    ]


# ── legacy GET kept for backwards compat ─────────────────────────────────────

@router.get("/run")
async def run_scan_get(user: User = Depends(get_current_user)):
    return {"symbols": [], "results": [], "total_scanned": 0, "matched": 0, "duration_ms": 0}
