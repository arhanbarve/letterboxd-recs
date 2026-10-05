// The demo tabs render a bundled snapshot, so they need no backend, no
// username and no access code — and must never call the API.
import { test, expect } from "@playwright/test";

let apiCalls;
test.beforeEach(async ({ page }) => {
  apiCalls = [];
  page.on("request", (r) => { if (r.url().includes("/api/")) apiCalls.push(r.url()); });
});

test("demo recs: hero, grid, popup with providers, no API calls", async ({ page }) => {
  await page.goto("/demo");
  await expect(page.locator(".control-bar")).toHaveCount(0);
  await expect(page.locator(".trio-panel")).toHaveCount(3);
  expect(await page.locator(".card").count()).toBeGreaterThanOrEqual(20);
  await page.locator(".trio-panel").first().click();  // The Aviator: has overview + providers
  await expect(page.locator(".expand-overview")).toBeVisible();
  await expect(page.locator(".provider-row").first()).toBeVisible();
  await page.keyboard.press("Escape");
  await page.locator(".long-shots-toggle").click();
  await page.locator(".long-shots-section .card").first().click();
  await expect(page.locator(".expand-card")).toBeVisible();
  expect(apiCalls).toEqual([]);
});

test("demo taste: dashboard renders, no API calls", async ({ page }) => {
  await page.goto("/demo/taste");
  await expect(page.locator(".control-bar")).toHaveCount(0);
  await expect(page.locator(".dashboard-eyebrow")).toBeVisible();
  await expect(page.locator(".histogram-bar")).toHaveCount(10);
  await expect(page.locator(".genre-radar .radar-vertex")).toHaveCount(10);
  expect(await page.locator(".person-card, .people-wall > *").count()).toBeGreaterThan(0);
  expect(apiCalls).toEqual([]);
});

test("demo tabs sit beside the real ones", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".control-bar")).toBeVisible();
  await page.getByRole("link", { name: "Demo: Taste" }).click();
  await expect(page).toHaveURL(/\/demo\/taste$/);
  await page.getByRole("link", { name: "Demo: Recs" }).click();
  await expect(page).toHaveURL(/\/demo$/);
});
