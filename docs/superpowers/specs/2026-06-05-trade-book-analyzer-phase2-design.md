# Trade Book Analyzer — Phase 2 Design Spec

**Date:** 2026-06-05
**Status:** Approved
**Phase:** 2 — Metrics, Calendar, Analytics, Pair Detail, Rules, Chart, LLM, API Import
**Executor:** Claude Sonnet. Every section is explicit. No assumptions left to the implementer.

---

## 0. Reading Guide for the Executor (Sonnet)

This spec is benchmarked against leading trade journals (Tradezella, Tradervue,
Edgewonk, TradesViz). It bakes in every correction discovered during codebase
verification. **There is no separate "corrections" section — the rules below are
already applied throughout. Follow the spec literally.**

Hard facts verified in this codebase (do not re-derive, do not assume otherwise):

1. **asyncpg returns JSONB columns as raw strings.** Every endpoint returning a
   JSONB column MUST parse it with the existing `_to_dict(r, jsonb=(...))` helper
   in `backend/api/routers/journal.py`. Forgetting this crashed Phase 1
   (`val.toFixed is not a function`).
2. **No SSE / streaming exists in this codebase. `EventSource` cannot POST.**
   LLM analysis is therefore a **plain POST that returns the full text in one JSON
   response**. Do NOT build server-sent events. Do NOT use `EventSource`.
3. **QuestDB `ohlcv_1min` DOES hold option premium candles** (verified: 355M rows; option
   symbols span 2019→2026). Stored symbol form is
   `[UNDERLYING][YY][MON3][DD][STRIKE][CE|PE]`, e.g. `SENSEX26JAN0184100PE`,
   `BANKNIFTY21DEC0935900PE`. Fetch via `MarketData.ohlcv(qdb_symbol, "1min", from, to)`
   (the QuestDB historical path — NOT `live_ohlcv`/Kite MCP). Per-contract coverage is the
   option's active window only (a weekly carries ~days of bars), so a specific contract may
   occasionally be missing → chart/MFE/MAE still degrade gracefully (null + banner), but
   this is the edge case now, not the norm.
4. **Anthropic client pattern is fixed.** Copy `backend/llm/translator.py`:
   `client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY.get_secret_value())`,
   model = `settings.LLM_MODEL`. anthropic 0.102.0 is installed. Do NOT invent
   `AsyncAnthropic()` with no key or a hardcoded model string.
5. **Timeframe strings are `"1min"`, `"1h"`, `"1d"`** (see `TF_TABLE` in `sdk.py`).
   Never pass `tf=1` or `tf="1"`.
6. **Frontend chart stack is `lightweight-charts` v5.2.** Reuse the existing
   `components/Chart/CandlestickChart.tsx` (takes `Bar[]` = `{ts,open,high,low,close,volume}`)
   and `lib/time.ts` `tsToUnix(ts)`. Do not add a new chart library.
7. **Router is react-router v6 `<Routes>/<Route element=…>`** in `App.tsx`. The journal
   is mounted at `/journal`. Add a sibling route `/journal/pairs/:id`.
8. **R-multiple needs risk-per-trade. PDFs/most APIs do not carry a stop.** R-multiple
   is computed ONLY when the user supplies `risk_amount` on the pair (annotation field).
   Never fabricate a stop.

### Build Stages (each is independently shippable AND independently testable)

| Stage | Scope | External deps |
|---|---|---|
| **A** | Metrics engine + P&L calendar + aggregate Analytics tab | none (pure DB/compute) |
| **B** | Pair detail page + annotations + structured tags + rule engine | none (pure DB) |
| **C** | Pair chart (QuestDB ohlcv) + MFE/MAE + replay | QuestDB (local) |
| **D** | LLM analysis (non-streaming POST) + Kite/Upstox API import | anthropic, broker auth |

Build A→B→C→D. Each stage ends with its own passing tests before the next starts.

---

## 1. Purpose

Phase 1 built ingestion (PDF import, FIFO pairs, per-broker day summaries). Phase 2
builds the **analysis layer** that makes this a real trade journal comparable to
Tradezella/Tradervue:

- Industry-standard **metrics**: win rate, profit factor, expectancy, avg win/loss,
  max drawdown, largest win/loss — plus per-pair MFE/MAE excursion and (optional) R-multiple.
- **P&L calendar heatmap** as the journal landing view (signature UI of every journal).
- **Aggregate Analytics**: group performance by symbol, weekday, hour-of-day, and tag.
- **Pair detail page** with P&L breakdown, fills, chart, rule violations, annotations,
  structured tags, and on-demand LLM critique.
- **Rule engine** with a management UI and quantified P&L impact of broken rules.
- **API import** (Kite/Upstox) for same-day journaling (PDF is EOD-only).

---

## 2. Data Model Changes

All changes are idempotent `ALTER TABLE … ADD COLUMN IF NOT EXISTS` in `schema.sql`,
applied by the existing `init_journal_tables()`.

### 2.1 `jrn_day_summary` — extended metrics + violations

