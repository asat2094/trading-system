# Trade Book Analyzer — Phase 2 Design Spec

**Date:** 2026-06-05
**Status:** Approved
**Phase:** 2 — Pair Detail, Rule Engine, LLM Analysis, API Import, Chart Replay

---

## 1. Purpose

Extend Phase 1 (PDF import, FIFO pairs, per-broker summaries) with:
- Full pair detail page with P&L breakdown and fill expansion
- QuestDB-backed mini chart with entry/exit markers and replay
- Rule engine with frontend management UI
- LLM streaming analysis per pair and per day
- Trade annotations (rationale, mistakes, session notes)
- Kite/Upstox/mStock API import for intraday use

Phase 1 built the data pipeline. Phase 2 builds the analysis layer on top of it.

---

## 2. Architecture

```
/journal                    (existing — day list + summary)
/journal/pairs/:id          (new — full pair detail page)

Pair detail page layout:
  ├─ Header: symbol · broker · side · qty · lots · date
  ├─ P&L card: entry price → exit price → gross → charges breakdown → net
  ├─ Fills table: expanded jrn_trades from entry_trade_ids + exit_trade_ids
  ├─ Mini chart: QuestDB 1-min OHLCV ±90min around trade + replay
  ├─ Rule violations: which rules this trade day triggered
  ├─ Annotation editor: rationale / mistakes / session_notes (PATCH)
  └─ LLM analysis panel: SSE stream → stored in jrn_analyses
```

### 2.1 New Backend Endpoints

```
GET   /journal/pairs/{id}           — single pair + expanded fills (entry + exit trades)
PATCH /journal/pairs/{id}/annotate  — save rationale / mistakes / session_notes
POST  /journal/pairs/{id}/analyze   — trigger LLM, returns SSE stream (text/event-stream)
POST  /journal/analyze/day          — day+broker level LLM, returns SSE stream
GET   /journal/rules                — list all rules
POST  /journal/rules                — create rule
PATCH /journal/rules/{id}           — update config + enabled flag
DELETE /journal/rules/{id}          — delete rule
```

Existing `POST /journal/import/api` stays — just needs auth reads wired.

### 2.2 New Frontend Files

```
pages/Journal/PairDetailPage.tsx        — full page route /journal/pairs/:id
components/Journal/PairChart.tsx        — lightweight-charts wrapper + replay
components/Journal/RuleViolations.tsx   — list violations from day summary
components/Journal/LlmAnalysis.tsx      — SSE stream display + trigger button
components/Journal/AnnotationEditor.tsx — textarea save/edit for 3 annotation fields
```

Rules tab added to JournalPage (5th tab alongside Summary/Pairs/Trades/Import).

### 2.3 Schema Change

One new column on `jrn_day_summary`:

```sql
ALTER TABLE jrn_day_summary ADD COLUMN IF NOT EXISTS rule_violations JSONB;
```

All other Phase 2 fields already exist in schema from Phase 1 design
(`trade_rationale`, `trade_mistakes`, `session_notes` on `jrn_trade_pairs`;
`jrn_analyses`, `jrn_chart_snapshots` tables already created).

---

## 3. Pair Detail Page

### 3.1 Route

`/journal/pairs/:id` — added to React Router. `PairDetailPage` calls
`GET /journal/pairs/{id}` on mount via `useParams`.

Back button → `navigate(-1)`. Full page route means no Zustand reset() hack needed
(Phase 1 lesson: crash-on-back was caused by stale Zustand state in SPA navigation;
a real route avoids this entirely).

### 3.2 P&L Card

Displays:
- Entry price · Exit price · Gross P&L
- Charges breakdown: brokerage · STT · exchange_txn · stamp · SEBI · GST
- Net P&L (color: green if ≥ 0, red if < 0)
- hold_seconds as `Xm Ys` if non-null; "(PDF — no timestamp)" if null

`charges` field is JSONB — apply `_to_dict(r, jsonb=("charges",))` in router
(Phase 1 lesson: asyncpg returns JSONB as raw string → must parse before response).

### 3.3 Fills Table

`GET /journal/pairs/{id}` returns pair + two arrays:
- `entry_trades: JrnTrade[]` — fetched via `WHERE id = ANY(entry_trade_ids)`
- `exit_trades: JrnTrade[]` — fetched via `WHERE id = ANY(exit_trade_ids)`

Displayed as two collapsible sections: **Entry Fills** / **Exit Fills**.
Columns: time · symbol · side · qty · price · brokerage · fill_grain.

If `fill_grain='wap'`: show "(WAP — PDF import)" in time column instead of null.

---

## 4. Chart (QuestDB + Replay)

### 4.1 Data Fetch

```
GET /technical/ohlcv/{underlying}?tf=1&from=T-90m&to=T+90m
```

Where `T`:
- `fill_grain='fill'`: `open_date + open_time` (exact entry timestamp)
- `fill_grain='wap'`: `open_date 09:15:00` (full trading day, no time precision)

Response shape matches existing `Bar[]` (`{ts, open, high, low, close, volume}`).
Reuse existing `CandlestickChart` component unchanged.

