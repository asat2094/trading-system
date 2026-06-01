"""
Market REST endpoints:
  GET /market/ohlcv           — crypto OHLCV via yfinance
  GET /auth/upstox/login      — redirect to Upstox OAuth
  GET /auth/upstox/callback   — exchange code, store in Redis
  GET /auth/upstox/status     — check Redis for token
  GET /auth/kite/init         — start KiteMCP session, return Zerodha login URL
  GET /auth/kite/status       — verify KiteMCP session is authenticated
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse

from core.auth.middleware import get_current_user
from core.auth.provider import User
from core.cache import get_redis
from core.config import settings

router = APIRouter(tags=["market"])

_IST = timezone(timedelta(hours=5, minutes=30))


def _ttl_until_midnight_ist() -> int:
    """Seconds from now until midnight IST — when Upstox tokens expire."""
    now = datetime.now(_IST)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(60, int((midnight - now).total_seconds()))

# Hyperliquid interval names match their chart UI
_HL_TF_MAP = {
    "1min": "1m", "3min": "3m", "5min": "5m", "15min": "15m",
    "30min": "30m", "1h": "1h", "4h": "4h", "1d": "1d", "1w": "1w",
}

_HL_INFO_URL = "https://api.hyperliquid.xyz/info"


@router.get("/market/ohlcv")
async def get_market_ohlcv(
    symbol: str = Query(...),
    tf: str = Query("1d"),
    from_dt: datetime = Query(...),
    to_dt: datetime = Query(...),
    user: User = Depends(get_current_user),
):
    """Fetch OHLCV from Hyperliquid's own candle REST API.
    Data is identical to what Hyperliquid's chart displays.
    """
    if not symbol.startswith("CRYPTO:"):
        raise HTTPException(400, "Only CRYPTO: prefix supported")
    coin = symbol.split(":", 1)[1]
    hl_interval = _HL_TF_MAP.get(tf, "1d")
    # FastAPI parses ISO strings without tz as naive datetimes.
    # Python .timestamp() on naive datetimes uses local time (IST on dev machine).
    # Force UTC so start_ms/end_ms are always correct regardless of server tz.
    if from_dt.tzinfo is None:
        from_dt = from_dt.replace(tzinfo=timezone.utc)
    if to_dt.tzinfo is None:
        to_dt = to_dt.replace(tzinfo=timezone.utc)
    start_ms = int(from_dt.timestamp() * 1000)
    end_ms   = int(to_dt.timestamp() * 1000)
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                _HL_INFO_URL,
                json={
                    "type": "candleSnapshot",
                    "req": {
                        "coin": coin,
                        "interval": hl_interval,
                        "startTime": start_ms,
                        "endTime": end_ms,
                    },
                },
            )
            resp.raise_for_status()
            candles = resp.json()
    except httpx.HTTPStatusError as exc:
        raise HTTPException(502, f"Hyperliquid API error: {exc.response.status_code}") from exc
    except Exception as exc:
        raise HTTPException(500, f"Hyperliquid fetch failed: {exc}") from exc

    rows = [
        {
            "ts": datetime.fromtimestamp(c["t"] / 1000, tz=timezone.utc).isoformat(),
            "open":   float(c["o"]),
            "high":   float(c["h"]),
            "low":    float(c["l"]),
            "close":  float(c["c"]),
            "volume": float(c["v"]),
        }
        for c in candles
    ]
    return {"rows": rows}


_UPSTOX_REDIRECT = "http://127.0.0.1:8000/auth/upstox/callback"


@router.get("/auth/upstox/login")
async def upstox_login():
    if not settings.UPSTOX_API_KEY:
        raise HTTPException(503, "UPSTOX_API_KEY not configured")
    url = (
        "https://api.upstox.com/v2/login/authorization/dialog"
        f"?response_type=code&client_id={settings.UPSTOX_API_KEY}"
        f"&redirect_uri={_UPSTOX_REDIRECT}"
    )
    return RedirectResponse(url)


@router.get("/auth/upstox/callback")
async def upstox_callback(code: str = Query(...)):
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.upstox.com/v2/login/authorization/token",
            data={
                "code": code,
                "client_id": settings.UPSTOX_API_KEY,
                "client_secret": settings.UPSTOX_API_SECRET,
                "redirect_uri": _UPSTOX_REDIRECT,
                "grant_type": "authorization_code",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        )
    if resp.status_code != 200:
        raise HTTPException(502, f"Upstox token exchange failed: {resp.text}")
    access_token = resp.json().get("access_token")
    if not access_token:
        raise HTTPException(502, "No access_token in response")
    try:
        redis = get_redis()
        await redis.setex("upstox:token", _ttl_until_midnight_ist(), access_token)
    except Exception:
        pass  # Redis down — token exchange succeeded but can't persist; will retry on next poll
    # Trigger Upstox adapter reconnect
    try:
        from api.market_ws import get_manager
        await get_manager().reconnect_adapter("upstox")
    except Exception:
        pass
    return """
<!DOCTYPE html>
<html><head><title>Upstox Connected</title></head>
<body style="font-family:system-ui;text-align:center;padding:40px;background:#131722;color:#d1d4dc">
    <h2 style="color:#26a69a">Upstox Connected</h2>
    <p>You can close this window.</p>
    <script>
        if (window.opener) {
            window.opener.postMessage({type: "upstox-auth-complete", status: "ok"}, "http://localhost:5173");
        }
    </script>
