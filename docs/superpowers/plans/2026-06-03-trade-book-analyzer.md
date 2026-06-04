# Trade Book Analyzer — Revised Implementation Plan
**Date:** 2026-06-04 (revised post contract note analysis: mStock + Lemonn + Zerodha)
**Phase:** 1 — Data Ingestion (analysis layer deferred)

---

## ⚠️ PLAN REVIEW — Gaps Found & Required Fixes (reviewed 2026-06-04)

> **Executor (general-purpose model): READ THIS FIRST.** The task code blocks below
> were written incrementally and contain contradictions + factual errors. Apply every
> fix in this section. Where a fix conflicts with a later code block, **this section wins.**

### G1 — PDF extraction contradiction (BLOCKER)
Task 6 broker parsers (`mstock.py`, `zerodha.py`, `lemonn.py`) are written for **markitdown
markdown + regex**, signature `parse(md, source_file)`. But the later section "PDF parsing:
pdfplumber (not markitdown)" mandates **pdfplumber table rows**, signature
`parse(rows, text=, source_file=)`. The parsers were never rewritten — signatures don't match.

**Decision: pdfplumber wins.** Required:
- All broker parsers take `parse(rows: list[list[str]], text: str, source_file: str)`.
- Iterate table rows by **column index**, not regex, for fill extraction. Keep regex only as a
  fallback against `text` for header metadata (trade date, contract note no) and when
  `extract_tables()` returns nothing.
- Delete `_to_markdown` / markitdown usage. `_to_markdown` also has a bug (annotated
  `-> tuple[str,str]` but returns a single value) — moot once removed.
- Dependencies (line ~1387): change `pip install markitdown anthropic` →
  `pip install pdfplumber` (drop `anthropic` — no LLM in Phase 1).
- pdfplumber may fail on scanned/image PDFs. Add a guard: if `extract_tables()` and
  `extract_text()` both empty → raise a clear `ValueError("Unparseable PDF — no text layer")`
  so the API returns a 422, not a silent empty import.

### G2 — Charge rates are WRONG (accuracy BLOCKER) — verified against live 2026 rates
All three contract notes are **index OPTIONS**, dated May/June 2026 (post 1-Apr-2026). Fix `config.py`:

- **STT**: plan's `FO_SELL = 0.000625` is wrong for options. Options STT is on the **sell premium**:
  `0.0015` (0.15%, effective 1-Apr-2026; was 0.001 before). Futures sell STT = `0.0005`.
  Split into `FO_OPT_SELL = Decimal("0.0015")` and `FO_FUT_SELL = Decimal("0.0005")`.
- **Exchange transaction charge**: plan's `NSE_FO=0.000053` / `BSE_FO=0.000047` are **futures**
  rates — options are ~7× higher and charged on premium:
  `NSE_OPT = Decimal("0.0003503")` (₹3503/cr), `BSE_OPT = Decimal("0.000325")`
  (₹3250/cr, SENSEX/BANKEX). Keep the futures keys for later but **select by option vs future**,
  not just segment.
- `SEBI_FEE = 0.000001` ✓ correct. `STAMP_DUTY["FO"]=0.00003` ✓ for options (0.003%);
  add `FO_FUT = 0.00002` if futures are ever supported. Stamp on **buy side only** ✓.
- GST 0.18 on `(brokerage + exchange_txn + sebi_fee)` ✓.