### 4.2 Entry/Exit Markers

Use `ISeriesApi.createPriceLine()`:
- Entry: `{price: entry_price, color: '#26a69a', lineStyle: 1, title: 'Entry'}`
- Exit: `{price: exit_price, color: '#ef5350', lineStyle: 1, title: 'Exit'}` (if closed)

For WAP rows: price lines only, no time-based markers.
Show banner: "Trade times unavailable — PDF import (WAP grain)."

### 4.3 Replay

State: `replayIdx: number | null`. When null, full chart shown.

Controls: **Play** / **Pause** / **Reset** buttons.

Play: `setInterval(() => setReplayIdx(i => i + 1), 200)` until `replayIdx >= bars.length`.
Chart renders `bars.slice(0, replayIdx)` — lightweight-charts handles partial data natively.
Speed slider: 50ms / 200ms / 500ms per bar.

No TV MCP dependency. Pure QuestDB data.

---

## 5. Rule Engine

### 5.1 Registry Pattern

```python
# backend/journal/rules.py
_EVALUATORS: dict[str, Callable] = {}

def register(rule_type: str):
    def decorator(fn):
        _EVALUATORS[rule_type] = fn
        return fn
    return decorator
```

Adding new rule type = one `@register("type_name")` decorated function.
No other code changes needed.

### 5.2 Built-in Rule Types

| rule_type | config keys | fires when |
|---|---|---|
| `threshold` | `field, op, value` | `summary[field] op value` — e.g. net_pnl < -5000 |
| `flag` | `field, op, value` | same, for integer/bool fields |
| `streak` | `consecutive_losses` | N consecutive loss pairs in day |
| `revenge_trade` | `min_gap_seconds` | any new entry within N seconds of a loss pair close (N=0 means any immediate re-entry after loss) |
| `time_window` | `no_trade_after` | any trade after HH:MM (e.g. 14:30) |

### 5.3 Evaluation Flow

Called inside `_recompute_day` after `build_day_summary`:

```python
rules = await _load_enabled_rules(conn)
violations = evaluate_rules(pairs, summary, rules)
# stored as JSONB: [{"rule_id": 1, "name": "max_daily_loss", "rule_type": "threshold"}]
await conn.execute(
    "UPDATE jrn_day_summary SET rule_violations=$1 WHERE trade_date=$2 AND COALESCE(broker,'')=$3",
    json.dumps(violations), dt, broker or ""
)
```

### 5.4 Rules Management UI

5th tab "Rules" in JournalPage. List view with per-row: name · type · config summary · enabled toggle · edit · delete.

Add/Edit: inline form. Fields adapt per rule_type:
- `threshold`/`flag`: field dropdown (net_pnl / total_fills / force_squared_count) · op dropdown (< / > / =) · value input
- `streak`: consecutive_losses number input
- `revenge_trade`: min_gap_seconds input
- `time_window`: no_trade_after time input (HH:MM)

---

## 6. LLM Streaming Analysis

### 6.1 Backend

```python
# backend/journal/analysis.py
def build_pair_prompt(pair: dict, entry_trades: list, exit_trades: list, violations: list) -> str:
    # Returns structured prompt with all trade context
    ...

async def stream_analysis(prompt: str) -> AsyncIterator[str]:
    client = anthropic.AsyncAnthropic()
    async with client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}]
    ) as stream:
        async for text in stream.text_stream:
            yield f"data: {text}\n\n"
    yield "data: [DONE]\n\n"
```

FastAPI endpoint returns `StreamingResponse(stream_analysis(prompt), media_type="text/event-stream")`.

The endpoint — not the generator — stores completed response in `jrn_analyses` after the stream finishes (collect full text from streamed chunks, then INSERT).

### 6.2 Pair Prompt Context

```
Trade Analysis Request
======================
Symbol:     NIFTY 23200 PE (OPTIDX, NSE)
Date:       2026-06-03  |  Broker: zerodha
Side:       LONG  |  Qty: 65 (1 lot)
Entry:      ₹47.20  |  Exit: ₹35.80
Hold time:  4m 32s
Gross P&L:  -₹734.00
Charges:    brokerage ₹20 · STT ₹32 · exchange ₹15 · stamp ₹1 · SEBI ₹0.05 · GST ₹6.3 = ₹74.35
Net P&L:    -₹808.35

Rule violations: max_daily_loss (net_pnl < -5000)

Trader notes (rationale): [text if set]
Trader notes (mistakes):  [text if set]

Provide: (1) what likely went wrong, (2) pattern if visible, (3) one actionable improvement.
```

### 6.3 Day Prompt

Same structure but with `DaySummary` fields + all pairs listed as a table. Triggered from summary view "Analyze Day" button.

### 6.4 Frontend

`LlmAnalysis.tsx`:
- "Analyze" button → `POST /journal/pairs/{id}/analyze`
- Opens SSE connection, appends tokens to state string
- Renders as markdown (use existing markdown renderer if present, else `<pre>`)
- If `jrn_analyses` row exists for this pair: show cached response + "Re-analyze" button
- `[DONE]` sentinel closes EventSource

