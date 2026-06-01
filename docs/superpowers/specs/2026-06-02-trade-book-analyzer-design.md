# Trade Book Analyzer — Design Spec

**Date:** 2026-06-02
**Status:** Draft
**Author:** Claude + Ankit

---

## 1. Purpose

A self-contained trade book analyzer embedded in the existing trading system as a new `/journal` route. Imports trades from broker APIs (Kite, Upstox, mStock) or PDF contract notes, pairs entries with exits, calculates P&L with full charge breakdown, evaluates rule violations automatically, and offers on-demand AI-powered deep analysis per trade.

**Portability constraint:** The journal module's business logic (matching, rules, analysis) has no coupling to dashboard/FnO/indicator code. It uses the existing infrastructure (Redis sessions, `core/sdk.py`, QuestDB) directly — isolation is at the business logic level, not the infra level. All journal DB tables are prefixed `jrn_*` for independent migration.

---

## 2. Data Sources

### 2.1 Broker APIs

| Broker | Endpoint | Scope | Auth |
|--------|----------|-------|------|
| Kite | `GET /trades` | Today only | `token api_key:access_token` via KiteMCP or REST |
| Upstox | `GET /v2/order/trades/get-trades-for-day` | Today only | Bearer token (Redis `upstox:access_token`) |
| mStock | `GET /openapi/typeb/trades?fromdate=&todate=` | Date range | Bearer JWT + API key (separate auth flow — `/auth/mstock` endpoint to be added) |

**Kite response fields:** `trade_id`, `order_id`, `exchange`, `tradingsymbol`, `instrument_token`, `product`, `average_price`, `quantity`, `transaction_type` (BUY/SELL), `fill_timestamp`, `order_timestamp`, `exchange_timestamp`.

**Upstox response fields:** `trade_id`, `order_id`, `exchange`, `trading_symbol`, `instrument_token`, `product`, `average_price`, `quantity`, `transaction_type`, `exchange_timestamp`, `order_type`, `exchange_order_id`.

**mStock response fields:** `fillid`, `orderid`, `exchange`, `tradingsymbol`, `instrumenttype`, `strikeprice`, `optiontype`, `expirydate`, `fillprice`, `fillsize`, `transactiontype`, `filltime`, `producttype`.

### 2.2 PDF Contract Note

Indian broker contract notes follow a SEBI-prescribed format. Key sections:

**Annexure A (trade detail rows):**
- Order No, Order Time, Trade No, Trade Time
- Security/Contract description
- Buy(B)/Sell(S), Exchange, Quantity
- Gross Rate / Trade Price per unit
- Brokerage per unit, Net Rate per unit
- Net total (before levies)

**Page 3 (charges):**
- Brokerage, GST (CGST+SGST or IGST), STT, Stamp duty, SEBI turnover fee, Exchange transaction charges

**Revised format (Feb 2025):** Consolidates all trades in a security across exchanges into a single row with Weighted Average Price (WAP). Parser must handle both old (per-trade rows) and new (WAP consolidated) formats.

**Parsing pipeline:**
1. Upload PDF → `microsoft/markitdown` converts to Markdown
2. Regex pass extracts Annexure A table rows + charges
3. If regex fails → Claude API fallback with structured extraction prompt → JSON
4. Preview parsed rows in frontend for user confirmation before storing

---

## 3. Data Model (PostgreSQL)

### 3.1 `jrn_trades` — Raw Fills

```sql
CREATE TABLE jrn_trades (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    broker          VARCHAR(16) NOT NULL,  -- kite | upstox | mstock | pdf
    trade_date      DATE NOT NULL,
    fill_timestamp  TIMESTAMPTZ NOT NULL,
    exchange        VARCHAR(10) NOT NULL,  -- NSE | BSE | NFO | BFO | MCX
    tradingsymbol   VARCHAR(100) NOT NULL,
    instrument_token VARCHAR(50),
    transaction_type VARCHAR(4) NOT NULL,  -- BUY | SELL
    quantity        INT NOT NULL,
    price           DECIMAL(12,4) NOT NULL,
    product         VARCHAR(10),           -- MIS | CNC | NRML
    order_id        VARCHAR(50),
    trade_id        VARCHAR(50),
    raw_data        JSONB,                 -- original broker response
    import_batch_id UUID NOT NULL,         -- groups trades from same import
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(broker, trade_id, trade_date)
);

CREATE INDEX idx_jrn_trades_date ON jrn_trades(trade_date);
CREATE INDEX idx_jrn_trades_symbol ON jrn_trades(tradingsymbol);
```

