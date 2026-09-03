// End-to-end test for the Letterboxd export import flow.
//
// Precondition: the backend running on 127.0.0.1:8000 (Vite dev server is
// started by playwright.config.js).
//
// Importing claims a username permanently — the backend mints an access code on
// first import and refuses later imports without it — so the importing test uses
// a freshly generated username and the profile-less fixture, which lets the
// typed username be authoritative. (That profile.csv takes precedence over the
// typed name is covered by the backend's own tests.)
//
// Fixtures are synthetic — regenerate with:
//   cd backend && .venv/bin/python scripts/make_sample_export.py
import { fileURLToPath } from "node:url";
import { test, expect } from "@playwright/test";

const FIXTURE_NO_PROFILE = fileURLToPath(
  new URL("./fixtures/letterboxd-export-sample-no-profile.zip", import.meta.url));

const freshUser = () => `e2e-${Date.now()}-${Math.floor(Math.random() * 1e6)}`;

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

test("uploading an export imports the films, mints a code, and unlocks refresh", async ({ page }) => {
  const user = freshUser();
  await page.addInitScript((u) => localStorage.setItem("letterboxd_username", u), user);
  await page.goto("/");
  await page.locator(".import-panel .import-input").setInputFiles(FIXTURE_NO_PROFILE);

  // The guided panel collapses to the compact re-import control...
  await expect(page.locator(".import-panel")).toHaveCount(0, { timeout: 15000 });
  await expect(page.locator(".import-compact .import-btn")).toBeVisible();
  // ...refresh becomes available...
  await expect(page.locator(".refresh-btn")).toBeEnabled();
  await expect(page.locator(".refresh-btn")).toHaveText("Refresh recommendations");
  // ...the film count is reported...
  await expect(page.locator(".empty-state")).toContainText("6 films imported");
  // ...and the access code that now guards this username is shown exactly once.
  const code = page.locator(".access-panel.issued .access-code");
  await expect(code).toBeVisible();
  expect((await code.innerText()).trim().length).toBeGreaterThanOrEqual(32);
});

test("a claimed username stays locked until the right code is pasted", async ({ page }) => {
  const user = freshUser();
  await page.addInitScript((u) => localStorage.setItem("letterboxd_username", u), user);
  await page.goto("/");
  await page.locator(".import-panel .import-input").setInputFiles(FIXTURE_NO_PROFILE);
  await expect(page.locator(".access-panel.issued")).toBeVisible({ timeout: 15000 });
  const code = (await page.locator(".access-panel.issued .access-code").innerText()).trim();

  // A second browser: same username, no stored code. The data must stay hidden
  // and the import panel must not offer to overwrite it.
  await page.context().clearCookies();
  await page.addInitScript((u) => {
    localStorage.clear();
    localStorage.setItem("letterboxd_username", u);
  }, user);
  await page.goto("/");

  await expect(page.locator(".access-panel")).toBeVisible();
  await expect(page.locator(".access-panel h3")).toContainText("already taken");
  await expect(page.locator(".import-panel")).toHaveCount(0);
  await expect(page.locator(".refresh-btn")).toBeDisabled();

  // A wrong code changes nothing.
  await page.locator("#access-code-input").fill("not-the-right-code");
  await page.locator(".access-form .import-btn").click();
  await expect(page.locator(".import-error")).toContainText("doesn't match");
  await expect(page.locator(".refresh-btn")).toBeDisabled();

  // The real one restores access.
  await page.locator("#access-code-input").fill(code);
  await page.locator(".access-form .import-btn").click();
  await expect(page.locator(".access-panel")).toHaveCount(0, { timeout: 10000 });
  await expect(page.locator(".empty-state")).toContainText("6 films imported");
  await expect(page.locator(".refresh-btn")).toBeEnabled();
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
