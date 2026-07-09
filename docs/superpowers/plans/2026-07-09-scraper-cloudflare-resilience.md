# Scraper Cloudflare Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the live Letterboxd crawl survive Cloudflare's session-keyed bot blocking by giving every fetch (and every retry) a fresh browser context, and make the remaining failure path steer users to the CSV-import escape hatch.

**Architecture:** Cloudflare keys its bot verdict to the browser session's cookie jar, not to IP or request count — the first navigation in a fresh context always passes; any later navigation to a protected path (`/{user}/films/page/*`) on that session 403s (confirmed live, see spec). The fix: keep one Playwright browser per thread, but open a fresh `browser.new_context()` per `default_get` attempt and close it before the next. Everything downstream (`crawl_films_list`, `scrape_profile`, the production `detail_fn`, the resolver cascade) calls through `default_get` and inherits the fix unchanged. Validated live end-to-end 2026-07-09: 87/87 films resolved, 5 requests, zero 403s.

**Spec:** `docs/superpowers/specs/2026-07-09-scraper-cloudflare-resilience-design.md`

**Tech Stack:** Python 3, Playwright (sync API), pytest, existing resolver cascade.

**File map:**
- Modify: `backend/app/scraper.py` — `_get_page`→`_get_browser`, `_close_page`→`_close_browser`, rewrite `default_get` (fresh context per attempt, `locale="en-US"`, actionable blocked-error message, corrected root-cause comment), `scrape_profile`'s `finally`.
- Modify: `backend/tests/test_scraper.py` — replace `_FakePage`-based fetcher tests with `_FakeBrowser`/`_FakeContext` fakes; add context-lifecycle tests; update the two teardown tests that poke `_thread_local.page`.
- Commit (already written, gated on PASS): `backend/scripts/live_acceptance.py`.
- Modify: `docs/superpowers/specs/2026-07-09-live-scrape-blocking-report.md` — resolution addendum.

No changes to `backend/app/api.py`, `resolver.py`, `rss.py`, or any frontend file.

---

### Task 1: Fetcher tests — fresh context per attempt

The current tests monkeypatch `scraper._get_page` (a name that will cease to exist) and a `_FakePage` that ignores context lifecycle. Replace them with fakes that model browser→context→page, then add the new lifecycle assertions. Written first; they must FAIL until Task 2 lands.

**Files:**
- Modify: `backend/tests/test_scraper.py:103-212`

- [ ] **Step 1: Replace the fake classes and `default_get` tests**

In `backend/tests/test_scraper.py`, replace everything from `class _FakeResp:` (line ~105) through `test_default_get_reports_each_attempt_via_on_request` (line ~143) with:

