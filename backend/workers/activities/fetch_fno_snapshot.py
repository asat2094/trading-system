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
    return round(abs(high - open_), 10) <= tick


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

        ratios = _compute_ratios(total_ce_oi, total_pe_oi, total_ce_delta, total_pe_delta)
        result = {
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
    finally:
        mc.close()
        rdb.close()

    return result


# ---------------------------------------------------------------------------
# Temporal activity wrapper
# ---------------------------------------------------------------------------

@activity.defn(name="fetch_fno_snapshot")
async def fetch_fno_snapshot_activity(symbol: str = "NIFTY", strikes: int = 10) -> dict:
    """Temporal activity: async wrapper around sync run_fno_snapshot."""
    return await asyncio.to_thread(run_fno_snapshot, symbol, strikes)