`compute_pair_charges` must therefore take **option_type / instrument** (not just `segment`) so it
can pick OPT vs FUT rates. Validate the output: total charges for a sample pair must reconcile
against the actual "Net Total" / charge breakdown printed on the real contract note (use the 3
PDFs as golden fixtures — see G8).
Sources: [STT 2026](https://cleartax.in/s/securities-transaction-tax-stt) ·
[NSE/BSE txn charges](https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/exchange-transaction-charges) ·
[Zerodha charges](https://zerodha.com/charges/)

### G3 — Cross-broker FIFO mismatch (correctness BLOCKER)
`match_all_symbols` groups by `t.symbol` **only**. If the same symbol trades on two brokers the
same day, a BUY on Zerodha can be matched against a SELL on mStock → fabricated pairs and P&L.
**Fix:** group by `(broker, symbol)` (and segment/exchange for safety). Because pairs are now
per-broker, `_recompute_day` must either compute a `jrn_day_summary` row **per (broker, date)**,
or aggregate brokers only after matching within each broker. Pick per-(broker,date) summary +
an optional rolled-up `broker=NULL` row; the `UNIQUE(trade_date, COALESCE(broker,''))` constraint
already supports both.

### G4 — Compact symbol decoding is fragile / broken
In `_compact`, the 6-digit `YYMMDD` weekly regex is tried **before** the single-char-month weekly
regex. BSE/SENSEX weekly symbols use a single-char month, so `SENSEX2660473600CE` hits the
`YYMMDD` branch with month=`60` → fails → whole parse falls through. Strike/expiry then wrong or null.

**CORRECTED by real-PDF analysis (see G9):** Zerodha and mStock compact symbols have **NO
separate expiry-date column** — the raw string is e.g. `NIFTY2660923200PE - NSE` (exchange is a
suffix). Only Lemonn carries a verbose, already-decoded form (`OPTIDX SENSEX 14May2026 74200 PE-BSE`).

**Fix — decode the compact form directly as `[UND][yy][M][dd][strike][CE|PE]`** where `M` is a
single-char weekly month code (`1`-`9`, `O`=10, `N`=11, `D`=12) and `dd` is the 2-digit day:
- `NIFTY2660923200PE` → UND=NIFTY, yy=26, M=6, dd=09, strike=23200, PE. Expiry = 2026-06-09.
- `SENSEX2660473600CE` → UND=SENSEX, yy=26, M=6, dd=04, strike=73600, CE. Expiry = 2026-06-04.
- **Try the single-char-month weekly branch BEFORE the 6-digit `YYMMDD` branch** (the 6-digit
  branch parses month=`60` from `2660...` and would mis-handle it). The date prefix is always
  5 chars (yy+M+dd); the remainder before `CE/PE` is the strike.
- Add unit tests asserting these exact raw strings from the real PDFs.
- Do **not** compute expiry from "last Thursday" for weeklies — `dd` is explicit in the symbol.
  (BSE weekly expiry day also moved to Tuesday in 2024-25; irrelevant now that we read `dd` directly.)

### G5 — `db.py` is named but never specified
Task 1 lists `db.py` with `init_journal_tables()` and `seed_default_rules()` but gives no body.
Specify: `init_journal_tables(pool)` reads `schema.sql` (incl. the "Schema corrections" ALTERs and
the partial-unique-index migration) and executes it idempotently inside a transaction.
`seed_default_rules(pool)` inserts default `jrn_rules` rows with `ON CONFLICT (name) DO NOTHING`
(Phase 1 may seed an empty/disabled set — list the rule names or leave a documented no-op).

### G6 — `fiscal_year` and `product_type` columns are never populated
The "Schema corrections" add `jrn_day_summary.fiscal_year`, `jrn_trades.product_type`,
`jrn_trade_pairs.product_type` — but `aggregator.py` and `matcher.py` never set them.
- Add FY helper: Indian FY is Apr–Mar → `fy = f"{y}-{str(y+1)[2:]}"` if `month>=4` else
  `f"{y-1}-{str(y)[2:]}"`. Set it in `build_day_summary`.
- `product_type` (MIS/NRML/CNC) comes from the **API** parsers (Kite/Upstox); **null** for PDF.
  The matched pair inherits the entry trade's `product_type`.
  `is_intraday = (product_type == 'MIS') or (open_date == close_date)`.
- `_upsert_trades` / pair INSERT must include these columns (they're currently omitted from the
  INSERT column lists in Task 8 — add them).

### G7 — Smaller correctness / consistency fixes
- `detect_broker` has a dead branch: `"Zerodha"` is checked twice, so the `kite` branch is
  unreachable. Kite **contract notes are Zerodha-format** — just map kite→`zerodha.parse` and
  drop the dead `kite` detection (the `kite` source only matters for the API parser).
- `list_trades` query builder (Task 8) is a fragile string-split hack. Replace with explicit
  per-filter `conds.append(...)` lines mirroring `list_pairs`.
- `get_pool()` does `from main import app` — **confirm this matches how existing routers in
  `backend/api/routers/` acquire the pool** before copying; use the established dependency instead
  of inventing one.
- Zerodha force-square detection (`'"\n' in m.group(0)`) is a regex artifact. With pdfplumber,
  read the **Remarks column** directly and pass it to `is_force_squared`.
- Frontend: `TimelineBuckets.tsx` is used in Task 9 but missing from the File-structure list
  (~line 99) — add it under `components/Journal/`.
- `models.py` uses one-line multi-statement `;` fields — fine, but the executor must not
  "reformat" them into invalid dataclass syntax; keep field defaults ordered (no non-default
  after default).

### G8 — No test strategy (add before implementing)
The 3 real PDFs are the spec. Required tests (pytest):
- `symbol_parser`: assert exact `ParsedSymbol` for the raw mStock/Lemonn/Zerodha/Kite strings.
- `charges`: assert `compute_pair_charges` total reconciles (±₹0.01) with the printed charge
  total on each contract note.
- `matcher`: FIFO across partial fills (Zerodha one order → many trades), open positions,
  and **no cross-broker matching** (G3).
- `aggregator`: counts, `time_bucket_pnl`, `avg_hold_seconds`, `fiscal_year`.
Locate the sample PDFs (ask the user for paths if not in repo) and commit redacted fixtures.

### G9 — REAL PDF ANALYSIS (3 notes extracted with pdfplumber 0.11.9, 2026-06-04)
The 3 readable sample notes (Zerodha NSE+BSE, mStock BSE, Lemonn BSE) were extracted. Findings
**override** the per-trade/timestamped assumptions baked into Tasks 1, 6, 8.

**9a — All three brokers emit the REVISED WAP-consolidated layout, not per-trade rows.**
Columns are identical across brokers:
`Contract Description | B/S | Quantity | WAP Per Unit | Brokerage Per Unit | WAP after brokerage |
Closing Rate | Net Total (Before Levies) | Remarks`.
There is **ONE buy row + ONE sell row per symbol** (already volume-weighted). Consequences:
- **No `Order No`, `Order Time`, `Trade No`, `Trade Time` columns exist in any PDF.**
  → `trade_id`, `order_no`, `order_time` are **NULL for all PDF imports**.
  → **`hold_seconds` is UNCOMPUTABLE from PDFs** (no timestamps). The plan's headline premise
    ("hold_seconds is THE metric") only holds for the **API path** (Kite/Upstox/mStock-today carry
    `fill_timestamp`). For PDF pairs set `hold_seconds = NULL`, `trade_time = NULL`, and treat
    `is_intraday = (settlement same day)` — true for all observed notes. Update Task 1 comments and
    `jrn_day_summary.avg_hold_seconds` / `first_trade_time` / `last_trade_time` to tolerate NULLs
    (they will be NULL for PDF-only days). Frontend must not show "avg hold" for PDF days.

**9b — Dedup key is wrong.** `UNIQUE(broker, trade_id)` cannot work — PDFs have no trade_id.
Re-importing a REVISED note would duplicate every row. **Use a content key for PDF rows:**
`UNIQUE(broker, contract_note_no, raw_symbol, trade_type, quantity)` (partial index
`WHERE source='pdf'`), and keep the `(broker, trade_id) WHERE trade_id IS NOT NULL` partial index
for API rows. On re-import of a same contract_note_no, prefer DELETE-by-note then re-insert so a
REVISED note supersedes the prior one cleanly.

**9c — Parser rewrites required (the Task-6 regex parsers do NOT match these PDFs):**
- **zerodha.py**: symbol `NIFTY2660923200PE - NSE` (compact + ` - <EXCH>` suffix). Parse the WAP
  table: price = `WAP Per Unit`, brokerage = `Brokerage Per Unit × Quantity`, side from `B/S`,
  exchange from suffix. No times. Remarks column read directly for force-square.
- **lemonn.py**: symbol `OPTIDX SENSEX 14May2026 74200 PE-BSE` (verbose — matches existing regex).
  **SELL quantity is printed NEGATIVE** (`-80`) → take `abs(qty)` and derive side from `B/S`.
- **mstock.py**: pdfplumber **merges the entire fill column into a single multi-line cell** — all
  `BSXOPT SENSEX...CE (BT)` descriptions, all `B S B S...`, all qtys, all prices arrive as one
  cell each, `\n`/space-separated. Parser must **split each column cell on whitespace and zip the
  columns positionally**, not iterate table rows. Brokerage column = `0.25/unit` ✓.
- All three: `WAP Per Unit (Rs)` is the gross price to store; ignore `WAP after brokerage`.

**9d — Charge rates VALIDATED to the rupee (confirms G2 fixes; original plan rates were wrong):**
| Charge | Zerodha (NSE+BSE) actual | mStock (BSE) actual | Predicted with G2 rates |
|--------|---|---|---|
| STT (opt sell 0.0015) | 320.00 | 782.00 | 320.01 / 781.7 ✓ |
| Exch txn (NSE 0.0003503 / BSE 0.000325) | 151.40 | 341.24 | 149.6 / 341.23 ✓ |
| Stamp (buy, FO 0.00003) | 7.00 | 16.00 | 6.6 / 15.9 ✓ |
| SEBI (0.000001) | ~0.43 | 1.05 | ✓ |
| GST/IGST (0.18 × (brok+exch+sebi)) | 120.93 | 180.41 | exact ✓ |
Note: GST is **IGST 18%** when client state ≠ broker state (all 3 clients UP, brokers in
Karnataka/Maharashtra). Charges.py already lumps GST — fine. Keep brokerage **from the PDF column**
(per-unit, varies: Zerodha ₹0.3077/u, mStock ₹0.25/u), do NOT apply the flat-₹20 config model to
PDF imports — `BROKERAGE_MODELS` flat-20 is for the API path only.

**9e — Encrypted PDFs.** Broker-emailed notes are password-protected with the client **PAN**
(verified: one sample opened with PAN). Add decrypt support in `pdf.py`: accept an optional
`password` param, try it via `pypdf`/pdfplumber; if a PDF `is_encrypted` and no/blank password
works, return 422 asking the user for the password. Add `pip install pypdf`. (The single
password-protected sample is set aside per the user; still implement decrypt for production.)

**9f — Net verdict.** Schema shape, FIFO matcher, charges (post-G2), and aggregator are sound. The
**parsers and the timestamp/hold_seconds/dedup assumptions are not** — they must be rebuilt around
the WAP-consolidated, timeless, trade_id-less reality of these PDFs. Do 9a–9e before coding Task 6.

---

## Context: What the contract notes revealed

Three real PDFs analyzed. All are intraday scalping in SENSEX/NIFTY options.
Hold time = seconds to minutes. `holding_days` is useless. `hold_seconds` is the metric.

| Broker | Format | Exchange | Force-square signal | Brokerage | Lot size seen |
|--------|--------|----------|--------------------|-----------|----|
| mStock | `BSXOPT SENSEX2660473600CE 1127872 (BT)` | BSE | None | ₹0.25/unit | 20 |
| Lemonn | `OPTIDX SENSEX 14May2026 74200 PE-BSE` | NSE routing BSE | Text remark | ₹20 flat | 20 |
| Zerodha | `NIFTY2660923200PE / 09 June 2026` + Exchange column | NSE+BSE | `"` in Remarks | ₹20 flat | 65 (NIFTY), 20 (SENSEX) |

Additional findings:
- mStock shows failed/rejected orders as ₹5 rows — behavioral signal
- Zerodha has partial fills: one Order No. → multiple Trade Nos.
- All PDFs are REVISED/SUPPLEMENTARY — dedup logic must handle re-imports
- Future analysis needs: chart at entry/exit, trade rationale, what went wrong

---

## What this system must do (Phase 1)

1. Ingest PDF contract notes (auto-detect broker, parse annexure)
2. Ingest via API (Kite, Upstox)
3. Normalize all formats → canonical `jrn_trades` rows
4. Derive FIFO pairs → `jrn_trade_pairs`
5. Aggregate per day → `jrn_day_summary`
6. Expose REST API for query + import
7. Basic frontend: import panel + trades table + pairs table + day summary

Schema designed with hooks for Phase 2 (chart snapshots, rule engine, LLM analysis).

---

## Architecture

```
PDF upload / API trigger
        ↓
broker auto-detect (from PDF header text)
        ↓
broker-specific annexure parser
        ↓
symbol normalizer (all formats → canonical)
        ↓
force-square detector
        ↓
jrn_trades (raw fills, deduped by broker+trade_id)
        ↓
FIFO matcher (per symbol, time-ordered)
        ↓
jrn_trade_pairs (derived, holds hold_seconds)
        ↓
day aggregator
        ↓
jrn_day_summary

Future:
jrn_chart_snapshots ←→ jrn_trade_pairs (chart at entry/exit)
jrn_analyses        ←  LLM streaming (per day or pair)
jrn_rules           →  rule violations → trigger analysis
```

---

## File structure

```
backend/
  journal/
    __init__.py
    config.py          # lot sizes, brokerage models, charge rates
    models.py          # dataclasses: Trade, TradePair, Charges, DaySummary, Rule
    schema.sql         # all CREATE TABLE IF NOT EXISTS
    db.py              # init_journal_tables(), seed_default_rules()
    symbol_parser.py   # all broker formats → ParsedSymbol
    force_square.py    # broker-specific force-square detection
    charges.py         # compute_charges(), compute_pair_charges()
    matcher.py         # match_all_symbols() → list[TradePair]
    aggregator.py      # build_day_summary() from pairs + trades
    parsers/
      __init__.py
      base.py          # BaseParser ABC
      pdf.py           # auto-detect + dispatch to broker parsers
      mstock.py        # mStock PDF annexure parser
      lemonn.py        # Lemonn PDF annexure parser
      zerodha.py       # Zerodha PDF annexure parser
      kite.py          # Kite API parser
      upstox.py        # Upstox API parser
  api/routers/
    journal.py         # FastAPI router, 10 endpoints

frontend/
  src/
    store/journal.ts
    pages/Journal/JournalPage.tsx
    components/Journal/
      ImportPanel.tsx
      TradeTable.tsx
      PairsTable.tsx
      DaySummaryCard.tsx
```

---

## Implementation order

1. `schema.sql` + `db.py`
2. `config.py`
3. `models.py`
4. `symbol_parser.py`
5. `force_square.py`
6. `charges.py`
7. `matcher.py`
8. `aggregator.py`
9. `parsers/pdf.py` + `parsers/mstock.py` + `parsers/lemonn.py` + `parsers/zerodha.py`
10. `parsers/kite.py` + `parsers/upstox.py`
11. `api/routers/journal.py`
12. Frontend store + components

---

## Task 1 — schema.sql

```sql
-- jrn_trades: ONE canonical normalized trade record. This is the standard target every
-- broker style normalizes into. A "record" is granularity-tagged via `fill_grain`:
--   'fill'  = one exchange fill (API: Kite/Upstox/mStock-today carry trade_id + timestamp)
--   'wap'   = one WAP-aggregated side per (symbol, note) (ALL PDF contract notes — they only
--             publish one buy + one sell weighted-average row per symbol; no per-fill data).
-- Fields that exist only in one style are NULL in the other (timestamps/ids → NULL for 'wap').
-- The matcher + aggregator must treat both grains uniformly (FIFO works on either).
CREATE TABLE IF NOT EXISTS jrn_trades (
    id               BIGSERIAL PRIMARY KEY,
    broker           TEXT NOT NULL,
    source           TEXT NOT NULL,          -- pdf|api
    source_format    TEXT NOT NULL DEFAULT 'pdf', -- pdf|api|csv
    fill_grain       TEXT NOT NULL DEFAULT 'wap', -- fill|wap  (see header note)
    source_file      TEXT,
    contract_note_no TEXT,
    is_revised       BOOLEAN DEFAULT FALSE,
    order_no         TEXT,                   -- NULL for PDF (no order col)
    order_time       TIME,                   -- NULL for PDF
    trade_id         TEXT,                   -- NULL for PDF (only API fills have it)
    trade_date       DATE NOT NULL,
    trade_time       TIME,                   -- NULL for PDF; HH:MM:SS only on API fills
    symbol           TEXT NOT NULL,          -- canonical "NIFTY 23200 PE 2026-06-09"
    raw_symbol       TEXT NOT NULL,          -- exact broker string, for audit/dedup
    underlying       TEXT NOT NULL,
    strike           INTEGER,
    option_type      TEXT,                   -- CE|PE|NULL
    expiry           DATE,
    instrument       TEXT,                   -- OPTIDX|FUTIDX|OPTSTK|FUTSTK|EQ
    exchange         TEXT NOT NULL,          -- NSE|BSE|MCX
    segment          TEXT NOT NULL,          -- FO|EQ|CDS
    product_type     TEXT,                   -- MIS|NRML|CNC (API only; NULL for PDF)
    trade_type       TEXT NOT NULL,          -- BUY|SELL  (Lemonn prints sell qty negative → abs())
    quantity         INTEGER NOT NULL,       -- always positive
    lot_size         INTEGER,
    lots             INTEGER,                -- quantity/lot_size (computed on import)
    price            NUMERIC(12,4) NOT NULL, -- WAP for 'wap' rows, average_price for API fills
    brokerage        NUMERIC(10,4) DEFAULT 0,-- from PDF brokerage column (per-unit×qty); NOT flat-20 for PDF
    closing_rate     NUMERIC(12,4),          -- EOD settlement (open position MTM); NULL if absent
    gross_amount     NUMERIC(14,4),          -- Net Total (before levies) from note, for reconciliation
    status           TEXT DEFAULT 'filled',  -- filled|rejected|cancelled
    remark           TEXT,
    is_force_squared BOOLEAN DEFAULT FALSE,
    chart_snapshot_id BIGINT,               -- future: FK jrn_chart_snapshots
    trade_notes      TEXT,                   -- future: manual annotation
    imported_at      TIMESTAMPTZ DEFAULT NOW()
    -- NO table-level UNIQUE(broker,trade_id): trade_id is NULL for all PDF rows.
    -- Dedup via partial unique indexes below (see G9b).
);
-- API fills: dedup on trade_id when present.
CREATE UNIQUE INDEX IF NOT EXISTS idx_jt_api_uniq
    ON jrn_trades(broker, trade_id) WHERE trade_id IS NOT NULL;
-- PDF WAP rows: content key (a REVISED note re-import must not duplicate).
CREATE UNIQUE INDEX IF NOT EXISTS idx_jt_pdf_uniq
    ON jrn_trades(broker, contract_note_no, raw_symbol, trade_type, quantity)
    WHERE source = 'pdf';
CREATE INDEX IF NOT EXISTS idx_jt_date   ON jrn_trades(trade_date);
CREATE INDEX IF NOT EXISTS idx_jt_sym    ON jrn_trades(symbol);
CREATE INDEX IF NOT EXISTS idx_jt_order  ON jrn_trades(order_no, broker);
CREATE INDEX IF NOT EXISTS idx_jt_broker ON jrn_trades(broker, trade_date);

-- jrn_trade_pairs: FIFO-matched entry+exit
CREATE TABLE IF NOT EXISTS jrn_trade_pairs (
    id               BIGSERIAL PRIMARY KEY,
    symbol           TEXT NOT NULL,
    underlying       TEXT NOT NULL,
    strike           INTEGER,
    option_type      TEXT,
    expiry           DATE,
    exchange         TEXT,
    segment          TEXT,
    side             TEXT NOT NULL,          -- LONG|SHORT
    quantity         INTEGER NOT NULL,
    lots             INTEGER,
    lot_size         INTEGER,
    open_date        DATE NOT NULL,
    open_time        TIME,
    entry_price      NUMERIC(12,4) NOT NULL,
    entry_trade_ids  BIGINT[],
    close_date       DATE,                   -- null = open position
    close_time       TIME,
    exit_price       NUMERIC(12,4),
    exit_trade_ids   BIGINT[],
    gross_pnl        NUMERIC(12,4),
    charges          JSONB,
    net_pnl          NUMERIC(12,4),
    hold_seconds     INTEGER,                -- null for open positions
    is_intraday      BOOLEAN,
    force_squared    BOOLEAN DEFAULT FALSE,
    chart_snapshot_id       BIGINT,          -- future: entry chart
    exit_chart_snapshot_id  BIGINT,          -- future: exit chart
    trade_rationale  TEXT,                   -- future: why taken
    trade_mistakes   TEXT,                   -- future: what went wrong
    session_notes    TEXT                    -- future: session context
);
CREATE INDEX IF NOT EXISTS idx_jtp_date ON jrn_trade_pairs(open_date);
CREATE INDEX IF NOT EXISTS idx_jtp_sym  ON jrn_trade_pairs(symbol);

-- jrn_day_summary: per-day aggregates
CREATE TABLE IF NOT EXISTS jrn_day_summary (
    id                   BIGSERIAL PRIMARY KEY,
    trade_date           DATE NOT NULL,
    broker               TEXT,               -- null = all brokers
    total_fills          INTEGER DEFAULT 0,
    total_orders         INTEGER DEFAULT 0,
    total_lots           INTEGER DEFAULT 0,
    failed_order_count   INTEGER DEFAULT 0,  -- rejected/cancelled (mStock)
    force_squared_count  INTEGER DEFAULT 0,
    first_trade_time     TIME,
    last_trade_time      TIME,
    avg_hold_seconds     INTEGER,
    time_bucket_pnl      JSONB,             -- {"09:15": -800, "09:30": 1200}
    gross_pnl            NUMERIC(12,4) DEFAULT 0,
    total_brokerage      NUMERIC(12,4) DEFAULT 0,
    total_charges        NUMERIC(12,4) DEFAULT 0,
    net_pnl              NUMERIC(12,4) DEFAULT 0,
    win_pairs            INTEGER DEFAULT 0,
    loss_pairs           INTEGER DEFAULT 0,
    open_pairs           INTEGER DEFAULT 0,
    UNIQUE(trade_date, COALESCE(broker, ''))
);

-- jrn_rules: rule engine config
CREATE TABLE IF NOT EXISTS jrn_rules (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL UNIQUE,
    rule_type   TEXT NOT NULL,
    enabled     BOOLEAN DEFAULT TRUE,
    config      JSONB NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- jrn_analyses: LLM analysis results (phase 2)
CREATE TABLE IF NOT EXISTS jrn_analyses (
    id            BIGSERIAL PRIMARY KEY,
    scope         TEXT NOT NULL,
    scope_id      TEXT NOT NULL,
    triggered_by  TEXT NOT NULL,
    rule_ids      BIGINT[],
    response      TEXT,
    model         TEXT,
    tokens_in     INTEGER,
    tokens_out    INTEGER,
    created_at    TIMESTAMPTZ DEFAULT NOW()
);

-- jrn_chart_snapshots: chart context at trade time (phase 2)
CREATE TABLE IF NOT EXISTS jrn_chart_snapshots (
    id            BIGSERIAL PRIMARY KEY,
    trade_pair_id BIGINT REFERENCES jrn_trade_pairs(id),
    snapshot_type TEXT,                      -- entry|exit|session
    symbol        TEXT,
    timeframe     TEXT,                      -- 1m|5m|15m
    snapshot_time TIMESTAMPTZ,
    candle_data   JSONB,                     -- OHLCV array
    indicators    JSONB,                     -- EMA/VWAP values
    image_path    TEXT,                      -- future TV MCP screenshot
    created_at    TIMESTAMPTZ DEFAULT NOW()
);
```

---

## Task 2 — config.py

```python
# backend/journal/config.py
from decimal import Decimal

# Update when SEBI changes lot sizes
LOT_SIZES: dict[str, int] = {
    "NIFTY":      75,
    "BANKNIFTY":  35,
    "FINNIFTY":   65,
    "MIDCPNIFTY": 120,
    "SENSEX":     20,
    "BANKEX":     20,
}

def get_lot_size(underlying: str) -> int:
    return LOT_SIZES.get(underlying.upper(), 1)

BROKERAGE_MODELS: dict[str, dict] = {
    "zerodha": {"type": "flat_per_order", "amount": Decimal("20")},
    "kite":    {"type": "flat_per_order", "amount": Decimal("20")},
    "upstox":  {"type": "flat_per_order", "amount": Decimal("20")},
    "lemonn":  {"type": "flat_per_order", "amount": Decimal("20")},
    "mstock":  {"type": "per_unit",       "amount": Decimal("0.25")},
    "pdf":     {"type": "from_data"},
}

# STT on SELL side. Options on premium; futures on turnover. (eff 1-Apr-2026, see G2)
STT_RATES = {
    "FO_OPT_SELL": Decimal("0.0015"),    # options sell, 0.15% of premium (was 0.001 pre-Apr-2026)
    "FO_FUT_SELL": Decimal("0.0005"),    # futures sell, 0.05% of turnover
    "EQ_DELIVERY": Decimal("0.001"),
    "EQ_INTRADAY": Decimal("0.00025"),
}

# Exchange transaction charge. *_OPT = on premium (much higher than futures). See G2.
EXCHANGE_TXN = {
    "NSE_OPT": Decimal("0.0003503"),     # NSE options ₹3503/cr premium
    "BSE_OPT": Decimal("0.000325"),      # BSE SENSEX/BANKEX options ₹3250/cr premium
    "NSE_FUT": Decimal("0.000053"),      # NSE futures
    "BSE_FUT": Decimal("0.000047"),      # BSE futures
    "NSE_EQ":  Decimal("0.0000322"),
    "BSE_EQ":  Decimal("0.0000375"),
}

SEBI_FEE   = Decimal("0.000001")
GST_RATE   = Decimal("0.18")
STAMP_DUTY = {
    "FO":           Decimal("0.00003"),
    "EQ_INTRADAY":  Decimal("0.00003"),
    "EQ_DELIVERY":  Decimal("0.00015"),
}
```

---

## Task 3 — models.py

```python
# backend/journal/models.py
from dataclasses import dataclass, field
from datetime import date, time
from decimal import Decimal
from typing import Optional

@dataclass
class Trade:
    broker: str; source: str; trade_date: date
    trade_time: Optional[time]
    symbol: str; raw_symbol: str; underlying: str
    exchange: str; segment: str
    trade_type: str; quantity: int; price: Decimal
    id: Optional[int] = None
    order_no: Optional[str] = None; order_time: Optional[time] = None
    trade_id: Optional[str] = None
    strike: Optional[int] = None; option_type: Optional[str] = None
    expiry: Optional[date] = None; instrument: Optional[str] = None
    lot_size: Optional[int] = None; lots: Optional[int] = None
    brokerage: Decimal = Decimal(0); closing_rate: Optional[Decimal] = None
    status: str = "filled"; remark: Optional[str] = None
    is_force_squared: bool = False
    source_file: Optional[str] = None
    contract_note_no: Optional[str] = None; is_revised: bool = False

@dataclass
class Charges:
    brokerage: Decimal = Decimal(0); stt: Decimal = Decimal(0)
    stamp_duty: Decimal = Decimal(0); exchange_txn: Decimal = Decimal(0)
    sebi_fee: Decimal = Decimal(0); gst: Decimal = Decimal(0)

    @property
    def total(self) -> Decimal:
        return sum([self.brokerage, self.stt, self.stamp_duty,
                    self.exchange_txn, self.sebi_fee, self.gst], Decimal(0))

    def to_dict(self) -> dict:
        return {k: str(getattr(self, k)) for k in
                ["brokerage","stt","stamp_duty","exchange_txn","sebi_fee","gst"]}

@dataclass
class TradePair:
    symbol: str; underlying: str; exchange: str; segment: str
    side: str; quantity: int
    open_date: date; open_time: Optional[time]; entry_price: Decimal
    entry_trade_ids: list[int] = field(default_factory=list)
    id: Optional[int] = None
    strike: Optional[int] = None; option_type: Optional[str] = None
    expiry: Optional[date] = None
    lot_size: Optional[int] = None; lots: Optional[int] = None
    close_date: Optional[date] = None; close_time: Optional[time] = None
    exit_price: Optional[Decimal] = None
    exit_trade_ids: list[int] = field(default_factory=list)
    gross_pnl: Optional[Decimal] = None; charges: Optional[Charges] = None
    net_pnl: Optional[Decimal] = None; hold_seconds: Optional[int] = None
    is_intraday: Optional[bool] = None; force_squared: bool = False

@dataclass
class DaySummary:
    trade_date: date; broker: Optional[str]
    total_fills: int; total_orders: int; total_lots: int
    failed_order_count: int; force_squared_count: int
    first_trade_time: Optional[time]; last_trade_time: Optional[time]
    avg_hold_seconds: Optional[int]; time_bucket_pnl: dict
    gross_pnl: Decimal; total_brokerage: Decimal
    total_charges: Decimal; net_pnl: Decimal
    win_pairs: int; loss_pairs: int; open_pairs: int

@dataclass
class Rule:
    id: Optional[int]; name: str; rule_type: str; enabled: bool; config: dict

@dataclass
class RuleViolation:
    rule: Rule; message: str; severity: str
    context: dict = field(default_factory=dict)
```

---

## Task 4 — symbol_parser.py

Handles all 4 symbol formats → canonical `"NIFTY 23200 PE 2026-06-09"`.

```python
# backend/journal/symbol_parser.py
import re, calendar
from dataclasses import dataclass
from datetime import date
from typing import Optional
from .config import get_lot_size

_MON3 = {"JAN":1,"FEB":2,"MAR":3,"APR":4,"MAY":5,"JUN":6,
          "JUL":7,"AUG":8,"SEP":9,"OCT":10,"NOV":11,"DEC":12}
_KITE_MON = {**{str(i):i for i in range(1,10)}, "O":10,"N":11,"D":12}

@dataclass
class ParsedSymbol:
    underlying: str; exchange: str; segment: str; instrument: str
    symbol: str; raw: str
    strike: Optional[int] = None; option_type: Optional[str] = None
    expiry: Optional[date] = None
    lot_size: Optional[int] = None; lots: Optional[int] = None


def parse_symbol(raw: str, broker: str = "unknown", quantity: int = 0) -> ParsedSymbol:
    s = raw.strip().upper()
    # Strip mStock prefixes: "BSXOPT SENSEX2660473600CE 1127872 (BT)"
    s = re.sub(r'^(BSXOPT|BSXFUT|NSXOPT|NSXFUT)\s+', '', s)
    s = re.sub(r'\s+\d+\s*\(BT\)\s*$', '', s).strip()

    # Lemonn verbose: "OPTIDX SENSEX 14MAY2026 74200 PE-BSE"
    m = re.match(
        r'^(OPTIDX|FUTIDX|OPTSTK|FUTSTK)\s+(\w+)\s+'
        r'(\d{2}(?:JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\d{4})\s+'
        r'(\d+)\s+(CE|PE)(?:-(NSE|BSE|MCX))?$', s)
    if m:
        inst, und, exp_str, strike, opt, exch = m.groups()
        expiry = _ddmonyyyy(exp_str)
        exchange = exch or ("BSE" if und in ("SENSEX","BANKEX") else "NSE")
        return _make(raw, und, exchange, inst, expiry, int(strike), opt, quantity)

    # Zerodha annexure: "NIFTY2660923200PE / 09 JUNE 2026"
    m = re.match(r'^(\S+)\s*/\s*(\d{2}\s+\w+\s+\d{4})$', s)
    if m:
        compact, date_str = m.groups()
        p = _compact(compact, broker, quantity)
        if p:
            p.expiry = _dd_mon_yyyy(date_str.strip())
            p.symbol = _canonical(p.underlying, p.strike, p.option_type, p.expiry)
            return p

    # "NIFTY2660923200PE - NSE" or "SENSEX2660473600CE - BSE"
    m = re.match(r'^(\S+)\s*-\s*(NSE|BSE|MCX)$', s)
    if m:
        compact, exch = m.groups()
        p = _compact(compact, broker, quantity)
        if p: p.exchange = exch; return p

    # Pure compact
    p = _compact(s, broker, quantity)
    if p: return p

    # Equity
    if re.match(r'^[A-Z&]+$', s):
        return ParsedSymbol(underlying=s, exchange="NSE", segment="EQ",
                            instrument="EQ", symbol=s, raw=raw, lot_size=1, lots=quantity)

    return ParsedSymbol(underlying=s, exchange="NSE", segment="EQ",
                        instrument="EQ", symbol=s, raw=raw)


def _compact(s: str, broker: str, qty: int) -> Optional[ParsedSymbol]:
    # Weekly YYMMDD: SENSEX2660473600CE
    m = re.match(r'^([A-Z&]+?)(\d{2})(\d{2})(\d{2})(\d+)(CE|PE)$', s)
    if m:
        und, yy, mm, dd, strike, opt = m.groups()
        try:
            expiry = date(2000+int(yy), int(mm), int(dd))
            exch = "BSE" if und in ("SENSEX","BANKEX") else "NSE"
            return _make(s, und, exch, "OPTIDX", expiry, int(strike), opt, qty)
        except ValueError: pass

    # Kite compact weekly: single-char month NIFTY26O0923200PE
    m = re.match(r'^([A-Z&]+?)(\d{2})([A-Z1-9])(\d{2})(\d+)(CE|PE)$', s)
    if m:
        und, yy, mon_c, dd, strike, opt = m.groups()
        month = _KITE_MON.get(mon_c)
        if month:
            try:
                expiry = date(2000+int(yy), month, int(dd))
                return _make(s, und, "NSE", "OPTIDX", expiry, int(strike), opt, qty)
            except ValueError: pass

    # Monthly: NIFTY26JUN23200PE
    m = re.match(r'^([A-Z&]+?)(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d+)(CE|PE)$', s)
    if m:
        und, yy, mon3, strike, opt = m.groups()
        expiry = _last_thu(2000+int(yy), _MON3[mon3])
        return _make(s, und, "NSE", "OPTIDX", expiry, int(strike), opt, qty)

    # Futures
    m = re.match(r'^([A-Z&]+?)(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)FUT$', s)
    if m:
        und, yy, mon3 = m.groups()
        expiry = _last_thu(2000+int(yy), _MON3[mon3])
        ls = get_lot_size(und)
        return ParsedSymbol(underlying=und, exchange="NSE", segment="FO",
                            instrument="FUTIDX", raw=s, expiry=expiry,
                            symbol=f"{und} FUT {expiry}", lot_size=ls,
                            lots=qty//ls if ls else None)
    return None


def _make(raw, und, exch, inst, expiry, strike, opt, qty) -> ParsedSymbol:
    seg = "FO"
    ls = get_lot_size(und)
    return ParsedSymbol(underlying=und, exchange=exch, segment=seg, instrument=inst,
                        raw=raw, symbol=_canonical(und, strike, opt, expiry),
                        strike=strike, option_type=opt, expiry=expiry,
                        lot_size=ls, lots=qty//ls if ls else None)

def _canonical(und, strike, opt, expiry) -> str:
    if opt:   return f"{und} {strike} {opt} {expiry}"
    if expiry: return f"{und} FUT {expiry}"
    return und

def _ddmonyyyy(s: str) -> date:
    m = re.match(r'^(\d{2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{4})$', s)
    if m: dd, mon, yyyy = m.groups(); return date(int(yyyy), _MON3[mon], int(dd))
    raise ValueError(s)

def _dd_mon_yyyy(s: str) -> date:
    parts = s.upper().split()
    if len(parts) == 3:
        dd, mon_name, yyyy = parts
        for i, name in enumerate(calendar.month_name):
            if name and name.upper().startswith(mon_name[:3]):
                return date(int(yyyy), i, int(dd))
    raise ValueError(s)

def _last_thu(year: int, month: int) -> date:
    last = calendar.monthrange(year, month)[1]
    d = date(year, month, last)
    while d.weekday() != 3: d = date(year, month, d.day - 1)
    return d
```

---

## Task 5 — force_square.py + charges.py + matcher.py

### force_square.py
```python
# backend/journal/force_square.py
_PATTERNS = {
    "lemonn":  ["squaring off", "non-compliance of margin"],
    "zerodha": ['"'],          # literal " char in Remarks
    "kite":    ["autosquareoff", "auto square"],
    "upstox":  ["auto square", "autosquare"],
    "mstock":  [],
}

def is_force_squared(remark: str | None, broker: str) -> bool:
    if not remark: return False
    r = remark.lower().strip()
    return any(p.lower() in r for p in _PATTERNS.get(broker, []))
```

### charges.py
```python
# backend/journal/charges.py
from decimal import Decimal, ROUND_HALF_UP
from .models import Charges
from .config import STT_RATES, EXCHANGE_TXN, SEBI_FEE, GST_RATE, STAMP_DUTY

def _r(v): return v.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def compute_pair_charges(segment, exchange, qty, entry_px, exit_px,
                          entry_brok=Decimal(0), exit_brok=Decimal(0),
                          intraday=True, is_option=True) -> Charges:
    # is_option distinguishes OPT vs FUT rates within the FO segment (see G2).
    def _side(trade_type, px, brok):
        tv = Decimal(qty) * px
        if segment == "FO":
            sell_key = "FO_OPT_SELL" if is_option else "FO_FUT_SELL"
            stt = _r(tv * STT_RATES[sell_key]) if trade_type == "SELL" else Decimal(0)
        elif intraday:
            stt = _r(tv * STT_RATES["EQ_INTRADAY"]) if trade_type == "SELL" else Decimal(0)
        else:
            stt = _r(tv * STT_RATES["EQ_DELIVERY"])
        stamp_k = "FO" if segment == "FO" else ("EQ_INTRADAY" if intraday else "EQ_DELIVERY")
        stamp = _r(tv * STAMP_DUTY[stamp_k]) if trade_type == "BUY" else Decimal(0)
        if segment == "FO":
            exch_k = f"{exchange}_{'OPT' if is_option else 'FUT'}"
        else:
            exch_k = f"{exchange}_EQ"
        etxn = _r(tv * EXCHANGE_TXN.get(exch_k, EXCHANGE_TXN["NSE_OPT"]))
        sebi = _r(tv * SEBI_FEE)
        gst = _r((brok + etxn + sebi) * GST_RATE)
        return stt, stamp, etxn, sebi, gst

    b_stt, b_stmp, b_etxn, b_sebi, b_gst = _side("BUY",  entry_px, entry_brok)
    s_stt, s_stmp, s_etxn, s_sebi, s_gst = _side("SELL", exit_px,  exit_brok)
    return Charges(
        brokerage=entry_brok+exit_brok, stt=b_stt+s_stt,
        stamp_duty=b_stmp+s_stmp, exchange_txn=b_etxn+s_etxn,
        sebi_fee=b_sebi+s_sebi, gst=b_gst+s_gst,
    )
```

### matcher.py (key logic only)
```python
# backend/journal/matcher.py
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date, time, datetime
from decimal import Decimal
from .models import Trade, TradePair, Charges
from .charges import compute_pair_charges

@dataclass
class _Lot:
    trade_ids: list[int]; qty: int; price: Decimal
    open_date: date; open_time: time | None
    brokerage: Decimal; force_squared: bool = False

def match_all_symbols(trades: list[Trade]) -> list[TradePair]:
    # Group by (broker, symbol) — NEVER match a fill on one broker against another (G3).
    by_key: dict[tuple, list[Trade]] = defaultdict(list)
    for t in trades:
        by_key[(t.broker, t.symbol)].append(t)
    return [p for ts in by_key.values() for p in _match(ts)]

def _match(trades: list[Trade]) -> list[TradePair]:
    trades = sorted(trades, key=lambda t: (
        t.trade_date, t.trade_time or time(0,0,0), t.id or 0))
    long_q: deque[_Lot] = deque()
    short_q: deque[_Lot] = deque()
    pairs = []
    for t in trades:
        if t.status != "filled": continue
        lot = _Lot([t.id] if t.id else [], t.quantity, t.price,
                   t.trade_date, t.trade_time, t.brokerage, t.is_force_squared)
        rem = t.quantity
        if t.trade_type == "BUY":
            while rem > 0 and short_q:
                e = short_q[0]; fill = min(rem, e.qty)
                pairs.append(_close(e, t, fill, "SHORT")); e.qty -= fill; rem -= fill
                if e.qty == 0: short_q.popleft()
            if rem > 0: lot.qty = rem; long_q.append(lot)
        else:
            while rem > 0 and long_q:
                e = long_q[0]; fill = min(rem, e.qty)
                pairs.append(_close(e, t, fill, "LONG")); e.qty -= fill; rem -= fill
                if e.qty == 0: long_q.popleft()
            if rem > 0: lot.qty = rem; short_q.append(lot)
    # Open positions
    t0 = trades[0] if trades else None
    for side, q in [("LONG", long_q), ("SHORT", short_q)]:
        for lot in q:
            pairs.append(TradePair(
                symbol=t0.symbol, underlying=t0.underlying,
                exchange=t0.exchange, segment=t0.segment,
                side=side, quantity=lot.qty, lot_size=t0.lot_size,
                lots=(lot.qty//t0.lot_size) if t0.lot_size else None,
                open_date=lot.open_date, open_time=lot.open_time,
                entry_price=lot.price, entry_trade_ids=lot.trade_ids,
                force_squared=lot.force_squared,
            ))
    return pairs

def _close(entry: _Lot, exit_t: Trade, qty: int, side: str) -> TradePair:
    ep = entry.price if side == "LONG" else exit_t.price
    xp = exit_t.price if side == "LONG" else entry.price
    gross = (xp - ep) * qty
    intraday = entry.open_date == exit_t.trade_date
    charges = compute_pair_charges(
        exit_t.segment, exit_t.exchange, qty, ep, xp,
        entry.brokerage, exit_t.brokerage, intraday,
        is_option=(exit_t.option_type is not None))
    hold_s = None
    if entry.open_time and exit_t.trade_time:
        e = datetime.combine(entry.open_date, entry.open_time)
        x = datetime.combine(exit_t.trade_date, exit_t.trade_time)
        hold_s = int((x-e).total_seconds())
    return TradePair(
        symbol=exit_t.symbol, underlying=exit_t.underlying,
        strike=exit_t.strike, option_type=exit_t.option_type, expiry=exit_t.expiry,
        exchange=exit_t.exchange, segment=exit_t.segment,
        side=side, quantity=qty, lot_size=exit_t.lot_size,
        lots=(qty//exit_t.lot_size) if exit_t.lot_size else None,
        open_date=entry.open_date, open_time=entry.open_time, entry_price=ep,
        entry_trade_ids=entry.trade_ids,
        close_date=exit_t.trade_date, close_time=exit_t.trade_time, exit_price=xp,
        exit_trade_ids=[exit_t.id] if exit_t.id else [],
        gross_pnl=gross, charges=charges, net_pnl=gross-charges.total,
        hold_seconds=hold_s, is_intraday=intraday,
        force_squared=(entry.force_squared or exit_t.is_force_squared),
    )
```

---

## Task 6 — PDF Parsers

### parsers/pdf.py (auto-detect + dispatch)

```python
# backend/journal/parsers/pdf.py
import tempfile
from pathlib import Path
from markitdown import MarkItDown
from ..models import Trade

_MD = MarkItDown()

def _to_markdown(file_bytes: bytes) -> tuple[str, str]:
    """Convert PDF bytes to markdown, return (markdown, tmp_path)."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(file_bytes); tmp = f.name
    result = _MD.convert(tmp)
    Path(tmp).unlink(missing_ok=True)
    return result.text_content

def detect_broker(md: str) -> str:
    """Detect broker from PDF header text."""
    if "Mirae Asset" in md or "mstock" in md.lower():
        return "mstock"
    if "NU Investors" in md or "lemonn" in md.lower():
        return "lemonn"
    if "Zerodha" in md:
        return "zerodha"     # Kite contract notes are Zerodha-format → zerodha.parse (G7)
    if "Upstox" in md or "rksv" in md.lower():
        return "upstox"
    return "pdf"

async def parse_pdf_contract_note(
    file_bytes: bytes,
    broker: str = "auto",
    source_file: str = "",
    trade_date_override: str | None = None,
) -> list[Trade]:
    md = _to_markdown(file_bytes)
    detected = broker if broker != "auto" else detect_broker(md)

    from . import mstock, lemonn, zerodha
    parsers = {"mstock": mstock.parse, "lemonn": lemonn.parse, "zerodha": zerodha.parse}
    parser_fn = parsers.get(detected, zerodha.parse)  # zerodha as generic fallback

    return parser_fn(md, source_file=source_file)
```

### parsers/mstock.py

```python
# backend/journal/parsers/mstock.py
# mStock annexure: rows with qty=0 (₹5 rejected orders) mixed with real fills
# Columns: Order No | Order Time | Trade No | Trade Time | Remark/Segment |
#          Contract Description | Sell/Buy | Qty | ... | Price | ... | Net Total
import re
from datetime import date, time
from decimal import Decimal
from ..models import Trade
from ..symbol_parser import parse_symbol
from ..force_square import is_force_squared

# Match real fill rows (have Order Time and Trade Time)
_FILL_ROW = re.compile(
    r'(\d{18,20})\s+'              # order no
    r'(\d{2}:\d{2}:\d{2})\s+'     # order time
    r'(\d+)\s+'                    # trade no
    r'(\d{2}:\d{2}:\d{2})\s+'     # trade time
    r'BSEFO\s*-\s*BT_B\s+'        # segment marker
    r'(BSXOPT\s+\S+(?:\s+\d+)?\s*\(BT\))\s+'  # contract description
    r'(BUY|SELL)\s+'               # side
    r'(\d+)\s+'                    # qty
    r'[\d.]+\s+'                   # price in foreign currency
    r'([\d.]+)\s+'                 # gross rate / trade price (Rs)
    r'[\d.]+\s+'                   # brokerage per unit
    r'[\d.]+\s+'                   # net rate per unit
    r'[\d.]+\s+'                   # closing rate
    r'(-?[\d,]+\.?\d*)',           # net total
    re.MULTILINE,
)

# Contract note header info
_DATE_RE   = re.compile(r'TRADE DATE[:\s]+([\w]+\s+\d{1,2}\s+\d{4})', re.IGNORECASE)
_NOTE_RE   = re.compile(r'CONTRACT NOTE NO[.\s:]+(\d+)', re.IGNORECASE)

def _parse_trade_date(md: str) -> date:
    m = _DATE_RE.search(md)
    if m:
        from datetime import datetime
        try: return datetime.strptime(m.group(1).strip(), "%b %d %Y").date()
        except: pass
    return date.today()

def parse(md: str, source_file: str = "") -> list[Trade]:
    trade_date = _parse_trade_date(md)
    note_no_m = _NOTE_RE.search(md)
    note_no = note_no_m.group(1) if note_no_m else None

    trades = []
    for m in _FILL_ROW.finditer(md):
        order_no, order_t, trade_no, trade_t, raw_sym, side, qty_s, price_s, _ = m.groups()
        qty = int(qty_s)
        if qty == 0: continue  # rejected order row

        ps = parse_symbol(raw_sym.strip(), broker="mstock", quantity=qty)
        # mStock brokerage: ₹0.25/unit
        brok = Decimal("0.25") * qty

        trades.append(Trade(
            broker="mstock", source="pdf", source_file=source_file,
            contract_note_no=note_no,
            order_no=order_no, order_time=_t(order_t),
            trade_id=trade_no, trade_date=trade_date, trade_time=_t(trade_t),
            symbol=ps.symbol, raw_symbol=raw_sym.strip(), underlying=ps.underlying,
            exchange=ps.exchange, segment=ps.segment,
            trade_type=side, quantity=qty,
            lot_size=ps.lot_size, lots=ps.lots,
            strike=ps.strike, option_type=ps.option_type, expiry=ps.expiry,
            instrument=ps.instrument,
            price=Decimal(price_s), brokerage=brok,
            status="filled",
        ))

    # Also capture rejected orders for overtrading analysis
    _capture_rejected(md, trade_date, note_no, source_file, trades)
    return trades

def _capture_rejected(md, trade_date, note_no, source_file, trades):
    """Capture ₹5 rejected rows as status=rejected."""
    _REJ = re.compile(
        r'(\d{18,20})\s+BSEFO\s*-\s*BT_B\s+(\S+(?:\s+\d+)?\s*\(BT\))\s+0\s+'
        r'[\d.]+\s+5\.0+\s', re.MULTILINE)
    seen_order_nos = {t.order_no for t in trades}
    for m in _REJ.finditer(md):
        order_no, raw_sym = m.groups()
        if order_no in seen_order_nos: continue
        seen_order_nos.add(order_no)
        ps = parse_symbol(raw_sym.strip(), broker="mstock")
        trades.append(Trade(
            broker="mstock", source="pdf", source_file=source_file,
            contract_note_no=note_no,
            order_no=order_no, trade_date=trade_date,
            symbol=ps.symbol, raw_symbol=raw_sym.strip(), underlying=ps.underlying,
            exchange=ps.exchange, segment=ps.segment or "FO",
            trade_type="BUY", quantity=0, price=Decimal("5"),
            status="rejected",
            trade_time=None,
        ))

def _t(s: str) -> time:
    parts = s.split(":"); return time(int(parts[0]), int(parts[1]), int(parts[2]))
```

### parsers/zerodha.py

```python
# backend/journal/parsers/zerodha.py
# Zerodha annexure format:
# Order No | Order Time | Trade No | Trade Time | Contract/Expiry | B/S |
# Exchange | Qty | Brokerage(₹) | Net Rate | Closing Rate | Net Total | Remarks
import re
from datetime import date, time
from decimal import Decimal
from ..models import Trade
from ..symbol_parser import parse_symbol
from ..force_square import is_force_squared

_ROW = re.compile(
    r'(\d{13,20})\s+'              # order no
    r'(\d{2}:\d{2}:\d{2})\s+'     # order time
    r'(\d+)\s+'                    # trade no
    r'(\d{2}:\d{2}:\d{2})\s+'     # trade time
    r'([A-Z0-9]+\s*/\s*\d{2}\s+\w+\s+\d{4})\s+'  # "NIFTY2660923200PE / 09 June 2026"
    r'(B|S)\s+'                    # buy/sell
    r'(NSE|BSE|MCX)\s+'           # exchange (explicit column!)
    r'(\d+)\s+'                    # qty
    r'([\d.]+)\s+'                 # brokerage
    r'([\d.]+)\s+'                 # net rate
    r'(?:[\d.]+\s+)?'             # closing rate (optional)
    r'(\([\d,.]+\)|[\d,.]+)',      # net total
    re.MULTILINE,
)

_DATE_RE = re.compile(r'Trade Date[:\s]+(\d{2}/\d{2}/\d{4})', re.IGNORECASE)
_NOTE_RE = re.compile(r'Contract Note No[:\s]+(CNT-[\d/\-]+)', re.IGNORECASE)

def parse(md: str, source_file: str = "") -> list[Trade]:
    d_m = _DATE_RE.search(md)
    if d_m:
        from datetime import datetime
        trade_date = datetime.strptime(d_m.group(1), "%d/%m/%Y").date()
    else:
        trade_date = date.today()
    n_m = _NOTE_RE.search(md)
    note_no = n_m.group(1) if n_m else None

    trades = []
    for m in _ROW.finditer(md):
        ord_no, ord_t, trd_no, trd_t, contract_expiry, bs, exch, qty_s, brok_s, price_s, _ = m.groups()
        qty = int(qty_s)
        side = "BUY" if bs == "B" else "SELL"

        # "NIFTY2660923200PE / 09 June 2026" — parse_symbol handles this format
        ps = parse_symbol(contract_expiry.strip(), broker="zerodha", quantity=qty)
        ps.exchange = exch  # use explicit column, overrides guess

        # Remark: check if `"` appears in the remark field
        # Full line context needed — approximate: check for trailing "
        remark = '"' if '"\n' in m.group(0) else None
        fsq = is_force_squared(remark, "zerodha")

        trades.append(Trade(
            broker="zerodha", source="pdf", source_file=source_file,
            contract_note_no=note_no,
            order_no=ord_no, order_time=_t(ord_t),
            trade_id=trd_no, trade_date=trade_date, trade_time=_t(trd_t),
            symbol=ps.symbol, raw_symbol=contract_expiry.strip(),
            underlying=ps.underlying, exchange=exch, segment=ps.segment,
            trade_type=side, quantity=qty,
            lot_size=ps.lot_size, lots=ps.lots,
            strike=ps.strike, option_type=ps.option_type, expiry=ps.expiry,
            instrument=ps.instrument,
            price=Decimal(price_s), brokerage=Decimal(brok_s),
            status="filled", remark=remark, is_force_squared=fsq,
        ))
    return trades

def _t(s: str) -> time:
    p = s.split(":"); return time(int(p[0]), int(p[1]), int(p[2]))
```

### parsers/lemonn.py

```python
# backend/journal/parsers/lemonn.py
# Lemonn annexure:
# Order Number | Order Time | Trade No | TradeTime | Security Description |
# Buy/Sell | Qty | Price | Net Rate | Net Amount | Remark
import re
from datetime import date, time
from decimal import Decimal
from ..models import Trade
from ..symbol_parser import parse_symbol
from ..force_square import is_force_squared

_ROW = re.compile(
    r'(\d{18,20}\s*\n?\s*\d*)\s+'  # order number (may wrap)
    r'(\d{2}:\d{2}:\d{2})\s+'
    r'(\d+)\s+'
    r'(\d{2}:\d{2}:\d{2})\s+'
    r'(OPTIDX\s+\w+\s+\d{2}\w{3}\d{4}\s+\d+\s+(?:CE|PE)(?:-(?:NSE|BSE))?)\s+'
    r'(B|S)\s+'
    r'(\d+)\s+'
    r'([\d.]+)\s+'                 # price
    r'([\d.]+)\s+'                 # net rate
    r'([\d,.]+)',                   # net amount
    re.MULTILINE | re.IGNORECASE,
)

_DATE_RE = re.compile(r'Trade Date\s*:\s*(\d{2}/\d{2}/\d{4})', re.IGNORECASE)
_NOTE_RE = re.compile(r'CONTRACT NOTE NO\s*:\s*(\d+)', re.IGNORECASE)
_REMARK_RE = re.compile(r'Squaring off|non-compliance of margin', re.IGNORECASE)

def parse(md: str, source_file: str = "") -> list[Trade]:
    d_m = _DATE_RE.search(md)
    if d_m:
        from datetime import datetime
        trade_date = datetime.strptime(d_m.group(1), "%d/%m/%Y").date()
    else:
        trade_date = date.today()
    n_m = _NOTE_RE.search(md)
    note_no = n_m.group(1) if n_m else None

    # Extract global remark (Lemonn puts it as footnote, applies to all)
    global_force_sq = bool(_REMARK_RE.search(md))

    trades = []
    for m in _ROW.finditer(md):
        ord_no_raw, ord_t, trd_no, trd_t, contract, bs, qty_s, price_s, _, _ = m.groups()
        ord_no = re.sub(r'\s+', '', ord_no_raw)
        qty = int(qty_s)
        side = "BUY" if bs.upper() == "B" else "SELL"
        ps = parse_symbol(contract.strip(), broker="lemonn", quantity=qty)

        trades.append(Trade(
            broker="lemonn", source="pdf", source_file=source_file,
            contract_note_no=note_no,
            order_no=ord_no, order_time=_t(ord_t),
            trade_id=trd_no, trade_date=trade_date, trade_time=_t(trd_t),
            symbol=ps.symbol, raw_symbol=contract.strip(),
            underlying=ps.underlying, exchange=ps.exchange, segment=ps.segment,
            trade_type=side, quantity=qty,
            lot_size=ps.lot_size, lots=ps.lots,
            strike=ps.strike, option_type=ps.option_type, expiry=ps.expiry,
            instrument=ps.instrument,
            price=Decimal(price_s), brokerage=Decimal("20"),
            status="filled",
            remark="Squaring off - margin" if global_force_sq else None,
            is_force_squared=global_force_sq,
        ))
    return trades

def _t(s: str) -> time:
    p = s.split(":"); return time(int(p[0]), int(p[1]), int(p[2]))
```

---

## Task 7 — aggregator.py

```python
# backend/journal/aggregator.py
from collections import defaultdict
from datetime import datetime, time
from decimal import Decimal
from .models import Trade, TradePair, DaySummary

def build_day_summary(
    trades: list[Trade],
    pairs: list[TradePair],
    broker: str | None = None,
) -> DaySummary:
    if not trades:
        raise ValueError("No trades")
    trade_date = trades[0].trade_date

    # Time bounds
    times = [t.trade_time for t in trades if t.trade_time and t.status == "filled"]
    first = min(times) if times else None
    last  = max(times) if times else None

    # Counts
    filled = [t for t in trades if t.status == "filled"]
    order_nos = {t.order_no for t in filled if t.order_no}

    # 30-min buckets
    buckets: dict[str, float] = defaultdict(float)
    for p in pairs:
        if p.net_pnl is not None and p.close_time:
            hh = p.close_time.hour
            mm = 0 if p.close_time.minute < 30 else 30
            key = f"{hh:02d}:{mm:02d}"
            buckets[key] += float(p.net_pnl)

    # Hold seconds
    holds = [p.hold_seconds for p in pairs if p.hold_seconds is not None]
    avg_hold = int(sum(holds)/len(holds)) if holds else None

    # P&L aggregation
    closed = [p for p in pairs if p.net_pnl is not None]
    gross_pnl = sum((p.gross_pnl or Decimal(0)) for p in closed)
    total_charges = sum((p.charges.total if p.charges else Decimal(0)) for p in closed)
    net_pnl = sum((p.net_pnl or Decimal(0)) for p in closed)
    total_brok = sum(t.brokerage for t in filled)
    total_lots = sum(t.lots or 0 for t in filled)

    return DaySummary(
        trade_date=trade_date,
        broker=broker,
        total_fills=len(filled),
        total_orders=len(order_nos),
        total_lots=total_lots,
        failed_order_count=sum(1 for t in trades if t.status == "rejected"),
        force_squared_count=sum(1 for t in filled if t.is_force_squared),
        first_trade_time=first,
        last_trade_time=last,
        avg_hold_seconds=avg_hold,
        time_bucket_pnl=dict(buckets),
        gross_pnl=Decimal(str(round(float(gross_pnl), 2))),
        total_brokerage=total_brok,
        total_charges=Decimal(str(round(float(total_charges), 2))),
        net_pnl=Decimal(str(round(float(net_pnl), 2))),
        win_pairs=sum(1 for p in closed if (p.net_pnl or 0) > 0),
        loss_pairs=sum(1 for p in closed if (p.net_pnl or 0) < 0),
        open_pairs=sum(1 for p in pairs if p.close_date is None),
    )
```

---

## Task 8 — API Router (journal.py)

**File:** `backend/api/routers/journal.py`

10 endpoints — import only, no analysis yet.

```python
# backend/api/routers/journal.py
from __future__ import annotations
import json
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from pydantic import BaseModel
import asyncpg
from decimal import Decimal

router = APIRouter(tags=["journal"])

async def get_pool():
    from main import app; return app.state.pool


# ── Import ───────────────────────────────────────────────────────────────────

@router.post("/import/pdf")
async def import_pdf(
    file: UploadFile = File(...),
    broker: str = Query("auto"),
    pool=Depends(get_pool),
):
    """Upload PDF contract note; auto-detect broker and parse."""
    from journal.parsers.pdf import parse_pdf_contract_note
    from journal.matcher import match_all_symbols
    from journal.aggregator import build_day_summary

    content = await file.read()
    trades = await parse_pdf_contract_note(content, broker=broker, source_file=file.filename or "")
    inserted = await _upsert_trades(pool, trades)

    # Recompute pairs and summary for affected dates
    affected_dates = list({t.trade_date for t in trades})
    for dt in affected_dates:
        await _recompute_day(pool, dt)

    return {"imported": len(trades), "inserted": inserted,
            "filename": file.filename, "dates": [str(d) for d in affected_dates]}


class ApiImportRequest(BaseModel):
    broker: str       # kite|upstox
    from_date: str
    to_date: str

@router.post("/import/api")
async def import_api(req: ApiImportRequest, pool=Depends(get_pool)):
    """Import trades from broker API."""
    trades = []
    if req.broker == "kite":
        from journal.parsers.kite import KiteParser
        from core.sdk import get_sdk
        trades = await KiteParser(await get_sdk()).fetch_trades(req.from_date, req.to_date)
    elif req.broker == "upstox":
        from journal.parsers.upstox import UpstoxParser
        from brokers.upstox import _get_access_token
        token = _get_access_token()
        if not token: raise HTTPException(400, "Upstox not connected")
        trades = await UpstoxParser(token).fetch_trades(req.from_date, req.to_date)
    else:
        raise HTTPException(400, f"Unsupported broker: {req.broker}")

    inserted = await _upsert_trades(pool, trades)
    for dt in {t.trade_date for t in trades}:
        await _recompute_day(pool, dt)
    return {"imported": len(trades), "inserted": inserted}


# ── Queries ───────────────────────────────────────────────────────────────────

@router.get("/trades")
async def list_trades(
    from_date: str | None = None, to_date: str | None = None,
    broker: str | None = None, symbol: str | None = None,
    status: str | None = None, pool=Depends(get_pool),
):
    conds, args = ["1=1"], []
    for col, val in [("trade_date >=", from_date), ("trade_date <=", to_date),
                     ("broker", broker), ("status", status)]:
        if val:
            args.append(val); conds.append(f"{col.split()[0]} {col.split()[-1] if '>=' in col or '<=' in col else '='} ${len(args)}")
    if symbol:
        args.append(f"%{symbol}%"); conds.append(f"symbol ILIKE ${len(args)}")
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM jrn_trades WHERE {' AND '.join(conds)} "
            f"ORDER BY trade_date DESC, trade_time DESC LIMIT 1000", *args)
    return [dict(r) for r in rows]


@router.get("/pairs")
async def list_pairs(
    from_date: str | None = None, to_date: str | None = None,
    symbol: str | None = None, pool=Depends(get_pool),
):
    conds, args = ["1=1"], []
    if from_date: args.append(from_date); conds.append(f"open_date >= ${len(args)}")
    if to_date:   args.append(to_date);   conds.append(f"open_date <= ${len(args)}")
    if symbol:    args.append(f"%{symbol}%"); conds.append(f"symbol ILIKE ${len(args)}")
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM jrn_trade_pairs WHERE {' AND '.join(conds)} "
            f"ORDER BY open_date DESC, open_time DESC LIMIT 500", *args)
    return [dict(r) for r in rows]