```python
class _FakeResp:
    def __init__(self, status):
        self.status = status

class _FakePage:
    def __init__(self, browser):
        self._browser = browser
    def goto(self, url, wait_until=None, timeout=None):
        return _FakeResp(self._browser._statuses.pop(0))
    def wait_for_timeout(self, ms):
        pass
    def content(self):
        return self._browser._content

class _FakeContext:
    def __init__(self, browser):
        self._browser = browser
    def new_page(self):
        return _FakePage(self._browser)
    def close(self):
        self._browser.contexts_closed += 1

class _FakeBrowser:
    """One goto() pops one status; tracks context lifecycle."""
    def __init__(self, statuses, content="<html>ok</html>"):
        self._statuses = list(statuses)
        self._content = content
        self.context_kwargs = []
        self.contexts_closed = 0
    @property
    def contexts_opened(self):
        return len(self.context_kwargs)
    def new_context(self, **kwargs):
        self.context_kwargs.append(kwargs)
        return _FakeContext(self)

def _install_fake_browser(monkeypatch, statuses, content="<html>ok</html>"):
    fb = _FakeBrowser(statuses, content)
    monkeypatch.setattr(scraper, "_get_browser", lambda: fb)
    monkeypatch.setattr(scraper.time, "sleep", lambda s: None)
    return fb

def test_default_get_returns_content_on_first_success(monkeypatch):
    _install_fake_browser(monkeypatch, [200])
    assert scraper.default_get("https://letterboxd.com/alice/films/") == "<html>ok</html>"

def test_default_get_raises_after_exhausting_retries_on_403(monkeypatch):
    _install_fake_browser(monkeypatch, [403, 403, 403, 403], content="<html>challenge</html>")
    with pytest.raises(RuntimeError, match="Blocked"):
        scraper.default_get("https://letterboxd.com/alice/films/")

def test_default_get_recovers_after_one_retry(monkeypatch):
    _install_fake_browser(monkeypatch, [429, 200])
    assert scraper.default_get("https://letterboxd.com/alice/films/") == "<html>ok</html>"

def test_default_get_reports_each_attempt_via_on_request(monkeypatch):
    _install_fake_browser(monkeypatch, [429, 200])
    events = []
    scraper.default_get("https://letterboxd.com/alice/films/", on_request=events.append)
    assert [e["status"] for e in events] == [429, 200]
    assert [e["attempt"] for e in events] == [0, 1]
    assert all(e["challenged"] is False for e in events)

def test_default_get_opens_and_closes_fresh_context_per_attempt(monkeypatch):
    # THE fix: a Cloudflare-flagged session must never be reused, so every
    # attempt (not just every call) gets its own context — and closes it.
    fb = _install_fake_browser(monkeypatch, [429, 200])
    scraper.default_get("https://letterboxd.com/alice/films/")
    assert fb.contexts_opened == 2
    assert fb.contexts_closed == 2

def test_default_get_closes_every_context_even_when_blocked(monkeypatch):
    fb = _install_fake_browser(monkeypatch, [403, 403, 403, 403], content="x")
    with pytest.raises(RuntimeError):
        scraper.default_get("https://letterboxd.com/alice/films/")
    assert fb.contexts_opened == 4
    assert fb.contexts_closed == 4

def test_default_get_context_sends_ua_and_locale(monkeypatch):
    fb = _install_fake_browser(monkeypatch, [200])
    scraper.default_get("https://letterboxd.com/alice/films/")
    assert fb.context_kwargs[0] == {"user_agent": scraper.USER_AGENT, "locale": "en-US"}

def test_default_get_blocked_error_names_the_export_escape_hatch(monkeypatch):
    _install_fake_browser(monkeypatch, [403, 403, 403, 403], content="x")
    with pytest.raises(RuntimeError, match="Letterboxd export"):
        scraper.default_get("https://letterboxd.com/alice/films/")
```

- [ ] **Step 2: Update the two teardown tests that poke `_thread_local.page`**

In the same file, `test_scrape_profile_closes_browser_on_cancel` (line ~176) and `test_scrape_profile_raises_cancelled_even_if_browser_close_fails` (line ~197) each contain the line `scraper._thread_local.page = object()`. Delete that line from both tests (the thread-local no longer holds a page — only `browser` and `pw`). Everything else in both tests stays: they set `_thread_local.browser`/`_thread_local.pw` directly and assert cleanup, which still matches the new `_close_browser`.

- [ ] **Step 3: Run the scraper tests to verify the new ones fail**

Run: `cd ~/letterboxd-recommenation/backend && .venv/bin/python -m pytest tests/test_scraper.py -v`
Expected: the rewritten/new `default_get` tests FAIL with `AttributeError: ... has no attribute '_get_browser'`. Teardown and parser tests still pass.

- [ ] **Step 4: Commit the failing tests? No — hold.**

Do not commit yet; this repo's convention is test+implementation in one commit. Proceed to Task 2.

---

### Task 2: Fetcher implementation — fresh context per attempt