### 3.2 `jrn_trade_pairs` — Matched Entry+Exit

```sql
CREATE TABLE jrn_trade_pairs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trade_date      DATE NOT NULL,
    broker          VARCHAR(16) NOT NULL,
    exchange        VARCHAR(10) NOT NULL,
    tradingsymbol   VARCHAR(100) NOT NULL,
    underlying      VARCHAR(30) NOT NULL,  -- NIFTY | BANKNIFTY | SENSEX | HDFCBANK
    instrument_desc VARCHAR(100),          -- "NIFTY 24100 CE 02-Jun-2026"
    instrument_type VARCHAR(10),           -- EQ | FUT | CE | PE
    strike_price    DECIMAL(10,2),
    expiry_date     DATE,
    side            VARCHAR(5) NOT NULL,   -- LONG | SHORT
    quantity        INT NOT NULL,
    entry_price     DECIMAL(12,4) NOT NULL,
    exit_price      DECIMAL(12,4),
    entry_time      TIMESTAMPTZ NOT NULL,
    exit_time       TIMESTAMPTZ,
    duration_min    INT,
    product         VARCHAR(10),
    -- P&L
    gross_pnl       DECIMAL(12,2),
    brokerage       DECIMAL(10,2) DEFAULT 0,
    stt             DECIMAL(10,2) DEFAULT 0,
    stamp_duty      DECIMAL(10,2) DEFAULT 0,
    exchange_txn    DECIMAL(10,2) DEFAULT 0,
    sebi_fee        DECIMAL(10,2) DEFAULT 0,
    gst             DECIMAL(10,2) DEFAULT 0,
    net_pnl         DECIMAL(12,2),
    -- status
    status          VARCHAR(10) DEFAULT 'closed', -- closed | open
    -- links
    entry_trade_ids UUID[] NOT NULL,       -- refs to jrn_trades
    exit_trade_ids  UUID[],
    import_batch_id UUID NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_jrn_pairs_date ON jrn_trade_pairs(trade_date);
CREATE INDEX idx_jrn_pairs_underlying ON jrn_trade_pairs(underlying);
```

### 3.3 `jrn_day_summary` — Daily Aggregates

```sql
CREATE TABLE jrn_day_summary (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trade_date      DATE UNIQUE NOT NULL,
    total_trades    INT NOT NULL,
    winners         INT NOT NULL,
    losers          INT NOT NULL,
    breakeven       INT NOT NULL,
    win_rate        DECIMAL(5,2),
    avg_winner      DECIMAL(12,2),
    avg_loser       DECIMAL(12,2),
    expectancy      DECIMAL(12,2),
    biggest_winner  DECIMAL(12,2),
    biggest_loser   DECIMAL(12,2),
    gross_pnl       DECIMAL(12,2),
    total_charges   DECIMAL(12,2),
    net_pnl         DECIMAL(12,2),
    max_consec_wins INT,
    max_consec_losses INT,
    first_trade_time TIMESTAMPTZ,
    last_trade_time  TIMESTAMPTZ,
    violations      JSONB DEFAULT '[]',    -- day-level rule violations
    created_at      TIMESTAMPTZ DEFAULT now()
);
```

### 3.4 `jrn_rules` — Rulebook

```sql
CREATE TABLE jrn_rules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(100) NOT NULL,
    description     TEXT,
    category        VARCHAR(20) NOT NULL,  -- discipline | risk | timing | sizing
    rule_type       VARCHAR(20) NOT NULL,  -- threshold | pattern | time
    is_default      BOOLEAN DEFAULT false,
    is_active       BOOLEAN DEFAULT true,
    params          JSONB NOT NULL,        -- {"max_trades": 3, "sl_buffer_pct": 0.5}
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);
```

### 3.5 `jrn_analyses` — LLM Analysis Cache

