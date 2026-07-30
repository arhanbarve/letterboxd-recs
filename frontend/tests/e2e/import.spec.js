// End-to-end test for the Letterboxd export import flow.
//
// Precondition: the backend running on 127.0.0.1:8000 (Vite dev server is
// started by playwright.config.js). Uses its own username so it never disturbs
// the developer's real imported data; the username comes from the fixture's
// profile.csv, which is authoritative.
//
// Fixture is synthetic — regenerate with:
//   cd backend && .venv/bin/python scripts/make_sample_export.py
import { fileURLToPath } from "node:url";
import { test, expect } from "@playwright/test";

const FIXTURE = fileURLToPath(new URL("./fixtures/letterboxd-export-sample.zip", import.meta.url));
const FIXTURE_USER = "e2e-sample";

test.beforeEach(async ({ page }) => {
  // A username with no import yet, so the guided panel is what renders.
  await page.addInitScript(() => localStorage.setItem("letterboxd_username", "e2e-no-import"));
});

test("cold start shows the guided export instructions", async ({ page }) => {
  await page.goto("/");
  const panel = page.locator(".import-panel");
  await expect(panel).toBeVisible();
  await expect(panel.locator("a[href*='letterboxd.com/settings/data']")).toBeVisible();
  await expect(panel.locator(".import-input")).toBeVisible();
  // Nothing to score yet, so refreshing is blocked rather than failing loudly.
  await expect(page.locator(".refresh-btn")).toBeDisabled();
});

test("uploading an export imports the films and unlocks refresh", async ({ page }) => {
  await page.goto("/");
  await page.locator(".import-panel .import-input").setInputFiles(FIXTURE);

  // The guided panel collapses to the compact re-import control...
  await expect(page.locator(".import-panel")).toHaveCount(0, { timeout: 15000 });
  await expect(page.locator(".import-compact .import-btn")).toBeVisible();
  // ...refresh becomes available...
  await expect(page.locator(".refresh-btn")).toBeEnabled();
  await expect(page.locator(".refresh-btn")).toHaveText("Refresh recommendations");
  // ...the film count is reported...
  await expect(page.locator(".empty-state")).toContainText("6 films imported");
  // ...and the username was taken from the export's profile.csv, not the typed one.
  await expect(page.locator("#letterboxd-username")).toHaveValue(FIXTURE_USER);
});

test("uploading a non-export file reports why, without wiping state", async ({ page }) => {
  await page.goto("/");
  await page.locator(".import-panel .import-input").setInputFiles({
    name: "ratings.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("Name,Year\nParasite,2019\n"),
  });
  await expect(page.locator(".import-error")).toContainText("zip");
  await expect(page.locator(".import-panel")).toBeVisible();  // still usable, can retry
  await expect(page.locator(".refresh-btn")).toBeDisabled();
});
