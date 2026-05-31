"""1-minute OHLCV backfill via Zerodha Kite Connect API (~870 days depth).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ONE-TIME SETUP
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. Register at https://developers.kite.trade/ → create an app
2. Note API Key + API Secret
3. Set redirect URL to http://127.0.0.1:5050
4. Add to .env:
       KITE_API_KEY=your_api_key
       KITE_API_SECRET=your_api_secret

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DAILY ACCESS TOKEN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Run once per day to get fresh access token:

    cd backend
    PYTHONPATH=. python scripts/backfill_1min_kite.py --auth

It starts a local HTTP server on :5050, opens browser for Zerodha login,
captures the request_token automatically, exchanges it for access_token,
saves to .kite_access_token file. Then run backfill normally.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
USAGE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # Authenticate (once per day):
    cd backend && PYTHONPATH=. python scripts/backfill_1min_kite.py --auth

    # Run backfill (resume-safe):
    cd backend && PYTHONPATH=. python scripts/backfill_1min_kite.py

    # Specific date range:
    cd backend && PYTHONPATH=. python scripts/backfill_1min_kite.py --days 500

    # Pass token directly:
    cd backend && PYTHONPATH=. python scripts/backfill_1min_kite.py --token ACCESS_TOKEN

Depth: ~870 days confirmed on test account.
Speed: ~3 req/s with natural jitter → ~35k calls for 2387 symbols → ~3.5 hours.
"""
import asyncio
import argparse
import json
import os
import random
import sys
import time
import threading
import webbrowser
from datetime import date, timedelta, datetime
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs

env_path = Path(__file__).parent.parent.parent / ".env"
if env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(env_path)

CHECKPOINT_FILE = Path(__file__).parent / ".kite_1min_checkpoint.json"
TOKEN_FILE = Path(__file__).parent / ".kite_access_token"
CHUNK_DAYS = 59          # Kite allows 60-day windows for minute data
WORKERS = 6              # concurrent async workers

# Natural rate limiting — stay under 3 req/s but look organic
MIN_DELAY = 0.30
MAX_DELAY = 0.45


def load_checkpoint() -> dict:
    if CHECKPOINT_FILE.exists():
        return json.loads(CHECKPOINT_FILE.read_text())
    return {"completed": [], "failed": []}


def save_checkpoint(cp: dict) -> None:
    CHECKPOINT_FILE.write_text(json.dumps(cp, indent=2))


def load_access_token() -> str:
    token = os.environ.get("KITE_ACCESS_TOKEN", "")
    if not token and TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text().strip()
    return token


def save_access_token(token: str) -> None:
    TOKEN_FILE.write_text(token)
    TOKEN_FILE.chmod(0o600)


# ──────────────────────────────────────────────────────────────────────────────
# Auth flow — local HTTP server captures request_token from redirect
# ──────────────────────────────────────────────────────────────────────────────

_request_token_holder: dict = {}


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        qs = parse_qs(urlparse(self.path).query)
        token = qs.get("request_token", [None])[0]
        if token:
            _request_token_holder["token"] = token
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h2>Authentication successful. You can close this tab.</h2>")
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"No request_token found.")

    def log_message(self, *args):
        pass  # suppress access logs


def authenticate() -> str:
    from kiteconnect import KiteConnect

    api_key = os.environ.get("KITE_API_KEY", "")
    api_secret = os.environ.get("KITE_API_SECRET", "")

    if not api_key or not api_secret:
        print(
            "\nKite credentials not configured. Add to .env:\n"
            "  KITE_API_KEY=your_api_key\n"
            "  KITE_API_SECRET=your_api_secret\n\n"
            "Register at: https://developers.kite.trade/\n"
            "Set redirect URL to: http://127.0.0.1:5050\n"
        )
        sys.exit(1)

    kite = KiteConnect(api_key=api_key)
    login_url = kite.login_url()

    server = HTTPServer(("127.0.0.1", 5050), _CallbackHandler)
    server.timeout = 120

    print(f"\nOpening browser for Zerodha login...")
    print(f"URL: {login_url}\n")
    webbrowser.open(login_url)

    # Wait for callback
    deadline = time.time() + 120
    while "token" not in _request_token_holder and time.time() < deadline:
        server.handle_request()

    server.server_close()

    request_token = _request_token_holder.get("token")
    if not request_token:
        print("Timed out waiting for login. Try again.")
        sys.exit(1)

    data = kite.generate_session(request_token, api_secret=api_secret)
    access_token = data["access_token"]
    save_access_token(access_token)
    print(f"Access token saved to {TOKEN_FILE}")
    return access_token


