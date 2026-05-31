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

from workers.activities.fetch_kitemcp_1min import _kite_limiter

IST             = timezone(timedelta(hours=5, minutes=30))
_REDIS_FALLBACK = "redis://localhost:6379"

# Per-symbol config: spot instrument, strike step, option exchange, expiry type
# expiry_type: "weekly_thu" | "weekly_tue" | "monthly_thu"
_SYMBOL_CONFIGS: dict[str, dict] = {
    "NIFTY": {
        "spot": "NSE:NIFTY 50",
        "step": 50,
        "exchange": "NFO",
        "expiry_type": "weekly_tue",    # every Tuesday
    },
    "BANKNIFTY": {
        "spot": "NSE:NIFTY BANK",
        "step": 100,
        "exchange": "NFO",
        "expiry_type": "monthly_tue",   # last Tuesday of month
    },
    "MIDCPNIFTY": {
        "spot": "NSE:NIFTY MID SELECT",
        "step": 25,
        "exchange": "NFO",
        "expiry_type": "monthly_tue",   # last Tuesday of month
    },
    "SENSEX": {
        "spot": "BSE:SENSEX",
        "step": 100,
        "exchange": "BFO",
        "expiry_type": "weekly_thu",    # every Thursday
    },
}

# Kite 1-char month codes used in weekly option symbols
_MONTH_CHAR = {
    1:"1", 2:"2", 3:"3", 4:"4", 5:"5", 6:"6",
    7:"7", 8:"8", 9:"9", 10:"O", 11:"N", 12:"D",
}


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
        from core.config import settings
        url = settings.redis_url
    except Exception:
        url = _REDIS_FALLBACK
    return redis_lib.from_url(url, decode_responses=True)


def _fallback_expiries(symbol: str, count: int = 8) -> list[str]:
    """Compute upcoming expiries from rule — used when Kite MCP is unavailable."""
    cfg = _SYMBOL_CONFIGS.get(symbol, _SYMBOL_CONFIGS["NIFTY"])
    expiry_type = cfg["expiry_type"]
    today = date.today()
    results: list[str] = []

    if expiry_type in ("weekly_tue", "weekly_thu"):
        target = 1 if expiry_type == "weekly_tue" else 3
        days = (target - today.weekday()) % 7 or 7
        d = today + timedelta(days=days)
        for _ in range(count):
            results.append(str(d))
            d += timedelta(weeks=1)
    else:
        target = 1 if expiry_type == "monthly_tue" else 3
        y, m = today.year, today.month
        while len(results) < count:
            exp = _last_weekday_of_month(y, m, target)
            if exp >= today:
                results.append(str(exp))
            m += 1
            if m > 12:
                m = 1; y += 1

    return results


def _last_weekday_of_month(y: int, m: int, weekday: int) -> date:
    """Last occurrence of weekday (0=Mon..6=Sun) in given month."""
    if m == 12:
        last = date(y + 1, 1, 1) - timedelta(days=1)
    else:
        last = date(y, m + 1, 1) - timedelta(days=1)
    return last - timedelta(days=(last.weekday() - weekday) % 7)


def _nearest_expiry(symbol: str, today: date) -> date:
    """Return next expiry for the given symbol based on its expiry_type."""
    cfg = _SYMBOL_CONFIGS.get(symbol, _SYMBOL_CONFIGS["NIFTY"])
    expiry_type = cfg["expiry_type"]

    # Weekly expiries: find next occurrence of target weekday
    if expiry_type in ("weekly_tue", "weekly_thu"):
        target = 1 if expiry_type == "weekly_tue" else 3  # 1=Tue, 3=Thu
        days = (target - today.weekday()) % 7 or 7
        return today + timedelta(days=days)

    # Monthly expiries: last Tuesday (monthly_tue) or last Thursday (monthly_thu)
    target = 1 if expiry_type == "monthly_tue" else 3
    exp = _last_weekday_of_month(today.year, today.month, target)
    if exp < today:
        nm = today.month % 12 + 1
        ny = today.year + (1 if today.month == 12 else 0)
        exp = _last_weekday_of_month(ny, nm, target)
    return exp


def _expiry_prefix(symbol_name: str, expiry: date, is_monthly: bool) -> str:
    """Build Kite option instrument prefix.

    Monthly: NIFTY26JUN  (YYMMM 3-char month)
    Weekly:  NIFTY26605  (YY + 1-char month + 2-digit day)
    """
    if is_monthly:
        return f"{symbol_name}{expiry.strftime('%y%b').upper()}"
    char = _MONTH_CHAR[expiry.month]
    return f"{symbol_name}{expiry.strftime('%y')}{char}{expiry.day:02d}"


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
# ---------------------------------------------------------------------------
# Expiry list
# ---------------------------------------------------------------------------