```sql
ALTER TABLE jrn_day_summary ADD COLUMN IF NOT EXISTS win_rate        NUMERIC(6,4);
ALTER TABLE jrn_day_summary ADD COLUMN IF NOT EXISTS profit_factor   NUMERIC(10,4);
ALTER TABLE jrn_day_summary ADD COLUMN IF NOT EXISTS expectancy      NUMERIC(12,4);
ALTER TABLE jrn_day_summary ADD COLUMN IF NOT EXISTS avg_win         NUMERIC(12,4);
ALTER TABLE jrn_day_summary ADD COLUMN IF NOT EXISTS avg_loss        NUMERIC(12,4);
ALTER TABLE jrn_day_summary ADD COLUMN IF NOT EXISTS largest_win     NUMERIC(12,4);
ALTER TABLE jrn_day_summary ADD COLUMN IF NOT EXISTS largest_loss    NUMERIC(12,4);
ALTER TABLE jrn_day_summary ADD COLUMN IF NOT EXISTS max_drawdown    NUMERIC(12,4);
ALTER TABLE jrn_day_summary ADD COLUMN IF NOT EXISTS rule_violations JSONB;
ALTER TABLE jrn_day_summary ADD COLUMN IF NOT EXISTS rule_loss_impact NUMERIC(12,4);
```

### 2.2 `jrn_trade_pairs` — excursion, risk, tags

```sql
ALTER TABLE jrn_trade_pairs ADD COLUMN IF NOT EXISTS mfe          NUMERIC(12,4); -- max favorable excursion (₹, +)
ALTER TABLE jrn_trade_pairs ADD COLUMN IF NOT EXISTS mae          NUMERIC(12,4); -- max adverse excursion (₹, -)
ALTER TABLE jrn_trade_pairs ADD COLUMN IF NOT EXISTS mfe_capture  NUMERIC(6,4);  -- net_pnl / mfe when mfe>0
ALTER TABLE jrn_trade_pairs ADD COLUMN IF NOT EXISTS risk_amount  NUMERIC(12,4); -- user-supplied ₹ risk; NULL = unknown
ALTER TABLE jrn_trade_pairs ADD COLUMN IF NOT EXISTS r_multiple   NUMERIC(8,4);  -- net_pnl / risk_amount when set
ALTER TABLE jrn_trade_pairs ADD COLUMN IF NOT EXISTS tags         TEXT[];        -- structured tags (see 2.3)
```

`trade_rationale`, `trade_mistakes`, `session_notes` already exist from Phase 1.

### 2.3 Tag vocabulary

Tags are a controlled list stored in a new table so the UI can offer a dropdown and
Analytics can aggregate. Seeded once in `seed_default_rules()` (rename concept to
`seed_defaults()` or add a sibling `seed_default_tags()`).

```sql
CREATE TABLE IF NOT EXISTS jrn_tags (
    id    BIGSERIAL PRIMARY KEY,
    name  TEXT NOT NULL UNIQUE,
    kind  TEXT NOT NULL DEFAULT 'behavior'  -- behavior | setup | mistake
);
-- seeded defaults (ON CONFLICT (name) DO NOTHING):
-- behavior: fomo, revenge, overtrading, hesitation, chased
-- mistake:  early_exit, late_exit, no_stop, oversized, against_trend
-- setup:    breakout, reversal, trend_follow, scalp, news
```

