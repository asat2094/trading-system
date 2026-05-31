"""1-minute OHLCV backfill via Kite MCP server (mcp.kite.trade).

No Kite Connect developer account needed — uses the same MCP server
that Claude Code uses. Auth via browser login, token tied to session.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
USAGE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    cd backend
    PYTHONPATH=. python scripts/backfill_1min_kitemcp.py

    # Specific date range:
    PYTHONPATH=. python scripts/backfill_1min_kitemcp.py --days 60

    # Resume after interruption:
    PYTHONPATH=. python scripts/backfill_1min_kitemcp.py

Rate: 1 req / 2–3s (conservative — shared MCP server, be respectful).
Output: rawdata/1min/{symbol}/{symbol}_{from_date}.csv
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import random
import sys
import time
import webbrowser
from datetime import date, timedelta
from pathlib import Path

import httpx
import logging
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

# ──────────────────────────────────────────────────────────────────────────────
env_path = Path(__file__).parent.parent.parent / ".env"
if env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(env_path)

MCP_URL = "https://mcp.kite.trade/mcp"
RAWDATA_DIR = Path(__file__).parent.parent.parent / "rawdata" / "1min"
CHECKPOINT_FILE = Path(__file__).parent / ".kitemcp_checkpoint.json"
SESSION_FILE = Path(__file__).parent / ".kitemcp_session"
TOKEN_CACHE_FILE = Path(__file__).parent / ".kitemcp_tokens.json"

CHUNK_DAYS = 59          # Kite allows 60-day windows for minute data
MIN_DELAY = 2.0          # conservative — shared public MCP server
MAX_DELAY = 3.0


# ──────────────────────────────────────────────────────────────────────────────
# MCP HTTP client
# ──────────────────────────────────────────────────────────────────────────────

class KiteMCPClient:
    def __init__(self):
        self.session_id: str = ""
        self.client = httpx.Client(timeout=30)

    def _post(self, method: str, params: dict, call_id: int = 1) -> dict:
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
            "id": call_id,
        }
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.session_id:
            headers["mcp-session-id"] = self.session_id

        resp = self.client.post(MCP_URL, json=payload, headers=headers)
        resp.raise_for_status()

        # Capture session ID from response headers
        sid = resp.headers.get("mcp-session-id", "")
        if sid:
            self.session_id = sid

        return resp.json()

    def initialize(self) -> None:
        self._post("initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "kitemcp-backfill", "version": "1.0"},
        })

    def call_tool(self, name: str, arguments: dict, call_id: int = 1) -> dict:
        return self._post("tools/call", {"name": name, "arguments": arguments}, call_id)

    def login(self) -> str:
        """Call login tool, return auth URL."""
        result = self.call_tool("login", {})
        text = result["result"]["content"][0]["text"]
        # Extract URL from the response text
        for word in text.split():
            if word.startswith("https://kite.zerodha.com"):
                return word.rstrip(")")
        # Try markdown link format
        import re
        m = re.search(r"https://kite\.zerodha\.com[^\s\)\"]+", text)
        return m.group(0) if m else ""

    def get_historical_data(self, token: int, from_date: str, to_date: str) -> list:
        """Fetch 1-min OHLCV. Returns list of candle dicts."""
        result = self.call_tool("get_historical_data", {
            "instrument_token": token,
            "interval": "minute",
            "from_date": f"{from_date} 09:00:00",
            "to_date": f"{to_date} 15:30:00",
        })
        content = result.get("result", {}).get("content", [{}])[0]
        if content.get("type") == "text":
            text = content["text"]
            if text.startswith("Failed") or text.startswith("Error"):
                raise RuntimeError(text)
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return []
        return []

    def search_instrument(self, symbol: str) -> int | None:
        """Return instrument token for NSE EQ symbol."""
        result = self.call_tool("search_instruments", {"query": f"NSE:{symbol}"})
        text = result.get("result", {}).get("content", [{}])[0].get("text", "[]")
        try:
            instruments = json.loads(text)
            for inst in instruments:
                if (inst.get("tradingsymbol") == symbol
                        and inst.get("exchange") == "NSE"
                        and inst.get("instrument_type") == "EQ"):
                    return inst["instrument_token"]
        except Exception:
            pass
        return None

    def close(self):
        self.client.close()


# ──────────────────────────────────────────────────────────────────────────────
# Session + token cache
# ──────────────────────────────────────────────────────────────────────────────

def load_session() -> str:
    if SESSION_FILE.exists():
        return SESSION_FILE.read_text().strip()
    return ""


def save_session(sid: str) -> None:
    SESSION_FILE.write_text(sid)


def load_token_cache() -> dict[str, int]:
    if TOKEN_CACHE_FILE.exists():
        return json.loads(TOKEN_CACHE_FILE.read_text())
    return {}


def save_token_cache(cache: dict[str, int]) -> None:
    TOKEN_CACHE_FILE.write_text(json.dumps(cache, indent=2))


# ──────────────────────────────────────────────────────────────────────────────
# Checkpoint
# ──────────────────────────────────────────────────────────────────────────────

def load_checkpoint() -> dict:
    if CHECKPOINT_FILE.exists():
        return json.loads(CHECKPOINT_FILE.read_text())
    return {"completed": [], "failed": []}


def save_checkpoint(cp: dict) -> None:
    CHECKPOINT_FILE.write_text(json.dumps(cp, indent=2))


# ──────────────────────────────────────────────────────────────────────────────
# Save candles to CSV
# ──────────────────────────────────────────────────────────────────────────────

def save_candles(symbol: str, from_date: str, candles: list) -> int:
    if not candles:
        return 0
    out_dir = RAWDATA_DIR / symbol
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"{symbol}_{from_date}.csv"

    fieldnames = ["ts", "open", "high", "low", "close", "volume"]
    with open(out_file, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for c in candles:
            writer.writerow({
                "ts": c.get("date", c.get("timestamp", "")),
                "open": c.get("open", ""),
                "high": c.get("high", ""),
                "low": c.get("low", ""),
                "close": c.get("close", ""),
                "volume": c.get("volume", ""),
            })
    return len(candles)


# ──────────────────────────────────────────────────────────────────────────────
# Main backfill
# ──────────────────────────────────────────────────────────────────────────────

def build_chunks(days_back: int) -> list[tuple[str, str]]:
    today = date.today()
    start = today - timedelta(days=days_back)
    chunks = []
    d = start
    while d < today:
        end = min(d + timedelta(days=CHUNK_DAYS), today)
        chunks.append((d.isoformat(), end.isoformat()))
        d = end + timedelta(days=1)
    return chunks


def _fetch_fno_via_mcp(client: KiteMCPClient) -> set[str]:
    """Fetch active FnO underlyings via MCP search_instruments (NFO futures)."""
    symbols: set[str] = set()
    try:
        # search_instruments with filter_on="underlying" returns futures/options for a symbol
        # Instead: fetch all NFO instruments by querying common index names + let token cache cover rest
        # Quickest: use known FnO list as seed, verify via search
        result = client.call_tool("search_instruments", {
            "query": "NFO",
            "filter_on": "tradingsymbol",
            "limit": 500,
        })
        text = result.get("result", {}).get("content", [{}])[0].get("text", "[]")
        instruments = json.loads(text)
        for inst in instruments:
            if inst.get("instrument_type") == "FUT":
                # tradingsymbol like "RELIANCE26MAYFUT" — extract underlying from name field
                name = inst.get("name", "").strip()
                if name:
                    symbols.add(name)
    except Exception as e:
        print(f"  FnO fetch via MCP failed: {e} — using fallback list")
        symbols = set(_FNO_FALLBACK)
    return symbols


# Fallback FnO list (update periodically — ~180 active F&O stocks)
_FNO_FALLBACK: list[str] = [
    "AARTIIND", "ABB", "ABBOTINDIA", "ABCAPITAL", "ABFRL", "ACC", "ADANIENT",
    "ADANIPORTS", "ALKEM", "AMBUJACEM", "ANGELONE", "APLAPOLLO", "APOLLOHOSP",
    "APOLLOTYRE", "ASHOKLEY", "ASIANPAINT", "ASTRAL", "ATGL", "AUBANK",
    "AUROPHARMA", "AXISBANK", "BAJAJ-AUTO", "BAJAJFINSV", "BAJFINANCE",
    "BALKRISIND", "BANDHANBNK", "BANKBARODA", "BANKINDIA", "BEL", "BERGEPAINT",
    "BHARATFORG", "BHARTIARTL", "BHEL", "BIOCON", "BPCL", "BRITANNIA",
    "BSE", "BSOFT", "CAMS", "CANFINHOME", "CHOLAFIN", "CIPLA", "COALINDIA",
    "COFORGE", "COLPAL", "COROMANDEL", "CROMPTON", "CUMMINSIND", "CYIENT",
    "DABUR", "DALBHARAT", "DEEPAKNTR", "DELHIVERY", "DIVISLAB", "DIXON",
    "DLF", "DMART", "DRREDDY", "ESCORTS", "EXIDEIND", "FACT", "FEDERALBNK",
    "FINNIFTY", "GAIL", "GLAND", "GLENMARK", "GMRINFRA", "GNFC", "GODREJCP",
    "GODREJPROP", "GRASIM", "GUJGASLTD", "HAL", "HCLTECH", "HDFCAMC",
    "HDFCBANK", "HDFCLIFE", "HEROMOTOCO", "HINDALCO", "HINDCOPPER", "HINDPETRO",
    "HINDUNILVR", "HINDZINC", "ICICIBANK", "ICICIGI", "ICICIPRULI", "IDEA",
    "IDFCFIRSTB", "IEX", "IGL", "INDHOTEL", "INDIAMART", "INDIGO",
    "INDUSINDBK", "INDUSTOWER", "INFY", "IOC", "IPCALAB", "IRCTC", "IRFC",
    "ITC", "JINDALSTEL", "JKCEMENT", "JSWENERGY", "JSWSTEEL", "JUBLFOOD",
    "KAJARIACER", "KOTAKBANK", "KPIL", "L&TFH", "LALPATHLAB", "LAURUSLABS",
    "LICHSGFIN", "LICI", "LT", "LTIM", "LTTS", "LUPIN", "M&M", "M&MFIN",
    "MARICO", "MARUTI", "MAXHEALTH", "MCX", "METROPOLIS", "MFSL", "MGL",
    "MPHASIS", "MRF", "MUTHOOTFIN", "NAUKRI", "NAVINFLUOR", "NESTLEIND",
    "NMDC", "NTPC", "OBEROIRLTY", "OFSS", "OIL", "ONGC", "PAGEIND",
    "PEL", "PERSISTENT", "PETRONET", "PFC", "PHOENIXLTD", "PIDILITIND",
    "PIIND", "PNB", "POLYCAB", "POONAWALLA", "POWERGRID", "PVRINOX",
    "RAMCOCEM", "RECLTD", "RELIANCE", "SAIL", "SBICARD", "SBILIFE", "SBIN",
    "SHREECEM", "SHRIRAMFIN", "SIEMENS", "SJVN", "SUNPHARMA", "SUNTV",
    "SUPREMEIND", "SUZLON", "SYNGENE", "TATACHEM", "TATACOMM", "TATACONSUM",
    "TATAELXSI", "TATAMOTORS", "TATAPOWER", "TATASTEEL", "TCS", "TECHM",
    "TITAN", "TORNTPHARM", "TORNTPOWER", "TRENT", "TVSMOTOR", "UBL",
    "ULTRACEMCO", "UNIONBANK", "UPL", "VEDL", "VOLTAS", "WIPRO", "YESBANK",
    "ZEEL", "ZOMATO", "ZYDUSLIFE",
]


def backfill(days_back: int = 60) -> None:
    import structlog
    from core.logging import setup_logging
    from core.universe import fetch_nifty500

    setup_logging()
    log = structlog.get_logger(__name__)

    client = KiteMCPClient()

    # Restore or create session
    saved_sid = load_session()
    if saved_sid:
        client.session_id = saved_sid
        print(f"Restored session: {saved_sid[:30]}...")
    else:
        client.initialize()
        save_session(client.session_id)
        print(f"New session: {client.session_id}")

    # Verify session works / authenticate
    print("Verifying session (fetching RELIANCE test candle)...")
    try:
        test = client.get_historical_data(738561,
                                          (date.today() - timedelta(days=5)).isoformat(),
                                          date.today().isoformat())
        print(f"Session OK — {len(test)} test candles fetched")
    except RuntimeError:
        print("Session needs fresh login...")
        client.initialize()
        save_session(client.session_id)
        auth_url = client.login()
        print(f"\nOpen in browser to login:\n{auth_url}\n")
        webbrowser.open(auth_url)
        input("Press Enter after completing Zerodha login in browser...")
        save_session(client.session_id)

    # Build universe: Nifty 500 + FnO
    # FnO list fetched via MCP search (NFO underlying filter)
    nifty500 = set(fetch_nifty500())
    print(f"Nifty 500: {len(nifty500)} symbols")

    fno = _fetch_fno_via_mcp(client)
    print(f"FnO: {len(fno)} symbols")

    symbols = sorted(nifty500 | fno)
    print(f"Universe (N500 ∪ FnO): {len(symbols)} symbols")

    # Build / restore instrument token cache
    token_cache = load_token_cache()
    missing = [s for s in symbols if s not in token_cache]
    if missing:
        print(f"Looking up {len(missing)} instrument tokens...")
        for i, sym in enumerate(missing):
            try:
                token = client.search_instrument(sym)
                if token:
                    token_cache[sym] = token
                time.sleep(random.uniform(0.5, 1.0))
            except Exception as e:
                print(f"  Token lookup failed for {sym}: {e}")
            if (i + 1) % 50 == 0:
                save_token_cache(token_cache)
                print(f"  {i+1}/{len(missing)} tokens resolved")
        save_token_cache(token_cache)
    print(f"Tokens resolved: {len(token_cache)}/{len(symbols)}")

    # Build work queue
    chunks = build_chunks(days_back)
    cp = load_checkpoint()
    completed_set = set(cp["completed"])

    work = [
        (sym, fd, td)
        for sym in symbols
        if sym in token_cache
        for fd, td in chunks
        if f"{sym}:{fd}" not in completed_set
    ]

    log.info("backfill_kitemcp_start",
             symbols=len(symbols),
             chunks=len(chunks),
             total_calls=len(work),
             days_back=days_back,
             eta_hours=round(len(work) * ((MIN_DELAY + MAX_DELAY) / 2) / 3600, 1))

    total_rows = 0
    done = 0
    failed: list[str] = []
    last_call = 0.0

    for sym, from_dt, to_dt in work:
        # Rate limit — conservative for shared MCP server
        now = time.monotonic()
        wait = random.uniform(MIN_DELAY, MAX_DELAY) - (now - last_call)
        if wait > 0:
            time.sleep(wait)
        last_call = time.monotonic()

        try:
            token = token_cache[sym]
            candles = client.get_historical_data(token, from_dt, to_dt)
            rows = save_candles(sym, from_dt, candles)
            total_rows += rows
            cp["completed"].append(f"{sym}:{from_dt}")
        except Exception as exc:
            msg = str(exc)
            log.warning("chunk_failed", symbol=sym, from_dt=from_dt, error=msg)
            failed.append(f"{sym}:{from_dt}")
            # Session expired — re-auth
            if "session" in msg.lower() or "token" in msg.lower() or "login" in msg.lower():
                print("\nSession expired. Re-authenticating...")
                client.initialize()
                save_session(client.session_id)
                auth_url = client.login()
                print(f"Open: {auth_url}")
                webbrowser.open(auth_url)
                input("Press Enter after login...")

        done += 1
        if done % 100 == 0 or done == len(work):
            save_checkpoint({"completed": cp["completed"], "failed": failed})
            log.info("backfill_kitemcp_progress",
                     done=done, total=len(work),
                     pct=f"{done/len(work)*100:.1f}%",
                     rows=total_rows, failed=len(failed))

    save_checkpoint({"completed": cp["completed"], "failed": failed})
    client.close()
    log.info("backfill_kitemcp_complete",
             rows=total_rows, failed=len(failed),
             output=str(RAWDATA_DIR))


# ──────────────────────────────────────────────────────────────────────────────

def do_auth() -> None:
    """Interactive auth — creates session and links to Zerodha account."""
    client = KiteMCPClient()
    client.initialize()
    save_session(client.session_id)
    print(f"Session created: {client.session_id}")

    auth_url = client.login()
    print(f"\nOpen in browser:\n{auth_url}\n")
    webbrowser.open(auth_url)
    input("Press Enter after completing Zerodha login in browser...")

    # Verify
    try:
        test = client.get_historical_data(
            738561,
            (date.today() - timedelta(days=5)).isoformat(),
            date.today().isoformat(),
        )
        print(f"\nAuth OK — {len(test)} RELIANCE candles fetched")
        print(f"Session saved to {SESSION_FILE}")
    except Exception as e:
        print(f"\nAuth failed: {e}")
        sys.exit(1)
    client.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="1-min NSE backfill via Kite MCP server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--auth", action="store_true",
                        help="Authenticate session (run once, then run without --auth)")
    parser.add_argument("--days", type=int, default=60,
                        help="Days of history to backfill (default: 60, max ~870)")
    args = parser.parse_args()

    if args.auth:
        do_auth()
    else:
        backfill(days_back=args.days)
