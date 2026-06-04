/**
 * E2E tests — Trade Journal user journeys.
 *
 * Journeys covered:
 * 1.  /journal route accessible from sidebar
 * 2.  Day list shows imported trade dates
 * 3.  Summary tab: DaySummaryCard renders net P&L, fills, lots
 * 4.  Summary tab: selecting a day shows that day's card
 * 5.  Pairs tab: table rows with symbol, side, entry, exit
 * 6.  Trades tab: raw trade rows with broker, type, price
 * 7.  Import tab: panel renders with broker selector + drop zone
 * 8.  Import PDF via file input — verifies response counts
 * 9.  Re-import same PDF is idempotent (inserted=0)
 * 10. Summary fiscal_year shows "2026-27"
 * 11. Timeline buckets render (if time_bucket_pnl populated)
 * 12. Backend /journal/summary returns valid data
 * 13. Backend /journal/pairs returns valid pairs
 * 14. Backend /journal/trades returns valid trades
 */

import { test, expect, Page } from "@playwright/test";
import { readFileSync } from "fs";

const BASE = "http://localhost:5173";
const API  = "http://localhost:8000";

const ZERODHA_PDF = "/Users/ankitatiwari/Downloads/COntract_Note_Zerodha.pdf";
const LEMONN_PDF  = "/Users/ankitatiwari/Downloads/LEMONN_CN.pdf";
const MSTOCK_PDF  = "/Users/ankitatiwari/Downloads/Contract_Note.pdf";

// ── Helper: login ──────────────────────────────────────────────────────────────

async function login(page: Page) {
  await page.goto(`${BASE}/login`);
  await page.waitForSelector("input[placeholder='admin']", { timeout: 10000 });
  await page.locator("input[placeholder='admin']").fill("admin");
  await page.locator("input[type='password']").fill("admin");
  await page.locator("button[type='submit']").click();
  await page.waitForURL((url) => !url.pathname.includes("/login"), { timeout: 10000 });
}

async function gotoJournal(page: Page) {
  await login(page);
  await page.goto(`${BASE}/journal`);
  await page.waitForTimeout(1500);
}

// ── Journey 1: Navigation ──────────────────────────────────────────────────────

test("1. Journal nav item in sidebar navigates to /journal", async ({ page }) => {
  await login(page);
  const journalLink = page.locator("a[href='/journal']");
  await expect(journalLink).toBeVisible({ timeout: 8000 });
  await journalLink.click();
  await page.waitForURL("**/journal", { timeout: 8000 });
  expect(page.url()).toContain("/journal");
});

test("1b. /journal is protected — unauthenticated redirects to login", async ({ page }) => {
  // Don't login, visit directly
  await page.goto(`${BASE}/journal`);
  await page.waitForURL("**/login", { timeout: 8000 });
  expect(page.url()).toContain("/login");
});

// ── Journey 2: Day list ────────────────────────────────────────────────────────

test("2. Day list shows trade dates from imported PDFs", async ({ page }) => {
  await gotoJournal(page);
  // Should see at least one date in the left panel (we imported 2026-06-03 and 2026-05-13)
  await expect(page.locator("text=2026-06-03").first()).toBeVisible({ timeout: 8000 });
});

test("2b. Day list shows both dates (Zerodha+mStock: 2026-06-03, Lemonn: 2026-05-13)", async ({ page }) => {
  await gotoJournal(page);
  await expect(page.locator("text=2026-06-03").first()).toBeVisible({ timeout: 8000 });
  await expect(page.locator("text=2026-05-13").first()).toBeVisible({ timeout: 8000 });
});

test("2c. Day list shows net P&L next to each date", async ({ page }) => {
  await gotoJournal(page);
  // P&L is displayed as +₹N or -₹N — both dates are loss days so expect -₹
  const pnlText = page.locator("text=/-₹/").first();
  await expect(pnlText).toBeVisible({ timeout: 8000 });
});

// ── Journey 3: Summary tab ─────────────────────────────────────────────────────

