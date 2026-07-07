# Refresh & Progress Overhaul — Design

Date: 2026-07-07
Status: Approved for planning

## Problem

The refresh experience is broken across three dimensions:

1. **State loss on navigation.** A refresh started on the Recommendations tab dies visually when the user switches tabs. The backend keeps running, but the UI shows an idle, re-enabled "Refresh my data" button. Clicking it again returns `{status: "already_running"}`, which the frontend ignores, leaving the user stuck with no progress and no way back into the running job.

2. **Useless progress UI.** The progress bar is jumpy and indeterminate for the slowest stages, shows no percent, and the elapsed timer is frozen. There is no ETA and no sense of how far along the run is.

3. **Scrape failures surface as dead ends.** Letterboxd/Cloudflare returns `403` partway through a scrape (observed: `Blocked fetching https://letterboxd.com/moviefan/films/page/2/: status 403 after 3 retries`). The run aborts, all prior work is discarded, and the user cannot cancel a run themselves.

Secondary UX gaps: the button label does not reflect whether data already exists; stale "click Refresh" instructions remain visible after a run starts; the username field layout and typography are weak.

## Root Causes (evidence-based)

- **Idle bug.** Refresh state (`loading`, `progress`, poll interval) lives entirely inside `RecommendationsPage`. Tab switch unmounts the page → `clearInterval(pollRef)` on unmount cleanup → polling stops. The backend already tracks progress globally in `progress_by_user` and exposes `GET /api/refresh/status`, but nothing on the frontend rehydrates from it on mount or shares it across tabs. `RecommendationsPage.jsx:71-92`, `api.py:114-118`.

- **Frozen elapsed timer.** In `ProgressBar.jsx`, the 1-second tick lives in a `useEffect` keyed on `[progress]`. The poll updates `progress` every 800ms, tearing down and recreating the 1000ms interval before it can fire. `setNow` effectively never runs, so the elapsed clock is frozen. `ProgressBar.jsx:43-47`.

- **Jumpy bar.** Scraping and profiling report no `total`, so the bar renders indeterminate for the longest stages. There is no unified percent across stages. `ProgressBar.jsx:51-52`.

- **403 on page 2 (hypothesis, to be confirmed in Phase 0).** `scraper.py:default_get` reuses one Playwright session (`_thread_local.page`). Between films-page-1 and films-page-2 the crawler fires N film-detail requests, so Cloudflare likely flags the session by the time page 2 is requested. Retries reuse the same flagged session, so all four attempts fail. Root cause will be confirmed by live reproduction before any fix is committed. `scraper.py:62-116`.

- **No cancel path.** The refresh runs in a daemon thread with no cancellation mechanism; there is no cancel endpoint and no cancel flag checked inside the pipeline. `api.py:104-112`, `pipeline.py:65-133`.

## Goals

- A refresh survives tab switches and page reloads, and both tabs show its live progress.
- Progress reads as a single, honest, always-forward percent with a working clock and an ETA.
- The user can cancel a running refresh, and cancellation truly stops the backend work.
- Scrape failures are root-caused and fixed, not guessed at.
- Button and instructional copy reflect the actual state (no data yet vs. data exists vs. running).

## Non-Goals

- Resumable/checkpointed scraping (may fall out of the 403 fix, but is not a committed goal here).
- Multi-user concurrency beyond what `progress_by_user` already supports.
- Any change to the recommendation scoring or taste-dashboard logic.

## Design

### 1. Global refresh state — `RefreshContext`

Introduce a `RefreshProvider` mounted at the `App` level. It owns the entire refresh lifecycle for the current username:

- State: `status` (the latest `/api/refresh/status` payload), derived `isRunning`.
- Actions: `start()` (POST `/api/refresh`, then begin polling), `cancel()` (POST `/api/refresh/cancel`).
- A single poll loop (interval) lives here, not in any page.
- **Rehydration:** on mount and whenever `username` changes, it calls `GET /api/refresh/status`. If the stage is active, it resumes polling and exposes the live status immediately — so navigating to either tab, or reloading the page, re-attaches to a running job.

