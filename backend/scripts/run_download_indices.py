"""Supervised 1-min index download via Kite MCP — async workers with auto session refresh.

Universe: NSE indices (NIFTY family) + BSE indices (SENSEX, BANKEX).

Usage:
    PYTHONPATH=. python scripts/run_download_indices.py
    PYTHONPATH=. python scripts/run_download_indices.py --resume
    PYTHONPATH=. python scripts/run_download_indices.py --consolidate
    PYTHONPATH=. python scripts/run_download_indices.py --from 2019-01-01 --to 2019-12-31
    PYTHONPATH=. python scripts/run_download_indices.py --workers 3
"""
import asyncio, csv, json, random, re, sys, time, argparse, signal, logging, webbrowser
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
import httpx
from tqdm import tqdm

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

LOG_DIR = Path(__file__).parent.parent.parent / "logs"


def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(exist_ok=True)
    log_file = LOG_DIR / "run_download_indices.log"
    fmt     = "%(asctime)s %(levelname)-5s %(message)s"
    datefmt = "%Y-%m-%d %H:%M:%S"
    logger  = logging.getLogger("download_indices")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    if not logger.handlers:
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(fmt, datefmt))
        sh = logging.StreamHandler(
            open(sys.stdout.fileno(), mode="w", buffering=1, closefd=False)
        )
        sh.setLevel(logging.INFO)
        sh.setFormatter(logging.Formatter(fmt, datefmt))
        logger.addHandler(fh)
        logger.addHandler(sh)
    return logger


MCP_URL       = "https://mcp.kite.trade/mcp"
SESSION_FILE  = Path(__file__).parent / ".kitemcp_session"
TOKEN_FILE    = Path(__file__).parent / ".kitemcp_index_tokens.json"
PROGRESS_FILE = Path(__file__).parent / ".download_index_progress.json"
RUNS_DIR      = Path(__file__).parent / ".runs"
RAWDATA_DIR   = Path(__file__).parent.parent.parent / "rawdata" / "1min_indices"

DEFAULT_CHUNK_DAYS  = 7
END_DATE            = date(2019, 1, 1)
EXHAUST_AFTER_EMPTY = 3
DELAY_MIN        = 1.0
DELAY_MAX        = 2.0
TOKEN_DELAY_MIN  = 1.2
TOKEN_DELAY_MAX  = 2.0
DEFAULT_WORKERS  = 3
CHECKPOINT_SECS  = 300

