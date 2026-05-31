# FnO Live Analysis — NIFTY Option Chain Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/fno` page to the trading-system that shows NIFTY option chain live data — PCR / PCDR / PCD summary and per-strike Open-High analysis — fetched on-demand from Kite MCP with ≤3 API calls per refresh.

**Architecture:** A sync Python function (`run_fno_snapshot`) fetches NIFTY spot via `get_ltp`, then batch-fetches ~42 ATM±10 option quotes via `get_quotes` (one call). Redis stores per-strike OI baselines set at first daily fetch, enabling delta OI computation without extra API calls. A Temporal activity wraps the function; a FastAPI router calls it directly via `asyncio.to_thread`. The React page refreshes on button click, shows PCR cards + colour-coded options chain table with OH indicators.

**Tech Stack:** Python 3.12, httpx, redis-py, Temporal, FastAPI, React 18, TypeScript, Zustand (existing).

---

## File Structure

```
New files:
  backend/workers/activities/fetch_fno_snapshot.py   — KiteMCP calls + metric compute
  backend/workers/workflows/fno_snapshot.py          — on-demand Temporal workflow
  backend/api/routers/fno.py                         — GET /fno/snapshot endpoint
  frontend/src/pages/FnoLive.tsx                     — main page
  frontend/src/components/Fno/PcrCards.tsx           — PCR / PCDR / PCD summary cards
  frontend/src/components/Fno/OptionsChainTable.tsx  — per-strike CE|Strike|PE table
  backend/tests/unit/test_fno_snapshot.py            — unit tests for core logic
  frontend/src/components/Fno/types.ts               — shared TS interfaces

Modified files:
  backend/api/main.py                  — include fno_router
  backend/workers/main.py              — register FnoSnapshotWorkflow + activity
  frontend/src/App.tsx                 — add /fno route
  frontend/src/components/Layout/Sidebar.tsx — add FnO nav item
```

---

## Key Design Notes

### KiteMCP call pattern (sync)

`backend/scripts/backfill_1min_kitemcp.py` has the canonical `KiteMCPClient` class. The activity uses a self-contained `_FnoMCPClient` that mirrors it exactly — no cross-import from scripts into production code.

```python
class _FnoMCPClient:
    """Minimal KiteMCP client — mirrors KiteMCPClient from scripts."""
    _SESSION_FILE = Path(__file__).parent.parent.parent / "scripts" / ".kitemcp_session"

    def __init__(self):
        if not self._SESSION_FILE.exists():
            raise RuntimeError(
                "No Kite MCP session. Run: python scripts/backfill_1min_kitemcp.py --auth"
            )
        self.session_id = self._SESSION_FILE.read_text().strip()
        self._client = httpx.Client(timeout=30)

    def call_tool(self, name: str, arguments: dict) -> Any:
        """Rate-limited JSON-RPC call. Captures session refresh from response headers."""
        _kite_limiter.acquire()
        resp = self._client.post(
            "https://mcp.kite.trade/mcp",
            json={"jsonrpc": "2.0", "method": "tools/call",
                  "params": {"name": name, "arguments": arguments}, "id": 1},
            headers={"Content-Type": "application/json",
                     "Accept": "application/json",
                     "mcp-session-id": self.session_id},
            timeout=30,
        )
        resp.raise_for_status()
        sid = resp.headers.get("mcp-session-id", "")
        if sid:
            self.session_id = sid   # update if server refreshes session
        text = resp.json().get("result", {}).get("content", [{}])[0].get("text", "{}")
        return json.loads(text)

    def close(self):
        self._client.close()
```

Rate limiter imported from existing activity:
```python
from backend.workers.activities.fetch_kitemcp_1min import _kite_limiter
```

### Delta OI strategy
- No change-in-OI field in Kite API → compute ourselves
- First fetch of day: store `oi` in Redis key `fno:baseline:NIFTY:{expiry}:{strike}:{CE|PE}` with TTL = seconds until IST midnight
- Subsequent fetches: `delta_oi = current_oi - float(redis.get(key))`

### NIFTY instrument naming
- Monthly format: `NFO:NIFTY26JUN24700CE` (NIFTY + YY + MMM + STRIKE + type)
- Strike step: 50
- Active NIFTY options have monthly expiry only (as of 2026)
- `_nearest_monthly_expiry(today)` → last Thursday of current (or next) month

### Open-High detection
- `is_oh`: `abs(high - open) <= 0.05` (within 1 tick)
- `is_oh_hit`: `is_oh AND last_price >= open - 0.05` (price is back at the open/high)

---

## Task 1: Core FnO snapshot logic + Temporal activity

**Files:**
- Create: `backend/workers/activities/fetch_fno_snapshot.py`
- Create: `backend/tests/unit/test_fno_snapshot.py`

### Step 1: Write failing tests