```sql
CREATE TABLE jrn_analyses (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trade_pair_id   UUID NOT NULL REFERENCES jrn_trade_pairs(id),
    analysis_text   TEXT NOT NULL,
    model           VARCHAR(50) NOT NULL,  -- claude-sonnet-4-6
    context_summary JSONB,                 -- what was sent to LLM
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(trade_pair_id)
);
```

---

## 4. Backend Architecture

### 4.1 Module Structure

```
backend/journal/
    __init__.py
    config.py              # journal-specific config (charge rates, default rules)
    models.py              # SQLAlchemy/Pydantic models for all jrn_* tables
    parsers/
        __init__.py
        base.py            # NormalizedFill dataclass, BrokerParser protocol
        kite.py            # parse_kite_trades(token) → list[NormalizedFill]
        upstox.py          # parse_upstox_trades(token) → list[NormalizedFill]
        mstock.py          # parse_mstock_trades(token, from_date, to_date) → list[NormalizedFill]
        pdf.py             # parse_pdf(file_bytes) → list[NormalizedFill]
    matcher.py             # FIFO match fills → TradePair list
    charges.py             # calculate brokerage, STT, stamp, exchange, SEBI, GST
    symbol_parser.py       # "NIFTY24100CE" → {underlying, strike, type, expiry}
    rules.py               # RuleEngine: evaluate trade pairs against rules
    analyzer.py            # Claude API streaming analysis
    seed_rules.py          # default rule definitions

backend/api/routers/
    journal.py             # all /journal/* endpoints
```

### 4.2 Core Data Types

```python
@dataclass
class NormalizedFill:
    broker: str                # kite | upstox | mstock | pdf
    trade_date: date
    fill_timestamp: datetime
    exchange: str
    tradingsymbol: str
    instrument_token: str | None
    transaction_type: str      # BUY | SELL
    quantity: int
    price: Decimal
    product: str | None
    order_id: str | None
    trade_id: str | None
    raw_data: dict

@dataclass
class ParsedInstrument:
    underlying: str            # NIFTY | BANKNIFTY | SENSEX | HDFCBANK
    instrument_type: str       # EQ | FUT | CE | PE
    strike_price: Decimal | None
    expiry_date: date | None
    display_name: str          # "NIFTY 24100 CE 02-Jun-2026"
```

### 4.3 Symbol Parser Logic

```
Input: "NIFTY24100CE"  →  underlying=NIFTY, strike=24100, type=CE
Input: "BANKNIFTY55000PE25JUN"  →  underlying=BANKNIFTY, strike=55000, type=PE, expiry=2025-06-xx
Input: "HDFCBANK"  →  underlying=HDFCBANK, type=EQ
Input: "NIFTY25JUNFUT"  →  underlying=NIFTY, type=FUT, expiry=2025-06-xx
Input: "SENSEX78000CE25606"  →  underlying=SENSEX, strike=78000, type=CE
```

Regex-based parser with known underlying prefixes: `NIFTY`, `BANKNIFTY`, `FINNIFTY`, `MIDCPNIFTY`, `SENSEX`, `BANKEX`. Anything not matching known F&O patterns → equity.

### 4.4 FIFO Matching Engine (`matcher.py`)

```
Input: list[NormalizedFill] for a single tradingsymbol, sorted by fill_timestamp

Algorithm:
  1. Separate BUY and SELL fills, sorted by time
  2. FIFO match: first buy pairs with first sell (or vice versa for short)
  3. Handle partial fills: if buy qty=100, sell qty=60 → pair 60, remainder 40 stays in queue
  4. Unpaired remainder → status="open" (position still held)

Output: list[TradePair]
  - side: LONG if first fill is BUY, SHORT if SELL
  - entry_price: volume-weighted avg of entry fills
  - exit_price: volume-weighted avg of exit fills
  - quantity: matched quantity
  - duration_min: (exit_time - entry_time).minutes
```

### 4.5 Charge Calculation (`charges.py`)

Indian market charges (all rates configurable in `config.py` — SEBI revises periodically):