# Each entry: (tradingsymbol, exchange)
# Key used throughout: "EXCHANGE:tradingsymbol"  e.g. "NSE:NIFTY 50", "BSE:SENSEX"
INDEX_UNIVERSE: list[tuple[str, str]] = [
    # ── NSE broad market ──────────────────────────────────────────────────────
    ("NIFTY 50",              "NSE"),
    ("NIFTY NEXT 50",         "NSE"),
    ("NIFTY 100",             "NSE"),
    ("NIFTY 200",             "NSE"),
    ("NIFTY 500",             "NSE"),
    ("NIFTY TOTAL MKT",       "NSE"),  # NIFTY Total Market
    ("INDIA VIX",             "NSE"),
    # ── NSE midcap / smallcap / largecap ─────────────────────────────────────
    ("NIFTY MIDCAP 50",       "NSE"),
    ("NIFTY MIDCAP 100",      "NSE"),
    ("NIFTY MIDCAP 150",      "NSE"),
    ("NIFTY MID SELECT",      "NSE"),
    ("NIFTY SMLCAP 50",       "NSE"),
    ("NIFTY SMLCAP 100",      "NSE"),
    ("NIFTY SMLCAP 250",      "NSE"),
    ("NIFTY LARGEMID250",     "NSE"),
    ("NIFTY MICROCAP250",     "NSE"),
    ("NIFTY MIDSML 400",      "NSE"),
    # ── NSE sectoral ─────────────────────────────────────────────────────────
    ("NIFTY BANK",            "NSE"),
    ("NIFTY AUTO",            "NSE"),
    ("NIFTY FIN SERVICE",     "NSE"),
    ("NIFTY FMCG",            "NSE"),
    ("NIFTY IT",              "NSE"),
    ("NIFTY MEDIA",           "NSE"),
    ("NIFTY METAL",           "NSE"),
    ("NIFTY PHARMA",          "NSE"),
    ("NIFTY PSU BANK",        "NSE"),
    ("NIFTY PVT BANK",        "NSE"),  # NIFTY Private Bank
    ("NIFTY REALTY",          "NSE"),
    ("NIFTY ENERGY",          "NSE"),
    ("NIFTY INFRA",           "NSE"),
    ("NIFTY COMMODITIES",     "NSE"),
    ("NIFTY CONSUMPTION",     "NSE"),
    ("NIFTY CPSE",            "NSE"),
    ("NIFTY HEALTHCARE",      "NSE"),
    ("NIFTY OIL AND GAS",     "NSE"),
    ("NIFTY CONSR DURBL",     "NSE"),  # Consumer Durables
    ("NIFTY MNC",             "NSE"),
    ("NIFTY PSE",             "NSE"),
    ("NIFTY SERV SECTOR",     "NSE"),
    # ── NSE thematic ─────────────────────────────────────────────────────────
    ("NIFTY IND DEFENCE",     "NSE"),
    ("NIFTY IND DIGITAL",     "NSE"),
    ("NIFTY INDIA MFG",       "NSE"),
    ("NIFTY DIV OPPS 50",     "NSE"),
    ("NIFTY HOUSING",         "NSE"),
    ("NIFTY CAPITAL MKT",     "NSE"),
    ("NIFTY MOBILITY",        "NSE"),
    ("NIFTY IND TOURISM",     "NSE"),
    # ── BSE ──────────────────────────────────────────────────────────────────
    ("SENSEX",                "BSE"),
    ("BANKEX",                "BSE"),
    ("SENSEX NEXT 30",        "BSE"),
    ("BSE100",                "BSE"),
    ("BSE200",                "BSE"),
    ("BSE500",                "BSE"),
    ("BSE IT",                "BSE"),
    ("BSE HC",                "BSE"),  # BSE Healthcare
    ("BSE CD",                "BSE"),  # BSE Consumer Durables
    ("BSE CG",                "BSE"),  # BSE Capital Goods
    ("BSE PSU BANK",          "BSE"),
    ("BSE POWER & ENERGY",    "BSE"),
]

# Unique key: "EXCHANGE:tradingsymbol"
def sym_key(sym: str, exchange: str) -> str:
    return f"{exchange}:{sym}"


def safe_name(key: str) -> str:
    """Filesystem-safe: 'NSE:NIFTY 50' → 'NSE_NIFTY_50'"""
    return key.replace(":", "_").replace(" ", "_").replace("&", "AND")


# ── MCP helpers ───────────────────────────────────────────────────────────────
async def mcp_post(client: httpx.AsyncClient, session_id: str,
                   tool: str, args: dict) -> dict:
    resp = await client.post(MCP_URL, json={
        "jsonrpc": "2.0", "method": "tools/call",
        "params": {"name": tool, "arguments": args}, "id": 1,
    }, headers={"Content-Type": "application/json", "mcp-session-id": session_id})
    resp.raise_for_status()
    return resp.json()


def get_text(result: dict) -> str:
    return result.get("result", {}).get("content", [{}])[0].get("text", "")


# ── Session management ────────────────────────────────────────────────────────
async def init_session() -> str:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(MCP_URL, json={
            "jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {"protocolVersion": "2024-11-05",
                       "capabilities": {}, "clientInfo": {"name": "dl-idx", "version": "1"}},
        }, headers={"Content-Type": "application/json"})
        sid = r.headers.get("mcp-session-id", "")
        if not sid:
            raise RuntimeError("No session ID in initialize response")
        return sid


async def get_login_url(session_id: str) -> str:
    async with httpx.AsyncClient(timeout=30) as c:
        r = await mcp_post(c, session_id, "login", {})
        text = get_text(r)
        m = re.search(r"https://kite\.zerodha\.com/connect/login[^\s\)\]]+", text)
        return m.group(0) if m else text


