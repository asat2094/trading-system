"""Retry the 45 failed chunks from .download_progress.json.

Reads failed list, re-fetches each via Kite MCP, writes CSV.
On success: moves key from failed → done.
Prints full error per chunk for debugging.

Usage:
    cd backend
    PYTHONPATH=. python scripts/retry_failed_chunks.py
"""
import asyncio, csv, json, sys, time, random, re
from pathlib import Path
import httpx

MCP_URL       = "https://mcp.kite.trade/mcp"
SESSION_FILE  = Path(__file__).parent / ".kitemcp_session"
TOKEN_FILE    = Path(__file__).parent / ".kitemcp_tokens.json"
PROGRESS_FILE = Path(__file__).parent / ".download_progress.json"
RAWDATA_DIR   = Path(__file__).parent.parent.parent / "rawdata" / "1min"

CHUNK_DAYS = 7
DELAY      = 1.5   # seconds between requests


async def mcp_post(client, session_id, tool, args):
    r = await client.post(MCP_URL, json={
        "jsonrpc": "2.0", "method": "tools/call",
        "params": {"name": tool, "arguments": args}, "id": 1,
    }, headers={"Content-Type": "application/json", "mcp-session-id": session_id})
    r.raise_for_status()
    return r.json()


def get_text(result):
    return result.get("result", {}).get("content", [{}])[0].get("text", "")


def save_csv(symbol, from_date, to_date, candles):
    if not candles:
        return 0
    out = RAWDATA_DIR / symbol / f"{symbol}_{from_date}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ts", "open", "high", "low", "close", "volume"])
        w.writeheader()
        for c in candles:
            # Kite MCP returns either 'date' or 'ts'; also has extra 'oi' field — ignore it
            ts = c.get("ts") or c.get("date") or ""
            w.writerow({
                "ts": ts, "open": c["open"], "high": c["high"],
                "low": c["low"], "close": c["close"], "volume": c["volume"],
            })
    return len(candles)


def build_chunk_dates(key):
    """key = 'SYMBOL:YYYY-MM-DD' → (from_date, to_date)"""
    # from_date is the chunk start; reconstruct to_date from chunk boundaries
    from datetime import date, timedelta
    sym, fd = key.rsplit(":", 1)
    from_dt = date.fromisoformat(fd)
    to_dt   = from_dt + timedelta(days=CHUNK_DAYS - 1)
    today   = date.today()
    if to_dt > today:
        to_dt = today
    return sym, fd, to_dt.isoformat()


async def main():
    session_id = SESSION_FILE.read_text().strip() if SESSION_FILE.exists() else ""
    if not session_id:
        print("ERROR: No session. Run auth first.")
        sys.exit(1)

    tokens = json.loads(TOKEN_FILE.read_text()) if TOKEN_FILE.exists() else {}
    progress = json.loads(PROGRESS_FILE.read_text()) if PROGRESS_FILE.exists() else {}

    failed_keys = list(progress.get("failed", []))
    print(f"Retrying {len(failed_keys)} failed chunks...\n")

    results = {"ok": [], "empty": [], "still_failed": []}

    async with httpx.AsyncClient(timeout=30) as client:
        for i, key in enumerate(failed_keys):
            sym, fd, td = build_chunk_dates(key)

            if sym not in tokens:
                print(f"[{i+1:2d}/{len(failed_keys)}] SKIP   {key}  — no token")
                results["still_failed"].append(key)
                continue

            try:
                r = await mcp_post(client, session_id, "get_historical_data", {
                    "instrument_token": tokens[sym],
                    "interval": "minute",
                    "from_date": f"{fd} 09:00:00",
                    "to_date":   f"{td} 15:30:00",
                })
                text = get_text(r)

                if not text:
                    print(f"[{i+1:2d}/{len(failed_keys)}] EMPTY  {key}  — empty response")
                    results["empty"].append(key)
                elif "Failed" in text or ("error" in text.lower() and not text.startswith("[")):
                    print(f"[{i+1:2d}/{len(failed_keys)}] FAIL   {key}  — {text[:120]}")
                    results["still_failed"].append(key)
                else:
                    candles = json.loads(text)
                    if candles is None or len(candles) == 0:
                        print(f"[{i+1:2d}/{len(failed_keys)}] EMPTY  {key}  — 0 candles")
                        results["empty"].append(key)
                    else:
                        rows = save_csv(sym, fd, td, candles)
                        print(f"[{i+1:2d}/{len(failed_keys)}] OK     {key}  — {rows} rows → {sym}/{sym}_{fd}.csv")
                        results["ok"].append(key)

            except httpx.HTTPStatusError as exc:
                print(f"[{i+1:2d}/{len(failed_keys)}] FAIL   {key}  — HTTP {exc.response.status_code}: {exc.response.text[:100]}")
                results["still_failed"].append(key)
            except Exception as exc:
                print(f"[{i+1:2d}/{len(failed_keys)}] FAIL   {key}  — {type(exc).__name__}: {exc}")
                results["still_failed"].append(key)

            if i < len(failed_keys) - 1:
                await asyncio.sleep(DELAY)

    # Update progress file
    print(f"\n{'='*60}")
    print(f"OK: {len(results['ok'])}  EMPTY: {len(results['empty'])}  STILL_FAILED: {len(results['still_failed'])}")

    if results["ok"] or results["empty"]:
        # Rebuild failed list
        new_failed = results["still_failed"]
        progress["failed"] = new_failed
        for k in results["ok"]:
            if k not in progress["done"]:
                progress["done"].append(k)
        for k in results["empty"]:
            if k not in progress["empty"]:
                progress["empty"].append(k)
        PROGRESS_FILE.write_text(json.dumps(progress, indent=2))
        print(f"Progress file updated. Failed: {len(progress['failed'])}")

    if results["still_failed"]:
        print(f"\nStill failing ({len(results['still_failed'])}):")
        for k in results["still_failed"]:
            print(f"  {k}")


if __name__ == "__main__":
    asyncio.run(main())