| Charge | Equity Intraday | Equity Delivery | F&O |
|--------|----------------|-----------------|-----|
| Brokerage | ₹20/order or 0.03% | ₹20/order or 0.03% | ₹20/order |
| STT | 0.025% sell side | 0.1% both sides | 0.0125% sell (options), 0.02% both (futures) |
| Exchange txn | 0.00345% | 0.00345% | 0.05% (options), 0.002% (futures) |
| SEBI fee | 0.0001% | 0.0001% | 0.0001% |
| Stamp duty | 0.003% buy side | 0.015% buy side | 0.003% buy side |
| GST | 18% on (brokerage + exchange txn + SEBI) | same | same |

For PDF imports: charges come from the contract note directly (already broken down). For API imports: calculate from rates above.

### 4.6 Charge Override for PDF

When importing from PDF, the contract note contains actual charges. These override the calculated values:

```python
def apply_contract_note_charges(pair: TradePair, charges: dict):
    """Override calculated charges with actual contract note values."""
    pair.brokerage = charges.get("brokerage", pair.brokerage)
    pair.stt = charges.get("stt", pair.stt)
    # ... etc
```

---

## 5. Rule Engine

### 5.1 Default Rules (Shipped)

| # | Rule | Category | Type | Default Params | Evaluation |
|---|------|----------|------|----------------|------------|
| 1 | SL Not Respected | discipline | threshold | `sl_buffer_pct: 2.0` | Exit price worse than entry ± buffer% in losing direction |
| 2 | Overtrading | discipline | threshold | `max_trades_per_day: 5` | Count of trade pairs for the day > threshold |
| 3 | Revenge Trade | discipline | pattern | `cooldown_min: 5` | New entry within N minutes of a losing exit |
| 4 | Averaging Down | risk | pattern | — | Same symbol, same direction, new entry after adverse move since first entry |
| 5 | Early Entry | timing | pattern | — | Evaluated by LLM during on-demand analysis (requires knowing trader's reference timeframe) |
| 6 | Late Exit / Gave Back Profits | timing | pattern | `profit_giveback_pct: 50` | Peak unrealized P&L from 1min candles (if available in QuestDB); skipped gracefully if no granular data |
| 7 | Max Daily Loss Breached | risk | threshold | `max_daily_loss: 5000` | Day's net P&L exceeds negative threshold |
| 8 | Outside Session Hours | timing | time | `session_start: "09:15", session_end: "15:30"` | Trade entry outside defined hours |

### 5.2 Rule Evaluation Flow

```python
class RuleEngine:
    def evaluate(self, pairs: list[TradePair], rules: list[Rule]) -> dict[UUID, list[Violation]]:
        """Returns violations keyed by trade_pair_id."""
        # Day-level rules (overtrading, max loss) run once across all pairs
        # Trade-level rules (SL, revenge, timing) run per pair
        # Rules needing candle data (late exit, early entry) fetch from QuestDB on demand
```

### 5.3 Custom Rule Schema

Users create rules via the UI with:

```json
{
    "name": "Max 3 trades before lunch",
    "category": "discipline",
    "rule_type": "threshold",
    "params": {
        "max_trades": 3,
        "time_window_start": "09:15",
        "time_window_end": "12:00"
    }
}
```

The rule engine supports these param types:
- `threshold` — compare a numeric value against a limit
- `pattern` — detect a sequence (revenge, averaging)
- `time` — time-window constraints

Custom rules with logic beyond threshold/pattern/time are evaluated by the LLM during on-demand analysis (not the rule engine).

---

## 6. LLM Analysis

### 6.1 System Prompt Structure

```
You are a trading coach analyzing an intraday trade on the Indian markets.

TRADE DATA:
{trade_pair JSON: instrument, underlying, side, qty, entry/exit price+time, duration, P&L}

CANDLE DATA (5min, ±1hr around trade):
{OHLCV rows for the traded instrument}

UNDERLYING INDEX (5min, same window):
{OHLCV rows for NIFTY/BANKNIFTY/SENSEX}

RULE VIOLATIONS DETECTED:
{list of violations already flagged by rule engine}

TRADER'S RULEBOOK:
{all active rules with descriptions}

ALL TRADES TODAY:
{summary of other trades taken — for context on overtrading, tilt, etc.}

INSTRUCTIONS:
1. Evaluate entry timing: Was the entry at a good level? Too early? Too late? Did the trader wait for confirmation?
2. Evaluate exit timing: Did the trader exit at an appropriate level? Too early (left money on table)? Too late (gave back profits)?
3. SL discipline: Was a stop loss respected? What would an appropriate SL have been?
4. Position sizing: Was the quantity appropriate relative to other trades?
5. Market context: What was the underlying doing? Was this a with-trend or counter-trend trade?
6. Rule adherence: Comment on each violation detected.
7. What could be improved: Specific, actionable suggestions with reference to price levels and candle patterns.

Be direct. Reference specific prices and times. No generic advice.
```

### 6.2 Streaming

- Endpoint: `POST /journal/analyze/{trade_pair_id}`
- Response: SSE stream (`text/event-stream`)
- Frontend: `EventSource` reading chunks into `AnalysisPanel`
- Model: `claude-sonnet-4-6` (cost-effective for analysis; user can override)
- Cache: stored in `jrn_analyses` after complete; re-analyze clears cache

### 6.3 Day-Level Analysis (Future Extension)

Not in v1 scope, but designed for: analyze all trades for a day as a batch. System prompt includes all trade pairs + full day's candle data. Produces daily review report.

---

## 7. PDF Import Pipeline

### 7.1 Flow

```
PDF bytes → MarkItDown → Markdown text
    ↓
Regex parser (primary):
    - Find "Annexure" section
    - Extract table rows: Order No, Trade No, Time, Symbol, B/S, Qty, Price
    - Find charges section: Brokerage, STT, Stamp, Exchange, SEBI, GST
    ↓
If regex confidence < 80% (too few rows extracted vs expected):
    - Send full markdown to Claude API
    - Structured extraction prompt → JSON array of fills + charges
    ↓
Return: list[NormalizedFill] + charges dict
    ↓
Frontend preview: show parsed rows in table
    - User reviews, can edit/delete misparses
    - "Confirm Import" button
    ↓
Store in jrn_trades → match → pair → persist
```

### 7.2 Contract Note Format Handling

**Pre-Feb 2025 format:** Individual trade rows with per-trade price.
**Post-Feb 2025 format:** Consolidated rows with WAP per security across exchanges.

Parser detects format by checking for WAP column header. WAP format trades are stored as single fills (since individual trade-level detail is lost in consolidation).

### 7.3 MarkItDown Integration

```python
from markitdown import MarkItDown

md = MarkItDown()
result = md.convert(pdf_path)
markdown_text = result.text_content
```

Dependency: `pip install markitdown[all]` (includes PDF support via `pdfminer`).

---

## 8. API Endpoints

### 8.1 Trade Import & Retrieval

```
POST /journal/import/broker
  Body: { "broker": "kite" | "upstox" | "mstock", "from_date"?: "YYYY-MM-DD", "to_date"?: "YYYY-MM-DD" }
  - kite/upstox: ignore date params (today only)
  - mstock: date range supported
  Auth: reads broker token from Redis session (same as existing app)
  Response: { "import_batch_id": UUID, "trades_imported": int, "pairs_matched": int }

POST /journal/import/pdf
  Body: multipart/form-data with PDF file
  Response: { "preview": list[NormalizedFill], "charges": dict }
  - Does NOT persist yet — returns preview for user confirmation

POST /journal/import/pdf/confirm
  Body: { "fills": list[NormalizedFill], "charges": dict }
  - Persists after user confirms preview
  Response: { "import_batch_id": UUID, "trades_imported": int, "pairs_matched": int }

GET /journal/trades?date=YYYY-MM-DD&broker=all|kite|upstox|mstock|pdf
  Response: {
    "pairs": list[TradePair with violations[]],
    "summary": DaySummary
  }
  - Runs rule engine on return (lightweight, cached per request)
```

### 8.2 Analysis

```
POST /journal/analyze/{trade_pair_id}
  Response: SSE text/event-stream
  - Streams Claude analysis
  - Saves to jrn_analyses on completion

POST /journal/analyze/{trade_pair_id}/refresh
  - Clears cached analysis, re-runs
```

### 8.3 Rules

```
GET /journal/rules
  Response: list[Rule] (default + custom, active + inactive)

POST /journal/rules
  Body: { "name", "description", "category", "rule_type", "params" }
  Response: Rule

PUT /journal/rules/{id}
  Body: partial Rule fields
  Response: Rule

DELETE /journal/rules/{id}
  - Cannot delete default rules (toggle inactive instead)
```

### 8.4 Summary

```
GET /journal/summary?date=YYYY-MM-DD
  Response: DaySummary

GET /journal/summary/range?from=YYYY-MM-DD&to=YYYY-MM-DD
  Response: list[DaySummary]
  - For multi-day performance views
```

---

## 9. Frontend Architecture

### 9.1 Component Tree

```
pages/Journal/
    JournalPage.tsx          — route component, layout shell

components/Journal/
    JournalTopBar.tsx        — date picker, broker selector, import/refresh buttons, PDF upload
    DaySummaryBar.tsx        — stats cards: total trades, win rate, net P&L, biggest W/L
    TradeTable.tsx           — sortable table of TradePairs, violation badges per row
    TradeDetailDrawer.tsx    — slide-out panel on row click
    TradeChart.tsx           — wraps ChartUnit with entry/exit markers overlay
    PnlBreakdown.tsx         — gross → charges → net P&L breakdown card
    ViolationBadges.tsx      — colored badges for rule violations
    AnalysisPanel.tsx        — streaming AI analysis display + trigger button
    PdfUploadModal.tsx       — drag-drop, preview parsed rows, confirm/edit
    RuleBookPanel.tsx        — list/add/edit/toggle rules (accessible from sidebar or TopBar)
```

### 9.2 State Management

```typescript
// store/journal.ts (Zustand)
interface JournalStore {
    selectedDate: string;          // YYYY-MM-DD
    selectedBroker: string;        // all | kite | upstox | mstock | pdf
    tradePairs: TradePair[];
    daySummary: DaySummary | null;
    selectedPairId: string | null; // opens drawer
    isImporting: boolean;
    rules: Rule[];

    setDate(date: string): void;
    setBroker(broker: string): void;
    fetchTrades(): Promise<void>;
    importFromBroker(broker: string): Promise<void>;
    selectPair(id: string | null): void;
    fetchRules(): Promise<void>;
}
```

### 9.3 TradeTable Columns

| Column | Source | Sortable |
|--------|--------|----------|
| Time | `entry_time` (HH:MM) | Yes |
| Underlying | `underlying` | Yes |
| Instrument | `instrument_desc` | No |
| Side | `side` (LONG/SHORT) | Yes |
| Qty | `quantity` | Yes |
| Entry | `entry_price` | No |
| Exit | `exit_price` | No |
| Duration | `duration_min` | Yes |
| Gross P&L | `gross_pnl` | Yes |
| Charges | sum of all charges | Yes |
| Net P&L | `net_pnl` (color-coded green/red) | Yes |
| Violations | badge count | Yes |

### 9.4 TradeDetailDrawer Layout

```
┌─────────────────────────────────────────┐
│  NIFTY 24100 CE · 02 Jun 2026 · LONG   │  ← header
├─────────────────────────────────────────┤
│                                         │
│  [ChartUnit: 5min, ±30min window]       │  ← entry/exit markers on chart
│  Green ▲ at entry, Red ▼ at exit        │
│                                         │
├─────────────────────────────────────────┤
│  Entry: ₹245.50 @ 10:14                │
│  Exit:  ₹261.00 @ 10:48                │
│  Duration: 34 min                       │
│  Qty: 75 (1 lot)                        │
├─────────────────────────────────────────┤
│  P&L Breakdown:                         │
│    Gross P&L     ₹1,162.50             │
│    Brokerage     -₹40.00               │
│    STT           -₹14.53               │
│    Stamp Duty    -₹5.52                │
│    Exchange Txn  -₹9.78                │
│    SEBI Fee      -₹0.20                │
│    GST           -₹9.00                │
│    ─────────────────────                │
│    Net P&L       ₹1,083.47             │
├─────────────────────────────────────────┤
│  Rule Violations:                       │
│    ⚠ Overtraded (6 trades today)       │
│    ✓ SL Respected                      │
│    ✓ No revenge trade                  │
├─────────────────────────────────────────┤
│  [🔍 Analyze with AI]                  │
│                                         │
│  (streaming analysis text appears here) │
└─────────────────────────────────────────┘
```

### 9.5 PDF Upload Flow

```
┌──────────────────────────────┐
│  Drop contract note PDF here │  ← drag-drop zone
│  or click to browse          │
└──────────────────────────────┘
        ↓ (upload)
┌──────────────────────────────┐
│  Parsing...                  │  ← spinner
└──────────────────────────────┘
        ↓
┌──────────────────────────────┐
│  Parsed 12 trades            │
│  ┌────────────────────────┐  │
│  │ Symbol │ B/S │ Qty │ $ │  │  ← editable preview table
│  │ NIFTY..│ BUY │ 75  │...│  │
│  │ ...    │     │     │   │  │
│  └────────────────────────┘  │
│  Charges: Brok ₹200 STT ₹x  │
│                              │
│  [Cancel]  [Confirm Import]  │
└──────────────────────────────┘
```

---

## 10. Sidebar Integration

New nav item in existing `Sidebar.tsx`:

```
📊 Dashboard
📈 FnO Live
📓 Trade Book    ← NEW
```

Route: `/journal` → `JournalPage.tsx`

---

## 11. Chart Entry/Exit Markers

`TradeChart.tsx` wraps `ChartUnit` and overlays markers using lightweight-charts markers API:

```typescript
const markers = [
    {
        time: entryTime,
        position: 'belowBar',
        color: '#22c55e',
        shape: 'arrowUp',
        text: `Entry ₹${entryPrice}`,
    },
    {
        time: exitTime,
        position: 'aboveBar',
        color: '#ef4444',
        shape: 'arrowDown',
        text: `Exit ₹${exitPrice}`,
    },
];
candlestickSeries.setMarkers(markers);
```

---

## 12. Dependencies

### Backend (new)
- `markitdown[all]` — PDF to Markdown conversion
- `anthropic` — Claude API for analysis (likely already installed)

### Frontend (new)
- No new deps — uses existing lightweight-charts, Zustand, React

---

## 13. Error Handling

| Scenario | Handling |
|----------|----------|
| Broker token expired | Return 401, frontend shows "Re-authenticate" link (same flow as dashboard) |
| PDF parse fails completely | Return parsed rows=0 with raw markdown, let user copy-paste manually |
| Claude API fails/timeout | Return error, keep [Analyze] button available for retry |
| Duplicate import (same trade_id+date) | Upsert — skip existing, add new fills only |
| No candle data in QuestDB for instrument | Show trade detail without chart, message "Chart data unavailable" |
| mStock API down | Return error with last successful import date |

---

## 14. Scope Boundaries

### In scope (v1)
- Kite, Upstox, mStock trade import (API)
- PDF contract note import (MarkItDown + regex + LLM fallback)
- FIFO trade pairing with partial fill support
- Full charge calculation (Indian market rates)
- 8 default rules + custom rule CRUD
- Per-trade AI analysis (streaming)
- Trade table + detail drawer with chart + P&L + violations
- Day summary aggregates
- Date range summary endpoint (for future multi-day views)

### Out of scope (v1)
- Trading journal (playbook, notes, tags, screenshots) — separate spec
- Day-level batch AI analysis
- Multi-day performance charts / equity curve
- Trade replay
- Email/push notifications for violations
- Auto-import on schedule (webhook/cron)
- CSV export
- Mobile responsive layout

---

## 15. Testing Strategy

| Layer | Approach |
|-------|----------|
| Symbol parser | Unit tests: 20+ tradingsymbol variants → expected ParsedInstrument |
| FIFO matcher | Unit tests: simple pair, partial fills, multiple symbols, shorts, open positions |
| Charge calculator | Unit tests: equity intraday, delivery, options, futures with known expected values |
| Rule engine | Unit tests: each default rule with triggering and non-triggering scenarios |
| PDF parser | Integration tests: 3-4 sample contract note PDFs (pre/post Feb 2025 format) |
| Broker parsers | Unit tests: mock API responses → NormalizedFill |
| API endpoints | Integration tests: import → fetch → verify pairs and summary |
| Frontend | Manual: import flow, table sort, drawer open, chart markers, PDF upload, AI streaming |