Both `RecommendationsPage` and `TasteProfilePage` become consumers via a `useRefresh()` hook. No page owns `loading` or `progress` anymore. When a run transitions to `done`, the provider triggers each page's data reload (pages subscribe to the done transition, or the provider exposes a `lastCompletedAt` that pages watch).

**Why Context** (over lifting state into `App` with prop-drilling, or an external store): two sibling tabs need the same live state, it must survive page unmount, and the poll loop must be single-owner. Context is the least machinery that satisfies all three.

This section is the root fix for the idle bug (survives tab switch via rehydration) and delivers cross-tab progress (Taste Profile renders the same status).

### 2. Progress redesign — one honest, always-moving percent

Replace the indeterminate bar with a single monotonic **0–100% bar that never moves backward**, computed from weighted stage bands calibrated to real timing:

| Stage      | Band     | Determinacy                            |
|------------|----------|----------------------------------------|
| scraping   | 0–55%    | indeterminate until film count known   |
| enriching  | 55–80%   | determinate (`current/total`)          |
| profiling  | 80–86%   | indeterminate (short)                  |
| scoring    | 86–99%   | determinate (`current/total`)          |
| done       | 100%     | —                                      |

- **Determinate stages** (enriching, scoring): interpolate the band linearly from the real `current/total` the backend already reports.
- **Indeterminate stages** (scraping before a count exists, profiling): **creep** toward the band ceiling as a function of `elapsed_in_stage / estimated_stage_duration`, easing so it approaches but never reaches the ceiling until the real stage change bumps it forward. This is the "fake but honest" percent — synthetic motion bounded by the next real signal.
- **Monotonic guarantee:** the displayed percent is `max(previous, computed)` so a late/again-lower reading can never rewind the bar.
- **Per-step estimates:** stored as constants (e.g. seconds-per-film for scraping and enriching, flat estimates for profiling; scoring scales with candidate count). Used only to drive the creep and the ETA — real counts always win when available.
- **Fixed elapsed timer:** a self-owned 1-second ticker keyed on `[]` (empty deps) that reads timestamps from refs, fully decoupled from the poll cadence. Starts when the run starts, stops on done/error/cancelled.
- **ETA:** derived from remaining bands and their estimates (remaining films × sec-per-film for the active determinate stage, plus flat estimates for later stages).
- **Decluttered layout:** step chip ("Step 2 of 4") · one-line stage label · percent · elapsed + "~ETA left". The long scraper apology note is trimmed to a single quiet line.

The progress component becomes pure: it takes the current `status` (from context) plus its own timing refs and renders. All timing math is unit-testable given a status sequence.

### 3. Data-aware button, CTA copy, and Cancel

- **Button label** (`RefreshButton`):
  - No recommendations/profile yet → **"Load my data"**.
  - Data exists → **"Refresh my data"**.
  - Running → **"Refreshing…"**, disabled.
  - "Has data" is determined from whichever signal the page already holds (recs length / `last_updated`), passed into the button.
- **Cancel button:** rendered beside the refresh button only while running; calls `cancel()`.
- **Stale CTA removal:** the empty-state text "Click Refresh my data to…" is hidden the moment a run starts (gate on `isRunning`), so the user is never told to click a button they already clicked.

### 4. `UsernameField` layout and typography

- Label and input on a **single row** (flex), replacing the stacked label-over-input layout.
- The username input/value renders at a **larger font size** than the label.
- The inline "Saved" affordance is retained.

### 5. Backend cancel — truly abort

- A per-user cancel flag: `cancel_events: dict[str, threading.Event]`, guarded by the existing `progress_lock`.
- `POST /api/refresh/cancel` sets the event for the username.
- `run_refresh` (and the scraper) check the event at loop boundaries — the films-page loop, the per-film-detail loop, the enrich loop, and the scoring loop — and raise a `Cancelled` exception when set.
- The scraper's `_get_page`/scrape path tears down its Playwright browser in a `finally` so a cancelled run does not leak a browser.
- On `Cancelled`, the run sets status stage `cancelled` (new stage) instead of `error`. The provider renders "Cancelled" and resets the UI cleanly (button returns to its data-aware label; no error banner).
- The cancel event is cleared when a new run starts for that username.