@router.get("/summary")
async def list_summaries(
    from_date: str | None = None, to_date: str | None = None,
    pool=Depends(get_pool),
):
    conds, args = ["1=1"], []
    if from_date: args.append(from_date); conds.append(f"trade_date >= ${len(args)}")
    if to_date:   args.append(to_date);   conds.append(f"trade_date <= ${len(args)}")
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            f"SELECT * FROM jrn_day_summary WHERE {' AND '.join(conds)} "
            f"ORDER BY trade_date DESC", *args)
    return [dict(r) for r in rows]


@router.post("/recompute")
async def recompute(trade_date: str, pool=Depends(get_pool)):
    """Recompute pairs + summary for a date from raw trades."""
    await _recompute_day(pool, date.fromisoformat(trade_date))
    return {"recomputed": trade_date}


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _upsert_trades(pool, trades) -> int:
    inserted = 0
    async with pool.acquire() as conn:
        for t in trades:
            try:
                await conn.execute("""
                    INSERT INTO jrn_trades
                    (broker,source,source_file,contract_note_no,is_revised,
                     order_no,order_time,trade_id,trade_date,trade_time,
                     symbol,raw_symbol,underlying,strike,option_type,expiry,
                     instrument,exchange,segment,trade_type,quantity,
                     lot_size,lots,price,brokerage,status,remark,is_force_squared)
                    VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,
                            $15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25,$26,$27,$28)
                    ON CONFLICT (broker, trade_id) DO NOTHING
                """,
                t.broker, t.source, t.source_file, t.contract_note_no, t.is_revised,
                t.order_no, t.order_time, t.trade_id, t.trade_date, t.trade_time,
                t.symbol, t.raw_symbol, t.underlying, t.strike, t.option_type,
                t.expiry, t.instrument, t.exchange, t.segment, t.trade_type,
                t.quantity, t.lot_size, t.lots, float(t.price), float(t.brokerage),
                t.status, t.remark, t.is_force_squared)
                inserted += 1
            except Exception as e:
                import logging; logging.getLogger(__name__).debug(f"upsert skip: {e}")
    return inserted