---

## 7. Trade Annotations

Fields already in `jrn_trade_pairs` schema: `trade_rationale TEXT`, `trade_mistakes TEXT`, `session_notes TEXT`.

```
PATCH /journal/pairs/{id}/annotate
Body: { "trade_rationale": "...", "trade_mistakes": "...", "session_notes": "..." }
```

`AnnotationEditor.tsx`: three labeled textarea fields. "Save" button fires PATCH. Success: brief "Saved ✓" inline (no toast library needed). Pre-populated from pair data on load.

Annotations fed into LLM prompt if non-empty.

---

## 8. API Import

### 8.1 Auth Wiring

Parsers exist. Auth reads:

| Broker | Auth source |
|---|---|
| Kite | `api_key` + `access_token` from Redis session (same as rest of app) |
| Upstox | Bearer token from Redis `upstox:access_token` |
| mStock API | JWT from Redis `mstock:access_token`; skip if token absent (out of scope — mStock auth flow is separate; implement Kite+Upstox first) |

`POST /journal/import/api` body: `{ broker: "kite" | "upstox" | "mstock", trade_date: "YYYY-MM-DD" }`.

Date param accepts any date (not today-only). Parsers already handle date ranges.

### 8.2 Frontend

`ImportPanel.tsx` — add API tab alongside existing PDF tab:

```
[ PDF ] [ API ]

Broker:  [Kite ▼]
Date:    [2026-06-05]
         [Import Trades]
```

On success: same flow as PDF import — `reset()` + `fetchSummaries()` + switch to Summary tab.

---

## 9. Phase 1 Lessons Applied

| Lesson | Applied where |
|---|---|
| asyncpg JSONB = raw string, must `json.loads()` | All new endpoints use `_to_dict(r, jsonb=(...))` |
| Crash-on-back from stale Zustand state | Full page route → React Router manages state lifecycle |
| Per-broker FIFO isolation | Pair detail shows broker prominently; violations per-broker |
| WAP grain has no timestamps | Chart shows price lines only; hold_seconds shown as null |
| `idx_jt_pdf_uniq` blocked fill-grain rows | No new dedup indexes needed; existing partial indexes correct |
| Playwright `page.on('pageerror')` catches silent crashes | Wired in all new e2e tests |

---

## 10. Test Strategy

### 10.1 Backend (pytest)

**`test_rules.py`**
- Each built-in rule_type fires on matching data, no false-positive on non-matching
- `@register` decorator adds to `_EVALUATORS` — new type callable without other changes
- `evaluate_rules` with empty rules list → empty violations

**`test_analysis.py`**
- `build_pair_prompt` includes symbol, P&L, violations, annotations when non-empty
- Annotations omitted from prompt when empty (no "Trader notes: None" noise)
- SSE stream returns non-empty string before `[DONE]`

**`test_pair_detail.py`**
- `GET /journal/pairs/{id}` expands fills, JSONB charges parsed, 404 on missing id
- `PATCH /journal/pairs/{id}/annotate` persists all three fields; partial update works

### 10.2 Frontend Playwright (e2e)

All tests wire `page.on('pageerror', e => { throw e })` (Phase 1 lesson).

- **Navigation:** click pair row → URL becomes `/journal/pairs/:id`; browser back → `/journal`, day still selected, no crash
- **Annotations:** type rationale → Save → reload page → text persists
- **LLM:** click Analyze → streaming text appears; second visit shows cached response
- **Rules tab:** create threshold rule → appears in list; disable toggle → rule absent from violations after recompute
- **API import tab:** select Kite + date → Import → summary refreshes with new day
- **Chart:** renders with entry price line; Play button → bars animate; Reset → full chart returns
- **WAP chart:** banner "Trade times unavailable" visible; no crash on null open_time

---

## 11. Implementation Order

1. Schema migration (`rule_violations` column) + `seed_default_rules` update
2. `backend/journal/rules.py` — registry + 5 built-in evaluators
3. Wire `evaluate_rules` into `_recompute_day`
4. `GET /journal/pairs/{id}` endpoint (fills expansion)
5. `PATCH /journal/pairs/{id}/annotate` endpoint
6. Rules CRUD endpoints (`GET/POST/PATCH/DELETE /journal/rules`)
7. `backend/journal/analysis.py` + SSE endpoints
8. API import auth wiring (Kite + Upstox; mStock if token present)
9. Frontend routing (`/journal/pairs/:id` route in React Router)
10. `PairDetailPage.tsx` skeleton + P&L card + fills table
11. `PairChart.tsx` + replay controls
12. `AnnotationEditor.tsx`
13. `RuleViolations.tsx`
14. `LlmAnalysis.tsx` (SSE consumer)
15. Rules tab in `JournalPage.tsx` + Rules management components
16. API tab in `ImportPanel.tsx`
17. Backend tests (`test_rules`, `test_analysis`, `test_pair_detail`)
18. Playwright e2e tests (all journeys above)