</body></html>
    """


@router.post("/auth/upstox/reconnect")
async def upstox_reconnect(user: User = Depends(get_current_user)):
    """Reconnect Upstox adapter using the token already stored in Redis.
    Call this when the adapter dropped but the token is still valid — avoids
    forcing the user through a full OAuth flow again.
    """
    try:
        redis = get_redis()
        token = await redis.get("upstox:token")
        if not token:
            raise HTTPException(400, "No Upstox token stored — use /auth/upstox/login")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(503, "Redis unavailable")
    try:
        from api.market_ws import get_manager
        await get_manager().reconnect_adapter("upstox")
        return {"status": "reconnecting"}
    except Exception as exc:
        raise HTTPException(500, f"Reconnect failed: {exc}") from exc


@router.post("/auth/hyperliquid/reconnect")
async def hyperliquid_reconnect(user: User = Depends(get_current_user)):
    """Reconnect Hyperliquid WS adapter."""
    try:
        from api.market_ws import get_manager
        await get_manager().reconnect_adapter("hyperliquid")
        return {"status": "reconnecting"}
    except Exception as exc:
        raise HTTPException(500, f"Reconnect failed: {exc}") from exc


@router.get("/auth/upstox/status")
async def upstox_status(user: User = Depends(get_current_user)):
    try:
        redis = get_redis()
        token = await redis.get("upstox:token")
        ttl = await redis.ttl("upstox:token") if token else 0
        return {"connected": bool(token), "ttl_seconds": int(ttl)}
    except Exception:
        return {"connected": False, "ttl_seconds": 0}


# ── KiteMCP auth ──────────────────────────────────────────────────────────────

_KITEMCP_URL = "https://mcp.kite.trade/mcp"


def _kitemcp_post(session_id: str, method: str, params: dict) -> tuple[dict, str]:
    """Synchronous KiteMCP JSON-RPC call. Returns (response_body, new_session_id)."""
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if session_id:
        headers["mcp-session-id"] = session_id
    with httpx.Client(timeout=20) as client:
        resp = client.post(
            _KITEMCP_URL,
            json={"jsonrpc": "2.0", "method": method, "params": params, "id": 1},
            headers=headers,
        )
        resp.raise_for_status()
        new_sid = resp.headers.get("mcp-session-id", session_id)
        return resp.json(), new_sid


@router.get("/auth/kite/init")
async def kite_init(user: User = Depends(get_current_user)):
    """Initialize a KiteMCP session and return the Zerodha login URL.

    Flow:
      1. POST initialize → get mcp-session-id header
      2. Call login tool → extract Zerodha auth URL
      3. Store session_id in Redis under kite:session_id
      4. Return {auth_url} to frontend — user opens it to authenticate
    """
    import asyncio
    loop = asyncio.get_event_loop()

    def _init_and_login():
        # Step 1: initialize
        _, sid = _kitemcp_post("", "initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "trading-system", "version": "1.0"},
        })
        if not sid:
            raise RuntimeError("KiteMCP did not return a session ID")
        # Step 2: login tool → Zerodha URL
        body, sid = _kitemcp_post(sid, "tools/call", {"name": "login", "arguments": {}})
        text = body.get("result", {}).get("content", [{}])[0].get("text", "")
        import re
        m = re.search(r"https://kite\.zerodha\.com[^\s\)\"\]]+", text)
        auth_url = m.group(0) if m else ""
        return sid, auth_url

    try:
        sid, auth_url = await loop.run_in_executor(None, _init_and_login)
    except Exception as exc:
        raise HTTPException(502, f"KiteMCP init failed: {exc}") from exc

    try:
        redis = get_redis()
        await redis.set("kite:session_id", sid)   # no expiry — sessions persist
    except Exception:
        pass

    # Also write to file so sdk.py thread executor can read it without async Redis
    try:
        from pathlib import Path
        session_file = Path(__file__).parent.parent.parent / "scripts" / ".kitemcp_session"
        session_file.write_text(sid)
    except Exception:
        pass

    return {"auth_url": auth_url, "session_id": sid[:20] + "..."}


@router.get("/auth/kite/status")
async def kite_status(user: User = Depends(get_current_user)):
    """Check if the stored KiteMCP session is authenticated.

    Verifies by making a lightweight get_profile call. Returns
    {connected: bool, user: str|None}.
    """
    import asyncio
    loop = asyncio.get_event_loop()

    try:
        redis = get_redis()
        raw = await redis.get("kite:session_id")
        sid = raw.decode() if isinstance(raw, bytes) else (raw or "")
    except Exception:
        sid = ""

    # Fall back to file if Redis empty
    if not sid:
        try:
            from pathlib import Path
            session_file = Path(__file__).parent.parent.parent / "scripts" / ".kitemcp_session"
            if session_file.exists():
                sid = session_file.read_text().strip()
        except Exception:
            pass

    if not sid:
        return {"connected": False, "user": None}

    def _verify():
        body, _ = _kitemcp_post(sid, "tools/call", {"name": "get_profile", "arguments": {}})
        text = body.get("result", {}).get("content", [{}])[0].get("text", "")
        # get_profile returns JSON with user_name if authenticated
        import json as _json
        try:
            data = _json.loads(text)
            name = data.get("user_name") or data.get("user_id") or ""
            return bool(name), name
        except Exception:
            # If text is non-JSON error, session is not authenticated
            return False, None

    try:
        ok, name = await loop.run_in_executor(None, _verify)
        return {"connected": ok, "user": name}
    except Exception:
        return {"connected": False, "user": None}
