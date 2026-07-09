# Live scrape blocking report — why Letterboxd refresh still isn't provably working

> **RESOLVED 2026-07-09 (same day, later session).** Root cause: Cloudflare keys
> its bot verdict to the browser-session cookie jar, not to IP or request count;
> hypothesis 2 confirmed, hypotheses 1 and 4 refuted, hypothesis 3 half-right
> (pagination URLs are the enforcement point, session state is the trigger).
> The original "request #74" was always the first `films/page/2/` fetch —
> request count was a coincidence of architecture ordering. Fix (fresh browser
> context per fetch attempt) validated live: 87/87 films, 5 requests, zero 403s.
> Full evidence and design:
> `docs/superpowers/specs/2026-07-09-scraper-cloudflare-resilience-design.md`.

Status as of 2026-07-09. Written for a future investigator (human or model) picking this up cold. Everything below is either a direct quote of code in the repo, a direct quote of a live run's console output, or explicitly labeled as hypothesis.

## 1. Original bug (fixed, evidence below)

**Symptom:** any Letterboxd profile with more than ~72 rated films failed to refresh — deterministic 403 from Cloudflare.

**Root cause, confirmed live on 2026-07-08** (see `docs/superpowers/plans/2026-07-08-refresh-and-progress-overhaul-plan.md`, Task 0 outcome note, lines 13-33):