```bash
# Create test file
cat > backend/tests/unit/test_fno_snapshot.py << 'HEREDOC'
"""Unit tests for FnO snapshot logic."""
import pytest
from unittest.mock import MagicMock, patch
from datetime import date


# --- _nearest_monthly_expiry ---

def test_nearest_monthly_expiry_before_expiry():
    """If today is before last Thursday, return current month's last Thursday."""
    from backend.workers.activities.fetch_fno_snapshot import _nearest_monthly_expiry
    # June 30 2026 is Tuesday; last Thursday of June 2026 is June 25
    result = _nearest_monthly_expiry(date(2026, 6, 1))
    assert result == date(2026, 6, 25)


def test_nearest_monthly_expiry_after_expiry():
    """If today is after last Thursday, return next month."""
    from backend.workers.activities.fetch_fno_snapshot import _nearest_monthly_expiry
    # June 25 2026 passed → return last Thursday of July 2026
    result = _nearest_monthly_expiry(date(2026, 6, 26))
    assert result == date(2026, 7, 30)


def test_nearest_monthly_expiry_december_rolls_to_january():
    """December expiry passed → rolls to January next year."""
    from backend.workers.activities.fetch_fno_snapshot import _nearest_monthly_expiry
    # Last Thursday Dec 2026 is Dec 31; after that rolls to Jan 2027
    result = _nearest_monthly_expiry(date(2027, 1, 2))
    assert result.year == 2027
    assert result.month == 1
    assert result.weekday() == 3  # Thursday


# --- _expiry_prefix ---

def test_expiry_prefix():
    from backend.workers.activities.fetch_fno_snapshot import _expiry_prefix
    assert _expiry_prefix(date(2026, 6, 25)) == "NIFTY26JUN"
    assert _expiry_prefix(date(2026, 12, 31)) == "NIFTY26DEC"


# --- Open-High detection ---

def test_is_oh_true_when_high_equals_open():
    from backend.workers.activities.fetch_fno_snapshot import _is_oh
    assert _is_oh(open_=138.0, high=138.0) is True


def test_is_oh_true_within_one_tick():
    from backend.workers.activities.fetch_fno_snapshot import _is_oh
    assert _is_oh(open_=138.0, high=138.05) is True


def test_is_oh_false_when_high_above_open():
    from backend.workers.activities.fetch_fno_snapshot import _is_oh
    assert _is_oh(open_=138.0, high=140.0) is False


def test_is_oh_hit_true_when_price_at_open():
    from backend.workers.activities.fetch_fno_snapshot import _is_oh_hit
    assert _is_oh_hit(open_=138.0, last_price=138.0) is True


def test_is_oh_hit_false_when_price_below_open():
    from backend.workers.activities.fetch_fno_snapshot import _is_oh_hit
    assert _is_oh_hit(open_=138.0, last_price=120.0) is False


# --- PCR / PCDR / PCD computation ---

def test_pcr_computation():
    """PCR = total PE OI / total CE OI."""
    from backend.workers.activities.fetch_fno_snapshot import _compute_ratios
    result = _compute_ratios(
        ce_oi=1_000_000, pe_oi=1_500_000,
        ce_delta=50_000, pe_delta=100_000,
    )
    assert result["pcr"] == pytest.approx(1.5, rel=1e-3)
    assert result["pcdr"] == pytest.approx(2.0, rel=1e-3)
    assert result["pcd"] == 50_000


def test_pcr_zero_ce_oi_does_not_crash():
    from backend.workers.activities.fetch_fno_snapshot import _compute_ratios
    result = _compute_ratios(ce_oi=0, pe_oi=500_000, ce_delta=0, pe_delta=10_000)
    assert result["pcr"] == 0.0
    assert result["pcdr"] == 0.0


# --- run_fno_snapshot integration (mocked KiteMCP + Redis) ---

def _make_quote(ltp, oi, open_, high):
    return {
        "last_price": ltp, "oi": oi,
        "ohlc": {"open": open_, "high": high, "low": ltp * 0.9, "close": ltp},
    }


def test_run_fno_snapshot_returns_expected_keys():
    """run_fno_snapshot returns all required keys when KiteMCP + Redis are mocked."""
    from backend.workers.activities.fetch_fno_snapshot import run_fno_snapshot

    fake_spot = {"NSE:NIFTY 50": {"last_price": 24700.0}}
    # Build fake quotes for 21 strikes × 2 types
    fake_quotes = {}
    for i in range(-10, 11):
        strike = int(24700 + i * 50)
        for t in ("CE", "PE"):
            key = f"NFO:NIFTY26JUN{strike}{t}"
            fake_quotes[key] = _make_quote(100.0, 1_000_000, 100.0, 100.0)

    mock_redis = MagicMock()
    mock_redis.get.return_value = None  # no baseline yet

    call_count = [0]
    def fake_call_tool(self_ignored, name, arguments):
        call_count[0] += 1
        if name == "get_ltp":
            return fake_spot
        if name == "get_quotes":
            return fake_quotes
        return {}

    with (
        patch(
            "backend.workers.activities.fetch_fno_snapshot._FnoMCPClient.call_tool",
            side_effect=fake_call_tool,
        ),
        patch(
            "backend.workers.activities.fetch_fno_snapshot._FnoMCPClient.__init__",
            return_value=None,
        ),
        patch(
            "backend.workers.activities.fetch_fno_snapshot._FnoMCPClient.close",
            return_value=None,
        ),
        patch("backend.workers.activities.fetch_fno_snapshot._redis", return_value=mock_redis),
    ):
        result = run_fno_snapshot("NIFTY", strikes=10)

    assert result["symbol"] == "NIFTY"
    assert result["spot"] == 24700.0
    assert result["atm_strike"] == 24700
    assert "pcr" in result
    assert "pcdr" in result
    assert "pcd" in result
    assert len(result["strikes"]) == 21
    assert result["strikes"][10]["strike"] == 24700  # ATM is middle
    assert call_count[0] == 2  # exactly 2 MCP calls: get_ltp + get_quotes
HEREDOC
```