async def verify_session(session_id: str) -> bool:
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await mcp_post(c, session_id, "get_profile", {})
            return "user_id" in get_text(r)
    except Exception:
        return False


async def refresh_session(session_state: dict):
    log = logging.getLogger("download_indices")
    log.info("\n" + "=" * 60)
    log.info("SESSION EXPIRED — starting re-auth flow")
    log.info("=" * 60)
    for attempt in range(3):
        try:
            new_sid = await init_session()
            login_url = await get_login_url(new_sid)
            log.warning(f"\n⚠️  Opening browser for re-auth:\n{login_url}\n")
            webbrowser.open(login_url)
            log.info("Polling every 10s until auth completes...")
            for _ in range(72):
                await asyncio.sleep(10)
                if await verify_session(new_sid):
                    session_state["id"] = new_sid
                    SESSION_FILE.write_text(new_sid)
                    log.info("✓ Session refreshed — resuming download\n")
                    return
            log.warning("Auth timeout — retrying init...")
        except Exception as e:
            log.error(f"Session refresh error: {e}")
    log.error("FATAL: Could not refresh session after 3 attempts. Exiting.")
    sys.exit(1)


# ── Token cache ───────────────────────────────────────────────────────────────
def load_tokens() -> dict:
    return json.loads(TOKEN_FILE.read_text()) if TOKEN_FILE.exists() else {}


def save_tokens(t: dict):
    TOKEN_FILE.write_text(json.dumps(t, indent=2))


def resolve_tokens(session_id: str, universe: list[tuple[str, str]], cache: dict) -> dict:
    """Resolve instrument tokens for index symbols. Cache key = 'EXCHANGE:sym'."""
    log = logging.getLogger("download_indices")
    missing = [(s, ex) for s, ex in universe if sym_key(s, ex) not in cache]
    if not missing:
        return cache
    print(f"Resolving {len(missing)} index tokens...")
    with httpx.Client(timeout=30) as client:
        for sym, exchange in tqdm(missing, desc="Tokens", unit="sym", dynamic_ncols=True):
            key = sym_key(sym, exchange)
            try:
                resp = client.post(MCP_URL, json={
                    "jsonrpc": "2.0", "method": "tools/call",
                    "params": {"name": "search_instruments",
                               "arguments": {"query": f"{exchange}:{sym}"}}, "id": 1,
                }, headers={"Content-Type": "application/json",
                            "mcp-session-id": session_id}, timeout=30)
                resp.raise_for_status()
                instruments = json.loads(get_text(resp.json()))
                for inst in instruments:
                    if (inst.get("tradingsymbol") == sym
                            and inst.get("exchange") == exchange
                            and inst.get("segment") == "INDICES"):
                        cache[key] = inst["instrument_token"]
                        break
                else:
                    log.warning(f"  WARN no INDEX token found for {key}")
            except Exception as e:
                log.warning(f"  WARN token {key}: {e}")
            time.sleep(random.uniform(TOKEN_DELAY_MIN, TOKEN_DELAY_MAX))
    save_tokens(cache)
    resolved = sum(1 for s, ex in universe if sym_key(s, ex) in cache)
    print(f"Tokens resolved: {resolved}/{len(universe)}")
    return cache


# ── Progress ──────────────────────────────────────────────────────────────────
def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text())
    return {"done": [], "failed": [], "empty": []}


def save_progress(p: dict):
    if PROGRESS_FILE.exists():
        existing = json.loads(PROGRESS_FILE.read_text())
        merged = {
            "done":   sorted(set(existing.get("done",   []) + p.get("done",   []))),
            "empty":  sorted(set(existing.get("empty",  []) + p.get("empty",  []))),
            "failed": sorted(set(
                [k for k in existing.get("failed", []) if k not in p.get("done", []) and k not in p.get("empty", [])]
                + p.get("failed", [])
            )),
        }
        PROGRESS_FILE.write_text(json.dumps(merged, indent=2))
    else:
        PROGRESS_FILE.write_text(json.dumps(p, indent=2))