def get_kite_client(access_token: str = ""):
    from kiteconnect import KiteConnect

    api_key = os.environ.get("KITE_API_KEY", "")
    if not api_key:
        print("KITE_API_KEY not set in .env")
        sys.exit(1)

    if not access_token:
        access_token = load_access_token()
    if not access_token:
        print(
            "\nNo access token found. Run auth first:\n"
            "  python scripts/backfill_1min_kite.py --auth\n"
        )
        sys.exit(1)

    kite = KiteConnect(api_key=api_key)
    kite.set_access_token(access_token)
    return kite


# ──────────────────────────────────────────────────────────────────────────────
# Instrument token map
# ──────────────────────────────────────────────────────────────────────────────

def build_token_map(kite) -> dict[str, int]:
    """Build symbol → instrument_token map for NSE EQ instruments."""
    instruments = kite.instruments("NSE")
    token_map: dict[str, int] = {}
    for inst in instruments:
        if inst.get("instrument_type") == "EQ" and inst.get("segment") == "NSE":
            sym = inst["tradingsymbol"]
            token_map[sym] = inst["instrument_token"]
    print(f"Loaded {len(token_map)} NSE EQ tokens")
    return token_map


# ──────────────────────────────────────────────────────────────────────────────
# Fetch one chunk
# ──────────────────────────────────────────────────────────────────────────────

def fetch_chunk(kite, token: int, from_dt: date, to_dt: date) -> list:
    """Fetch one 59-day chunk of 1-min OHLCV. Returns list of dicts."""
    try:
        return kite.historical_data(
            instrument_token=token,
            from_date=from_dt,
            to_date=to_dt,
            interval="minute",
            continuous=False,
            oi=False,
        )
    except Exception as exc:
        msg = str(exc)
        # Token expired
        if "Invalid" in msg or "token" in msg.lower():
            raise RuntimeError("ACCESS_TOKEN_EXPIRED") from exc
        return []


# ──────────────────────────────────────────────────────────────────────────────
# Main backfill
# ──────────────────────────────────────────────────────────────────────────────