- [ ] **Step 2: Run tests to confirm they fail**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system
backend/.venv/bin/python -m pytest backend/tests/unit/test_fno_snapshot.py -v 2>&1 | head -30
```

Expected: `ModuleNotFoundError: No module named 'backend.workers.activities.fetch_fno_snapshot'`

- [ ] **Step 3: Implement `fetch_fno_snapshot.py`**

Create `backend/workers/activities/fetch_fno_snapshot.py`:

```python
"""Fetch NIFTY FnO option-chain snapshot via Kite MCP: OI, OHLC, PCR, PCDR, PCD, OH.

MCP client pattern mirrors KiteMCPClient from scripts/backfill_1min_kitemcp.py.
Session is loaded from scripts/.kitemcp_session (same file the scripts create).
Rate limiter shared with fetch_kitemcp_1min.py (180 RPM global).
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import redis as redis_lib
from temporalio import activity

from backend.workers.activities.fetch_kitemcp_1min import _kite_limiter

NIFTY_STEP   = 50
NSE_NIFTY    = "NSE:NIFTY 50"
IST          = timezone(timedelta(hours=5, minutes=30))
_REDIS_FALLBACK = "redis://localhost:6379"


# ---------------------------------------------------------------------------
# Minimal KiteMCP client (mirrors scripts/backfill_1min_kitemcp.KiteMCPClient)
# ---------------------------------------------------------------------------

class _FnoMCPClient:
    """
    Self-contained KiteMCP client for FnO snapshot.
    Mirrors KiteMCPClient from backfill_1min_kitemcp.py — no cross-import from scripts.
    """
    _SESSION_FILE = Path(__file__).parent.parent.parent / "scripts" / ".kitemcp_session"

    def __init__(self) -> None:
        if not self._SESSION_FILE.exists():
            raise RuntimeError(
                "No Kite MCP session — run: cd backend && "
                "PYTHONPATH=. python scripts/backfill_1min_kitemcp.py --auth"
            )
        self.session_id = self._SESSION_FILE.read_text().strip()
        self._client    = httpx.Client(timeout=30)

    def call_tool(self, name: str, arguments: dict) -> Any:
        """Rate-limited JSON-RPC call. Captures session refresh from response headers."""
        _kite_limiter.acquire()
        resp = self._client.post(
            "https://mcp.kite.trade/mcp",
            json={"jsonrpc": "2.0", "method": "tools/call",
                  "params": {"name": name, "arguments": arguments}, "id": 1},
            headers={"Content-Type": "application/json",
                     "Accept": "application/json",
                     "mcp-session-id": self.session_id},
            timeout=30,
        )
        resp.raise_for_status()
        sid = resp.headers.get("mcp-session-id", "")
        if sid:
            self.session_id = sid   # update if server refreshes session
        text = resp.json().get("result", {}).get("content", [{}])[0].get("text", "{}")
        return json.loads(text)

    def close(self) -> None:
        self._client.close()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _redis() -> redis_lib.Redis:
    try:
        from backend.core.config import settings
        url = settings.redis_url
    except Exception:
        url = _REDIS_FALLBACK
    return redis_lib.from_url(url, decode_responses=True)


def _nearest_monthly_expiry(today: date) -> date:
    """Return last Thursday of current month; roll to next month if already expired."""
    def _last_thursday(y: int, m: int) -> date:
        if m == 12:
            last = date(y + 1, 1, 1) - timedelta(days=1)
        else:
            last = date(y, m + 1, 1) - timedelta(days=1)
        return last - timedelta(days=(last.weekday() - 3) % 7)

    exp = _last_thursday(today.year, today.month)
    if exp < today:
        nm = today.month % 12 + 1
        ny = today.year + (1 if today.month == 12 else 0)
        exp = _last_thursday(ny, nm)
    return exp


def _expiry_prefix(expiry: date) -> str:
    """date(2026, 6, 25) -> 'NIFTY26JUN'"""
    return f"NIFTY{expiry.strftime('%y%b').upper()}"


def _secs_to_ist_midnight() -> int:
    now = datetime.now(IST)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(int((midnight - now).total_seconds()), 3600)


def _is_oh(open_: float, high: float, tick: float = 0.05) -> bool:
    """True when day's high == open (within 1 tick): bearish OH candle."""
    return abs(high - open_) <= tick


def _is_oh_hit(open_: float, last_price: float, tick: float = 0.05) -> bool:
    """True when price has returned to the open/high level (OH candle reversal)."""
    return last_price >= open_ - tick


def _compute_ratios(
    ce_oi: float, pe_oi: float, ce_delta: float, pe_delta: float,
) -> dict:
    """Compute PCR, PCDR, PCD from aggregated OI values."""
    pcr  = round(pe_oi  / ce_oi,   4) if ce_oi   else 0.0
    pcdr = round(pe_delta / ce_delta, 4) if ce_delta else 0.0
    pcd  = round(pe_delta - ce_delta)
    return {"pcr": pcr, "pcdr": pcdr, "pcd": pcd}


# ---------------------------------------------------------------------------
# Core snapshot logic
# ---------------------------------------------------------------------------