def save_run(run_id: str, meta: dict, progress: dict):
    RUNS_DIR.mkdir(exist_ok=True)
    run_file = RUNS_DIR / f"{run_id}.json"
    data = {
        **meta,
        "done":   sorted(set(progress.get("done",   []))),
        "empty":  sorted(set(progress.get("empty",  []))),
        "failed": sorted(set(progress.get("failed", []))),
    }
    run_file.write_text(json.dumps(data, indent=2))


def load_run(run_id: str) -> dict:
    run_file = RUNS_DIR / f"{run_id}.json"
    if not run_file.exists():
        raise FileNotFoundError(f"Run file not found: {run_file}")
    return json.loads(run_file.read_text())


# ── CSV ───────────────────────────────────────────────────────────────────────
def save_csv(key: str, from_date: str, candles: list) -> int:
    """key = 'EXCHANGE:tradingsymbol', e.g. 'NSE:NIFTY 50'"""
    if not candles:
        return 0
    fname = safe_name(key)
    out = RAWDATA_DIR / fname / f"{fname}_{from_date}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ts","open","high","low","close","volume"])
        w.writeheader()
        for c in candles:
            w.writerow({"ts": c.get("date",""), "open": c["open"],
                        "high": c["high"], "low": c["low"],
                        "close": c["close"], "volume": c.get("volume", 0)})
    return len(candles)


# ── Chunks ────────────────────────────────────────────────────────────────────
def build_chunks(
    from_date:  date | None = None,
    to_date:    date | None = None,
    chunk_days: int         = DEFAULT_CHUNK_DAYS,
) -> list[tuple[str, str]]:
    today   = date.today()
    to_date = min(to_date or today, today)

    if from_date is not None:
        chunks, d = [], from_date
        while d <= to_date:
            end = min(d + timedelta(days=chunk_days - 1), to_date)
            chunks.append((d.isoformat(), end.isoformat()))
            d = end + timedelta(days=1)
        return list(reversed(chunks))
    else:
        start_date = END_DATE
        ANCHOR = date(2099, 12, 31)
        chunks, d = [], ANCHOR
        while d > start_date:
            start = max(d - timedelta(days=chunk_days - 1), start_date)
            if start <= today:
                chunks.append((start.isoformat(), min(d, today).isoformat()))
            d = start - timedelta(days=1)
        return chunks


# ── Async worker ──────────────────────────────────────────────────────────────
AUTH_FAIL_PHRASES = ("Failed to get historical data", "Invalid session", "Unauthorized", "not logged in")
AUTH_FAIL_COUNTER: dict = {"n": 0}
AUTH_FAIL_THRESHOLD = 5


