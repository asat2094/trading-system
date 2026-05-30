"""
Market REST endpoints:
  GET /market/ohlcv           — crypto OHLCV via yfinance
  GET /auth/upstox/login      — redirect to Upstox OAuth
  GET /auth/upstox/callback   — exchange code, store in Redis
  GET /auth/upstox/status     — check Redis for token
"""
from __future__ import annotations

from datetime import datetime

import httpx
import yfinance as yf
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse

from core.auth.middleware import get_current_user
from core.auth.provider import User
from core.cache import get_redis
from core.config import settings

router = APIRouter(tags=["market"])

_CRYPTO_MAP = {
    "BTC": "BTC-USD", "ETH": "ETH-USD", "SOL": "SOL-USD",
    "BNB": "BNB-USD", "DOGE": "DOGE-USD", "XRP": "XRP-USD",
    "AVAX": "AVAX-USD", "MATIC": "MATIC-USD", "ARB": "ARB-USD",
    "OP": "OP-USD", "SUI": "SUI-USD", "APT": "APT-USD",
}

_TF_MAP = {
    "1min": "1m", "3min": "3m", "5min": "5m", "15min": "15m",
    "30min": "30m", "1h": "1h", "4h": "60m", "1d": "1d", "1w": "1wk",
}


@router.get("/market/ohlcv")
async def get_market_ohlcv(
    symbol: str = Query(...),
    tf: str = Query("1d"),
    from_dt: datetime = Query(...),
    to_dt: datetime = Query(...),
    user: User = Depends(get_current_user),
):
    if not symbol.startswith("CRYPTO:"):
        raise HTTPException(400, "Only CRYPTO: prefix supported")
    coin = symbol.split(":", 1)[1]
    yf_sym = _CRYPTO_MAP.get(coin, f"{coin}-USD")
    yf_interval = _TF_MAP.get(tf, "1d")
    try:
        tkr = yf.Ticker(yf_sym)
        df = tkr.history(start=from_dt.date(), end=to_dt.date(), interval=yf_interval)
        if df.empty:
            return {"rows": []}
        rows = [
            {
                "ts": idx.isoformat(),
                "open": float(row["Open"]), "high": float(row["High"]),
                "low": float(row["Low"]),  "close": float(row["Close"]),
                "volume": float(row["Volume"]),
            }
            for idx, row in df.iterrows()
        ]
        return {"rows": rows}
    except Exception as exc:
        raise HTTPException(500, f"yfinance error: {exc}") from exc


@router.get("/auth/upstox/login")
async def upstox_login():
    if not settings.UPSTOX_API_KEY:
        raise HTTPException(503, "UPSTOX_API_KEY not configured")
    url = (
        "https://api.upstox.com/v2/login/authorization/dialog"
        f"?response_type=code&client_id={settings.UPSTOX_API_KEY}"
        "&redirect_uri=http://127.0.0.1:8000/auth/upstox/callback"
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
                "redirect_uri": "http://127.0.0.1:8000/auth/upstox/callback",
                "grant_type": "authorization_code",
            },
            headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        )
    if resp.status_code != 200:
        raise HTTPException(502, f"Upstox token exchange failed: {resp.text}")
    access_token = resp.json().get("access_token")
    if not access_token:
        raise HTTPException(502, "No access_token in response")
    redis = get_redis()
    await redis.setex("upstox:token", 86400, access_token)
    return {"status": "ok", "message": "Upstox connected. You can close this tab."}


@router.get("/auth/upstox/status")
async def upstox_status(user: User = Depends(get_current_user)):
    redis = get_redis()
    token = await redis.get("upstox:token")
    ttl = await redis.ttl("upstox:token") if token else 0
    return {"connected": bool(token), "ttl_seconds": int(ttl)}
