// End-to-end tests for the REEL recommendations UI.
//
// Precondition: a backend running with seeded data for a known username, plus
// the Vite dev server (Playwright starts `npm run dev` via playwright.config.js).
// Reuse the local DB the developer has already refreshed. To seed:
//   cd backend && python -m app.pipeline --username <USER>   # or refresh via the UI
// Run with:  E2E_USERNAME=<USER> npm run e2e
import { test, expect } from "@playwright/test";

const USER = process.env.E2E_USERNAME || "moviefan";

test.beforeEach(async ({ page }) => {
  // useLocalStorage stores plain strings (no JSON) — must match that format.
  await page.addInitScript((u) => localStorage.setItem("letterboxd_username", u), USER);
});

test("header + one-line control bar render", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".bulb-title")).toHaveText("REEL");
  const bar = page.locator(".control-bar");
  await expect(bar.locator(".username-field")).toBeVisible();
  await expect(bar.locator(".refresh-btn")).toBeVisible();
});

test("at least 20 recommendations render and hero shows predicted", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".trio-match").first()).toContainText("predicted");
  await expect(page.locator(".card")).toHaveCount(20, { timeout: 15000 }).catch(async () => {
    expect(await page.locator(".card").count()).toBeGreaterThanOrEqual(20);
  });
});

test("clicking a card expands to center; Esc closes", async ({ page }) => {
  await page.goto("/");
  await page.locator(".card").first().click();
  await expect(page.locator(".expand-card")).toBeVisible();
  // Not .expand-hero: it only renders when TMDB has a backdrop for the film, and
  // plenty of obscure titles have none.
  await expect(page.locator(".expand-title")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator(".expand-card")).toHaveCount(0);
});

test("long shots reveal 50 at a time and open without reload", async ({ page }) => {
  await page.goto("/");
  const toggle = page.locator(".long-shots-toggle");
  if (await toggle.count()) {
    await toggle.click();
    const longCards = page.locator(".long-shots-section .card");
    expect(await longCards.count()).toBeLessThanOrEqual(50);
    await longCards.first().click();
    await expect(page.locator(".expand-card")).toBeVisible();  // regression: opened without reload
  }
});

test("taste profile is its own URL, centered, half-star histogram, 10-axis radar", async ({ page }) => {
  await page.goto("/taste");
  await expect(page).toHaveURL(/\/taste$/);
  await expect(page.locator(".dashboard-eyebrow")).toBeVisible();
  await expect(page.locator(".histogram-bar")).toHaveCount(10);
  await expect(page.locator(".genre-radar .radar-vertex")).toHaveCount(10);
});

test("hovering a director reveals top films", async ({ page }) => {
  await page.goto("/taste");
  await page.locator(".person-face").first().hover();
  await expect(page.locator(".person-popover").first()).toBeVisible();
});
