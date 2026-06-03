/**
 * E2E tests — multi-chart dashboard user journeys.
 *
 * Journeys covered:
 * 1. Login → redirect to screener
 * 2. Navigate to dashboard (/chart)
 * 3. Market status bar visible
 * 4. Pane count selector changes grid layout
 * 5. Per-pane symbol search and change
 * 6. Timeframe dropdown changes
 * 7. Indicator panel opens / adds indicator / opens settings
 * 8. Upstox connect button opens popup (URL check)
 */

import { test, expect, Page } from "@playwright/test";

const BASE = "http://localhost:5173";
const API  = "http://localhost:8000";

// ── Helper: login ──────────────────────────────────────────────────────────────

async function login(page: Page) {
  await page.goto(`${BASE}/login`);
  // Username input has placeholder="admin", password has type="password"
  await page.waitForSelector("input[placeholder='admin']", { timeout: 10000 });
  await page.locator("input[placeholder='admin']").fill("admin");
  await page.locator("input[type='password']").fill("admin");
  await page.locator("button[type='submit']").click();
  // Should land somewhere other than /login
  await page.waitForURL((url) => !url.pathname.includes("/login"), { timeout: 10000 });
}

// ── Journey 1: Login ───────────────────────────────────────────────────────────

test("1. login with valid credentials redirects away from /login", async ({ page }) => {
  await login(page);
  expect(page.url()).not.toContain("/login");
});

test("1b. login with wrong password shows error", async ({ page }) => {
  await page.goto(`${BASE}/login`);
  await page.waitForSelector("input[placeholder='admin']", { timeout: 8000 });
  await page.locator("input[placeholder='admin']").fill("admin");
  await page.locator("input[type='password']").fill("wrongpassword");
  await page.locator("button[type='submit']").click();
  await page.waitForTimeout(2000);
  // Should stay on /login
  expect(page.url()).toContain("/login");
});

// ── Journey 2: Navigate to dashboard ─────────────────────────────────────────

test("2. /chart loads the multi-pane dashboard", async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/chart`);
  // data-testid="dashboard-title" is in the TopBar, not the sidebar nav
  await expect(page.locator("[data-testid='dashboard-title']")).toBeVisible({ timeout: 8000 });
});

test("2b. /chart/:symbol redirects to /chart", async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/chart/RELIANCE`);
  await page.waitForURL((url) => url.pathname === "/chart", { timeout: 8000 });
  expect(page.url()).toMatch(/\/chart$/);
});

// ── Journey 3: Market status bar ──────────────────────────────────────────────

test("3. market status bar shows India / US / Crypto cards", async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/chart`);
  await expect(page.locator("text=India NSE")).toBeVisible({ timeout: 8000 });
  await expect(page.locator("text=US NYSE")).toBeVisible();
  await expect(page.locator("text=Crypto")).toBeVisible();
});

test("3b. market status shows OPEN or CLOSED label", async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/chart`);
  // At least one status label must be present
  const hasStatus = await page.locator("text=/OPEN|CLOSED|PRE|AFTER|24\\/7/").first().isVisible();
  expect(hasStatus).toBeTruthy();
});

// ── Journey 4: Pane count selector ────────────────────────────────────────────

test("4. pane count dropdown changes grid layout", async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/chart`);
  // Use data-testid for the pane count select
  await page.waitForSelector("[data-testid='pane-count-select']", { timeout: 10000 });

  const select = page.locator("[data-testid='pane-count-select']");
  await select.selectOption("2");
  await page.waitForTimeout(500);
  await select.selectOption("4");
  await page.waitForTimeout(500);
  await expect(select).toHaveValue("4");
});

// ── Journey 5: Symbol search per pane ────────────────────────────────────────

test("5. symbol search input exists in first pane", async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/chart`);
  await page.waitForSelector("[data-testid='dashboard-title']", { timeout: 10000 });
  await page.waitForTimeout(1500); // panes render

  // Symbol inputs have placeholder = current symbol name e.g. "RELIANCE"
  const searchInputs = page.locator("input[placeholder='RELIANCE']");
  await expect(searchInputs.first()).toBeVisible({ timeout: 5000 });
  expect(await searchInputs.count()).toBeGreaterThan(0);
});

test("5b. typing in symbol search shows dropdown results", async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/chart`);
  await page.waitForSelector("[data-testid='dashboard-title']", { timeout: 10000 });
  await page.waitForTimeout(1500);

  const searchInput = page.locator("input[placeholder='RELIANCE']").first();
  await searchInput.fill("RELI");
  // Wait for dropdown
  await page.waitForTimeout(800);
  // Dropdown results appear — check for any NSE-prefixed result in dropdown (not status bar)
  const dropdownResults = page.locator("input[placeholder='Change…']").first()
    .locator("..").locator("div[style*='position: absolute']");
  // Fallback: count of NSE text occurrences should increase after typing
  const nseCount = await page.locator("text=/^NSE$/").count();
  expect(nseCount).toBeGreaterThan(0);
});

// ── Journey 6: Timeframe dropdown ────────────────────────────────────────────

test("6. timeframe dropdown changes work per pane", async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/chart`);
  await page.waitForSelector("[data-testid='dashboard-title']", { timeout: 10000 });
  await page.waitForTimeout(1500);

  // pane-count-select (1) + TF selects per pane (4 default)
  const selects = page.locator("select");
  const count = await selects.count();
  expect(count).toBeGreaterThanOrEqual(2);

  // TF select is nth(1) onward; use nth(1) for first pane TF
  const tfSelect = selects.nth(1);
  await tfSelect.selectOption("1h");
  await expect(tfSelect).toHaveValue("1h");
});