def run_fno_snapshot(symbol: str = "NIFTY", strikes: int = 10) -> dict:
    """
    Fetch FnO snapshot for NIFTY.

    Makes exactly 2 Kite MCP calls:
      1. get_ltp   → NIFTY 50 spot price
      2. get_quotes → OI + OHLC for (strikes*2+1) × 2 option instruments

    Delta OI computed via Redis baselines (set on first fetch each trading day).

    Returns
    -------
    dict: symbol, spot, expiry, atm_strike, pcr, pcdr, pcd,
          total_ce_oi, total_pe_oi, strikes[{strike, ce, pe}], fetched_at
    """
    today  = date.today()
    expiry = _nearest_monthly_expiry(today)
    prefix = _expiry_prefix(expiry)
    mc     = _FnoMCPClient()
    rdb    = _redis()

    try:
        # --- call 1: spot ---
        spot_data = mc.call_tool("get_ltp", {"instruments": [NSE_NIFTY]})
        spot = float((spot_data.get(NSE_NIFTY) or {}).get("last_price", 0))
        if spot <= 0:
            raise RuntimeError(f"Could not fetch NIFTY spot. Response: {spot_data}")

        atm         = round(spot / NIFTY_STEP) * NIFTY_STEP
        strike_list = [int(atm + i * NIFTY_STEP) for i in range(-strikes, strikes + 1)]
        instruments = [
            f"NFO:{prefix}{s}{t}"
            for s in strike_list
            for t in ("CE", "PE")
        ]

        # --- call 2: batch quotes (OI + OHLC + LTP for all ~42 instruments) ---
        quotes = mc.call_tool("get_quotes", {"instruments": instruments})

    finally:
        mc.close()

    # --- process quotes + compute per-strike metrics ---
    bp           = f"fno:baseline:{symbol}:{expiry}"
    strikes_data: list[dict] = []
    total_ce_oi = total_pe_oi = total_ce_delta = total_pe_delta = 0.0

    for s in strike_list:
        row: dict[str, Any] = {"strike": s}
        for typ in ("CE", "PE"):
            sym  = f"NFO:{prefix}{s}{typ}"
            q    = quotes.get(sym) or {}
            if not q:
                row[typ.lower()] = None
                continue

            ltp   = float(q.get("last_price", 0))
            oi    = float(q.get("oi", 0))
            ohlc  = q.get("ohlc") or {}
            open_ = float(ohlc.get("open", 0))
            high  = float(ohlc.get("high", 0))

            # Delta OI via Redis baseline
            b_key = f"{bp}:{s}:{typ}"
            raw   = rdb.get(b_key)
            if raw is None:
                rdb.setex(b_key, _secs_to_ist_midnight(), str(oi))
                delta = 0.0
            else:
                delta = oi - float(raw)

            oh     = _is_oh(open_, high)
            oh_hit = oh and _is_oh_hit(open_, ltp)

            side = {
                "ltp": ltp, "oi": oi, "delta_oi": delta,
                "open": open_, "high": high,
                "is_oh": oh, "is_oh_hit": oh_hit,
            }

            if typ == "CE":
                total_ce_oi    += oi
                total_ce_delta += delta
            else:
                total_pe_oi    += oi
                total_pe_delta += delta

            row[typ.lower()] = side
        strikes_data.append(row)

    rdb.close()

    ratios = _compute_ratios(total_ce_oi, total_pe_oi, total_ce_delta, total_pe_delta)
    return {
        "symbol":      symbol,
        "spot":        spot,
        "expiry":      str(expiry),
        "atm_strike":  atm,
        **ratios,
        "total_ce_oi": total_ce_oi,
        "total_pe_oi": total_pe_oi,
        "strikes":     strikes_data,
        "fetched_at":  datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Temporal activity wrapper
# ---------------------------------------------------------------------------

@activity.defn(name="fetch_fno_snapshot")
async def fetch_fno_snapshot_activity(symbol: str = "NIFTY", strikes: int = 10) -> dict:
    """Temporal activity: async wrapper around sync run_fno_snapshot."""
    return await asyncio.to_thread(run_fno_snapshot, symbol, strikes)
```

- [ ] **Step 4: Run tests — expect pass**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system
backend/.venv/bin/python -m pytest backend/tests/unit/test_fno_snapshot.py -v
```

Expected output:
```
PASSED test_nearest_monthly_expiry_before_expiry
PASSED test_nearest_monthly_expiry_after_expiry
PASSED test_nearest_monthly_expiry_december_rolls_to_january
PASSED test_expiry_prefix
PASSED test_is_oh_true_when_high_equals_open
PASSED test_is_oh_true_within_one_tick
PASSED test_is_oh_false_when_high_above_open
PASSED test_is_oh_hit_true_when_price_at_open
PASSED test_is_oh_hit_false_when_price_below_open
PASSED test_pcr_computation
PASSED test_pcr_zero_ce_oi_does_not_crash
PASSED test_run_fno_snapshot_returns_expected_keys
12 passed
```

- [ ] **Step 5: Commit**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system
git add backend/workers/activities/fetch_fno_snapshot.py backend/tests/unit/test_fno_snapshot.py
git commit -m "feat: add FnO snapshot activity — PCR/PCDR/PCD/OH via Kite MCP"
```

---

## Task 2: On-demand Temporal workflow + worker registration

**Files:**
- Create: `backend/workers/workflows/fno_snapshot.py`
- Modify: `backend/workers/main.py`

- [ ] **Step 1: Create `backend/workers/workflows/fno_snapshot.py`**

```python
"""On-demand Temporal workflow: fetch FnO snapshot for a given symbol."""
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy

with workflow.unsafe.imports_passed_through():
    from backend.workers.activities.fetch_fno_snapshot import fetch_fno_snapshot_activity


@workflow.defn(name="FnoSnapshotWorkflow")
class FnoSnapshotWorkflow:
    """
    Short-lived on-demand workflow triggered by the FastAPI /fno/snapshot endpoint.
    Runs fetch_fno_snapshot_activity once and returns the result dict.
    """

    @workflow.run
    async def run(self, symbol: str, strikes: int) -> dict:
        return await workflow.execute_activity(
            fetch_fno_snapshot_activity,
            args=[symbol, strikes],
            schedule_to_close_timeout=timedelta(seconds=90),
            start_to_close_timeout=timedelta(seconds=60),
            retry_policy=RetryPolicy(maximum_attempts=2, backoff_coefficient=1.5),
        )
```

- [ ] **Step 2: Register workflow + activity in `backend/workers/main.py`**

Open `backend/workers/main.py`. Find the Worker construction (where `workflows=[...]` and `activities=[...]` lists are defined). Add imports and append to both lists:

```python
# Add these imports near the other activity/workflow imports
from backend.workers.activities.fetch_fno_snapshot import fetch_fno_snapshot_activity
from backend.workers.workflows.fno_snapshot import FnoSnapshotWorkflow
```

In the Worker construction, add to:
```python
workflows=[
    ...,          # existing workflows
    FnoSnapshotWorkflow,
],
activities=[
    ...,          # existing activities
    fetch_fno_snapshot_activity,
],
```

- [ ] **Step 3: Verify worker starts without error**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system
backend/.venv/bin/python -c "
from backend.workers.activities.fetch_fno_snapshot import fetch_fno_snapshot_activity
from backend.workers.workflows.fno_snapshot import FnoSnapshotWorkflow
print('FnoSnapshotWorkflow:', FnoSnapshotWorkflow)
print('fetch_fno_snapshot_activity:', fetch_fno_snapshot_activity)
print('Import OK')
"
```

Expected: `Import OK` with no errors.

- [ ] **Step 4: Commit**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system
git add backend/workers/workflows/fno_snapshot.py backend/workers/main.py
git commit -m "feat: add FnoSnapshotWorkflow and register activity in worker"
```

---

## Task 3: FastAPI FnO router + wire into main

**Files:**
- Create: `backend/api/routers/fno.py`
- Modify: `backend/api/main.py`

- [ ] **Step 1: Create `backend/api/routers/fno.py`**

```python
"""FnO live analysis API endpoints."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/fno", tags=["fno"])


@router.get("/snapshot")
async def get_fno_snapshot(
    symbol: str = Query("NIFTY", description="Underlying symbol (NIFTY only for v1)"),
    strikes: int = Query(10, ge=5, le=20, description="Number of strikes on each side of ATM"),
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
        from backend.workers.activities.fetch_fno_snapshot import run_fno_snapshot
        result = await asyncio.to_thread(run_fno_snapshot, symbol, strikes)
        return result
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"FnO fetch failed: {exc}") from exc
```

- [ ] **Step 2: Add fno router to `backend/api/main.py`**

Open `backend/api/main.py`. Find where other routers are imported and included, then add:

```python
# import (near existing router imports)
from backend.api.routers.fno import router as fno_router

# include (near existing app.include_router calls)
app.include_router(fno_router)
```

- [ ] **Step 3: Smoke-test the route is registered**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system
backend/.venv/bin/python -c "
from backend.api.main import app
routes = [r.path for r in app.routes]
assert '/fno/snapshot' in routes, f'/fno/snapshot not found in {routes}'
print('Route registered OK')
"
```

Expected: `Route registered OK`

- [ ] **Step 4: Commit**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system
git add backend/api/routers/fno.py backend/api/main.py
git commit -m "feat: add /fno/snapshot FastAPI endpoint"
```

---

## Task 4: Frontend shared types

**Files:**
- Create: `frontend/src/components/Fno/types.ts`

- [ ] **Step 1: Create `frontend/src/components/Fno/types.ts`**

```typescript
/** Shared TypeScript interfaces for FnO live analysis. */

export interface OptionSide {
  ltp: number;
  oi: number;
  delta_oi: number;
  open: number;
  high: number;
  is_oh: boolean;      // open == high (bearish OH candle)
  is_oh_hit: boolean;  // price has returned to the open/high level
}

export interface StrikeRow {
  strike: number;
  ce: OptionSide | null;
  pe: OptionSide | null;
}

export interface FnoSnapshot {
  symbol: string;
  spot: number;
  expiry: string;       // "YYYY-MM-DD"
  atm_strike: number;
  pcr: number;
  pcdr: number;
  pcd: number;
  total_ce_oi: number;
  total_pe_oi: number;
  strikes: StrikeRow[];
  fetched_at: string;   // ISO timestamp
}
```

- [ ] **Step 2: Commit**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system
git add frontend/src/components/Fno/types.ts
git commit -m "feat: add FnO TypeScript interfaces"
```

---

## Task 5: PCR Cards component

**Files:**
- Create: `frontend/src/components/Fno/PcrCards.tsx`

- [ ] **Step 1: Create `frontend/src/components/Fno/PcrCards.tsx`**

```tsx
/**
 * PcrCards — summary strip showing PCR, PCDR, PCD, Spot.
 * PCR > 1 = bullish (more PE OI = more hedging/puts) → green.
 * PCD > 0 = more PE OI added today → green.
 */
import type { FnoSnapshot } from "./types";

const TV = {
  panel: "#131722", border: "#2a2e39",
  text: "#d1d4dc", muted: "#787b86",
  up: "#26a69a", down: "#ef5350",
} as const;

interface Props {
  snapshot: FnoSnapshot;
}

function fmt(n: number, decimals = 3): string {
  return n.toFixed(decimals);
}

function fmtOi(n: number): string {
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (Math.abs(n) >= 1_000)     return `${(n / 1_000).toFixed(1)}K`;
  return String(Math.round(n));
}

export default function PcrCards({ snapshot }: Props) {
  const cards = [
    {
      label: "PCR",
      value: fmt(snapshot.pcr),
      color: snapshot.pcr >= 1 ? TV.up : TV.down,
      sub: `${fmtOi(snapshot.total_pe_oi)} PE / ${fmtOi(snapshot.total_ce_oi)} CE`,
      title: "Put-Call Ratio: total PE OI ÷ total CE OI. >1 = bullish",
    },
    {
      label: "PCR Δ",
      value: fmt(snapshot.pcdr),
      color: snapshot.pcdr >= 1 ? TV.up : TV.down,
      sub: "ΔPE OI ÷ ΔCE OI",
      title: "Put-Call Delta Ratio: change in PE OI ÷ change in CE OI today",
    },
    {
      label: "PCD",
      value: fmtOi(snapshot.pcd),
      color: snapshot.pcd >= 0 ? TV.up : TV.down,
      sub: "ΔPE OI − ΔCE OI",
      title: "Put-Call Delta: net change in PE OI minus CE OI (today)",
    },
    {
      label: "SPOT",
      value: snapshot.spot.toFixed(2),
      color: TV.text,
      sub: `ATM ${snapshot.atm_strike}  ·  exp ${snapshot.expiry}`,
      title: "NIFTY 50 last traded price",
    },
  ];

  return (
    <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
      {cards.map(c => (
        <div
          key={c.label}
          title={c.title}
          style={{
            background: TV.panel,
            border: `1px solid ${TV.border}`,
            borderRadius: 6,
            padding: "10px 18px",
            minWidth: 130,
            cursor: "default",
          }}
        >
          <div style={{ color: TV.muted, fontSize: 10, textTransform: "uppercase", letterSpacing: 1 }}>
            {c.label}
          </div>
          <div style={{ color: c.color, fontSize: 22, fontWeight: 700, fontFamily: "monospace", marginTop: 2 }}>
            {c.value}
          </div>
          <div style={{ color: TV.muted, fontSize: 10, marginTop: 3 }}>
            {c.sub}
          </div>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system
git add frontend/src/components/Fno/PcrCards.tsx
git commit -m "feat: add PcrCards component for FnO summary metrics"
```

---

## Task 6: Options Chain Table component

**Files:**
- Create: `frontend/src/components/Fno/OptionsChainTable.tsx`

The table layout: `CE LTP | CE ΔOI | CE OI | CE OH | STRIKE | PE OH | PE OI | PE ΔOI | PE LTP`

ATM row highlighted. OH cells amber-highlighted. OH Hit cells pulse green.

- [ ] **Step 1: Create `frontend/src/components/Fno/OptionsChainTable.tsx`**

```tsx
/**
 * OptionsChainTable — options chain grid.
 *
 * Columns (left=CE, right=PE):
 *   CE LTP | CE ΔOI | CE OI | CE OH | STRIKE | PE OH | PE OI | PE ΔOI | PE LTP
 *
 * Colour rules:
 *   - ATM row: slightly brighter background
 *   - CE columns: dim red on hover (writer perspective)
 *   - PE columns: dim green on hover (writer perspective)
 *   - OH cell: amber text "OH" badge
 *   - OH Hit cell: green pulsing "HIT" badge
 */
import type { FnoSnapshot, OptionSide } from "./types";

const TV = {
  bg: "#0d0d1a", panel: "#131722", border: "#2a2e39",
  text: "#d1d4dc", muted: "#787b86",
  up: "#26a69a", down: "#ef5350", warn: "#f59e0b",
  accent: "#2962ff",
  atm: "#1a1e2e",
} as const;

function fmt2(n: number | undefined): string {
  if (n === undefined || n === null) return "—";
  return n.toFixed(2);
}

function fmtOi(n: number | undefined): string {
  if (n === undefined || n === null) return "—";
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(Math.round(n));
}

function fmtDelta(n: number | undefined): string {
  if (n === undefined || n === null) return "—";
  const prefix = n > 0 ? "+" : "";
  return prefix + fmtOi(n);
}

function OhBadge({ side }: { side: OptionSide | null }) {
  if (!side) return null;
  if (side.is_oh_hit) {
    return (
      <span style={{
        color: TV.up, fontSize: 9, fontWeight: 700,
        border: `1px solid ${TV.up}`, borderRadius: 3,
        padding: "1px 4px", animation: "pulse 1s infinite",
      }}>HIT</span>
    );
  }
  if (side.is_oh) {
    return (
      <span style={{
        color: TV.warn, fontSize: 9, fontWeight: 700,
        border: `1px solid ${TV.warn}`, borderRadius: 3,
        padding: "1px 4px",
      }}>OH</span>
    );
  }
  return null;
}

const cell: React.CSSProperties = {
  padding: "5px 8px", textAlign: "right", fontSize: 12,
  fontFamily: "monospace", borderBottom: `1px solid ${TV.border}`,
  whiteSpace: "nowrap",
};
const centreCell: React.CSSProperties = { ...cell, textAlign: "center" };
const headerCell: React.CSSProperties = {
  ...cell, color: TV.muted, fontSize: 10, fontWeight: 600,
  textTransform: "uppercase", letterSpacing: 0.5,
  position: "sticky", top: 0, background: TV.bg, zIndex: 1,
};

interface Props {
  snapshot: FnoSnapshot;
}

export default function OptionsChainTable({ snapshot }: Props) {
  return (
    <div style={{ overflowX: "auto", overflowY: "auto", maxHeight: "70vh" }}>
      <style>{`
        @keyframes pulse {
          0%,100% { opacity: 1; }
          50%      { opacity: 0.4; }
        }
      `}</style>
      <table style={{ borderCollapse: "collapse", width: "100%", fontSize: 12 }}>
        <thead>
          <tr>
            {/* CE headers */}
            <th style={{ ...headerCell, textAlign: "right" }}>CE LTP</th>
            <th style={{ ...headerCell, textAlign: "right" }}>CE ΔOI</th>
            <th style={{ ...headerCell, textAlign: "right" }}>CE OI</th>
            <th style={{ ...headerCell, textAlign: "center" }}>OH</th>
            {/* Strike */}
            <th style={{ ...headerCell, textAlign: "center", color: TV.accent }}>STRIKE</th>
            {/* PE headers */}
            <th style={{ ...headerCell, textAlign: "center" }}>OH</th>
            <th style={{ ...headerCell, textAlign: "left" }}>PE OI</th>
            <th style={{ ...headerCell, textAlign: "left" }}>PE ΔOI</th>
            <th style={{ ...headerCell, textAlign: "left" }}>PE LTP</th>
          </tr>
        </thead>
        <tbody>
          {snapshot.strikes.map(row => {
            const isAtm = row.strike === snapshot.atm_strike;
            const rowBg = isAtm ? TV.atm : "transparent";
            const ceLtp  = row.ce?.ltp;
            const peOi   = row.pe?.oi;
            const ceOi   = row.ce?.oi;

            return (
              <tr
                key={row.strike}
                style={{ background: rowBg }}
              >
                {/* CE side (right-aligned, strike decreases left-to-right) */}
                <td style={{ ...cell, color: ceLtp ? TV.down : TV.muted }}>
                  {fmt2(ceLtp)}
                </td>
                <td style={{ ...cell, color: row.ce?.delta_oi ?? 0 > 0 ? TV.down : TV.up }}>
                  {fmtDelta(row.ce?.delta_oi)}
                </td>
                <td style={{ ...cell, color: TV.text }}>
                  {fmtOi(ceOi)}
                </td>
                <td style={centreCell}>
                  <OhBadge side={row.ce} />
                </td>

                {/* Strike */}
                <td style={{
                  ...centreCell,
                  fontWeight: isAtm ? 700 : 400,
                  color: isAtm ? TV.accent : TV.text,
                  fontSize: isAtm ? 13 : 12,
                }}>
                  {row.strike}
                </td>

                {/* PE side (left-aligned) */}
                <td style={centreCell}>
                  <OhBadge side={row.pe} />
                </td>
                <td style={{ ...cell, textAlign: "left", color: TV.text }}>
                  {fmtOi(peOi)}
                </td>
                <td style={{ ...cell, textAlign: "left", color: row.pe?.delta_oi ?? 0 > 0 ? TV.up : TV.down }}>
                  {fmtDelta(row.pe?.delta_oi)}
                </td>
                <td style={{ ...cell, textAlign: "left", color: row.pe?.ltp ? TV.up : TV.muted }}>
                  {fmt2(row.pe?.ltp)}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 2: Commit**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system
git add frontend/src/components/Fno/OptionsChainTable.tsx
git commit -m "feat: add OptionsChainTable component with OH badge and ATM highlight"
```

---

## Task 7: FnoLive page + routing + sidebar

**Files:**
- Create: `frontend/src/pages/FnoLive.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/Layout/Sidebar.tsx`

- [ ] **Step 1: Create `frontend/src/pages/FnoLive.tsx`**

```tsx
/**
 * FnoLive page — live NIFTY FnO analysis.
 *
 * Layout:
 *   [Header: symbol + expiry + fetched_at + Refresh button]
 *   [PcrCards]
 *   [OptionsChainTable]
 */
import { useState, useCallback } from "react";
import { apiClient } from "../api/client";
import PcrCards from "../components/Fno/PcrCards";
import OptionsChainTable from "../components/Fno/OptionsChainTable";
import type { FnoSnapshot } from "../components/Fno/types";

const TV = {
  bg: "#0d0d1a", panel: "#131722", border: "#2a2e39",
  text: "#d1d4dc", muted: "#787b86", accent: "#2962ff",
  warn: "#f59e0b",
} as const;

const btnStyle = (disabled: boolean): React.CSSProperties => ({
  background: disabled ? "#1e222d" : TV.accent,
  border: `1px solid ${disabled ? TV.border : TV.accent}`,
  borderRadius: 4, color: disabled ? TV.muted : "#fff",
  padding: "6px 18px", cursor: disabled ? "default" : "pointer",
  fontSize: 13, fontWeight: 600,
});

export default function FnoLive() {
  const [snapshot, setSnapshot] = useState<FnoSnapshot | null>(null);
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState<string>("");

  const refresh = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const { data } = await apiClient.get<FnoSnapshot>("/fno/snapshot", {
        params: { symbol: "NIFTY", strikes: 10 },
      });
      setSnapshot(data);
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } }; message?: string })
        ?.response?.data?.detail ?? (e as Error)?.message ?? "Fetch failed";
      setError(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  return (
    <div style={{ height: "100%", overflowY: "auto", background: TV.bg, padding: 16 }}>
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center", gap: 14,
        marginBottom: 16, flexWrap: "wrap",
      }}>
        <span style={{ fontSize: 18, fontWeight: 700, color: TV.text }}>
          NIFTY FnO Live
        </span>

        {snapshot && (
          <span style={{ fontSize: 12, color: TV.muted }}>
            Expiry: {snapshot.expiry}
            &nbsp;·&nbsp;
            Fetched: {new Date(snapshot.fetched_at).toLocaleTimeString("en-IN")}
          </span>
        )}

        <button onClick={refresh} disabled={loading} style={btnStyle(loading)}>
          {loading ? "⏳ Fetching…" : "↻ Refresh"}
        </button>

        {error && (
          <span style={{ color: "#ef5350", fontSize: 12 }}>{error}</span>
        )}
      </div>

      {/* Empty state */}
      {!snapshot && !loading && (
        <div style={{
          display: "flex", flexDirection: "column", alignItems: "center",
          justifyContent: "center", minHeight: 300, gap: 12,
          color: TV.muted,
        }}>
          <div style={{ fontSize: 40 }}>📊</div>
          <div style={{ fontSize: 14 }}>Press Refresh to load NIFTY option chain</div>
          <div style={{ fontSize: 11 }}>Requires active Kite MCP session</div>
        </div>
      )}

      {/* Data */}
      {snapshot && (
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <PcrCards snapshot={snapshot} />
          <OptionsChainTable snapshot={snapshot} />
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Add `/fno` route to `frontend/src/App.tsx`**

Open `frontend/src/App.tsx`. Add the import at the top:

```tsx
import FnoLive from "./pages/FnoLive";
```

Inside the protected routes (where `/screener`, `/chart/:symbol` etc are defined), add:

```tsx
<Route path="/fno" element={<FnoLive />} />
```

- [ ] **Step 3: Add FnO nav item to `frontend/src/components/Layout/Sidebar.tsx`**

Open `Sidebar.tsx`. Find the nav items array (where `/screener`, `/chart/RELIANCE`, `/signals`, `/chat` are listed). Add the FnO entry:

```tsx
{ path: "/fno", label: "FnO Live", icon: "📈" },
```

(Match the exact shape of the existing nav item objects — icon + label + path.)

- [ ] **Step 4: Verify TypeScript compiles**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system/frontend
npx tsc --noEmit 2>&1
```

Expected: no output (clean compile).

- [ ] **Step 5: Commit**

```bash
cd /Users/ankitatiwari/Desktop/claude-playground/trading-system
git add frontend/src/pages/FnoLive.tsx \
        frontend/src/App.tsx \
        frontend/src/components/Layout/Sidebar.tsx
git commit -m "feat: add FnoLive page, /fno route, and sidebar nav item"
```

---

## Self-Review Checklist

### Spec coverage
| Requirement | Task |
|---|---|
| PCR (total PE OI / total CE OI) | Task 1, `_compute_ratios` |
| PCDR (ΔPE OI / ΔCE OI) | Task 1, `_compute_ratios` |
| PCD (ΔPE OI − ΔCE OI) | Task 1, `_compute_ratios` |
| Nearby strikes for NIFTY | Task 1, `_build_instruments` with ±10 strikes |
| Open-High detection | Task 1, `_is_oh` / `_is_oh_hit` |
| OH Hit shown in UI | Task 6, `OhBadge` pulsing HIT |
| KiteMCP as data source | Task 1, `_mcp()` via `https://mcp.kite.trade/mcp` |
| ≤200 RPM constraint | Task 1, `_kite_limiter.acquire()` (180 RPM) |
| Refresh button | Task 7, `FnoLive.tsx` |
| Temporal workflow | Task 2, `FnoSnapshotWorkflow` |

### Potential issues to watch
1. **`NSE:NIFTY 50` LTP key**: space in instrument name — verify `spot_data.get("NSE:NIFTY 50")` returns data (may need URL encoding or different key format from Kite).
2. **NIFTY expiry schedule**: `_nearest_monthly_expiry` assumes last Thursday; verify this against actual NSE expiry calendar.
3. **`get_quotes` OI field**: field might be named `oi` or `open_interest` — read actual response during first live test and adjust.
4. **Sidebar nav item shape**: Match existing nav object structure exactly when editing `Sidebar.tsx`.