`jrn_trade_pairs.tags TEXT[]` stores chosen tag names. No FK (arrays can't FK);
the UI constrains input to `jrn_tags.name`. Aggregation uses `unnest(tags)`.

---

## 3. Stage A — Metrics Engine + Calendar + Analytics

### 3.1 `backend/journal/metrics.py` (new)

Pure functions over a list of closed `TradePair` (open pairs excluded from win/loss math).

```python
def compute_metrics(pairs: list[TradePair]) -> dict:
    closed = [p for p in pairs if p.net_pnl is not None]
    wins   = [p for p in closed if p.net_pnl > 0]
    losses = [p for p in closed if p.net_pnl < 0]
    gross_profit = sum(p.net_pnl for p in wins)            # ≥ 0
    gross_loss   = abs(sum(p.net_pnl for p in losses))     # ≥ 0
    n = len(closed)
    win_rate = (len(wins) / n) if n else None
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None  # None = no losses
    avg_win  = (gross_profit / len(wins)) if wins else None
    avg_loss = (-gross_loss / len(losses)) if losses else None               # negative
    # expectancy = avg ₹ per trade
    expectancy = (sum(p.net_pnl for p in closed) / n) if n else None
    largest_win  = max((p.net_pnl for p in wins), default=None)
    largest_loss = min((p.net_pnl for p in losses), default=None)
    max_drawdown = _max_drawdown([p.net_pnl for p in _by_close_time(closed)])
    return {...}  # all keys above

def _max_drawdown(pnls: list[float]) -> float:
    # running equity peak-to-trough, returns a negative number (₹), 0 if never underwater
    equity = 0.0; peak = 0.0; mdd = 0.0
    for x in pnls:
        equity += x
        peak = max(peak, equity)
        mdd = min(mdd, equity - peak)
    return mdd
```

`build_day_summary` (in `aggregator.py`) calls `compute_metrics(pairs)` and writes the
new columns. **Tolerate NULLs everywhere** — a PDF-only day with one open position has
no closed pairs; every metric is None and that must not error.

### 3.2 Calendar endpoint

```
GET /journal/calendar?from=YYYY-MM-DD&to=YYYY-MM-DD&broker=<optional>
→ [{ "trade_date": "...", "broker": "zerodha"|null, "net_pnl": -861.0,
     "trade_count": 12, "win_rate": 0.42 }, ...]
```

Query `jrn_day_summary` filtered by date range. If `broker` omitted, return the
combined (`broker IS NULL`) rows for multi-broker days and the single-broker row
otherwise — mirror Phase 1's per-broker summary logic. Date params are converted with
`date.fromisoformat()` before binding (Phase 1 lesson: raw strings fail asyncpg).

### 3.3 Analytics endpoint

```
GET /journal/analytics?from=&to=&group_by=symbol|weekday|hour|tag&broker=<optional>
→ [{ "key": "NIFTY 23200 PE", "net_pnl": -1200, "trades": 8,
     "wins": 3, "losses": 5, "win_rate": 0.375, "profit_factor": 0.6 }, ...]
```

Implemented in SQL over `jrn_trade_pairs` (closed pairs only, `net_pnl IS NOT NULL`):

- `group_by=symbol`  → `GROUP BY symbol`
- `group_by=weekday` → `GROUP BY EXTRACT(DOW FROM open_date)` (label Mon..Sun)
- `group_by=hour`    → `GROUP BY EXTRACT(HOUR FROM open_time)` (NULL bucket = "PDF/no-time")
- `group_by=tag`     → `GROUP BY t FROM jrn_trade_pairs, unnest(tags) t`

`profit_factor` computed in SQL as `sum(net_pnl) filter (where net_pnl>0) /
nullif(abs(sum(net_pnl) filter (where net_pnl<0)),0)`.

### 3.4 Frontend — Calendar + Analytics

- `components/Journal/PnlCalendar.tsx`: month grid, each day cell colored by net P&L
  (green `#26a69a` ↑, red `#ef5350` ↓, intensity ∝ |pnl|), shows ₹ + trade count.
  Click a day → set `selectedDate` (+broker) and switch to Summary tab (reuse Phase 1
  handlers). Month prev/next nav. This becomes the **default landing** of the Summary tab
  when no day is selected (replaces the bare card list).
- `components/Journal/AnalyticsPanel.tsx`: a `group_by` selector
  (Symbol / Weekday / Hour / Tag) + a sortable bar list (net P&L per key, win-rate badge).
  New **Analytics tab** in `JournalPage` (now 6 tabs:
  Summary, Pairs, Trades, Analytics, Rules, Import).
- `MetricsStrip.tsx`: a row of metric chips (Win rate, Profit factor, Expectancy,
  Avg win, Avg loss, Max DD) rendered on the day Summary and on Analytics. Reads the
  new summary columns. Renders "—" for null.

### 3.5 Stage A tests

Backend (`test_metrics.py`):
- `compute_metrics` on a known pair set → exact win_rate, profit_factor, expectancy,
  avg_win/avg_loss, largest_win/loss.
- `_max_drawdown([+100,-50,-80,+30])` == -100 (peak 100 → trough 0… verify by hand).
- all-wins day → profit_factor None (no division by zero); empty day → all None, no raise.
- `GET /journal/calendar` returns one entry per day in range; `GET /journal/analytics`
  groups correctly for each `group_by`; hour grouping puts NULL open_time in "no-time" bucket.

Frontend (Playwright, `page.on('pageerror')` wired):
- Calendar renders cells; clicking a green day opens its summary.
- Analytics tab: switch group_by → list updates; null-time trades appear under "No time".
- MetricsStrip shows "—" for a PDF-only open-position day (no crash).

---

## 4. Stage B — Pair Detail Page + Annotations + Tags + Rule Engine

### 4.1 Route + page

Add to `App.tsx` inside `<Routes>` (same auth guard wrapper as `/journal`):

```tsx
<Route path="/journal/pairs/:id" element={<RequireAuth><PairDetailPage /></RequireAuth>} />
```

`pages/Journal/PairDetailPage.tsx`: reads `id` via `useParams`, calls
`GET /journal/pairs/{id}` on mount. Back button → `navigate(-1)`. Because this is a
real route (not SPA tab state), there is no stale-Zustand crash risk — do NOT route the
detail through the Zustand journal store; use local `useState` + a direct axios call.

### 4.2 `GET /journal/pairs/{id}` (new)

Returns the pair plus its expanded fills:

```python
@router.get("/pairs/{pair_id}")
async def get_pair(pair_id: int):
    async with pool.acquire() as conn:
        p = await conn.fetchrow("SELECT * FROM jrn_trade_pairs WHERE id=$1", pair_id)
        if p is None:
            raise HTTPException(404, "pair not found")
        entry = await conn.fetch(
            "SELECT * FROM jrn_trades WHERE id = ANY($1::bigint[]) ORDER BY trade_time",
            list(p["entry_trade_ids"] or []))
        exit_ = await conn.fetch(
            "SELECT * FROM jrn_trades WHERE id = ANY($1::bigint[]) ORDER BY trade_time",
            list(p["exit_trade_ids"] or []))
    pair = _to_dict(p, jsonb=("charges",))          # JSONB parse — mandatory
    return {"pair": pair,
            "entry_trades": [_to_dict(r) for r in entry],
            "exit_trades":  [_to_dict(r) for r in exit_]}
```

### 4.3 P&L card + fills

`PairDetailPage` layout:
- Header: `symbol · broker · side · qty (lots) · open_date`.
- P&L card: entry → exit → gross → each charge line (from parsed `charges` dict) → net.
  net colored green/red. `hold_seconds` shown as `Xm Ys`; if null → "(PDF — no timestamp)".
  MFE/MAE/R-multiple shown when non-null (Stage C/B fills them), else hidden.
- Two collapsible fill sections (Entry Fills / Exit Fills): time · side · qty · price ·
  brokerage · fill_grain. `fill_grain='wap'` rows show "(WAP)" in the time column.

### 4.4 Annotations + tags

```
PATCH /journal/pairs/{id}/annotate
Body (all optional): {
  "trade_rationale": str, "trade_mistakes": str, "session_notes": str,
  "risk_amount": number|null, "tags": string[]
}
```

Server: `UPDATE` only the provided keys (build SET clause dynamically from present keys).
When `risk_amount` set and `net_pnl` present → recompute `r_multiple = net_pnl / risk_amount`,
else `r_multiple = NULL`. `tags` validated against `jrn_tags.name` (silently drop unknown).

`components/Journal/AnnotationEditor.tsx`:
- three textareas (rationale / mistakes / session notes)
- a numeric `risk_amount` input (₹ risked; placeholder "leave blank if unknown")
- a tag multi-select (chips from `GET /journal/tags`)
- Save → PATCH → inline "Saved ✓". Pre-populated from the pair on load.

`GET /journal/tags` → `[{name, kind}]` for the picker.

### 4.5 Rule engine — `backend/journal/rules.py` (new)

Registry pattern so new rule types need ONE function, no switch edits:

```python
from typing import Callable
_EVALUATORS: dict[str, Callable] = {}

def register(rule_type: str):
    def deco(fn): _EVALUATORS[rule_type] = fn; return fn
    return deco

# Each evaluator returns (fired: bool, loss_impact: float). loss_impact = ₹ P&L
# attributable to the violation (0.0 when not quantifiable), used for rule_loss_impact.

@register("threshold")   # config: {field, op, value}; field ∈ summary keys
def _threshold(rule, pairs, summary):
    v = summary.get(rule.config["field"])
    if v is None: return (False, 0.0)
    fired = _cmp(v, rule.config["op"], rule.config["value"])
    return (fired, 0.0)

@register("flag")        # config: {field, op, value}; integer/bool summary fields
def _flag(rule, pairs, summary):
    v = summary.get(rule.config["field"]) or 0
    return (_cmp(v, rule.config["op"], rule.config["value"]), 0.0)

@register("streak")      # config: {consecutive_losses: N}
def _streak(rule, pairs, summary):
    n = rule.config["consecutive_losses"]; run = 0; hit = False
    for p in _by_close_time(pairs):
        if p.net_pnl is None: continue
        run = run + 1 if p.net_pnl < 0 else 0
        hit = hit or run >= n
    return (hit, 0.0)

@register("revenge_trade")  # config: {min_gap_seconds: N}
def _revenge(rule, pairs, summary):
    # a new entry opened within N s of a losing pair's close. loss_impact = sum net_pnl
    # of the revenge entries that themselves lost.
    ordered = _by_close_time([p for p in pairs if p.close_time]); impact = 0.0; fired = False
    losers = [p for p in ordered if p.net_pnl is not None and p.net_pnl < 0]
    for nxt in pairs:
        if nxt.open_time is None: continue
        for L in losers:
            gap = _secs_between(L.close_date, L.close_time, nxt.open_date, nxt.open_time)
            if gap is not None and 0 <= gap <= rule.config["min_gap_seconds"]:
                fired = True
                if nxt.net_pnl and nxt.net_pnl < 0: impact += nxt.net_pnl
    return (fired, impact)

@register("time_window")  # config: {no_trade_after: "HH:MM"}
def _time_window(rule, pairs, summary):
    cutoff = _parse_hhmm(rule.config["no_trade_after"]); impact = 0.0; fired = False
    for p in pairs:
        if p.open_time and p.open_time > cutoff:
            fired = True
            if p.net_pnl and p.net_pnl < 0: impact += p.net_pnl
    return (fired, impact)

def evaluate_rules(pairs, summary, rules) -> tuple[list[dict], float]:
    violations, total_impact = [], 0.0
    for r in rules:
        if not r.enabled: continue
        fn = _EVALUATORS.get(r.rule_type)
        if fn is None: continue                 # unknown type → skip, never crash
        fired, impact = fn(r, pairs, summary)
        if fired:
            violations.append({"rule_id": r.id, "name": r.name,
                               "rule_type": r.rule_type, "loss_impact": round(impact, 2)})
            total_impact += impact
    return violations, round(total_impact, 2)
```

Wired into `_recompute_day` AFTER pairs+summary are built, per (broker,date) summary row:

```python
rules = await _load_enabled_rules(conn)
violations, impact = evaluate_rules(broker_pairs, summary_dict, rules)
# write to that summary row:
await conn.execute(
  "UPDATE jrn_day_summary SET rule_violations=$1, rule_loss_impact=$2 "
  "WHERE trade_date=$3 AND COALESCE(broker,'')=$4",
  json.dumps(violations), impact, dt, broker or "")
```

`summary_dict` is the summary as a plain dict (so `.get(field)` works for threshold rules).

### 4.6 Rules CRUD + management UI

```
GET    /journal/rules         → [{id,name,rule_type,enabled,config}]  (config JSONB parsed)
POST   /journal/rules         body {name,rule_type,config,enabled}    → created row
PATCH  /journal/rules/{id}    body {config?,enabled?,name?}           → updated row
DELETE /journal/rules/{id}                                            → {deleted:true}
```

`name` is UNIQUE (existing constraint) → POST catches `asyncpg.UniqueViolationError`
→ 409. `config` stored as `json.dumps(...)`; read back through `_to_dict(...,jsonb=("config",))`.

**Rules tab** in `JournalPage`: list rows (name · type · config summary · enabled toggle ·
edit · delete) + "Add Rule". Add/Edit form fields adapt to `rule_type`:
- threshold/flag: field dropdown (`net_pnl, total_fills, force_squared_count, max_drawdown,
  loss_pairs`) · op dropdown (`<,>,=,<=,>=`) · numeric value
- streak: `consecutive_losses` number
- revenge_trade: `min_gap_seconds` number
- time_window: `no_trade_after` time (HH:MM)

`seed_default_rules()` seeds these **disabled** by default (so an empty journal shows
nothing fired): `max_daily_loss` (threshold net_pnl < -5000), `max_trades`
(flag total_fills > 20), `force_square_present` (flag force_squared_count > 0),
`loss_streak_3` (streak consecutive_losses 3), `no_trade_after_1500`
(time_window 15:00). All `ON CONFLICT (name) DO NOTHING`.

### 4.7 RuleViolations component

`components/Journal/RuleViolations.tsx`: reads `rule_violations` (JSONB → already parsed
by the summary endpoint) for the selected day; lists each fired rule with its
`loss_impact` (₹) when non-zero. Rendered on the day Summary and on the pair detail page
(detail page shows the parent day's violations).

### 4.8 Stage B tests

Backend (`test_rules.py`):
- each evaluator: fires on matching fixture, silent on non-matching; `revenge_trade` and
  `time_window` return correct `loss_impact`.
- `@register("custom")` adds to `_EVALUATORS` and is callable — proves extensibility.
- unknown `rule_type` in DB → `evaluate_rules` skips it, no raise.
- CRUD endpoints: create→list→patch(enabled false)→recompute→violation absent; duplicate
  name → 409.

Backend (`test_pair_detail.py`):
- `GET /journal/pairs/{id}` expands entry/exit fills, parses `charges`, 404 on missing.
- `PATCH …/annotate` persists all fields; setting `risk_amount` populates `r_multiple`;
  clearing it nulls `r_multiple`; unknown tags dropped.

Frontend (Playwright):
- click a pair row → URL `/journal/pairs/:id`; browser Back → `/journal`, day still
  selected, no crash (the Phase-1 regression test, now via real routing).
- annotate: type rationale + pick 2 tags + set risk 1500 → Save → reload → all persist;
  detail shows computed R-multiple.
- Rules tab: add threshold rule → appears; toggle off → after recompute the day's
  RuleViolations no longer lists it.

---

## 5. Stage C — Pair Chart + MFE/MAE + Replay

### 5.1 Option candles are in QuestDB (historical, deep)

`ohlcv_1min` contains option premium bars (verified, 2019→2026), so chart + MFE/MAE work
for essentially any dated option trade — PDF or API, old or recent. Fetch through the
existing QuestDB path `MarketData.ohlcv(qdb_symbol, "1min", from_dt, to_dt)` (returns a
DataFrame with `ts, open, high, low, close, volume`). Only when a specific contract was
never ingested does the DataFrame come back empty → graceful banner, MFE/MAE NULL. Never
crash, never block.

**The table has EXACTLY these columns — no open interest, IV, greeks, or bid/ask.** The
source feed (icharts) emits only OHLCV+volume; do not query or expect any greeks/OI column.
The stored `close` is the option **premium** in ₹, same unit as the contract-note entry/exit
price — so price lines and MFE/MAE math are unit-consistent with the pair's prices.
Physical design (do not alter): `ts` designated timestamp, partition by MONTH, WAL + dedup
on `(ts, symbol)` → re-ingestion is idempotent. `symbol` is QuestDB `SYMBOL` type (fast
equality filter); always query with `symbol = '<exact>'`.

### 5.2 Building the QuestDB symbol for a pair

QuestDB symbol form is `[UNDERLYING][YY][MON3][DD][STRIKE][CE|PE]`. The pair already
carries decoded `underlying`, `expiry` (DATE), `strike` (INT), `option_type` from Phase 1's
symbol parser — rebuild deterministically (do NOT reuse the broker raw compact string,
whose month is single-char):

```python
_MON3 = ["JAN","FEB","MAR","APR","MAY","JUN","JUL","AUG","SEP","OCT","NOV","DEC"]

def qdb_symbol_for(pair) -> str | None:
    if pair["option_type"] not in ("CE", "PE"):       # equity/fut → no option chart
        return None
    if not (pair.get("expiry") and pair.get("strike") and pair.get("underlying")):
        return None
    e = pair["expiry"]                                 # datetime.date
    yy  = e.year % 100
    mon = _MON3[e.month - 1]
    dd  = f"{e.day:02d}"
    return f"{pair['underlying']}{yy:02d}{mon}{dd}{int(pair['strike'])}{pair['option_type']}"
# e.g. NIFTY expiry 2026-06-09 strike 23200 PE -> "NIFTY26JUN0923200PE"
```

If `qdb_symbol_for` returns None → no chart, show "Chart unavailable for this instrument".
The exact QuestDB symbol string built here is verified to match stored symbols (e.g.
`SENSEX26JAN0184100PE`); a unit test asserts the exact output for known pairs.

### 5.3 Chart data + MFE/MAE endpoint

```
GET /journal/pairs/{id}/chart
→ { "bars": [{ts,open,high,low,close,volume}...],
    "entry_price": .., "exit_price": .., "entry_ts": ..|null, "exit_ts": ..|null,
    "available": true|false, "reason": "no_candles"|"not_option"|null }
```

Server:
1. Build window. If `fill_grain='fill'` and times present:
   `from = open_datetime - 30min`, `to = close_datetime + 30min` (fallback `open+90min`
   if still open). If `fill_grain='wap'` (no times): `from = open_date 09:15`,
   `to = open_date 15:30`.
2. `sym = qdb_symbol_for(pair)`. If None → `{available:false, reason:"not_option"}`.
3. `df = await MarketData().ohlcv(sym, "1min", from_dt, to_dt)` (QuestDB historical). If
   empty → `{available:false, reason:"no_candles"}`.
4. **Compute MFE/MAE here** (only when candles available) over bars between entry_ts and
   exit_ts (or whole window for WAP):

```python
# LONG: favorable = high above entry; adverse = low below entry. SHORT: inverted.
seg = df[(df.ts >= entry_ts) & (df.ts <= exit_ts)] if entry_ts and exit_ts else df
if side == "LONG":
    mfe = (seg.high.max() - entry_price) * qty
    mae = (seg.low.min()  - entry_price) * qty      # ≤ 0
else:  # SHORT (sold to open)
    mfe = (entry_price - seg.low.min())  * qty
    mae = (entry_price - seg.high.max()) * qty      # ≤ 0
mfe_capture = (net_pnl / mfe) if mfe and mfe > 0 else None
# persist mfe, mae, mfe_capture to jrn_trade_pairs (so Analytics/summary can use them)
```

Note granularity caveat in the response and UI: 1-min bars under-measure sub-minute
scalps; MFE/MAE are directional estimates, labeled "≈".

### 5.4 Frontend `PairChart.tsx`

- Fetch `/journal/pairs/{id}/chart`. If `available:false` → render banner with `reason`
  ("No intraday candles for this contract" / "Not an options contract"). No chart, no crash.
- If available → feed `bars` to the existing `CandlestickChart` (`tfOffsetSec=60`).
- Entry/exit price lines via `series.createPriceLine({price, color, title})` — entry
  `#26a69a`, exit `#ef5350`.
- **Replay**: local state `replayIdx:number|null`. Play → `setInterval` advancing idx,
  chart shows `bars.slice(0, idx)`. Speed select 50/200/500 ms. Pause/Reset buttons.
  Reset → idx null → full chart. Pure client, no backend calls during replay.
- Use `tsToUnix` from `lib/time.ts` for any manual time mapping.

### 5.5 When MFE/MAE are computed

QuestDB is local and indexed by `(symbol, ts)` — a per-contract day query is sub-second.
So MFE/MAE ARE computed inside `_recompute_day` (Stage C onward): for each closed option
pair, build `qdb_symbol_for`, fetch the day window via `MarketData.ohlcv`, compute and
persist `mfe/mae/mfe_capture`. Wrap in try/except → on empty/missing candles leave them
NULL and continue (never fail the recompute). The `GET /pairs/{id}/chart` endpoint
recomputes opportunistically too (so a contract ingested after import still backfills on
first detail-page open). Day-summary excursion aggregates ignore NULLs.

### 5.6 Stage C tests

Backend (`test_chart.py`, monkeypatch `MarketData.ohlcv` to return a fixture DataFrame):
- `qdb_symbol_for`: NIFTY 2026-06-09 / 23200 / PE → `"NIFTY26JUN0923200PE"`;
  SENSEX 2026-01-01 / 84100 / PE → `"SENSEX26JAN0184100PE"`; non-option → None.
- option pair + fixture bars → MFE/MAE correct sign and magnitude for LONG and SHORT.
- empty DataFrame → `{available:false, reason:"no_candles"}`, pair MFE/MAE stay NULL.
- non-option pair → `{available:false, reason:"not_option"}`.

Frontend (Playwright, mock the chart endpoint — no QuestDB needed in CI):
- available → chart renders, entry price line present, Play animates, Reset restores.
- unavailable → banner shown, page does not crash, rest of detail page works.

---

## 6. Stage D — LLM Analysis (non-streaming) + API Import

### 6.1 `backend/journal/analysis.py` (new)

NO streaming. One synchronous Anthropic call returning full text. Copy the client pattern
from `llm/translator.py`.

```python
import anthropic
from core.config import settings

def build_pair_prompt(pair, entry_trades, exit_trades, violations) -> str:
    notes = []
    if pair.get("trade_rationale"): notes.append(f"Rationale: {pair['trade_rationale']}")
    if pair.get("trade_mistakes"):  notes.append(f"Mistakes: {pair['trade_mistakes']}")
    if pair.get("tags"):            notes.append(f"Tags: {', '.join(pair['tags'])}")
    excursion = ""
    if pair.get("mfe") is not None:
        excursion = (f"MFE ≈ ₹{pair['mfe']:.0f}, MAE ≈ ₹{pair['mae']:.0f}, "
                     f"capture {pair.get('mfe_capture')}")
    rule_txt = ", ".join(v["name"] for v in violations) or "none"
    return f"""You are a trading coach. Analyze ONE options trade.

Symbol: {pair['symbol']} ({pair.get('option_type')})  Broker: {pair['broker']}
Side: {pair['side']}  Qty: {pair['quantity']} ({pair.get('lots')} lot)
Entry ₹{pair['entry_price']} → Exit ₹{pair.get('exit_price')}
Hold: {pair.get('hold_seconds')} s   Gross ₹{pair.get('gross_pnl')}  Net ₹{pair.get('net_pnl')}
{excursion}
Rule violations: {rule_txt}
{chr(10).join(notes)}

Give 3 short sections: (1) what likely went wrong/right, (2) the pattern,
(3) one concrete change. Be specific and brief."""

def run_analysis(prompt: str) -> tuple[str, int, int]:
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY.get_secret_value())
    resp = client.messages.create(model=settings.LLM_MODEL, max_tokens=900,
                                  messages=[{"role": "user", "content": prompt}])
    text = "".join(b.text for b in resp.content if b.type == "text")
    return text, resp.usage.input_tokens, resp.usage.output_tokens
```

### 6.2 Endpoints

```
POST /journal/pairs/{id}/analyze   → { "response": str, "cached": false }
POST /journal/analyze/day          body {trade_date, broker?} → { "response": str }
GET  /journal/pairs/{id}/analysis  → latest stored analysis or {response:null}
```

`POST …/analyze`: gather pair+fills+violations, build prompt, `run_analysis`, INSERT into
`jrn_analyses(scope='pair', scope_id=str(id), triggered_by='user', response=text,
model=settings.LLM_MODEL, tokens_in=.., tokens_out=..)`, return text. If
`settings.ENABLE_LLM_CHAT` is false → 503 (mirror `chat.py`). Day-level uses the day
summary + a compact table of that day's pairs.

Run blocking SDK call in a threadpool: `await run_in_threadpool(run_analysis, prompt)`
(FastAPI's `fastapi.concurrency.run_in_threadpool`) so the event loop is not blocked.

### 6.3 Frontend `LlmAnalysis.tsx`

- On mount: `GET …/analysis`. If a stored response exists → render it (markdown) + a
  "Re-analyze" button. Else show an "Analyze this trade" button.
- Click → POST → button shows spinner → render returned markdown. No SSE, no EventSource.
- Render markdown with the app's existing markdown renderer if one exists; else a styled
  `<pre>` is acceptable.
- Day-level "Analyze Day" button on the Summary tab → `POST /journal/analyze/day`.

### 6.4 API import (Kite / Upstox)

Parsers exist (`parsers/kite.py`, `parsers/upstox.py`). Wire auth + a frontend trigger.

```
POST /journal/import/api   body { broker: "kite"|"upstox", trade_date: "YYYY-MM-DD" }
```

- Kite: read `api_key`+`access_token` from the same Redis session the rest of the app
  uses (find the existing accessor in `core/`; do NOT invent a new one). Call Kite
  `/trades`, parse via `kite.py`, `_upsert_trades`, `_recompute_day(trade_date)`.
- Upstox: bearer from Redis `upstox:access_token`; Upstox trades endpoint → `upstox.py`.
- mStock API: **out of scope this phase** (separate JWT flow); leave the broker option
  disabled in the UI with a tooltip "coming soon".
- `trade_date` may be ANY date (not today-only). If the broker API only returns today,
  return a clear 422 "broker API only exposes today's trades" rather than silent empty.

Dedup is already handled by the Phase-1 partial unique index on `(broker, trade_id)`
for API fills — re-import of the same day is safe.

**Frontend**: add an "API" tab to `ImportPanel.tsx` next to PDF:
broker dropdown (Kite, Upstox; mStock disabled) · date picker · "Import Trades".
On success reuse the PDF flow: `reset()` + `fetchSummaries()` + switch to Summary.

### 6.5 Stage D tests

Backend (`test_analysis.py`):
- `build_pair_prompt` includes symbol, P&L, violations; omits empty notes (no
  "Rationale: None" noise); includes MFE line only when set.
- `run_analysis` mocked (monkeypatch `anthropic.Anthropic`) → endpoint returns
  `{response}` and writes one `jrn_analyses` row with token counts.
- `ENABLE_LLM_CHAT=false` → 503.
- `test_api_import.py`: mock broker client → `POST /journal/import/api` upserts fills and
  triggers recompute; re-import same day inserts 0 dupes.

Frontend (Playwright, mock endpoints):
- Analyze button → spinner → text appears; revisit page → cached text + Re-analyze shown.
- Import API tab: Kite + date → Import → summaries refresh; mStock option disabled.

---

## 7. Endpoint Summary (all new in Phase 2)

```
GET    /journal/calendar?from=&to=&broker=
GET    /journal/analytics?from=&to=&group_by=symbol|weekday|hour|tag&broker=
GET    /journal/pairs/{id}
GET    /journal/pairs/{id}/chart
POST   /journal/pairs/{id}/analyze
GET    /journal/pairs/{id}/analysis
PATCH  /journal/pairs/{id}/annotate
POST   /journal/analyze/day
GET    /journal/tags
GET    /journal/rules
POST   /journal/rules
PATCH  /journal/rules/{id}
DELETE /journal/rules/{id}
POST   /journal/import/api
```

Every endpoint returning JSONB (`charges`, `config`, `rule_violations`, `time_bucket_pnl`)
parses it via `_to_dict(r, jsonb=(...))`. Every date param is bound as `date.fromisoformat()`.

---

## 8. User Journeys (acceptance — these must work end to end)

1. **EOD review (primary).** Import PDF → land on P&L calendar → click a red day →
   see metrics strip + rule violations → open a losing pair → read P&L breakdown + fills →
   (recent date) see chart with entry/exit lines + MFE/MAE telling me I exited early →
   tag it `early_exit`, set risk ₹1500 (R-multiple appears), write what went wrong →
   click Analyze → read the coach critique.
2. **Intraday journaling.** Mid-session: Import → API tab → Kite → today → trades appear
   without waiting for the EOD PDF.
3. **Pattern hunting.** Analytics tab → group by Hour → see I lose most 14:30–15:00 →
   group by Tag → `revenge` trades are net-negative → add a `no_trade_after 14:30` rule →
   future days flag it with ₹ impact.
4. **Rule tuning.** Rules tab → create/edit/disable rules → recompute reflects changes.

Each journey maps 1:1 to a Playwright test.

---

## 9. Implementation Order (strict; test gate between stages)

**Stage A** 1) summary metric columns + `metrics.py` + wire into `aggregator`.
2) `/journal/calendar` + `/journal/analytics`. 3) `PnlCalendar`, `AnalyticsPanel`,
`MetricsStrip`, Analytics tab. 4) Stage-A tests green.