async def _recompute_day(pool, dt: date):
    from journal.matcher import match_all_symbols
    from journal.aggregator import build_day_summary
    from journal.models import Trade
    from decimal import Decimal

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT * FROM jrn_trades WHERE trade_date = $1 ORDER BY trade_time, id", dt)

    if not rows: return

    trades = [_row_to_trade(r) for r in rows]
    pairs  = match_all_symbols([t for t in trades if t.status == "filled"])

    async with pool.acquire() as conn:
        # Clear old pairs for this date
        await conn.execute(
            "DELETE FROM jrn_trade_pairs WHERE open_date = $1 OR close_date = $1", dt)
        for p in pairs:
            await conn.execute("""
                INSERT INTO jrn_trade_pairs
                (symbol,underlying,strike,option_type,expiry,exchange,segment,
                 side,quantity,lots,lot_size,open_date,open_time,entry_price,
                 entry_trade_ids,close_date,close_time,exit_price,exit_trade_ids,
                 gross_pnl,charges,net_pnl,hold_seconds,is_intraday,force_squared)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,
                        $16,$17,$18,$19,$20,$21,$22,$23,$24,$25)
            """,
            p.symbol, p.underlying, p.strike, p.option_type, p.expiry,
            p.exchange, p.segment, p.side, p.quantity, p.lots, p.lot_size,
            p.open_date, p.open_time, float(p.entry_price),
            p.entry_trade_ids,
            p.close_date, p.close_time,
            float(p.exit_price) if p.exit_price else None,
            p.exit_trade_ids,
            float(p.gross_pnl) if p.gross_pnl else None,
            json.dumps(p.charges.to_dict()) if p.charges else None,
            float(p.net_pnl) if p.net_pnl else None,
            p.hold_seconds, p.is_intraday, p.force_squared)

        # Upsert day summary
        summary = build_day_summary(trades, pairs)
        await conn.execute("""
            INSERT INTO jrn_day_summary
            (trade_date,total_fills,total_orders,total_lots,failed_order_count,
             force_squared_count,first_trade_time,last_trade_time,avg_hold_seconds,
             time_bucket_pnl,gross_pnl,total_brokerage,total_charges,net_pnl,
             win_pairs,loss_pairs,open_pairs)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
            ON CONFLICT (trade_date, COALESCE(broker,'')) DO UPDATE SET
            total_fills=EXCLUDED.total_fills, net_pnl=EXCLUDED.net_pnl,
            win_pairs=EXCLUDED.win_pairs, loss_pairs=EXCLUDED.loss_pairs,
            force_squared_count=EXCLUDED.force_squared_count,
            time_bucket_pnl=EXCLUDED.time_bucket_pnl,
            avg_hold_seconds=EXCLUDED.avg_hold_seconds
        """,
        summary.trade_date, summary.total_fills, summary.total_orders,
        summary.total_lots, summary.failed_order_count, summary.force_squared_count,
        summary.first_trade_time, summary.last_trade_time, summary.avg_hold_seconds,
        json.dumps(summary.time_bucket_pnl),
        float(summary.gross_pnl), float(summary.total_brokerage),
        float(summary.total_charges), float(summary.net_pnl),
        summary.win_pairs, summary.loss_pairs, summary.open_pairs)