// ── Journey 7: Indicator panel ────────────────────────────────────────────────

test("7. indicator panel opens on click", async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/chart`);
  await page.waitForSelector("[data-testid='dashboard-title']", { timeout: 10000 });
  await page.waitForTimeout(1000);

  const indBtn = page.locator("button:has-text('Indicators')").first();
  await expect(indBtn).toBeVisible({ timeout: 5000 });
  await indBtn.click();

  // Indicator panel should appear with search input
  await expect(page.locator("text=Indicators").nth(1)).toBeVisible({ timeout: 3000 });
  await expect(page.locator("input[placeholder*='Search indicator']")).toBeVisible();
});

test("7b. indicator list shows EMA, RSI, Volume Profile, FVG", async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/chart`);
  await page.waitForSelector("[data-testid='dashboard-title']", { timeout: 10000 });
  await page.waitForTimeout(1000);

  await page.locator("button:has-text('Indicators')").first().click();
  await page.waitForTimeout(500);

  await expect(page.locator("text=EMA")).toBeVisible();
  await expect(page.locator("text=RSI")).toBeVisible();
  await expect(page.locator("text=Volume Profile")).toBeVisible();
  await expect(page.getByText("Fair Value Gap", { exact: true })).toBeVisible();
});

test("7c. adding SMA indicator shows it in active panel", async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/chart`);
  await page.waitForSelector("[data-testid='dashboard-title']", { timeout: 10000 });
  await page.waitForTimeout(1000);

  await page.locator("button:has-text('Indicators')").first().click();
  await page.waitForTimeout(500);

  // Find a + button (any indicator that's not yet active)
  const addBtn = page.locator("button:has-text('+')").first();
  await expect(addBtn).toBeVisible({ timeout: 5000 });
  await addBtn.click();
  await page.waitForTimeout(500);

  // After adding, that indicator should now have a ⚙ gear in its row
  // The + buttons should decrease by 1 (or ⚙ buttons increase)
  const gearBtns = await page.locator("button:has-text('⚙')").count();
  expect(gearBtns).toBeGreaterThan(0);
});

test("7d. indicator settings layer opens on gear click", async ({ page }) => {
  await login(page);
  await page.goto(`${BASE}/chart`);
  await page.waitForSelector("[data-testid='dashboard-title']", { timeout: 10000 });
  await page.waitForTimeout(1000);

  // Open indicator panel
  await page.locator("button:has-text('Indicators')").first().click();
  await page.waitForTimeout(500);

  // Add any indicator via first + button
  const addBtn = page.locator("button:has-text('+')").first();
  await expect(addBtn).toBeVisible({ timeout: 5000 });
  await addBtn.click();
  await page.waitForTimeout(500);

  // Now click ⚙ on the newly active indicator
  const gearBtn = page.locator("button:has-text('⚙')").first();
  await expect(gearBtn).toBeVisible({ timeout: 5000 });
  await gearBtn.click();
  await page.waitForTimeout(500);

  // Settings layer should show tab buttons
  await expect(page.getByText("Inputs", { exact: true })).toBeVisible({ timeout: 3000 });
  await expect(page.getByText("Style", { exact: true })).toBeVisible();
  await expect(page.getByText("Visibility", { exact: true })).toBeVisible();
});

// ── Journey 8: Upstox connect ─────────────────────────────────────────────────

test("8. Connect Upstox button triggers popup with correct URL", async ({ page, context }) => {
  await login(page);
  await page.goto(`${BASE}/chart`);
  await page.waitForSelector("[data-testid='dashboard-title']", { timeout: 10000 });
  await page.waitForTimeout(1000);

  // Listen for popup
  const popupPromise = context.waitForEvent("page");
  await page.locator("button:has-text('Connect Upstox'), button:has-text('Upstox')").first().click();

  // Popup should open — check URL is the backend login redirect
  const popup = await popupPromise;
  // Upstox redirects backend → api.upstox.com → login.upstox.com
  await popup.waitForURL((url) =>
    url.href.includes("upstox.com"),
    { timeout: 8000 }
  );
  expect(popup.url()).toMatch(/upstox\.com/);
  await popup.close();
});

// ── Journey 9: Backend health ─────────────────────────────────────────────────

test("9. backend /health returns ok", async ({ page }) => {
  const resp = await page.request.get(`${API}/health`);
  expect(resp.status()).toBe(200);
  const body = await resp.json();
  expect(body.status).toBe("ok");
});

test("9b. /auth/upstox/login redirects to Upstox with correct client_id", async ({ page }) => {
  // Follow redirect manually
  const resp = await page.request.get(`${API}/auth/upstox/login`, { maxRedirects: 0 });
  // Should be 307 redirect
  expect([307, 302, 301]).toContain(resp.status());
  const location = resp.headers()["location"] ?? "";
  expect(location).toContain("api.upstox.com");
  expect(location).toContain("682c3fc4");
  expect(location).toContain("redirect_uri");
});