async def worker(
    worker_id: int,
    queue: asyncio.Queue,
    session_state: dict,
    tokens: dict,
    progress: dict,
    progress_lock: asyncio.Lock,
    refresh_lock: asyncio.Lock,
    refreshing: asyncio.Event,
    bar: tqdm,
    counters: dict,
    interrupted_flag: list,
    sym_state: dict,
):
    log = logging.getLogger("download_indices")
    loop = asyncio.get_event_loop()
    async with httpx.AsyncClient(timeout=30) as client:
        last_call = 0.0
        while True:
            try:
                key, fd, td = queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            if interrupted_flag[0]:
                queue.task_done()
                break

            progress_key = f"{key}:{fd}"

            if key in sym_state["exhausted"]:
                async with progress_lock:
                    progress["empty"].append(progress_key)
                counters["ops"] += 1
                bar.update(1)
                bar.set_postfix_str(
                    f"rows={counters['rows']:,}  skip={counters.get('skipped',0):,}  "
                    f"fail={len(progress['failed'])}"
                )
                counters["skipped"] = counters.get("skipped", 0) + 1
                queue.task_done()
                continue

            if refreshing.is_set():
                await asyncio.sleep(1)
                while refreshing.is_set():
                    await asyncio.sleep(2)

            elapsed = loop.time() - last_call
            wait = random.uniform(DELAY_MIN, DELAY_MAX) - elapsed
            if wait > 0:
                await asyncio.sleep(wait)
            last_call = loop.time()

            try:
                r = await mcp_post(client, session_state["id"],
                                   "get_historical_data", {
                    "instrument_token": tokens[key],
                    "interval": "minute",
                    "from_date": f"{fd} 09:00:00",
                    "to_date":   f"{td} 15:30:00",
                })
                text = get_text(r)
                if any(p in text for p in AUTH_FAIL_PHRASES):
                    AUTH_FAIL_COUNTER["n"] += 1
                    if AUTH_FAIL_COUNTER["n"] >= AUTH_FAIL_THRESHOLD:
                        AUTH_FAIL_COUNTER["n"] = 0
                        log.warning(f"  Auth failure detected ({AUTH_FAIL_THRESHOLD}+ consecutive) — triggering re-auth")
                        async with refresh_lock:
                            if not refreshing.is_set():
                                refreshing.set()
                                await refresh_session(session_state)
                                refreshing.clear()
                    queue.put_nowait((key, fd, td))
                    queue.task_done()
                    continue
                elif "Error" in text or "error" in text:
                    raise RuntimeError(text[:120])

                AUTH_FAIL_COUNTER["n"] = 0
                candles = json.loads(text)
                rows = save_csv(key, fd, candles)
                counters["rows"] += rows

                async with progress_lock:
                    if not candles:
                        progress["empty"].append(progress_key)
                        sym_state["streak"][key] = sym_state["streak"].get(key, 0) + 1
                        if sym_state["streak"][key] >= EXHAUST_AFTER_EMPTY:
                            sym_state["exhausted"].add(key)
                            log.info(
                                f"  EXHAUST {key} — {sym_state['streak'][key]} consecutive "
                                f"empties, skipping older chunks"
                            )
                        else:
                            log.info(f"  EMPTY  {key} {fd}→{td}  "
                                     f"(streak={sym_state['streak'][key]})")
                    else:
                        progress["done"].append(progress_key)
                        sym_state["streak"][key] = 0
                        log.info(f"  OK     {key} {fd}→{td}  rows={rows}")

            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 400:
                    log.warning(f"  400 on {key} {fd} — checking session...")
                    async with refresh_lock:
                        if not refreshing.is_set():
                            refreshing.set()
                            await refresh_session(session_state)
                            refreshing.clear()
                    queue.put_nowait((key, fd, td))
                    queue.task_done()
                    continue
                else:
                    log.error(f"  FAIL   {key} {fd}→{td}  HTTP {exc.response.status_code}")
                    async with progress_lock:
                        progress["failed"].append(progress_key)

            except Exception as exc:
                log.error(f"  FAIL   {key} {fd}→{td}  {str(exc)[:80]}")
                async with progress_lock:
                    progress["failed"].append(progress_key)

            finally:
                counters["ops"] += 1
                bar.update(1)
                bar.set_postfix_str(
                    f"rows={counters['rows']:,}  fail={len(progress['failed'])}"
                )
                queue.task_done()


# ── Time-based checkpoint coroutine ───────────────────────────────────────────
async def checkpoint_loop(progress: dict, counters: dict,
                          interrupted_flag: list, done_event: asyncio.Event):
    log = logging.getLogger("download_indices")
    while not interrupted_flag[0]:
        try:
            await asyncio.wait_for(done_event.wait(), timeout=CHECKPOINT_SECS)
            break
        except asyncio.TimeoutError:
            pass
        if interrupted_flag[0]:
            break
        save_progress(progress)
        log.info(
            f"--- checkpoint @ {time.strftime('%H:%M:%S')} | "
            f"ops={counters['ops']:,} rows={counters['rows']:,} | "
            f"done={len(progress['done'])} "
            f"empty={len(progress['empty'])} "
            f"failed={len(progress['failed'])} ---"
        )