**Stage B** 5) pair/tags/risk columns + `jrn_tags` seed. 6) `GET /pairs/{id}`,
`PATCH …/annotate`, `GET /tags`. 7) `rules.py` registry + wire into `_recompute_day`.
8) rules CRUD. 9) `PairDetailPage` + route, `AnnotationEditor`, `RuleViolations`,
Rules tab. 10) Stage-B tests green.

**Stage C** 11) `/pairs/{id}/chart` + `qdb_symbol_for` + MFE/MAE persist (in `_recompute_day`).
12) `PairChart` + replay. 13) Stage-C tests green.

**Stage D** 14) `analysis.py` + analyze/analysis endpoints (threadpool).
15) `LlmAnalysis` + day analyze button. 16) API import auth wiring + API tab.
17) Stage-D tests green.

**Final** 18) full Playwright suite (all 4 journeys) green; update session handoff +
memory; commit per stage, push at end.

---

## 10. Out of Scope (Phase 2)

- mStock API import (separate JWT flow) — UI option disabled.
- SSE/streaming LLM output — non-streaming POST only.
- Scheduled bulk backfill of MFE/MAE for already-imported pairs (computed on
  recompute + on first chart open; no cron job this phase).
- Option greeks / OI / IV at entry — NOT in the data pipeline (icharts emits OHLCV+volume
  only) and not backfillable historically. A future feature could snapshot the live option
  chain at trade time into a `jrn_trades.greeks JSONB` for same-day API imports; not Phase 2.
- Automatic R-multiple (no stop data) — user supplies `risk_amount` or it stays null.
- Scheduled excursion backfill job.