def run_expiries(symbol: str = "NIFTY") -> dict:
    """Return available option expiry dates for the given symbol.

    Tries Kite MCP search_instruments first; falls back to rule-based computation.
    Results cached in Redis for 1 hour.
    """
    today = date.today()
    cfg   = _SYMBOL_CONFIGS.get(symbol, _SYMBOL_CONFIGS["NIFTY"])
    exchange = cfg["exchange"]
    rdb   = _redis()
    cache_key = f"fno:expiries:{symbol}"

    cached = rdb.get(cache_key)
    if cached:
        rdb.close()
        return json.loads(cached)

    try:
        mc = _FnoMCPClient()
    except RuntimeError:
        rdb.close()
        return {"expiries": _fallback_expiries(symbol), "source": "computed"}

    try:
        raw = mc.call_tool("search_instruments", {
            "query": symbol,
            "exchange": exchange,
        })

        # raw may be a list directly or wrapped in a dict
        if isinstance(raw, list):
            instruments = raw
        elif isinstance(raw, dict):
            instruments = (
                raw.get("instruments") or raw.get("data") or
                raw.get("result") or []
            )
        else:
            instruments = []

        expiries: set[str] = set()
        for inst in instruments:
            if not isinstance(inst, dict):
                continue
            itype    = inst.get("instrument_type", "")
            name     = (inst.get("name") or inst.get("underlying") or "").strip()
            exp_raw  = inst.get("expiry") or inst.get("expiry_date") or ""
            if itype not in ("CE", "PE"):
                continue
            if name.upper() != symbol.upper():
                continue
            exp_str = str(exp_raw)[:10]
            try:
                exp_date = date.fromisoformat(exp_str)
                if exp_date >= today:
                    expiries.add(exp_str)
            except ValueError:
                continue

        if not expiries:
            result = {"expiries": _fallback_expiries(symbol), "source": "computed"}
        else:
            result = {"expiries": sorted(expiries), "source": "kitemcp"}

        rdb.setex(cache_key, 3600, json.dumps(result))
        return result

    except Exception as exc:
        result = {
            "expiries": _fallback_expiries(symbol),
            "source": "computed",
            "error": str(exc),
        }
        return result
    finally:
        mc.close()
        rdb.close()


# Core snapshot logic
# ---------------------------------------------------------------------------

def run_fno_snapshot(symbol: str = "NIFTY", strikes: int = 10,
                     expiry_override: str | None = None) -> dict:
    """
    Fetch FnO snapshot for the given index symbol.

    Makes exactly 2 Kite MCP calls:
      1. get_ltp   → spot price
      2. get_quotes → OI + OHLC for (strikes*2+1) × 2 option instruments

    Delta OI computed via Redis baselines (set on first fetch each trading day).
    Results are cached in Redis for 5 minutes — if Kite MCP is down/expired,
    serves stale data with `stale: true` flag.

    Returns
    -------
    dict: symbol, spot, expiry, atm_strike, pcr, pcdr, pcd,
          total_ce_oi, total_pe_oi, strikes[{strike, ce, pe}], fetched_at
    """
    cfg = _SYMBOL_CONFIGS.get(symbol, _SYMBOL_CONFIGS["NIFTY"])
    step         = cfg["step"]
    spot_instr   = cfg["spot"]
    exchange     = cfg["exchange"]
    is_monthly   = cfg["expiry_type"].startswith("monthly")

    today = date.today()
    if expiry_override:
        try:
            expiry = date.fromisoformat(expiry_override)
        except ValueError:
            expiry = _nearest_expiry(symbol, today)
    else:
        expiry = _nearest_expiry(symbol, today)

    prefix = _expiry_prefix(symbol, expiry, is_monthly)
    rdb    = _redis()

    cache_key = f"fno:snapshot:{symbol}:{expiry}"

    try:
        mc = _FnoMCPClient()
    except RuntimeError:
        # No session file — try cache
        cached = rdb.get(cache_key)
        rdb.close()
        if cached:
            result = json.loads(cached)
            result["stale"] = True
            return result
        raise

    try:
        # --- call 1: spot ---
        spot_data = mc.call_tool("get_ltp", {"instruments": [spot_instr]})
        spot = float((spot_data.get(spot_instr) or {}).get("last_price", 0))
        if spot <= 0:
            raise RuntimeError(f"Could not fetch {symbol} spot. Response: {spot_data}")

        atm         = round(spot / step) * step
        strike_list = [int(atm + i * step) for i in range(-strikes, strikes + 1)]
        instruments = [
            f"{exchange}:{prefix}{s}{t}"
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
            row: dict[str, Any] = {
                "strike": s,
                "ce_symbol": f"{exchange}:{prefix}{s}CE",
                "pe_symbol": f"{exchange}:{prefix}{s}PE",
            }
            for typ in ("CE", "PE"):
                sym  = f"{exchange}:{prefix}{s}{typ}"
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
            "stale":       False,
        }

        # Cache for 5 minutes
        try:
            rdb.setex(cache_key, 300, json.dumps(result, default=str))
        except Exception:
            pass

    except Exception:
        # MCP call failed — try cache
        cached = rdb.get(cache_key)
        if cached:
            result = json.loads(cached)
            result["stale"] = True
            return result
        raise
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


# Registry alias — required by workers/registry.py (auto-discovery expects `activity_fn`)
activity_fn = fetch_fno_snapshot_activity