# ── Main ──────────────────────────────────────────────────────────────────────
async def run_async(
    resume:         bool,
    num_workers:    int,
    from_date:      date | None = None,
    to_date:        date | None = None,
    chunk_days:     int         = DEFAULT_CHUNK_DAYS,
    force:          bool        = False,
    run_id_resume:  str | None  = None,
):
    from datetime import datetime as _dt
    log = logging.getLogger("download_indices")
    session_id = SESSION_FILE.read_text().strip() if SESSION_FILE.exists() else ""
    if not session_id:
        print("ERROR: No session. Re-run auth first.")
        sys.exit(1)

    targeted = from_date is not None or to_date is not None

    if run_id_resume:
        run_id = run_id_resume
        prev_run = load_run(run_id)
        log.info(f"Resuming run {run_id} (was {prev_run.get('started_at', '?')})")
    else:
        run_id = _dt.now().strftime("%Y%m%d_%H%M%S") + ("_idx_targeted" if targeted else "_idx_backfill")

    run_meta = {
        "run_id":      run_id,
        "started_at":  _dt.now().isoformat(timespec="seconds"),
        "mode":        "targeted" if targeted else "backfill",
        "from_date":   from_date.isoformat() if from_date else None,
        "to_date":     to_date.isoformat()   if to_date   else None,
        "chunk_days":  chunk_days,
        "workers":     num_workers,
        "universe":    "indices",
    }

    tokens = resolve_tokens(session_id, INDEX_UNIVERSE, load_tokens())
    # Only include symbols that resolved a token
    keys   = [sym_key(s, ex) for s, ex in INDEX_UNIVERSE if sym_key(s, ex) in tokens]
    chunks = build_chunks(from_date, to_date, chunk_days)

    use_done_set = (not force) if targeted else resume
    if run_id_resume:
        prev_run = load_run(run_id)
        progress = {
            "done":   list(prev_run.get("done",   [])),
            "empty":  list(prev_run.get("empty",  [])),
            "failed": list(prev_run.get("failed", [])),
        }
        done_set = set(progress["done"]) | set(progress["empty"])
    elif use_done_set:
        progress = load_progress()
        done_set = set(progress["done"]) | set(progress["empty"])
    else:
        progress = {"done": [], "failed": [], "empty": []}
        done_set = set()

    def csv_exists(key: str, fd: str) -> bool:
        fname = safe_name(key)
        p = RAWDATA_DIR / fname / f"{fname}_{fd}.csv"
        return p.exists() and p.stat().st_size > 50

    work = []
    file_skipped = 0
    for key in keys:
        for fd, td in chunks:
            progress_key = f"{key}:{fd}"
            if progress_key in done_set or (not force and csv_exists(key, fd)):
                file_skipped += 1
            else:
                work.append((key, fd, td))

    total    = len(work)
    avg_dly  = (DELAY_MIN + DELAY_MAX) / 2
    eff_rps  = num_workers / avg_dly
    mode_str = (
        f"targeted  {from_date or END_DATE} → {to_date or date.today()}  "
        f"chunk={chunk_days}d  use_done_set={use_done_set}"
        if targeted else
        f"full backfill  chunk={chunk_days}d  resume={resume}"
    )
    print(f"\n{'='*60}")
    print(f"Run ID:  {run_id}")
    print(f"Mode:    {mode_str}")
    print(f"Indices: {len(INDEX_UNIVERSE)} configured | Tokens: {len(keys)} resolved | Chunks/sym: {len(chunks)}")
    print(f"Workers: {num_workers} | Delay/worker: {avg_dly:.1f}s | Rate: {eff_rps:.2f} req/s")
    print(f"Skipped (file exists): {file_skipped:,} | To fetch: {total:,} | ETA: ~{total / eff_rps / 3600:.1f}h")
    print(f"Checkpoint: every {CHECKPOINT_SECS//60} min")
    print(f"{'='*60}\n")
    log.info("run_id=%s  total_chunks=%d  skipped_by_file=%d  workers=%d",
             run_id, total, file_skipped, num_workers)

    interrupted_flag = [False]
    def _handle_signal(sig, frame):
        interrupted_flag[0] = True
        log.warning("\nInterrupted — saving progress, run --resume to continue")
    signal.signal(signal.SIGINT,  _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    session_state = {"id": session_id}
    queue         = asyncio.Queue()
    for item in work:
        queue.put_nowait(item)

    progress_lock = asyncio.Lock()
    refresh_lock  = asyncio.Lock()
    refreshing    = asyncio.Event()
    done_event    = asyncio.Event()
    counters      = {"rows": 0, "ops": 0, "skipped": 0}
    sym_state     = {"exhausted": set(), "streak": {}}

    bar = tqdm(
        total=total, desc="Downloading", unit="chunk", dynamic_ncols=True,
        bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}<{remaining}, {rate_fmt}]",
    )

    worker_tasks = [
        asyncio.create_task(worker(
            i, queue, session_state, tokens, progress,
            progress_lock, refresh_lock, refreshing,
            bar, counters, interrupted_flag, sym_state,
        ))
        for i in range(num_workers)
    ]
    cp_task = asyncio.create_task(
        checkpoint_loop(progress, counters, interrupted_flag, done_event)
    )

    try:
        await asyncio.gather(*worker_tasks)
        done_event.set()
        await cp_task
    finally:
        bar.close()
        save_progress(progress)
        save_run(run_id, run_meta, progress)
        log.info("run_id=%s  progress saved  done=%d empty=%d failed=%d",
                 run_id, len(progress["done"]), len(progress["empty"]), len(progress["failed"]))

    # ── Retry failed once ────────────────────────────────────────────────────
    failed_keys = list(progress["failed"])
    if failed_keys and not interrupted_flag[0]:
        print(f"\nRetrying {len(failed_keys)} failed chunks...")
        chunk_map = {f"{key}:{fd}": (key, fd, td) for key, fd, td in work}
        retry_items = [chunk_map[k] for k in failed_keys if k in chunk_map]
        progress["failed"] = []

        retry_q = asyncio.Queue()
        for item in retry_items:
            retry_q.put_nowait(item)

        retry_bar = tqdm(total=len(retry_items), desc="Retry",
                         unit="chunk", dynamic_ncols=True)
        retry_sym_state = {"exhausted": set(), "streak": {}}
        retry_tasks = [
            asyncio.create_task(worker(
                i, retry_q, session_state, tokens, progress,
                progress_lock, refresh_lock, refreshing,
                retry_bar, counters, interrupted_flag, retry_sym_state,
            ))
            for i in range(min(num_workers, 2))
        ]
        try:
            await asyncio.gather(*retry_tasks)
        finally:
            retry_bar.close()
            save_progress(progress)
            save_run(run_id, run_meta, progress)

    print(f"\n{'='*60}")
    print(f"COMPLETE: {len(progress['done'])} done | "
          f"{len(progress['failed'])} failed | "
          f"{len(progress['empty'])} empty | "
          f"{counters.get('skipped', 0):,} auto-skipped | "
          f"{counters['rows']:,} rows total")
    if sym_state["exhausted"]:
        print(f"Exhausted indices ({len(sym_state['exhausted'])}): "
              f"{', '.join(sorted(sym_state['exhausted']))}")
    print(f"{'='*60}")

    if not interrupted_flag[0]:
        consolidate()

    print(f"\nData in: {RAWDATA_DIR}")