**Files:**
- Modify: `backend/app/scraper.py:79-135` (`_get_page`, `_close_page`, `default_get`) and `backend/app/scraper.py:188-189` (`scrape_profile`'s `finally`)

- [ ] **Step 1: Replace `_get_page`/`_close_page`/`default_get`**

In `backend/app/scraper.py`, replace lines 79–135 (from `def _get_page():` through the end of `default_get`) with:

```python
def _get_browser():
    """Lazily creates one Playwright browser per thread. Letterboxd sits
    behind Cloudflare bot-management; plain HTTP clients (requests,
    cloudscraper) are refused outright on pagination URLs (TLS fingerprint —
    confirmed live 2026-07-09), but a real browser engine passes. Contexts are
    deliberately NOT cached here — see default_get."""
    if not hasattr(_thread_local, "browser"):
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        _thread_local.pw = pw
        _thread_local.browser = pw.chromium.launch(headless=True)
    return _thread_local.browser

def _close_browser():
    # Swallow close/stop errors so teardown never masks the exception that
    # triggered it (e.g. a Cancelled propagating through this finally block).
    if hasattr(_thread_local, "browser"):
        try:
            _thread_local.browser.close()
        except Exception:
            pass
        try:
            _thread_local.pw.stop()
        except Exception:
            pass
        del _thread_local.browser
        del _thread_local.pw

def default_get(url: str, on_request=None) -> str:
    # Cloudflare keys its bot verdict to the browser session's cookie jar —
    # not to the source IP and not to a request count. The first navigation in
    # a fresh context gets a grace pass while telemetry is collected; once the
    # (headless) session is flagged, every later navigation to a protected
    # path (profile pagination) 403s on that session, so retrying on the same
    # context is guaranteed futile. Confirmed live 2026-07-09 — see
    # docs/superpowers/specs/2026-07-09-scraper-cloudflare-resilience-design.md.
    # Therefore: one fresh context per attempt; a flagged session is never
    # reused. `on_request` lets investigations re-instrument cheaply.
    browser = _get_browser()
    backoffs = [2, 5, 10]
    last_status = None
    for attempt, wait in enumerate([0] + backoffs):
        if wait:
            time.sleep(wait)
        context = browser.new_context(user_agent=USER_AGENT, locale="en-US")
        page = context.new_page()
        try:
            t0 = time.monotonic()
            resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2500)
            dt = time.monotonic() - t0
            last_status = resp.status
            body = page.content()
            if on_request:
                challenged = "Just a moment" in body or "cf-browser-verification" in body
                on_request({"url": url, "status": last_status, "attempt": attempt, "elapsed_s": round(dt, 2), "challenged": challenged})
            if last_status not in (403, 429):
                return body
        finally:
            context.close()
    raise RuntimeError(
        f"Blocked fetching {url}: status {last_status} after {len(backoffs)} "
        f"retries. Letterboxd's bot protection refused the crawl — try again "
        f"in a minute, or import your Letterboxd export "
        f"(letterboxd.com Settings → Data → Export) instead."
    )
```

Notes for the implementer:
- `locale="en-US"` makes Chromium send an `Accept-Language` header (its absence is a known bot tell found in the fingerprint audit).
- `body = page.content()` is read once *inside* the try so the context can close before return.
- The stale comment block claiming "Cloudflare rate-limiting by source IP, not fixable client-side" is intentionally gone — it documented a disproven theory.

- [ ] **Step 2: Update `scrape_profile`'s finally block**

At `backend/app/scraper.py:188-189`, change:

```python
    finally:
        _close_page()
```

to:

```python
    finally:
        _close_browser()
```

- [ ] **Step 3: Run the scraper tests**

Run: `cd ~/letterboxd-recommenation/backend && .venv/bin/python -m pytest tests/test_scraper.py -v`
Expected: ALL pass (including the new lifecycle tests).

- [ ] **Step 4: Run the full backend suite**

Run: `cd ~/letterboxd-recommenation/backend && .venv/bin/python -m pytest`
Expected: all ~124 tests pass. (`api.py`'s `detail_fn` and the acceptance script call `default_get` by name; nothing else references `_get_page`/`_close_page` — verify with `grep -rn "_get_page\|_close_page" backend/ --include="*.py"`, which must return nothing.)

- [ ] **Step 5: Commit**

```bash
git add backend/app/scraper.py backend/tests/test_scraper.py
git commit -m "fix: fresh browser context per fetch attempt to dodge Cloudflare session flagging

Cloudflare keys its bot verdict to the session cookie jar, not IP or
request count (confirmed live via A/B: shared context 403s on
films/page/2, fresh context passes minutes apart on the same IP).
Retries now also get fresh contexts — retrying a flagged session was
provably futile. Blocked-fetch errors now point at the CSV export
import path."
```

---

### Task 3: Live acceptance gate (Task 11 of the resilient-scraper plan, still open)

The gate script exists untracked at `backend/scripts/live_acceptance.py` and needs no code changes — it injects `default_get`, so Task 2's fix flows through. The plan that created it requires a PASS before it may be committed.

**Files:**
- Commit: `backend/scripts/live_acceptance.py` (no modifications)

- [ ] **Step 1: Run the gate against the real profile**

Run: `cd ~/letterboxd-recommenation/backend && .venv/bin/python scripts/live_acceptance.py moviefan`
Expected: `PASS`, with `letterboxd requests < 15` and `tmdb ids resolved ≥ 95%`. Reference: the identical fetcher design passed live on 2026-07-09 with 87/87 (100%), 5 requests, zero 403s (rss=25, search=60, detail=2).

Cost note: this makes ~5 live Letterboxd requests (plus up to 40 capped detail fallbacks; 2 observed in practice). If it FAILS with a 403: stop, do not retry in a loop — re-run the E1/E2 probe pair from the spec's §2 (4 requests) to check whether Cloudflare's behavior changed, and report findings before any code change.

- [ ] **Step 2: Commit the gate script**

```bash
git add backend/scripts/live_acceptance.py
git commit -m "test: live acceptance gate for the layered scraper (PASS on moviefan)"
```

---

### Task 4: Documentation — close the investigation

**Files:**
- Modify: `docs/superpowers/specs/2026-07-09-live-scrape-blocking-report.md` (prepend addendum)
- Commit: `docs/superpowers/specs/2026-07-09-scraper-cloudflare-resilience-design.md`, `docs/superpowers/plans/2026-07-09-scraper-cloudflare-resilience.md`

- [ ] **Step 1: Prepend a resolution addendum to the blocking report**

Insert immediately after the first heading line of `docs/superpowers/specs/2026-07-09-live-scrape-blocking-report.md`:

```markdown
> **RESOLVED 2026-07-09 (same day, later session).** Root cause: Cloudflare keys
> its bot verdict to the browser-session cookie jar, not to IP or request count;
> hypothesis 2 confirmed, hypotheses 1 and 4 refuted, hypothesis 3 half-right
> (pagination URLs are the enforcement point, session state is the trigger).
> The original "request #74" was always the first `films/page/2/` fetch —
> request count was a coincidence of architecture ordering. Fix (fresh browser
> context per fetch attempt) validated live: 87/87 films, 5 requests, zero 403s.
> Full evidence and design:
> `docs/superpowers/specs/2026-07-09-scraper-cloudflare-resilience-design.md`.
```

- [ ] **Step 2: Present the CSV import path in the README (spec §5.4)**

In `README.md`, under `### Notes` (line ~54), append this bullet after the existing "A refresh scrapes the real Letterboxd site…" bullet:

```markdown
- If a refresh ever fails with a "blocked" message, use the **Import from Letterboxd export** button instead: on letterboxd.com go to Settings → Data → Export, download the zip, and upload it in the app. This path makes zero Letterboxd requests, so it works regardless of bot-protection state.
```

- [ ] **Step 3: Commit the docs**

```bash
git add README.md \
        docs/superpowers/specs/2026-07-09-live-scrape-blocking-report.md \
        docs/superpowers/specs/2026-07-09-scraper-cloudflare-resilience-design.md \
        docs/superpowers/plans/2026-07-09-scraper-cloudflare-resilience.md
git commit -m "docs: Cloudflare blocking root cause resolved — session-keyed verdict, spec + plan"
```

---

## Out of scope (deliberate, per spec §5.3)

Partial-scrape salvage/merge, RSS-only quick refresh, proxy rotation, `curl_cffi` TLS impersonation, UA-string correction, subresource blocking. The CSV upload path and frontend import button already exist and need no changes.

## Verification summary

| Check | Command | Gate |
|---|---|---|
| Fetcher lifecycle | `pytest tests/test_scraper.py -v` | all pass |
| No stale references | `grep -rn "_get_page\|_close_page" backend/ --include="*.py"` | empty |
| Full suite | `pytest` (backend) | ~124 pass |
| Live gate | `scripts/live_acceptance.py moviefan` | PASS, <15 req, ≥95% |