def _row_to_trade(r) -> "Trade":
    from journal.models import Trade
    return Trade(
        id=r["id"], broker=r["broker"], source=r["source"],
        source_file=r["source_file"], contract_note_no=r["contract_note_no"],
        order_no=r["order_no"], order_time=r["order_time"],
        trade_id=r["trade_id"], trade_date=r["trade_date"], trade_time=r["trade_time"],
        symbol=r["symbol"], raw_symbol=r["raw_symbol"], underlying=r["underlying"],
        exchange=r["exchange"], segment=r["segment"],
        trade_type=r["trade_type"], quantity=r["quantity"],
        lot_size=r["lot_size"], lots=r["lots"],
        strike=r["strike"], option_type=r["option_type"], expiry=r["expiry"],
        instrument=r["instrument"],
        price=Decimal(str(r["price"])), brokerage=Decimal(str(r["brokerage"])),
        status=r["status"] or "filled", remark=r["remark"],
        is_force_squared=r["is_force_squared"] or False,
    )
```

Wire into `main.py`:
```python
from journal.db import init_journal_tables, seed_default_rules
from api.routers.journal import router as journal_router

# In startup:
await init_journal_tables(pool)
await seed_default_rules(pool)
app.include_router(journal_router, prefix="/journal")
```

---

## Task 9 — Frontend (Phase 1 only)

Minimal — import + view. No analysis UI yet.

**Store:** `frontend/src/store/journal.ts` — trades[], pairs[], summaries[], loading, error
**Page:** `frontend/src/pages/Journal/JournalPage.tsx`
**Components:**
- `ImportPanel.tsx` — PDF upload (drag-drop + file picker) + API import (broker/dates)
- `DaySummaryCard.tsx` — cards: fills, lots, gross P&L, charges, net P&L, force-squared count, avg hold
- `PairsTable.tsx` — symbol | side | lots | entry | exit | hold (seconds) | gross | charges | net | ⚠ force-sq
- `TradeTable.tsx` — collapsible, raw fills with timestamps
- `TimelineBuckets.tsx` — bar chart of time_bucket_pnl (30-min windows)

**Route:** `/journal` — add to sidebar nav

---

## What's deferred to Phase 2

- Rule engine evaluation + violation display
- LLM streaming analysis (Claude)
- Chart snapshots at entry/exit (TV MCP integration)
- Per-trade rationale / mistakes annotation
- Session-level analysis prompt
- Kite/Upstox API parsers (can import via PDF for now)
- mStock API parser

---

## Dependencies

```bash
# backend  (pdfplumber for table extraction; NOT markitdown — see G1. No anthropic in Phase 1.)
pip install pdfplumber