def run(resume: bool, num_workers: int,
        from_date: date | None = None, to_date: date | None = None,
        chunk_days: int = DEFAULT_CHUNK_DAYS, force: bool = False,
        run_id_resume: str | None = None):
    asyncio.run(run_async(resume, num_workers, from_date, to_date, chunk_days, force, run_id_resume))


# ── Consolidate weekly → monthly ──────────────────────────────────────────────
def consolidate():
    if not RAWDATA_DIR.exists():
        print("No data to consolidate yet.")
        return
    syms = [d.name for d in RAWDATA_DIR.iterdir() if d.is_dir()]
    if not syms:
        print("No data to consolidate yet.")
        return
    print(f"\nConsolidating {len(syms)} indices into monthly files...")
    total_written = 0
    for fname in tqdm(syms, desc="Consolidating", unit="idx", dynamic_ncols=True):
        sym_dir = RAWDATA_DIR / fname
        monthly: dict[str, list[dict]] = defaultdict(list)
        for wf in sorted(sym_dir.glob(f"{fname}_????-??-??.csv")):
            with open(wf, newline="") as f:
                for row in csv.DictReader(f):
                    ts = row.get("ts", "")
                    monthly[ts[:7] if ts else "unknown"].append(row)
        if not monthly:
            continue
        for month_key, rows in sorted(monthly.items()):
            if month_key == "unknown":
                continue
            rows.sort(key=lambda r: r.get("ts", ""))
            out = sym_dir / f"{fname}_{month_key}.csv"
            with open(out, "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=["ts","open","high","low","close","volume"])
                w.writeheader()
                w.writerows(rows)
            total_written += len(rows)
        for wf in sorted(sym_dir.glob(f"{fname}_????-??-??.csv")):
            wf.unlink()
    print(f"Consolidation complete — {total_written:,} rows in monthly files")


def _parse_date(s: str) -> date:
    if s.lower() == "today":
        return date.today()
    return date.fromisoformat(s)


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="Download 1-min OHLCV bars for NSE/BSE indices from Kite MCP.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Indices covered:
  NSE: NIFTY 50, NIFTY BANK, NIFTY IT, NIFTY AUTO, NIFTY FMCG, NIFTY PHARMA,
       NIFTY METAL, NIFTY REALTY, NIFTY ENERGY, NIFTY INFRA, NIFTY PSU BANK,
       NIFTY PRIVATE BANK, NIFTY FIN SERVICE, NIFTY MEDIA, NIFTY COMMODITIES,
       NIFTY CONSUMPTION, NIFTY CPSE, NIFTY HEALTHCARE INDEX, NIFTY OIL AND GAS,
       NIFTY NEXT 50, NIFTY 100/200/500, NIFTY TOTAL MARKET, INDIA VIX,
       NIFTY MIDCAP 50/100/150, NIFTY MID SELECT, NIFTY SMALLCAP 50/100/250,
       NIFTY LARGEMIDCAP 250, NIFTY MICROCAP 250,
       NIFTY INDIA DEFENCE/DIGITAL/MANUFACTURING
  BSE: SENSEX, BANKEX, SENSEX 50, BSE100/200/500, BSEMIDCAP, BSESMALLCAP,
       BSE AUTO/FMCG/HEALTHCARE/IT/METAL/OIL&GAS/REALTY/TECK/POWER/CAPITAL GOODS/CONSUMER DURABLES

Examples:
  # Full backfill from 2019-01-01 to today
  python run_download_indices.py --resume

  # 2019 calendar year only
  python run_download_indices.py --from 2019-01-01 --to 2019-12-31

  # Today only
  python run_download_indices.py --date today

  # Date range
  python run_download_indices.py --from 2024-01-01 --to 2024-03-31

  # Re-fetch a range even if already done
  python run_download_indices.py --from 2024-03-01 --to 2024-03-31 --force
""",
    )
    p.add_argument("--resume",      action="store_true",
                   help="Full-backfill only: skip chunks already in done/empty list")
    p.add_argument("--force",       action="store_true",
                   help="Targeted runs only: re-fetch even already-done chunks")
    p.add_argument("--consolidate", action="store_true",
                   help="Consolidate weekly CSV files into monthly files and exit")
    p.add_argument("--workers",     type=int, default=DEFAULT_WORKERS,
                   help=f"Parallel workers (default {DEFAULT_WORKERS})")
    p.add_argument("--date",        type=_parse_date, metavar="YYYY-MM-DD|today",
                   help="Fetch a single date for all indices")
    p.add_argument("--from",        type=_parse_date, metavar="YYYY-MM-DD|today",
                   dest="from_date",
                   help="Start of date range (inclusive)")
    p.add_argument("--to",          type=_parse_date, metavar="YYYY-MM-DD|today",
                   dest="to_date",
                   help="End of date range (inclusive, default today)")
    p.add_argument("--chunk-days",  type=int, default=DEFAULT_CHUNK_DAYS,
                   dest="chunk_days",
                   help=f"Days per API call (default {DEFAULT_CHUNK_DAYS})")
    p.add_argument("--run-id",      type=str, default=None,
                   dest="run_id",
                   help="Resume a specific previous run by its ID")
    args = p.parse_args()

    if args.consolidate:
        consolidate()
        sys.exit(0)

    from_date  = args.date or args.from_date
    to_date    = args.date or args.to_date
    chunk_days = 1 if args.date else args.chunk_days

    setup_logging()
    run(args.resume, args.workers, from_date, to_date, chunk_days, args.force, args.run_id)