> Root-caused live against `moviefan` (a profile with 72+ rated films — exactly enough to require films-page 2). The 403 hits deterministically on the very first request to `films/page/2/` (request #74 in-session), every time, regardless of: 2x request delay + jitter, a 3x wider backoff ladder, click-driven pagination instead of raw `page.goto()`, `playwright-stealth` fingerprint patching, and rotating to a fresh browser context every 30 requests (tested in combination). All five real, live experiments failed identically at the same request count. This rules out session/fingerprint/pacing as the cause and points to Cloudflare rate-limiting the source IP itself — not fixable client-side without a residential proxy.

The old scraper made **one Letterboxd HTTP request per film** (a detail-page fetch to read the TMDB id off each film page), on top of the list-page requests. For a ~150-film profile that's ~150+ requests in one run — Cloudflare cut it off at #74 every time.

## 2. Fix implemented (2026-07-09, this session)

Full plan: `docs/superpowers/plans/2026-07-08-resilient-letterboxd-scraper.md` (11 tasks, all committed to `main` as of this report — commits `085de77` through `0fde1c4`).

**Architecture change:** split "crawl the list pages" from "resolve each film's TMDB id."

- `crawl_films_list()` (`backend/app/scraper.py`) fetches only the paginated `/username/films/` list pages (72 films/page each) — this is the *entire* Letterboxd HTML crawl on the happy path. For a 150-film profile that's 2 list-page requests + 1 profile-stats-page request = 3 Letterboxd requests total, down from ~150.
- TMDB ids are resolved afterward via a layered cascade (`backend/app/resolver.py`, `make_resolver`), tried in order per film, first hit wins:
  1. **DB cache** (`slug_tmdb_cache` table) — zero network cost, persists across runs.
  2. **RSS feed** (`backend/app/rss.py`) — Letterboxd's public RSS for a user carries exact TMDB ids for recent films. Fetched via plain HTTP (not Playwright, not subject to the same Cloudflare bot-wall), one request, covers however many recent films are in the feed.
  3. **TMDB title+year search** (`backend/app/tmdb.py: search_movie`) — hits TMDB's API directly, not Letterboxd at all. Unlimited, not part of the Letterboxd request budget.
  4. **Letterboxd detail-page fallback**, capped at `MAX_DETAIL_FALLBACKS = 40` (`backend/app/resolver.py`) — only for films that miss all three prior layers. Each of these *is* a Letterboxd request, rate-limited to 1/sec (`time.sleep(1.0)` in `backend/app/api.py`'s `detail_fn`, added specifically to avoid reintroducing the original bug).

**Escape hatch (Task 8-10):** `POST /api/refresh/upload` accepts a user-exported Letterboxd CSV/zip (Settings → Data → Export on letterboxd.com) and resolves every film via TMDB search only — **zero Letterboxd requests**, physically unaffected by any Cloudflare state. Frontend has an "Import from Letterboxd export" button next to the normal refresh button (`frontend/src/components/RefreshButton.jsx`).

**Test coverage:** 120 backend tests (pytest), 17 frontend tests (vitest), covering the cascade's cache/RSS/search/detail-fallback logic, the merge/cap behavior, the upload parsing, and the API wiring. All green as of the last run. This proves the *logic* is correct in isolation (mocked HTTP). It does **not** prove Cloudflare will actually let a live run through — that's what Task 11 (live acceptance gate) exists to check, and that's where this report picks up.

## 3. Task 11: live acceptance gate — what happened

Script: `backend/scripts/live_acceptance.py` (written, not yet committed — plan requires a PASS run before commit). Target: `<15` Letterboxd requests, `≥95%` TMDB id resolution, run against the real `moviefan` profile.

### Run 1 (2026-07-09, ~13:50 ET)

Exact console output:

```
RSS: 25 exact ids
LB[1] 200 https://letterboxd.com/moviefan/films/
LB[2] 403 https://letterboxd.com/moviefan/films/page/2/
LB[3] 403 https://letterboxd.com/moviefan/films/page/2/
LB[4] 403 https://letterboxd.com/moviefan/films/page/2/
LB[5] 403 https://letterboxd.com/moviefan/films/page/2/
Traceback (most recent call last):
  ...
  File "backend/app/scraper.py", line 133, in default_get
    raise RuntimeError(
RuntimeError: Blocked fetching https://letterboxd.com/moviefan/films/page/2/: status 403 after 3 retries
```

(`LB[2]` through `LB[5]` are the same URL because `default_get`'s internal retry ladder — `[0, 2, 5, 10]` second backoffs — re-requests the same URL up to 4 times before giving up; see §4 for the exact code.)

### Diagnostic: is the URL itself dead?

Immediately after Run 1's failure, the *same URL* was fetched in complete isolation (fresh script invocation, fresh Playwright browser/page, no preceding requests in that process):

```python
html = default_get('https://letterboxd.com/moviefan/films/page/2/', on_request=log)
```

Result:

```
{'url': 'https://letterboxd.com/moviefan/films/page/2/', 'status': 200, 'attempt': 0, 'elapsed_s': 2.9, 'challenged': False}
105964
```

**200, first attempt, not even Cloudflare-challenged.** The exact URL that failed 4/4 times inside the script succeeded 1/1 times in isolation, seconds later.

### Run 2 (immediately after the successful isolated diagnostic)

Re-ran the full script again:

```
RSS: 25 exact ids
LB[1] 200 https://letterboxd.com/moviefan/films/
LB[2] 403 https://letterboxd.com/moviefan/films/page/2/
LB[3] 403 https://letterboxd.com/moviefan/films/page/2/
LB[4] 403 https://letterboxd.com/moviefan/films/page/2/
LB[5] 403 https://letterboxd.com/moviefan/films/page/2/
RuntimeError: Blocked fetching https://letterboxd.com/moviefan/films/page/2/: status 403 after 3 retries
```

**Identical failure.** Same URL, same script, same shape: request #1 (`films/`) succeeds, request #2 (`films/page/2/`) fails 4/4 times with a fresh Playwright browser context.

### The puzzle

- The failing request is **not** the request that failed in the original Task 0 investigation (that was request #74, a detail-page fetch, on the *old* per-film-request architecture). This is request **#2** on the *new* list-only architecture.
- The exact same URL fetched with **zero prior requests in that process** succeeds cleanly.
- The exact same URL fetched as **the 2nd request in a process** (after one successful request to `films/`) fails 4/4 times, twice in a row (Run 1 and Run 2).
- `challenged: False` on the isolated success — page content didn't contain "Just a moment" / `cf-browser-verification`, so this isn't a JS-challenge-interstitial being misread as a 403; it's a real 403 status code from `page.goto()`.

## 4. Exact code in play

`backend/app/scraper.py`, `default_get` (lines 110-135):

```python
def default_get(url: str, on_request=None) -> str:
    page = _get_page()
    backoffs = [2, 5, 10]
    last_status = None
    for attempt, wait in enumerate([0] + backoffs):
        if wait:
            time.sleep(wait)
        t0 = time.monotonic()
        resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2500)
        dt = time.monotonic() - t0
        last_status = resp.status
        if on_request:
            challenged = "Just a moment" in page.content() or "cf-browser-verification" in page.content()
            on_request({"url": url, "status": last_status, "attempt": attempt, "elapsed_s": round(dt, 2), "challenged": challenged})
        if last_status not in (403, 429):
            return page.content()
    raise RuntimeError(
        f"Blocked fetching {url}: status {last_status} after {len(backoffs)} retries"
    )
```

`_get_page()` (lines 79-92) — one Playwright Chromium page per thread, created lazily, reused across all `default_get` calls within a run:

```python
def _get_page():
    if not hasattr(_thread_local, "page"):
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT)
        _thread_local.pw = pw
        _thread_local.browser = browser
        _thread_local.page = page
    return _thread_local.page
```

`USER_AGENT` (lines 72-75):

```python
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)
```

`crawl_films_list()` (lines 137-153) — the caller, showing the exact request sequence and the 1s inter-page delay:

```python
def crawl_films_list(username, get_html=default_get, delay: float = 1.0, should_cancel=None) -> list[dict]:
    entries = []
    url = f"{BASE}/{username}/films/"
    while url:
        if should_cancel and should_cancel():
            raise Cancelled()
        html = get_html(url)
        entries.extend(parse_films_page(html))
        nxt = parse_next_page_url(html)
        url = f"{BASE}{nxt}" if nxt else None
        if url and delay:
            time.sleep(delay)
    return entries
```

So the exact live sequence that failed both times: `GET films/` (succeeds) → `sleep(1.0)` → `GET films/page/2/` (fails 403, retries at +2s/+5s/+10s, all still 403).

## 5. Hypotheses (unconfirmed — this is the open question for the next investigator)

1. **Cumulative per-IP request budget, not per-run.** Cloudflare's rate-limit window may be tracking this source IP across *all* traffic today, not resetting per script invocation. Today's IP has taken significant live traffic: the original Task 0 investigation (five separate live experiment combinations against `moviefan`, each running to the #74 failure point before stopping), plus today's Run 1, the isolated diagnostic, and Run 2. If the budget is small and short-window, isolated single requests slip through while any 2-request-in-a-row pattern trips it — which matches what was observed, but doesn't explain why the *isolated* request succeeded when it should also count against the same cumulative budget. This hypothesis is incomplete as stated; may need a longer-window or per-session-cookie theory instead.
2. **Session/cookie-based fingerprinting across requests within one Playwright browser context**, distinct from pure IP-based limiting. The two in-script requests share one `page` object (one browser context, one cookie jar); the isolated diagnostic used a fresh context. If Cloudflare is keying on some session token set after request #1 that then gets flagged on request #2, a fresh context per request (or per N requests) might dodge it — but this contradicts the original Task 0 finding that "rotating to a fresh browser context every 30 requests" was already tried and failed identically. That test, however, was on the *old* per-film-request architecture at request #74, not on a 2-request list-only sequence — it may not be directly comparable.
3. **`films/page/2/` specifically is more heavily protected than `films/`** (e.g. Letterboxd/Cloudflare rate-limits pagination more aggressively than the landing page), independent of request count — i.e. request #1 to *any* URL succeeds, request #2 to *this specific pagination pattern* trips something URL-shape-based rather than count-based. Not tested: whether `GET films/page/2/` as request #1 (skipping `films/` first) also fails.
4. **Flaky/random Cloudflare challenge assignment** (some fraction of requests get bot-challenged regardless of history), and both live runs simply got unlucky on the same URL twice. Weakened by: the isolated diagnostic's clean pass right in between the two failing runs, and the *specific* URL (`page/2/`) failing both times rather than a random different one.

None of these are confirmed. No experiment has yet isolated request-count from URL-shape from browser-context-reuse from wall-clock-timing.

## 6. What would actually distinguish the hypotheses

Not yet run (deliberately — to avoid burning more of today's request budget while investigating):

- Fetch `films/page/2/` as the **first** request of a fresh process (no `films/` first) — tests hypothesis 3.
- Fetch `films/` twice in a row in one process, no `page/2/` involved — tests whether *any* 2nd request fails, or specifically `page/2/`.
- Insert a much longer delay (10s+) between request #1 and #2 in one process — tests whether this is a tight time-window rate limit.
- Use a fresh `browser.new_context()` (not just relying on Playwright's page-per-thread reuse) between request #1 and #2 within the same process — tests hypothesis 2 more precisely than "rotate every 30 requests" did.
- Try against a *different* Letterboxd profile with >72 films, to rule out `moviefan` specifically being flagged (unlikely — Cloudflare rate-limits are almost always IP-keyed, not target-path-keyed — but not yet ruled out).
- Try from a different network/IP entirely, to confirm this is IP-scoped and not something environmental (e.g. a corporate/ISP-level middlebox, DNS-level filtering, local Playwright/Chromium fingerprint issue).

## 7. What is and isn't proven right now

**Proven (unit/integration level, mocked HTTP):** the cascade logic is correct — cache hits skip network calls, RSS matches are used when present, TMDB search is tried next, detail-page fallback is capped at 40 and rate-limited to 1/sec, CSV upload resolves via search-only with zero Letterboxd calls, all merge/dedup/error-path behavior is tested. 120 backend + 17 frontend tests, all passing.

**Not proven:** that a live run against a real >72-film profile actually completes end-to-end without hitting a Cloudflare wall today. Two attempts both failed at the 2nd Letterboxd request, in a way that doesn't match either the original bug's signature (fails at #74) or simple flakiness (identical URL, identical position in sequence, twice).

**Definitely works regardless of the above:** the CSV-export upload path, since it makes zero Letterboxd requests. Not yet live-tested end-to-end this session, but architecturally immune to whatever is causing the list-crawl failures — worth confirming as a fallback while the list-crawl issue is unresolved.

## 8. Relevant files for the next investigator

- `backend/app/scraper.py` — `default_get`, `_get_page`, `crawl_films_list`, `scrape_profile`.
- `backend/app/resolver.py` — the cascade (`make_resolver`), `MAX_DETAIL_FALLBACKS = 40`.
- `backend/app/api.py` — `_real_refresh`, production `detail_fn` with its `time.sleep(1.0)` pacing.
- `backend/scripts/live_acceptance.py` — the gate script that produced the Run 1/Run 2 output above.
- `docs/superpowers/plans/2026-07-08-refresh-and-progress-overhaul-plan.md`, Task 0 (lines 13-33) — original 403 root-cause investigation.
- `docs/superpowers/plans/2026-07-08-resilient-letterboxd-scraper.md` — the 11-task plan that produced the current architecture (Task 11 is the live gate, still open).