# frontend — no new deps (zustand + axios already present)
```

---

## Broker API Capabilities + Auth (researched 2026-06-04)

### Summary table

| Broker | Historical API | Today API | Auth type | Credentials needed |
|--------|---------------|-----------|-----------|-------------------|
| Kite (Zerodha) | ❌ TODAY ONLY | ✅ `/trades` | OAuth-like (login URL + token exchange) | `api_key` + `api_secret` |
| Upstox | ✅ last 3 years | ✅ `/v2/order/trades/get-trades-for-day` | OAuth2 (auth code flow) | `client_id` + `client_secret` + `redirect_uri` |
| mStock | ❌ TODAY ONLY | ✅ `/openapi/typeb/tradebook` | api_key + username/password + OTP → JWT | `api_key` from trade.mstock.com + credentials |
| Lemonn | ❌ No public API | ❌ No public API | N/A | PDF only |

**Implication**: Historical trade import for Kite, mStock, Lemonn → PDF contract notes only. Upstox → API covers history.

---

### Kite (Zerodha) — API details

**Auth flow:**
```
1. Redirect user to:
   https://kite.zerodha.com/connect/login?v=3&api_key={api_key}

2. User logs in → Zerodha redirects to your redirect_url with ?request_token=xxx

3. POST /session/token:
   {api_key, request_token, checksum: SHA256(api_key + request_token + api_secret)}
   → returns {access_token}