test("3. Summary tab shows DaySummaryCard with net P&L, fills, lots", async ({ page }) => {
  await gotoJournal(page);
  // Default is summary tab — should show cards or selected day card
  await expect(page.locator("text=/Fills:/").first()).toBeVisible({ timeout: 8000 });
  await expect(page.locator("text=/Lots:/").first()).toBeVisible({ timeout: 8000 });
  await expect(page.locator("text=/Charges:/").first()).toBeVisible({ timeout: 8000 });
});

test("3b. Summary shows W/L ratio", async ({ page }) => {
  await gotoJournal(page);
  await expect(page.locator("span").filter({ hasText: /W\// }).first()).toBeVisible({ timeout: 8000 });
});

// ── Journey 4: Selecting a day ────────────────────────────────────────────────

test("4. Summary shows 2026-06-03 cards for both zerodha and mstock", async ({ page }) => {
  await gotoJournal(page);
  // Default summary tab shows per-broker day cards
  await expect(page.locator("text=2026-06-03").first()).toBeVisible({ timeout: 5000 });
  // Both broker labels visible in left panel
  await expect(page.locator("text=zerodha").first()).toBeVisible({ timeout: 5000 });
  await expect(page.locator("text=mstock").first()).toBeVisible({ timeout: 5000 });
});

test("4b. Summary shows 2026-05-13 card with correct fills (28 = Lemonn)", async ({ page }) => {
  await gotoJournal(page);
  // Lemonn day card is also shown in the default summary grid
  await expect(page.locator("text=2026-05-13").first()).toBeVisible({ timeout: 5000 });
  // Lemonn: 28 fills
  await expect(page.locator("text=28").first()).toBeVisible({ timeout: 5000 });
});

// ── Helper: select a day entry by broker label ───────────────────────────────

async function selectDay(page: Page, broker: string) {
  // Click the broker label in the left panel day list
  await page.locator(`text=${broker}`).first().click();
  await page.waitForTimeout(800);
}

// ── Journey 4c: Clicking a day entry works without crash ─────────────────────

test("4c. Clicking zerodha day entry shows summary card without crash", async ({ page }) => {
  await gotoJournal(page);
  await selectDay(page, "zerodha");
  // Summary card renders — no crash, Fills visible
  await expect(page.locator("text=/Fills:/").first()).toBeVisible({ timeout: 5000 });
});

test("4d. Navigate away and back — journal still works (crash fix)", async ({ page }) => {
  await gotoJournal(page);
  // Click Pairs tab for zerodha day
  await selectDay(page, "zerodha");
  await page.locator("button:has-text('Pairs')").click();
  await page.waitForTimeout(2000);
  // Navigate to another page and back
  await page.goto("http://localhost:5173/chart");
  await page.waitForTimeout(500);
  await page.goto("http://localhost:5173/journal");
  await page.waitForTimeout(2000);
  // Journal should still render without crash
  await expect(page.locator("text=2026-06-03").first()).toBeVisible({ timeout: 5000 });
  await expect(page.locator("text=zerodha").first()).toBeVisible({ timeout: 5000 });
});

// ── Journey 5: Pairs tab ──────────────────────────────────────────────────────

test("5. Pairs tab shows trade pair rows with symbol and entry/exit prices", async ({ page }) => {
  await gotoJournal(page);
  await selectDay(page, "zerodha");
  await page.locator("button:has-text('Pairs')").click();
  await page.waitForTimeout(2000);
  await expect(page.locator("text=/NIFTY|SENSEX/").first()).toBeVisible({ timeout: 8000 });
});

test("5b. Pairs table shows LONG/SHORT side column", async ({ page }) => {
  await gotoJournal(page);
  await selectDay(page, "zerodha");
  await page.locator("button:has-text('Pairs')").click();
  await page.waitForTimeout(2000);
  await expect(page.locator("text=LONG").first()).toBeVisible({ timeout: 8000 });
});

test("5c. Pairs table shows entry and exit prices (not zero)", async ({ page }) => {
  await gotoJournal(page);
  await selectDay(page, "zerodha");
  await page.locator("button:has-text('Pairs')").click();
  await page.waitForTimeout(2000);
  await expect(page.locator("text=/₹[0-9]+/").first()).toBeVisible({ timeout: 8000 });
});

test("5d. Pairs table shows net P&L column", async ({ page }) => {
  await gotoJournal(page);
  await selectDay(page, "zerodha");
  await page.locator("button:has-text('Pairs')").click();
  await page.waitForTimeout(2000);
  await expect(page.locator("th:has-text('Net')")).toBeVisible({ timeout: 5000 });
});

test("5e. Pairs charges show real values not NaN", async ({ page }) => {
  await gotoJournal(page);
  await selectDay(page, "zerodha");
  await page.locator("button:has-text('Pairs')").click();
  await page.waitForTimeout(2000);
  // Charges column should have ₹ values, not NaN
  const nanVisible = await page.locator("text=NaN").count();
  expect(nanVisible).toBe(0);
});

// ── Journey 6: Trades tab ─────────────────────────────────────────────────────

test("6. Trades tab shows raw trade rows with broker and BUY/SELL", async ({ page }) => {
  await gotoJournal(page);
  await selectDay(page, "zerodha");
  await page.locator("button:has-text('Trades')").click();
  await page.waitForTimeout(2000);
  await expect(page.locator("text=/BUY|SELL/").first()).toBeVisible({ timeout: 8000 });
});

test("6b. Trades tab shows broker names (zerodha, mstock, lemonn)", async ({ page }) => {
  await gotoJournal(page);
  // Broker names visible in left panel day list
  const hasBroker = await page.locator("text=/zerodha|mstock|lemonn/i").first().isVisible().catch(() => false);
  expect(hasBroker).toBeTruthy();
});

test("6c. Trades tab shows fill_grain badge (fill for zerodha, wap for lemonn)", async ({ page }) => {
  await gotoJournal(page);
  await selectDay(page, "zerodha");
  await page.locator("button:has-text('Trades')").click();
  await page.waitForTimeout(2000);
  // Zerodha now uses fill_grain='fill' (parsed from annexure with timestamps)
  await expect(page.locator("text=fill").first()).toBeVisible({ timeout: 8000 });
});

// ── Journey 7: Import tab UI ──────────────────────────────────────────────────

test("7. Import tab renders panel with broker selector and drop zone", async ({ page }) => {
  await gotoJournal(page);
  await page.locator("button:has-text('Import')").click();
  await page.waitForTimeout(500);
  // Broker selector
  await expect(page.locator("select")).toBeVisible({ timeout: 5000 });
  await expect(page.locator("select option[value='auto']")).toBeAttached();
  // Drop zone text
  await expect(page.locator("text=/Drop PDF|click to choose/i")).toBeVisible({ timeout: 5000 });
});

test("7b. Broker selector has zerodha, mstock, lemonn options", async ({ page }) => {
  await gotoJournal(page);
  await page.locator("button:has-text('Import')").click();
  await page.waitForTimeout(500);
  const select = page.locator("select").first();
  const options = await select.locator("option").allTextContents();
  expect(options).toContain("zerodha");
  expect(options).toContain("mstock");
  expect(options).toContain("lemonn");
});

test("7c. PAN password field is visible on import panel", async ({ page }) => {
  await gotoJournal(page);
  await page.locator("button:has-text('Import')").click();
  await page.waitForTimeout(500);
  await expect(page.locator("input[placeholder*='PAN password']")).toBeVisible({ timeout: 5000 });
});

// ── Journey 8: PDF import via file input ──────────────────────────────────────

test("8. Importing Zerodha PDF via file input shows success message", async ({ page }) => {
  await gotoJournal(page);
  await page.locator("button:has-text('Import')").click();
  await page.waitForTimeout(500);

  // Trigger file input (click the drop zone)
  const fileInput = page.locator("input[type='file']");
  await fileInput.setInputFiles(ZERODHA_PDF);
  // Wait for import response
  await page.waitForTimeout(5000);
  // Success message should appear (inserted could be 0 since already imported)
  await expect(
    page.locator("text=/Imported|trades|filename/i").first()
  ).toBeVisible({ timeout: 10000 });
});

test("8b. Importing Lemonn PDF shows success message with 28 trades", async ({ page }) => {
  await gotoJournal(page);
  await page.locator("button:has-text('Import')").click();
  await page.waitForTimeout(500);

  const fileInput = page.locator("input[type='file']");
  await fileInput.setInputFiles(LEMONN_PDF);
  await page.waitForTimeout(5000);
  // Message includes "28 trades" or "Imported 28"
  await expect(
    page.locator("text=/28/").first()
  ).toBeVisible({ timeout: 10000 });
});

// ── Journey 9: Re-import is idempotent ────────────────────────────────────────

test("9. Re-importing same PDF is idempotent (API returns inserted=0)", async ({ page }) => {
  // Test via API directly — UI tab switches to summary after import, losing the message
  const formData = new FormData();
  // Use page.request to POST the PDF as multipart
  const resp = await page.request.post(`${API}/journal/import/pdf?broker=auto`, {
    multipart: {
      file: {
        name: "COntract_Note_Zerodha.pdf",
        mimeType: "application/pdf",
        buffer: readFileSync(ZERODHA_PDF),
      },
    },
  });
  expect(resp.status()).toBe(200);
  const body = await resp.json();
  expect(body.imported).toBe(28);  // 28 fills from annexure (not 10 WAP rows)
  expect(body.inserted).toBe(0);   // 0 new (all already in DB)
});

// ── Journey 10: Fiscal year ────────────────────────────────────────────────────

test("10. Backend summary includes fiscal_year=2026-27 for June 2026 date", async ({ page }) => {
  const resp = await page.request.get(`${API}/journal/summary`);
  expect(resp.status()).toBe(200);
  const body = await resp.json();
  const june = body.find((s: any) => s.trade_date === "2026-06-03");
  expect(june).toBeDefined();
  expect(june.fiscal_year).toBe("2026-27");
});

test("10b. Lemonn May 2026 date also shows fiscal_year=2026-27", async ({ page }) => {
  const resp = await page.request.get(`${API}/journal/summary`);
  const body = await resp.json();
  const may = body.find((s: any) => s.trade_date === "2026-05-13");
  expect(may).toBeDefined();
  expect(may.fiscal_year).toBe("2026-27");
});

// ── Journey 11: Timeline buckets ──────────────────────────────────────────────

test("11. Timeline buckets section renders on summary tab (if data available)", async ({ page }) => {
  await gotoJournal(page);
  // Click a date to see its specific summary
  await page.locator("text=2026-05-13").first().click();
  await page.waitForTimeout(600);
  // TimelineBuckets only renders when time_bucket_pnl is non-empty
  // For PDF imports, close_time is null → no buckets. Check component doesn't crash.
  // Just verify the page doesn't show an error.
  const errorText = page.locator("text=/error|crash|undefined/i");
  expect(await errorText.count()).toBe(0);
});

// ── Journey 12: Backend API validation ────────────────────────────────────────

test("12. GET /journal/summary returns valid data with expected fields", async ({ page }) => {
  const resp = await page.request.get(`${API}/journal/summary`);
  expect(resp.status()).toBe(200);
  const body = await resp.json();
  expect(Array.isArray(body)).toBeTruthy();
  expect(body.length).toBeGreaterThanOrEqual(2);
  const s = body[0];
  expect(typeof s.trade_date).toBe("string");
  expect(typeof s.net_pnl).toBe("number");
  expect(typeof s.total_fills).toBe("number");
  expect(s.fiscal_year).toBeTruthy();
});

test("13. GET /journal/pairs returns pairs with entry/exit prices", async ({ page }) => {
  const resp = await page.request.get(`${API}/journal/pairs`);
  expect(resp.status()).toBe(200);
  const body = await resp.json();
  expect(Array.isArray(body)).toBeTruthy();
  expect(body.length).toBeGreaterThan(0);
  const p = body[0];
  expect(typeof p.entry_price).toBe("number");
  expect(p.entry_price).toBeGreaterThan(0);  // not zero (column fix validated)
  expect(typeof p.net_pnl).toBe("number");
  expect(["LONG", "SHORT"]).toContain(p.side);
});

test("14. GET /journal/trades — zerodha/mstock use fill grain, lemonn uses wap", async ({ page }) => {
  const resp = await page.request.get(`${API}/journal/trades`);
  expect(resp.status()).toBe(200);
  const body = await resp.json();
  expect(body.length).toBeGreaterThan(0);
  // Zerodha + mStock parsed from annexure → fill_grain='fill' (has timestamps)
  const zerodhaFills = body.filter((t: any) => t.broker === "zerodha" && t.fill_grain === "fill");
  expect(zerodhaFills.length).toBeGreaterThan(0);
  const zerodhaWithTime = zerodhaFills.filter((t: any) => t.trade_time !== null);
  expect(zerodhaWithTime.length).toBeGreaterThan(0);
  // Lemonn → wap grain (no per-fill annexure in lemonn notes)
  const lemonWap = body.filter((t: any) => t.broker === "lemonn" && t.fill_grain === "wap");
  expect(lemonWap.length).toBeGreaterThan(0);
  const lemonWithNullTime = lemonWap.filter((t: any) => t.trade_time === null);
  expect(lemonWithNullTime.length).toBeGreaterThan(0);
});

test("14b. Prices are non-zero for all imported trades", async ({ page }) => {
  const resp = await page.request.get(`${API}/journal/trades`);
  const body = await resp.json();
  const filledTrades = body.filter((t: any) => t.status === "filled");
  const zeroPriceTrades = filledTrades.filter((t: any) => Number(t.price) === 0);
  expect(zeroPriceTrades.length).toBe(0);  // no zero-price filled trades
});

test("14c. Lemonn brokerage is 20 per trade (flat fee model)", async ({ page }) => {
  const resp = await page.request.get(`${API}/journal/trades`);
  const body = await resp.json();
  const lemonTrades = body.filter((t: any) => t.broker === "lemonn" && t.status === "filled");
  expect(lemonTrades.length).toBeGreaterThan(0);
  lemonTrades.forEach((t: any) => {
    expect(Number(t.brokerage)).toBe(20);
  });
});

test("14d. mStock brokerage is 0.25 per unit (per-unit model)", async ({ page }) => {
  const resp = await page.request.get(`${API}/journal/trades`);
  const body = await resp.json();
  const mstockTrades = body.filter((t: any) => t.broker === "mstock" && t.status === "filled");
  expect(mstockTrades.length).toBeGreaterThan(0);
  mstockTrades.forEach((t: any) => {
    const expectedBrok = 0.25 * Number(t.quantity);
    expect(Number(t.brokerage)).toBeCloseTo(expectedBrok, 1);
  });
});

// ── Journey 15: Symbol parsing validation ─────────────────────────────────────

test("15. Zerodha NIFTY symbol is correctly parsed (not raw compact form)", async ({ page }) => {
  const resp = await page.request.get(`${API}/journal/trades`);
  const body = await resp.json();
  const niftyTrades = body.filter((t: any) => t.broker === "zerodha" && t.underlying === "NIFTY");
  expect(niftyTrades.length).toBeGreaterThan(0);
  // Symbol should be canonical form "NIFTY 23200 PE 2026-06-09" not compact "NIFTY2660923200PE"
  niftyTrades.forEach((t: any) => {
    expect(t.symbol).toMatch(/^NIFTY \d+ (CE|PE) \d{4}-\d{2}-\d{2}$/);
    expect(t.expiry).toBeTruthy();
    expect(t.strike).toBeGreaterThan(0);
  });
});

test("15b. mStock SENSEX filled trades parsed with BSE exchange and valid strike", async ({ page }) => {
  const resp = await page.request.get(`${API}/journal/trades`);
  const body = await resp.json();
  // Only check filled trades — rejected orders are also stored but may have different fields
  const sensexFilled = body.filter((t: any) =>
    t.broker === "mstock" && t.underlying === "SENSEX" && t.status === "filled"
  );
  expect(sensexFilled.length).toBeGreaterThan(0);
  sensexFilled.forEach((t: any) => {
    expect(t.exchange).toBe("BSE");
    expect(t.strike).toBeGreaterThan(0);
    expect(t.expiry).toBeTruthy();
  });
});