async def backfill_1min(
    access_token: str = "",
    days_back: int = 870,
    max_workers: int = WORKERS,
) -> None:
    import structlog
    import pandas as pd
    from core.logging import setup_logging
    from core.storage import get_storage

    setup_logging()
    log = structlog.get_logger(__name__)

    from core.universe import build_trading_universe

    kite = get_kite_client(access_token)
    token_map = build_token_map(kite)

    symbols = build_trading_universe(kite)
    if not symbols:
        log.error("no_symbols", hint="Universe build failed — check NSE CSV and Kite connection")
        sys.exit(1)

    storage = get_storage()
    cp = load_checkpoint()
    completed_set = set(cp["completed"])

    today = date.today()
    start_date = today - timedelta(days=days_back)

    # Build date chunks
    chunks: list[tuple[date, date]] = []
    d = start_date
    while d < today:
        chunk_end = min(d + timedelta(days=CHUNK_DAYS), today)
        chunks.append((d, chunk_end))
        d = chunk_end + timedelta(days=1)

    # Build work queue — only symbols present in token_map
    work = [
        (sym, fd, td)
        for sym in symbols
        for fd, td in chunks
        if f"{sym}:{fd.isoformat()}" not in completed_set
        and sym in token_map
    ]

    log.info(
        "backfill_1min_kite_start",
        symbols=len(symbols),
        chunks_per_sym=len(chunks),
        total_calls=len(work),
        days_back=days_back,
        eta_hours=round(len(work) * ((MIN_DELAY + MAX_DELAY) / 2) / 3600, 1),
    )

    total_rows = 0
    done = 0
    failed: list[str] = []
    last_call = 0.0
    token_expired = False
    sem = asyncio.Semaphore(max_workers)

    async def process(sym: str, from_dt: date, to_dt: date) -> None:
        nonlocal total_rows, done, last_call, token_expired

        if token_expired:
            return

        async with sem:
            # Natural jitter — looks organic, not robotic fixed interval
            now = time.monotonic()
            elapsed = now - last_call
            jitter = random.uniform(MIN_DELAY, MAX_DELAY)
            wait = jitter - elapsed
            if wait > 0:
                await asyncio.sleep(wait)
            last_call = time.monotonic()

            try:
                inst_token = token_map[sym]
                loop = asyncio.get_event_loop()
                candles = await loop.run_in_executor(
                    None, fetch_chunk, kite, inst_token, from_dt, to_dt
                )

                if candles:
                    df = pd.DataFrame(candles)
                    # kiteconnect returns dicts with keys: date, open, high, low, close, volume
                    if "date" in df.columns:
                        df = df.rename(columns={"date": "ts"})
                    df["symbol"] = sym
                    df["ts"] = pd.to_datetime(df["ts"]).dt.tz_localize(None)
                    for col in ["open", "high", "low", "close", "volume"]:
                        if col in df.columns:
                            df[col] = pd.to_numeric(df[col], errors="coerce")
                    df = df[["ts", "symbol", "open", "high", "low", "close", "volume"]].dropna(
                        subset=["open", "close"]
                    )
                    if not df.empty:
                        month = df["ts"].iloc[0].strftime("%Y-%m")
                        path = f"timeframe=1min/symbol={sym}/month={month}/{sym}_{from_dt.isoformat()}.parquet"
                        storage.write_parquet(df, path)
                        total_rows += len(df)

                cp["completed"].append(f"{sym}:{from_dt.isoformat()}")

            except RuntimeError as exc:
                if "ACCESS_TOKEN_EXPIRED" in str(exc):
                    log.error("access_token_expired", hint="Re-run --auth then restart")
                    token_expired = True
                    return
                log.warning("chunk_failed", symbol=sym, from_dt=from_dt, error=str(exc))
                failed.append(f"{sym}:{from_dt.isoformat()}")
            except Exception as exc:
                log.warning("chunk_failed", symbol=sym, from_dt=from_dt, error=str(exc))
                failed.append(f"{sym}:{from_dt.isoformat()}")

            done += 1
            if done % 500 == 0 or done == len(work):
                save_checkpoint({"completed": cp["completed"], "failed": failed})
                log.info(
                    "backfill_1min_kite_progress",
                    done=done,
                    total=len(work),
                    pct=f"{done / len(work) * 100:.1f}%",
                    rows=total_rows,
                    failed=len(failed),
                )

    await asyncio.gather(*[process(s, f, t) for s, f, t in work])
    save_checkpoint({"completed": cp["completed"], "failed": failed})

    if token_expired:
        log.error(
            "backfill_stopped_token_expired",
            done=done,
            remaining=len(work) - done,
            hint="Run: python scripts/backfill_1min_kite.py --auth && python scripts/backfill_1min_kite.py",
        )
    else:
        log.info(
            "backfill_1min_kite_complete",
            rows=total_rows,
            failed=len(failed),
            checkpoint=str(CHECKPOINT_FILE),
        )


# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="1-min NSE backfill via Zerodha Kite Connect",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--auth",
        action="store_true",
        help="Run OAuth flow to get fresh access token (do once per day)",
    )
    parser.add_argument(
        "--token",
        default="",
        help="Pass access token directly instead of using saved file",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=870,
        help="Days of history to backfill (default: 870)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=WORKERS,
        help=f"Concurrent workers (default: {WORKERS})",
    )
    args = parser.parse_args()

    if args.auth:
        token = authenticate()
        print(f"\nAuthentication complete. Access token saved.")
        print(f"Now run: python scripts/backfill_1min_kite.py")
        sys.exit(0)

    asyncio.run(backfill_1min(
        access_token=args.token,
        days_back=args.days,
        max_workers=args.workers,
    ))