4. All requests: Authorization: "token {api_key}:{access_token}"
   access_token valid 1 day (till midnight IST)
```

**Trade endpoints:**
```
GET /trades                → today's trades only
  Response fields: trade_id, order_id, tradingsymbol, exchange, segment,
                   transaction_type, quantity, average_price, trade_date (date+time)

GET /orders/{order_id}/trades  → trades for specific order
```

**Credentials user must provide:** `api_key`, `api_secret` (from Kite Connect developer console at developers.kite.trade)

---

### Upstox — API details

**Auth flow (already implemented in codebase):**
```
1. Redirect user to:
   https://api.upstox.com/v2/login/authorization/dialog
   ?response_type=code&client_id={api_key}&redirect_uri={redirect_uri}

2. User logs in → redirect to redirect_uri?code=xxx

3. POST https://api.upstox.com/v2/login/authorization/token:
   {code, client_id, client_secret, redirect_uri, grant_type: "authorization_code"}
   → returns {access_token}

4. All requests: Authorization: "Bearer {access_token}"
   access_token valid till 3:30 AM next day
```

**Trade endpoints:**
```
# Today's trades
GET https://api.upstox.com/v2/order/trades/get-trades-for-day
  Response fields: trade_id, order_id, tradingsymbol, exchange, segment,
                   transaction_type, quantity, average_price, trade_date, order_execution_time

# Historical trades (last 3 financial years)
GET https://api.upstox.com/v2/charges/historical-trades
  Params: segment (EQ|FO|MF), start_date (YYYY-MM-DD), end_date (YYYY-MM-DD),
          page_number, page_size
  Response: paginated list of trades with same fields + trade_time
```

**Credentials user must provide:** `api_key` (client_id), `api_secret` (client_secret), `redirect_uri`

---

### mStock — API details

**Auth flow:**
```
Type B (partner flow — simpler for our use):
1. User logs in at trade.mstock.com → gets JWT_TOKEN + ENCRYPTED_API_KEY
   (or via API: POST /openapi/typeb/user/login with username+password → OTP → JWT)

2. All requests:
   X-Mirae-Version: 1
   Authorization: Bearer {jwt_token}
   X-PrivateKey: {api_key}
   JWT valid till midnight.

Type A (simpler, direct):
1. Generate api_key at trade.mstock.com
2. POST login endpoint with username+password → OTP sent to mobile
3. Confirm OTP → returns jwt_token
```

**Trade endpoints:**
```
# Today's trades only (no historical API found)
GET https://api.mstock.trade/openapi/typeb/tradebook
  Headers: X-Mirae-Version:1, Authorization: Bearer {jwt}, X-PrivateKey: {api_key}
  Response: today's trade book (same structure as contract note annexure)

GET https://api.mstock.trade/openapi/typeb/orderbook
  → all orders for today including rejected/cancelled
```

**Credentials user must provide:** `api_key` (from trade.mstock.com developer section) + username + password + mobile OTP capability

---

### Lemonn — API details

**No public developer API found.** Retail-only platform. All trade history via PDF contract notes. (Do not confuse with lemon.markets which is European.)

---

## Revised parser strategy

```
Source          | Method
----------------|------------------------------------------
Kite today      | GET /trades API → KiteParser
Kite historical | PDF contract note → zerodha.py parser (Kite uses Zerodha format)
Upstox today    | GET /v2/order/trades/get-trades-for-day → UpstoxParser
Upstox history  | GET /v2/charges/historical-trades → UpstoxParser (paginated)
mStock today    | GET tradebook API → MStockApiParser
mStock history  | PDF contract note → mstock.py parser
Lemonn (all)    | PDF contract note → lemonn.py parser
Zerodha         | PDF contract note → zerodha.py parser
```

---

## Task 10 — API Parsers

### parsers/kite.py

```python
# backend/journal/parsers/kite.py
from datetime import date, datetime, time
from decimal import Decimal
from ..models import Trade
from ..symbol_parser import parse_symbol

class KiteParser:
    """Fetches today's trades via Kite Connect API."""
    broker = "kite"

    def __init__(self, sdk):
        self._sdk = sdk  # existing core.sdk.SDK with KiteMCP tools

    async def fetch_today(self) -> list[Trade]:
        """Returns today's trades from GET /trades."""
        raw = await self._sdk.kite_get_trades()  # existing MCP tool
        return self.parse_raw(raw, date.today())

    def parse_raw(self, raw: list[dict], trade_date: date) -> list[Trade]:
        trades = []
        for r in raw:
            ps = parse_symbol(r["tradingsymbol"], broker="kite",
                              quantity=int(r["quantity"]))
            # Parse trade timestamp
            ts = r.get("order_execution_time") or r.get("fill_timestamp") or ""
            t = _parse_kite_time(ts)
            trades.append(Trade(
                broker="kite", source="api",
                order_no=r.get("order_id"),
                trade_id=r.get("trade_id"),
                trade_date=trade_date,
                trade_time=t,
                symbol=ps.symbol, raw_symbol=r["tradingsymbol"],
                underlying=ps.underlying, exchange=r.get("exchange","NSE"),
                segment=_kite_segment(r.get("segment","FO")),
                trade_type=r["transaction_type"],   # BUY|SELL
                quantity=int(r["quantity"]),
                lot_size=ps.lot_size, lots=ps.lots,
                strike=ps.strike, option_type=ps.option_type,
                expiry=ps.expiry, instrument=ps.instrument,
                price=Decimal(str(r["average_price"])),
                brokerage=Decimal("20"),             # Kite flat ₹20
                status="filled",
            ))
        return trades