### 6. The 403 — reproduce first, then fix

**Phase 0, before any scraper change:** run a live scrape of **moviefan** with per-request instrumentation logging: request URL, HTTP status, whether a Cloudflare challenge/interstitial is present in the returned HTML, and time since the previous request. Run once to gather evidence showing exactly where and why the 403 occurs.

The evidence decides among the candidate fixes (no fix is committed until the log identifies the failing layer):

- **Session flagged by request velocity** → pace requests and/or use a fresh browser context per films-page instead of one long-lived session.
- **Challenge not settled** → replace the fixed `page.wait_for_timeout(2500)` with a wait-for-selector on real page content, so we do not read the interstitial as the result.
- **Pure rate limiting** → longer/again backoff with jitter.

Scrape completeness enforcement (`scraper.py:118-126`) already guards against silently partial crawls and stays.

### 7. Phasing

Single combined plan, implemented and verified in order:

0. **403 reproduction + fix.** Verify: a full scrape of moviefan completes without a 403, or the instrumented log pinpoints the cause and the chosen fix resolves it.
1. **`RefreshContext` + status rehydration.** Verify: start a refresh, switch tabs mid-run, return — progress is still shown and advancing; reload the page mid-run — progress re-attaches.
2. **Progress redesign.** Verify: percent climbs monotonically across all four stages, the elapsed clock ticks every second, and an ETA is shown; unit tests cover the band/percent/ETA math for a scripted status sequence.
3. **Button/CTA copy + `UsernameField` layout.** Verify: first-time user sees "Load my data"; returning user sees "Refresh my data"; the "click Refresh" instruction disappears once a run starts; username row is single-line with larger username text.
4. **Backend cancel + Cancel button.** Verify: starting a run and clicking Cancel stops backend progress within one loop iteration, tears down the browser, and returns the UI to a clean, data-aware idle state.

## Testing Strategy

- **Backend unit tests** (existing pytest suite): cancel flag stops `run_refresh` at each checkpoint; `/api/refresh/cancel` sets the event and status transitions to `cancelled`; scraper instrumentation helper is covered.
- **Frontend unit tests:** progress band/percent/ETA computation is a pure function tested against scripted status sequences (monotonicity, band boundaries, ETA sanity).
- **Manual/live verification:** the tab-switch, page-reload, and cancel flows against moviefan, plus a real 403-free scrape after the Phase 0 fix.

## Affected Files

Frontend:
- `frontend/src/App.jsx` — mount `RefreshProvider`.
- `frontend/src/context/RefreshContext.jsx` — new: lifecycle, poll loop, rehydration, cancel.
- `frontend/src/RecommendationsPage.jsx` — consume context, drop local refresh state.
- `frontend/src/TasteProfilePage.jsx` — consume context, render progress.
- `frontend/src/components/ProgressBar.jsx` — rewrite: percent model, fixed timer, ETA.
- `frontend/src/components/RefreshButton.jsx` — data-aware label + cancel affordance.
- `frontend/src/components/UsernameField.jsx` — single-row layout, larger username.
- `frontend/src/api.js` — add `cancelRefresh(username)`.
- `frontend/src/index.css` — layout/type for username row, progress, buttons.

Backend:
- `backend/app/scraper.py` — instrumentation (Phase 0), then the confirmed 403 fix; browser teardown on cancel.
- `backend/app/pipeline.py` — cancel checkpoints in loops.
- `backend/app/api.py` — cancel event store, `POST /api/refresh/cancel`, `cancelled` stage.

## Open Questions

None blocking. The specific 403 fix is intentionally deferred to Phase 0 evidence.
