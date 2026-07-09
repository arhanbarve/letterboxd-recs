# Scraper Cloudflare resilience — design spec

Date: 2026-07-09. Status: root cause confirmed live, fix validated live, design approved for implementation.

## 1. Problem statement

Live Letterboxd refresh fails with a Cloudflare 403 on `films/page/2/`, even after the 2026-07-09 architectural fix (list-page-only crawl + resolver cascade) reduced top-level Letterboxd requests from ~150 to ~5. Two live acceptance runs failed identically at request #2. See `docs/superpowers/specs/2026-07-09-live-scrape-blocking-report.md` for the full pre-investigation evidence trail.

## 2. Root cause (confirmed live, 2026-07-09 afternoon)

**The block is keyed to browser-session state, not to IP address and not to request count.**

The investigation that established this (all runs same afternoon, same IP, real letterboxd.com):

| # | Experiment | Result |
|---|---|---|
| E0 | Local fingerprint audit of `_get_page()`'s Chromium (zero Letterboxd requests) | Leaks `sec-ch-ua: "HeadlessChrome";v="149"` in plain HTTP headers while the UA override claims Chrome/120; `navigator.webdriver: true`; no `Accept-Language` header; malformed UA version string |
| E1 | `films/` in context A → close → `films/page/2/` in fresh context B, same browser, same process, 1s apart | **200 / 200** |
| E2 (control) | Same two URLs in one shared context (exactly what production `_get_page()` does) | **200 / 403**, minutes after E1 passed |
| T2 | Plain `requests` with a shared `Session` | `films/` 200 (grid parses: 72 entries), `page/2` 403 with "Just a moment" challenge |
| T2b | Plain `requests`, cookieless, independent per request | `films/` 200, `page/2` **still 403** — plain-HTTP clients fail pagination regardless of cookies (TLS/JA3 fingerprint, no JS) |
| T1 | Full end-to-end run with fresh-context-per-fetch fetcher + real cascade | **PASS: 87/87 films resolved (100%), 5 Letterboxd requests, zero 403s, zero retries** (rss=25, search=60, detail=2) |

**Mechanism (best supported by evidence):** Cloudflare protects the profile-pagination URL shape (`/{user}/films/page/*`) with a rule gated on session bot score. The first document navigation in any fresh browser context gets a grace pass while Cloudflare issues session cookies and collects JS telemetry during the page dwell. The headless fingerprint (webdriver flag, HeadlessChrome client hints, UA/client-hint contradiction) flags the session; every subsequent navigation to a protected path on that session's cookie jar is 403'd. A fresh context = fresh cookie jar = new grace pass. Unprotected paths (`films/` page 1, film detail pages) are never blocked — which is why the *old* architecture survived 72 consecutive detail-page requests and died only when it finally touched `page/2`.

**Reinterpretation of the original bug:** the "deterministic 403 at request #74" from the 2026-07-08 investigation was *always* the first `films/page/2/` fetch (1 list page + 72 detail pages = 73 requests before it). There was never a request-count budget. Both bugs were the same bug: `page/2` fetched on a flagged session.

Additional finding: each `page.goto()` on a films list page fires ~79 same-origin subrequests (the grid loads posters via ajax) plus ~300 third-party requests. "Letterboxd request counts" in prior docs counted only top-level documents. This did not turn out to be the blocking trigger, but future rate reasoning must account for it.

## 3. Design goal

A refresh pipeline where:

1. The live crawl works today, validated by a live gate (T1 already passed with the exact fetcher design below).
2. Every layer that can fail has a fallback, ending in a path that makes **zero Letterboxd requests** and therefore cannot be blocked.
3. When the live crawl does fail, the user gets an actionable path forward (CSV import), not a dead error.

## 4. Honest limits — read this first

**This cannot be made literally foolproof.** Letterboxd's Cloudflare configuration is an adversary that can change unilaterally. Concretely, the current fix survives because Cloudflare grants a first-navigation grace per session and keys its verdict to session cookies. Letterboxd could tighten any of these tomorrow: extend the pagination rule to page 1 and detail pages, key verdicts to IP once the fresh-context pattern is common, or require an interactive challenge that headless Chromium cannot pass. No client-side change would survive all of those.

**What *is* guaranteed:** the CSV-export upload path (`POST /api/refresh/upload`, already built and shipped) makes zero Letterboxd requests and resolves entirely through the TMDB API. It works regardless of any Cloudflare state, forever, as long as Letterboxd offers data export. The design therefore treats it as a first-class path, not a buried fallback.

**Verdict on "is this a dead end":** No — the live crawl is proven working end-to-end as of today (T1: 100% resolution, 5 requests, zero blocks). But its continued working is probabilistic, not guaranteed, and the system is designed so that its failure degrades to a one-click user action rather than a broken product.

## 5. Design

### 5.1 Layer 1 — live crawl, fixed fetcher (primary path)

`backend/app/scraper.py` changes:

- Keep **one Playwright browser per thread** (launch cost ~1s, amortized).
- **Create a fresh `browser.new_context()` + page for every `default_get()` call, and for every retry attempt within a call.** Close the context in a `finally` before returning/retrying. This is the entire fix — a flagged session is never reused, and every navigation gets the fresh-session grace pass. Context creation costs ~50ms, noise against multi-second page loads.
- The retry ladder (`[2, 5, 10]`s backoff) becomes meaningful for the first time: previously retries reran on the same poisoned session and were guaranteed to fail 4/4; now each retry is a fresh session.
- Set `locale="en-US"` on the context so Chromium sends an `Accept-Language` header (one of the audit's bot tells; one line, removes a free signal).
- Keep the UA override as-is. It is contradicted by client hints, but T1 passed with it; changing it is an unforced experiment. Recorded as a known cosmetic defect, revisit only if blocks resume.
- `_get_page()`/`_close_page()` become `_get_browser()`/`_close_browser()`; thread-local holds only `pw` + `browser`.
- Rewrite the stale "known limitation" comment block in `default_get` (it documents the disproven IP-rate-limit theory) to describe the session-keyed mechanism and cite this spec.
- Everything downstream inherits the fix untouched: `crawl_films_list`, `scrape_profile`, the production `detail_fn` in `api.py`, and the resolver cascade all call through `default_get`.

### 5.2 Layer 2 — resolver cascade (already built, unchanged)

Cache → RSS → TMDB search → detail-page fallback (capped at 40, 1s paced). T1 measured the real mix on an 87-film profile: RSS 25, search 60, detail 2. The detail cap is generous by ~20x in practice. RSS is fetched via plain `requests` (proven to pass — the RSS path is not behind the pagination rule). No changes.

The slug→TMDB cache additionally means each *successful* run shrinks all future runs: a re-refresh needs only the list pages plus resolution for newly added films.

### 5.3 Layer 3 — failure UX (small change)

When the crawl still fails (Cloudflare escalation, network), `scrape_profile` already raises an "Incomplete scrape" error that names the CSV-import escape hatch, and the frontend already shows an "Import from Letterboxd export" button. One gap: the hard `RuntimeError` from `default_get` ("Blocked fetching …: status 403") propagates raw, without steering the user to the import path. Fix: make the blocked-fetch error message user-facing-quality, matching the incomplete-scrape message's guidance (mention Settings → Data → Export → import button).

Explicitly rejected for now (YAGNI): partial-scrape salvage/merge semantics, RSS-only quick-refresh mode, proxy rotation, `curl_cffi` TLS impersonation, request interception to trim subresources. Each adds arms-race surface or merge complexity without being needed by the evidence.

### 5.4 Layer 4 — CSV upload (already built, promote in docs)

Zero-Letterboxd-request path via `POST /api/refresh/upload`. No code changes; the spec records it as the guaranteed fallback and the README/user docs should present it as a normal alternative, not an error recovery step.

### 5.5 Regression gate

- `backend/scripts/live_acceptance.py` (currently uncommitted, awaiting a PASS) is the ongoing canary: `<15` top-level Letterboxd requests, `≥95%` resolution, run manually against a real profile. Commit it once it passes on the fixed fetcher.
- Unit tests: fetcher lifecycle test (fresh context created and closed per attempt; no context reuse across calls) via a stubbed browser object; existing 23 scraper tests must pass unchanged (they inject `get_html` and are agnostic to the fetcher internals).

## 6. Success criteria

1. `live_acceptance.py moviefan` prints PASS on the committed code (T1 already demonstrated this outcome with the same fetcher design: 100% resolution, 5 requests, zero 403s).
2. All existing backend tests (120) and frontend tests (17) pass unchanged.
3. New fetcher lifecycle unit test passes.
4. A blocked live crawl surfaces an error that names the CSV import path.

## 7. Risks and monitoring

| Risk | Likelihood | Mitigation |
|---|---|---|
| Cloudflare keys verdicts to IP once fresh-context traffic grows | Unknown; nothing observed today despite ~15 top-level requests + thousands of subrequests from one IP | Cascade minimizes exposure (≤5 typical requests/run); CSV path unaffected |
| Pagination rule extended to `films/` page 1 or detail pages | Possible at any time | Crawl fails cleanly → CSV import message |
| First-navigation grace removed (interactive challenge on every request) | Would kill headless crawling entirely | CSV import becomes the primary path; RSS still covers ~50 recent films for partial freshness |
| Letterboxd HTML/markup changes break parsers | Ordinary maintenance risk | Existing parser unit tests catch on fixture update; unrelated to Cloudflare |

If blocks resume, re-run the probe ladder from §2 (E0 is free; E1/E2 cost 4 requests) before changing code — the A/B pair distinguishes session-keying from IP-keying in one comparison.

## 8. References

- `docs/superpowers/specs/2026-07-09-live-scrape-blocking-report.md` — pre-investigation evidence (hypotheses now resolved: H2 confirmed, H1/H4 refuted, H3 half-right as the enforcement point).
- `docs/superpowers/plans/2026-07-08-refresh-and-progress-overhaul-plan.md` Task 0 — original investigation, reinterpreted by §2.
- `docs/superpowers/plans/2026-07-08-resilient-letterboxd-scraper.md` — cascade architecture (unchanged by this design); its Task 11 live gate is closed by this work.