def _parse_kite_time(s: str) -> time | None:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M:%S"):
        try: return datetime.strptime(s, fmt).time()
        except: pass
    return None

def _kite_segment(s: str) -> str:
    return "FO" if "FO" in s.upper() or "F&O" in s.upper() else "EQ"
```

### parsers/upstox.py

```python
# backend/journal/parsers/upstox.py
import httpx
from datetime import date, datetime, time
from decimal import Decimal
from ..models import Trade
from ..symbol_parser import parse_symbol

class UpstoxParser:
    broker = "upstox"
    _BASE = "https://api.upstox.com/v2"

    def __init__(self, access_token: str):
        self._token = access_token
        self._headers = {"Authorization": f"Bearer {access_token}",
                         "Accept": "application/json"}

    async def fetch_today(self) -> list[Trade]:
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{self._BASE}/order/trades/get-trades-for-day",
                            headers=self._headers)
            r.raise_for_status()
        return self.parse_raw(r.json().get("data", []))

    async def fetch_history(self, segment: str, start: str, end: str) -> list[Trade]:
        """Fetches paginated historical trades. segment: EQ|FO"""
        trades = []
        page = 1
        async with httpx.AsyncClient() as c:
            while True:
                r = await c.get(f"{self._BASE}/charges/historical-trades",
                                headers=self._headers,
                                params={"segment": segment, "start_date": start,
                                        "end_date": end, "page_number": page,
                                        "page_size": 50})
                r.raise_for_status()
                data = r.json().get("data", {})
                batch = data.get("trades", data.get("data", []))
                if not batch: break
                trades.extend(self.parse_raw(batch))
                page += 1
        return trades

    def parse_raw(self, raw: list[dict]) -> list[Trade]:
        trades = []
        for r in raw:
            sym = r.get("trading_symbol") or r.get("tradingsymbol","")
            ps = parse_symbol(sym, broker="upstox",
                              quantity=int(r.get("quantity",0)))
            t = _upstox_time(r.get("order_execution_time",""))
            td = _upstox_date(r.get("trade_date","")) or date.today()
            side = r.get("transaction_type","BUY").upper()
            trades.append(Trade(
                broker="upstox", source="api",
                order_no=r.get("order_id"),
                trade_id=r.get("trade_id"),
                trade_date=td, trade_time=t,
                symbol=ps.symbol, raw_symbol=sym,
                underlying=ps.underlying,
                exchange=r.get("exchange","NSE"),
                segment="FO" if r.get("segment","") in ("FO","NFO","BFO") else "EQ",
                trade_type=side,
                quantity=int(r.get("quantity",0)),
                lot_size=ps.lot_size, lots=ps.lots,
                strike=ps.strike, option_type=ps.option_type,
                expiry=ps.expiry, instrument=ps.instrument,
                price=Decimal(str(r.get("average_price") or r.get("trade_price",0))),
                brokerage=Decimal("20"),
                status="filled",
            ))
        return trades

def _upstox_time(s: str) -> time | None:
    try: return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S%z").time()
    except:
        try: return datetime.strptime(s, "%Y-%m-%d %H:%M:%S").time()
        except: return None

def _upstox_date(s: str) -> date | None:
    try: return datetime.strptime(s[:10], "%Y-%m-%d").date()
    except: return None
```

### parsers/mstock_api.py

```python
# backend/journal/parsers/mstock_api.py
import httpx
from datetime import date, datetime, time
from decimal import Decimal
from ..models import Trade
from ..symbol_parser import parse_symbol

class MStockApiParser:
    """Fetches today's trades from mStock Type B API."""
    broker = "mstock"
    _BASE = "https://api.mstock.trade/openapi/typeb"

    def __init__(self, jwt_token: str, api_key: str):
        self._headers = {
            "X-Mirae-Version": "1",
            "Authorization": f"Bearer {jwt_token}",
            "X-PrivateKey": api_key,
        }

    async def fetch_today(self) -> list[Trade]:
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{self._BASE}/tradebook", headers=self._headers)
            r.raise_for_status()
        return self.parse_raw(r.json().get("data", {}).get("tradebook", []))

    async def fetch_orders(self) -> list[Trade]:
        """Fetch all orders (includes rejected) for overtrading analysis."""
        async with httpx.AsyncClient() as c:
            r = await c.get(f"{self._BASE}/orderbook", headers=self._headers)
            r.raise_for_status()
        orders = r.json().get("data", {}).get("orderbook", [])
        trades = []
        for o in orders:
            if o.get("status","").lower() in ("rejected","cancelled"):
                ps = parse_symbol(o.get("tradingsymbol",""), broker="mstock")
                trades.append(Trade(
                    broker="mstock", source="api",
                    order_no=o.get("order_id"),
                    trade_date=date.today(),
                    symbol=ps.symbol, raw_symbol=o.get("tradingsymbol",""),
                    underlying=ps.underlying, exchange=o.get("exchange","BSE"),
                    segment="FO", trade_type=o.get("transaction_type","BUY"),
                    quantity=0, price=Decimal("5"),
                    status="rejected",
                    remark=o.get("status_message"),
                ))
        return trades

    def parse_raw(self, raw: list[dict]) -> list[Trade]:
        trades = []
        for r in raw:
            sym = r.get("tradingsymbol","")
            qty = int(r.get("quantity", 0))
            ps = parse_symbol(sym, broker="mstock", quantity=qty)
            t = _mstock_time(r.get("trade_time","") or r.get("fill_timestamp",""))
            brok = Decimal("0.25") * qty  # mStock ₹0.25/unit
            trades.append(Trade(
                broker="mstock", source="api",
                order_no=r.get("order_id"),
                trade_id=r.get("trade_id"),
                trade_date=date.today(), trade_time=t,
                symbol=ps.symbol, raw_symbol=sym,
                underlying=ps.underlying,
                exchange=r.get("exchange","BSE"), segment="FO",
                trade_type=r.get("transaction_type","BUY").upper(),
                quantity=qty, lot_size=ps.lot_size, lots=ps.lots,
                strike=ps.strike, option_type=ps.option_type,
                expiry=ps.expiry, instrument=ps.instrument,
                price=Decimal(str(r.get("average_price",0))),
                brokerage=brok, status="filled",
            ))
        return trades

def _mstock_time(s: str) -> time | None:
    for fmt in ("%H:%M:%S", "%d-%m-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try: return datetime.strptime(s, fmt).time()
        except: pass
    return None
```

---

## PDF parsing: pdfplumber (not markitdown)

```bash
pip install pdfplumber   # replaces markitdown
```

```python
# backend/journal/parsers/pdf.py — revised
import pdfplumber, tempfile
from pathlib import Path
from ..models import Trade

def _extract_tables(file_bytes: bytes) -> list[list[str]]:
    """Extract all table rows from PDF using bounding-box column detection."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(file_bytes); tmp = f.name
    rows = []
    with pdfplumber.open(tmp) as pdf:
        for page in pdf.pages:
            for table in page.extract_tables():
                rows.extend(table)
    Path(tmp).unlink(missing_ok=True)
    return rows  # list[list[str | None]]

def _extract_text(file_bytes: bytes) -> str:
    """Extract first page text for broker detection."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(file_bytes); tmp = f.name
    with pdfplumber.open(tmp) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages[:2])
    Path(tmp).unlink(missing_ok=True)
    return text

def detect_broker(text: str) -> str:
    if "Mirae Asset" in text or "mstock" in text.lower(): return "mstock"
    if "NU Investors" in text or "lemonn" in text.lower(): return "lemonn"
    if "Zerodha" in text: return "zerodha"
    if "Upstox" in text: return "upstox"
    return "pdf"

async def parse_pdf_contract_note(
    file_bytes: bytes, broker: str = "auto", source_file: str = ""
) -> list[Trade]:
    text = _extract_text(file_bytes)
    detected = broker if broker != "auto" else detect_broker(text)
    rows = _extract_tables(file_bytes)

    from . import mstock, lemonn, zerodha
    _PARSERS = {"mstock": mstock.parse, "lemonn": lemonn.parse,
                "zerodha": zerodha.parse, "pdf": zerodha.parse}
    return _PARSERS.get(detected, zerodha.parse)(rows, text=text, source_file=source_file)
```

Each broker parser receives `rows: list[list[str]]` (structured) and `text: str` (for header metadata), no regex for row extraction.

---

## Auth credentials needed from user

| Broker | What to gather | Where |
|--------|---------------|-------|
| **Kite** | `api_key`, `api_secret` | developers.kite.trade → Create App |
| **Upstox** | `client_id` (API Key), `client_secret`, `redirect_uri` | upstox.com/developer → My Apps |
| **mStock** | `api_key`, username, password, OTP method (TOTP?) | trade.mstock.com → Developer/API section |
| **Lemonn** | ❌ No API — PDF only | — |

mStock auth is the most complex — requires interactive login with OTP. If TOTP/2FA is supported via authenticator app, can automate. Otherwise, manual login flow with popup (same pattern as existing Upstox/Kite in the codebase).

---

## Schema corrections — SUPERSEDED (now inlined in Task 1)

> The fixes that used to live here (`product_type`, `source_format`, partial-unique dedup
> indexes) are **already inlined into the consolidated Task 1 `jrn_trades` definition** — do not
> run them as separate ALTERs (they would fail on the now-present columns). Remaining additions
> for the other two tables, fold these columns directly into their Task 1 `CREATE TABLE`:
> - `jrn_trade_pairs`: add `product_type TEXT` — inherited from the entry trade.
>   `is_intraday = (product_type = 'MIS') OR (open_date = close_date)`.
> - `jrn_day_summary`: add `fiscal_year TEXT` — Indian FY "2026-27" (Apr–Mar), computed in
>   `build_day_summary` (see G6).

---

## Final: schema.sql is ONE consolidated file (the standard target)

Write `backend/journal/schema.sql` as a single idempotent script: the Task 1 `CREATE TABLE
IF NOT EXISTS` blocks (jrn_trades already consolidated above with `fill_grain`, `source_format`,
`product_type`, `gross_amount`, and the two partial-unique dedup indexes) **plus** `product_type`
on `jrn_trade_pairs` and `fiscal_year` on `jrn_day_summary`. No `ALTER` migrations — this is a
greenfield table set, so one clean DDL is the standard schema every broker parser normalizes into.
`init_journal_tables()` reads and executes this file in a transaction.

---

## Auth requirements — what user needs to gather

### Kite (Zerodha)
1. Go to: https://developers.kite.trade → Create an App
2. Provide: App name, redirect URL (use `http://localhost:8000/auth/kite/callback`)
3. Gets: `api_key` + `api_secret`
4. **Note**: Only today's trades via API. Historical = PDF contract notes from Console.

### Upstox
1. Go to: https://account.upstox.com/developer/apps → Create App
2. Provide: redirect URL (use `http://localhost:8000/auth/upstox/callback`)
3. Gets: `client_id` (API Key) + `client_secret`
4. **Historical**: API covers last 3 years via `GET /v2/charges/historical-trades` (paginated, segment-wise)

### mStock
1. Go to: https://trade.mstock.com → Developer/API section
2. Generate API Key
3. Gets: `api_key`
4. Also needs: username + password for OTP-based login
5. **Note**: Only today's trades via API. Historical = PDF contract notes.
6. OTP flow: either interactive (SMS) or TOTP if authenticator app is set up

### Lemonn
- ❌ No API. PDF only. No credentials needed.
