# Refresh & Progress Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the three broken dimensions of the refresh experience — state loss on tab switch, a jumpy/frozen/uninformative progress bar, and unrecoverable scrape failures with no cancel path — per `docs/superpowers/specs/2026-07-07-refresh-and-progress-overhaul-design.md`.

**Architecture:** A new `RefreshProvider` (React Context) owns refresh lifecycle/polling globally so both tabs share live state and survive unmount. Progress becomes a pure, unit-tested percent/ETA calculation consumed by a rewritten `ProgressBar`. Backend gains a per-user `threading.Event` cancel flag checked at four loop boundaries (films-page, per-film-detail, enrich, scoring), plus a `cancelled` terminal stage. The Letterboxd 403 is root-caused via one live instrumented run before any fix is written.

**Tech Stack:** FastAPI + sqlite3 (backend), pytest; React 19 + Vite (frontend), vitest (new, for pure progress-math unit tests).

---

## Task 0: Phase 0 — 403 reproduction and evidence-based fix

> **Outcome (2026-07-08):** Root-caused live against `moviefan` (a profile with
> 72+ rated films — exactly enough to require films-page 2). The 403 hits
> deterministically on the very first request to `films/page/2/` (request #74
> in-session), every time, regardless of: 2x request delay + jitter, a 3x wider
> backoff ladder, click-driven pagination instead of raw `page.goto()`,
> `playwright-stealth` fingerprint patching, and rotating to a fresh browser
> context every 30 requests (tested in combination). All five real, live
> experiments failed identically at the same request count. This rules out
> session/fingerprint/pacing as the cause and points to Cloudflare rate-limiting
> the source IP itself — not fixable client-side without a residential proxy
> (a paid third-party dependency, out of scope for this pass). Decision: accept
> as a known, documented limitation (see the comment on `default_get` in
> `backend/app/scraper.py`) and proceed with Tasks 1-4, which are independent
> of this fix. The existing scrape-completeness check still surfaces this
> clearly to the user ("try refreshing again"), and Task 4's new cancel button
> gives users a clean way to abort a doomed run instead of waiting it out.
> Only the Step 1 instrumentation (`on_request` hook) and its test landed;
> Steps 4-5 (apply a fix) were not applicable. `backend/scripts/probe_403.py`
> is kept for future re-investigation.

**Files:**
- Modify: `backend/app/scraper.py`
- Create (throwaway, not committed): `backend/scripts/probe_403.py`
- Test: `backend/tests/test_scraper.py`

This is a live, evidence-gathering step — the spec explicitly forbids guessing the fix. Do not skip straight to a candidate fix.

- [ ] **Step 1: Add an instrumentation hook to `default_get`**

Modify `backend/app/scraper.py:77-91`:

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

`on_request` defaults to `None` so existing behavior and callers are unaffected.

- [ ] **Step 2: Thread `on_request` through `scrape_profile`**

Modify `backend/app/scraper.py:93-117` — `scrape_profile` already accepts `get_html=default_get`. Add a thin wrapper in the probe script instead of changing `scrape_profile`'s signature (it calls `get_html(url)` with one arg only — keep that contract; the probe script below binds `on_request` via `functools.partial` before passing `get_html` in).

- [ ] **Step 3: Write the probe script**

Create `backend/scripts/probe_403.py`:

```python
"""One-off live reproduction of the 403 on films-page pagination.
Run manually: `cd backend && .venv/bin/python scripts/probe_403.py moviefan`
Not part of the test suite — hits real Letterboxd/Cloudflare.
"""
import functools
import sys

from app.scraper import default_get, scrape_profile

def log(event):
    print(f"[{event['attempt']}] {event['status']} challenged={event['challenged']} "
          f"{event['elapsed_s']}s {event['url']}")

def main(username):
    get_html = functools.partial(default_get, on_request=log)
    try:
        films = scrape_profile(username, get_html=get_html, delay=1.0)
        print(f"OK: scraped {len(films)} films")
    except RuntimeError as e:
        print(f"FAILED: {e}")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "moviefan")
```

- [ ] **Step 4: Run the probe against moviefan and read the log**

Run: `cd backend && .venv/bin/python scripts/probe_403.py moviefan`

Read every logged line. Decide which candidate applies:
- If `challenged=True` appears on a response that still returns 200 (interstitial read as success) → **fixed timeout wait** is the cause.
- If status flips to 403 only after N successful requests in quick succession (visible via `elapsed_s` staying low, no backoff yet triggered) → **session flagged by velocity** is the cause.
- If 403/429 appears from the very first films-page-2 request regardless of pacing, with no interstitial HTML → **pure rate limiting** is the cause.

- [ ] **Step 5: Apply exactly the fix matching the evidence**

**If "challenge not settled":** replace `page.wait_for_timeout(2500)` in `default_get` with a real content wait:

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
        try:
            page.wait_for_selector("body:not(:has(.challenge-running))", timeout=8000)
        except Exception:
            pass
        dt = time.monotonic() - t0
        last_status = resp.status
        if on_request:
            on_request({"url": url, "status": last_status, "attempt": attempt, "elapsed_s": round(dt, 2), "challenged": False})
        if last_status not in (403, 429):
            return page.content()
    raise RuntimeError(
        f"Blocked fetching {url}: status {last_status} after {len(backoffs)} retries"
    )
```

**If "session flagged by velocity":** raise the inter-request delay's floor and jitter it in `scrape_profile` (`backend/app/scraper.py:93-95`):

```python
import random
...
def scrape_profile(
    username: str, get_html=default_get, delay: float = 2.0, on_progress=None
) -> list[dict]:
```

and where `time.sleep(delay)` is called (`scraper.py:114`), jitter it:

```python
            if delay:
                time.sleep(delay + random.uniform(0, 0.75))
```

**If "pure rate limiting":** widen the backoff ladder in `default_get`:

```python
    backoffs = [5, 15, 30]
```

Apply only the one branch the evidence supports. Delete `backend/scripts/probe_403.py` after use (it is a diagnostic tool, not part of the shipped surface) — or leave it if you want it available for future incidents; either is fine, it is excluded from the test suite either way.

- [ ] **Step 6: Verify with a second live run**

Run: `cd backend && .venv/bin/python scripts/probe_403.py moviefan`
Expected: `OK: scraped N films` with no `FAILED` line.

- [ ] **Step 7: Add a regression test for the specific fix**

If the fix was the `wait_for_selector` change, add to `backend/tests/test_scraper.py`:

```python
def test_default_get_waits_for_challenge_to_clear(monkeypatch):
    calls = []
    class _ChallengePage(_FakePage):
        def wait_for_selector(self, sel, timeout=None):
            calls.append(sel)
    monkeypatch.setattr(scraper, "_get_page", lambda: _ChallengePage([200]))
    monkeypatch.setattr(scraper.time, "sleep", lambda s: None)
    scraper.default_get("https://letterboxd.com/alice/films/")
    assert calls  # wait_for_selector was invoked before reading content
```

(Adjust `_FakePage` in `test_scraper.py:79-88` to add a no-op `wait_for_selector` method so existing tests still pass — every existing `_FakePage` instantiation must keep working.)

If the fix was the delay/jitter change, add instead:

```python
def test_scrape_profile_uses_jittered_delay_between_requests(monkeypatch):
    page1 = (FIX / "films_page.html").read_text()
    stats = '<html><body><h4 class="profile-statistic statistic"><a href="/alice/films/"><span class="value">3</span></a></h4></body></html>'
    detail = (FIX / "film_detail.html").read_text()
    def fake_get(url):
        if url.endswith("/films/"):
            return page1
        if url.endswith("/alice/"):
            return stats
        return detail
    sleeps = []
    monkeypatch.setattr(scraper.time, "sleep", lambda s: sleeps.append(s))
    monkeypatch.setattr(scraper.random, "uniform", lambda a, b: 0.5)
    scrape_profile("alice", fake_get, delay=2.0)
    assert all(s == 2.5 for s in sleeps)
```

If the fix was the backoff-ladder change, add instead:

```python
def test_default_get_uses_widened_backoff_ladder(monkeypatch):
    waits = []
    monkeypatch.setattr(scraper, "_get_page", lambda: _FakePage([403, 403, 403, 200]))
    monkeypatch.setattr(scraper.time, "sleep", lambda s: waits.append(s))
    scraper.default_get("https://letterboxd.com/alice/films/")
    assert waits == [5, 15, 30]
```

- [ ] **Step 8: Run the full backend suite**

Run: `cd backend && .venv/bin/pytest -q`
Expected: all tests pass, including the new one.

- [ ] **Step 9: Commit**

```bash
git add backend/app/scraper.py backend/tests/test_scraper.py backend/scripts/probe_403.py
git commit -m "fix: root-cause and fix the Letterboxd 403 on films-page pagination"
```

---

## Task 1: `RefreshContext` — global state + rehydration (Phase 1)

**Files:**
- Create: `frontend/src/context/RefreshContext.jsx`
- Modify: `frontend/src/api.js` (add `cancelRefresh`, needed by the context now so it compiles — implemented fully in Task 4)
- Modify: `frontend/src/App.jsx`

- [ ] **Step 1: Add the `cancelRefresh` stub to `api.js`**

Modify `frontend/src/api.js` — add after `getRefreshStatus` (`api.js:27-30`):

```js
export async function cancelRefresh(username) {
  const r = await fetch(`${BASE}/api/refresh/cancel`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username }),
  });
  return r.json();
}
```

(The backend endpoint doesn't exist yet — that's Task 4. This function is safe to add now since nothing calls it until Task 4/5.)

- [ ] **Step 2: Write `RefreshContext.jsx`**

Create `frontend/src/context/RefreshContext.jsx`:

```jsx
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { refresh, getRefreshStatus, cancelRefresh } from "../api";

const ACTIVE_STAGES = new Set(["starting", "scraping", "enriching", "profiling", "scoring"]);
const POLL_MS = 800;

const RefreshContext = createContext(null);

export function RefreshProvider({ username, children }) {
  const [status, setStatus] = useState(null);
  const [lastCompletedAt, setLastCompletedAt] = useState(null);
  const pollRef = useRef(null);
  const prevStageRef = useRef(null);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const applyStatus = useCallback((s) => {
    setStatus(s);
    if (s.stage === "done" && prevStageRef.current !== "done") {
      setLastCompletedAt(Date.now());
    }
    prevStageRef.current = s.stage;
    if (!ACTIVE_STAGES.has(s.stage)) {
      stopPolling();
    }
  }, [stopPolling]);

  const startPolling = useCallback((user) => {
    stopPolling();
    pollRef.current = setInterval(async () => {
      let s;
      try {
        s = await getRefreshStatus(user);
      } catch {
        return; // transient poll failure, keep trying
      }
      applyStatus(s);
    }, POLL_MS);
  }, [applyStatus, stopPolling]);

  useEffect(() => {
    stopPolling();
    setStatus(null);
    prevStageRef.current = null;
    if (!username) return undefined;

    let cancelled = false;
    (async () => {
      let s;
      try {
        s = await getRefreshStatus(username);
      } catch {
        return;
      }
      if (cancelled) return;
      applyStatus(s);
      if (ACTIVE_STAGES.has(s.stage)) {
        startPolling(username);
      }
    })();

    return () => {
      cancelled = true;
      stopPolling();
    };
  }, [username, applyStatus, startPolling, stopPolling]);

  const start = useCallback(async () => {
    if (!username) return { status: "no_username" };
    applyStatus({ stage: "starting", current: 0, total: null, message: "Starting refresh..." });
    let res;
    try {
      res = await refresh(username);
    } catch {
      applyStatus({ stage: "error", current: 0, total: null, message: "Couldn't reach the backend to start the refresh. Is it running?" });
      return { status: "error" };
    }
    if (res.status !== "already_running") {
      startPolling(username);
    } else {
      startPolling(username); // rejoin the run already in flight
    }
    return res;
  }, [username, applyStatus, startPolling]);

  const cancel = useCallback(async () => {
    if (!username) return;
    try {
      await cancelRefresh(username);
    } catch {
      // ignore — the next poll reflects true backend state either way
    }
  }, [username]);

  const isRunning = !!status && ACTIVE_STAGES.has(status.stage);

  return (
    <RefreshContext.Provider value={{ status, isRunning, start, cancel, lastCompletedAt }}>
      {children}
    </RefreshContext.Provider>
  );
}

export function useRefresh() {
  const ctx = useContext(RefreshContext);
  if (!ctx) throw new Error("useRefresh must be used within RefreshProvider");
  return ctx;
}
```

- [ ] **Step 3: Mount the provider in `App.jsx`**

Modify `frontend/src/App.jsx`:

```jsx
import { useState } from "react";
import RecommendationsPage from "./RecommendationsPage";
import TasteProfilePage from "./TasteProfilePage";
import UsernameField from "./components/UsernameField";
import { useLocalStorage } from "./lib/useLocalStorage";
import { RefreshProvider } from "./context/RefreshContext";

const TABS = [
  { id: "recs", label: "Recommendations" },
  { id: "taste", label: "Taste Profile" },
];

export default function App() {
  const [tab, setTab] = useState("recs");
  const [username, setUsername] = useLocalStorage("letterboxd_username", "");

  return (
    <div className="app">
      <div className="brand">Letterboxd Recs by Arhan</div>
      <nav className="tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            className={`tab${tab === t.id ? " active" : ""}`}
            onClick={() => setTab(t.id)}
            aria-current={tab === t.id ? "page" : undefined}
          >
            {t.label}
          </button>
        ))}
      </nav>
      <UsernameField value={username} onChange={setUsername} />
      <RefreshProvider username={username}>
        <div className="page" key={tab}>
          {tab === "recs" ? (
            <RecommendationsPage username={username} />
          ) : (
            <TasteProfilePage username={username} />
          )}
        </div>
      </RefreshProvider>
    </div>
  );
}
```

- [ ] **Step 4: Build to confirm no syntax errors**

Run: `cd frontend && npm run build`
Expected: build succeeds (RecommendationsPage/TasteProfilePage still use their old local state at this point — Task 2/3 wire them to context — so this just confirms the new files compile).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/context/RefreshContext.jsx frontend/src/App.jsx frontend/src/api.js
git commit -m "feat: add RefreshProvider for global refresh state and status rehydration"
```

---

## Task 2: Progress redesign — pure percent/ETA math + `ProgressBar` rewrite (Phase 2)

**Files:**
- Create: `frontend/src/lib/progressMath.js`
- Create: `frontend/src/lib/progressMath.test.js`
- Modify: `frontend/src/components/ProgressBar.jsx`
- Modify: `frontend/package.json` (add vitest)

- [ ] **Step 1: Add vitest**

Run: `cd frontend && npm install -D vitest`

Modify `frontend/package.json` scripts block:

```json
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "lint": "oxlint",
    "preview": "vite preview",
    "test": "vitest run"
  },
```

- [ ] **Step 2: Write the failing tests for the pure math**

Create `frontend/src/lib/progressMath.test.js`:

```js
import { describe, it, expect } from "vitest";
import { computePercent, computeEtaSec, monotonicPercent, formatClock, STAGE_BANDS } from "./progressMath";

describe("STAGE_BANDS", () => {
  it("covers every pipeline stage with a non-overlapping, ascending band", () => {
    const order = ["scraping", "enriching", "profiling", "scoring", "done"];
    let prevCeil = 0;
    for (const stage of order) {
      const [floor, ceil] = STAGE_BANDS[stage];
      expect(floor).toBe(prevCeil);
      expect(ceil).toBeGreaterThanOrEqual(floor);
      prevCeil = ceil;
    }
    expect(prevCeil).toBe(100);
  });
});

describe("computePercent", () => {
  it("returns 100 for done", () => {
    expect(computePercent({ stage: "done", current: 5, total: 5 }, {})).toBe(100);
  });

  it("interpolates determinate enriching stage linearly within its band", () => {
    const [floor, ceil] = STAGE_BANDS.enriching;
    const pct = computePercent({ stage: "enriching", current: 5, total: 10 }, { stageElapsedMs: 0 });
    expect(pct).toBeCloseTo(floor + 0.5 * (ceil - floor), 5);
  });

  it("interpolates determinate scoring stage linearly within its band", () => {
    const [floor, ceil] = STAGE_BANDS.scoring;
    const pct = computePercent({ stage: "scoring", current: 3, total: 12 }, { stageElapsedMs: 0 });
    expect(pct).toBeCloseTo(floor + (3 / 12) * (ceil - floor), 5);
  });

  it("creeps toward but never reaches the scraping band ceiling as time passes", () => {
    const [, ceil] = STAGE_BANDS.scraping;
    const early = computePercent({ stage: "scraping", current: 0, total: null }, { stageElapsedMs: 1000 });
    const later = computePercent({ stage: "scraping", current: 0, total: null }, { stageElapsedMs: 120000 });
    expect(later).toBeGreaterThan(early);
    expect(later).toBeLessThan(ceil);
  });

  it("creeps toward but never reaches the profiling band ceiling", () => {
    const [, ceil] = STAGE_BANDS.profiling;
    const pct = computePercent({ stage: "profiling", current: 0, total: null }, { stageElapsedMs: 600000 });
    expect(pct).toBeLessThan(ceil);
  });

  it("never returns a percent below the stage floor", () => {
    const [floor] = STAGE_BANDS.scoring;
    const pct = computePercent({ stage: "scoring", current: 0, total: 100 }, { stageElapsedMs: 0 });
    expect(pct).toBeGreaterThanOrEqual(floor);
  });
});

describe("monotonicPercent", () => {
  it("never rewinds even if the raw computation dips", () => {
    expect(monotonicPercent(40, 60)).toBe(60);
    expect(monotonicPercent(70, 60)).toBe(70);
  });

  it("holds steady across a full scripted run", () => {
    const sequence = [
      { stage: "scraping", current: 0, total: null, stageElapsedMs: 0 },
      { stage: "scraping", current: 0, total: null, stageElapsedMs: 5000 },
      { stage: "enriching", current: 0, total: 20, stageElapsedMs: 0 },
      { stage: "enriching", current: 10, total: 20, stageElapsedMs: 5000 },
      { stage: "enriching", current: 20, total: 20, stageElapsedMs: 10000 },
      { stage: "profiling", current: 0, total: null, stageElapsedMs: 0 },
      { stage: "scoring", current: 0, total: 15, stageElapsedMs: 0 },
      { stage: "scoring", current: 15, total: 15, stageElapsedMs: 8000 },
      { stage: "done", current: 15, total: 15, stageElapsedMs: 0 },
    ];
    let max = 0;
    for (const s of sequence) {
      const raw = computePercent(s, { stageElapsedMs: s.stageElapsedMs });
      const displayed = monotonicPercent(raw, max);
      expect(displayed).toBeGreaterThanOrEqual(max);
      max = displayed;
    }
    expect(max).toBe(100);
  });
});

describe("computeEtaSec", () => {
  it("returns null once done", () => {
    expect(computeEtaSec({ stage: "done", current: 5, total: 5 }, {})).toBeNull();
  });

  it("returns null on error or cancelled", () => {
    expect(computeEtaSec({ stage: "error", current: 0, total: null }, {})).toBeNull();
    expect(computeEtaSec({ stage: "cancelled", current: 0, total: null }, {})).toBeNull();
  });

  it("is positive during an in-progress determinate stage", () => {
    const eta = computeEtaSec({ stage: "enriching", current: 2, total: 20 }, { stageElapsedMs: 4000 });
    expect(eta).toBeGreaterThan(0);
  });

  it("shrinks as a determinate stage nears completion at a constant rate", () => {
    const early = computeEtaSec({ stage: "enriching", current: 2, total: 20 }, { stageElapsedMs: 4000 });
    const late = computeEtaSec({ stage: "enriching", current: 18, total: 20 }, { stageElapsedMs: 36000 });
    expect(late).toBeLessThan(early);
  });
});

describe("formatClock", () => {
  it("formats seconds as m:ss", () => {
    expect(formatClock(5)).toBe("0:05");
    expect(formatClock(65)).toBe("1:05");
    expect(formatClock(0)).toBe("0:00");
  });

  it("floors negative input to zero", () => {
    expect(formatClock(-3)).toBe("0:00");
  });
});
```

- [ ] **Step 3: Run to confirm failure**

Run: `cd frontend && npx vitest run src/lib/progressMath.test.js`
Expected: FAIL — `Cannot find module './progressMath'`.

- [ ] **Step 4: Implement `progressMath.js`**

Create `frontend/src/lib/progressMath.js`:

```js
export const STAGE_BANDS = {
  scraping: [0, 55],
  enriching: [55, 80],
  profiling: [80, 86],
  scoring: [86, 99],
  done: [100, 100],
};

const DETERMINATE_STAGES = new Set(["enriching", "scoring"]);

// Constants driving the "fake but honest" creep for indeterminate stages
// and the ETA guess for stages with no live count yet. Real counts always
// override these once the backend reports them.
const SEC_PER_FILM_SCRAPE = 3.5;
const SCRAPE_BASE_ESTIMATE_SEC = 45;
const PROFILING_ESTIMATE_SEC = 8;
const SCORING_FALLBACK_ESTIMATE_SEC = 20;
const FLAT_ESTIMATE_SEC = { profiling: PROFILING_ESTIMATE_SEC };

function bandFor(stage) {
  return STAGE_BANDS[stage] || STAGE_BANDS.scraping;
}

function estimateStageDurationSec(stage, status) {
  if (stage === "scraping") {
    const found = status.current || 0;
    return Math.max(SCRAPE_BASE_ESTIMATE_SEC, found * SEC_PER_FILM_SCRAPE * 1.6);
  }
  if (stage === "profiling") return PROFILING_ESTIMATE_SEC;
  if (stage === "scoring") return SCORING_FALLBACK_ESTIMATE_SEC;
  return SCRAPE_BASE_ESTIMATE_SEC;
}

function creepFraction(elapsedSec, estimatedSec) {
  if (estimatedSec <= 0) return 0.96;
  const ratio = elapsedSec / estimatedSec;
  return Math.min(0.96, 1 - Math.exp(-ratio * 1.5));
}

export function computePercent(status, { stageElapsedMs = 0 } = {}) {
  const stage = status.stage;
  if (stage === "done") return 100;
  if (stage === "error" || stage === "cancelled" || !STAGE_BANDS[stage] && stage !== "scraping") {
    return 0;
  }
  const [floor, ceil] = bandFor(stage);
  const determinateReady = DETERMINATE_STAGES.has(stage) && typeof status.total === "number" && status.total > 0;
  if (determinateReady) {
    const frac = Math.min(1, Math.max(0, status.current / status.total));
    return floor + frac * (ceil - floor);
  }
  const estSec = estimateStageDurationSec(stage, status);
  const frac = creepFraction(stageElapsedMs / 1000, estSec);
  return floor + frac * (ceil - floor);
}

export function monotonicPercent(rawPercent, prevMaxPercent) {
  return Math.max(rawPercent, prevMaxPercent);
}

const STAGE_ORDER = ["scraping", "enriching", "profiling", "scoring"];

export function computeEtaSec(status, { stageElapsedMs = 0 } = {}) {
  const stage = status.stage;
  if (stage === "done" || stage === "error" || stage === "cancelled") return null;
  const idx = STAGE_ORDER.indexOf(stage);
  if (idx === -1) return null;

  let remaining = 0;
  for (let i = idx; i < STAGE_ORDER.length; i++) {
    const s = STAGE_ORDER[i];
    if (s === stage) {
      if (DETERMINATE_STAGES.has(s) && typeof status.total === "number" && status.total > 0 && status.current > 0) {
        const rate = status.current / Math.max(1, stageElapsedMs / 1000);
        remaining += rate > 0 ? (status.total - status.current) / rate : estimateStageDurationSec(s, status);
      } else {
        const est = estimateStageDurationSec(s, status);
        remaining += Math.max(0, est - stageElapsedMs / 1000);
      }
    } else {
      remaining += FLAT_ESTIMATE_SEC[s] ?? estimateStageDurationSec(s, status);
    }
  }
  return remaining;
}

export function formatClock(totalSeconds) {
  const s = Math.max(0, Math.round(totalSeconds));
  const m = Math.floor(s / 60);
  const rem = s % 60;
  return `${m}:${String(rem).padStart(2, "0")}`;
}
```

- [ ] **Step 5: Run to confirm the tests pass**

Run: `cd frontend && npx vitest run src/lib/progressMath.test.js`
Expected: PASS, all tests green.

- [ ] **Step 6: Rewrite `ProgressBar.jsx` to consume the pure math**

Modify `frontend/src/components/ProgressBar.jsx` (replace entire file):

```jsx
import { useEffect, useRef, useState } from "react";
import { computePercent, computeEtaSec, monotonicPercent, formatClock } from "../lib/progressMath";

const STAGE_LABELS = {
  starting: "Starting...",
  scraping: "Scraping your Letterboxd ratings",
  enriching: "Fetching film details",
  profiling: "Building your taste profile",
  scoring: "Scoring candidates",
  done: "Done",
  cancelled: "Cancelled",
  error: "Something went wrong",
};

const STEP_INDEX = { starting: 1, scraping: 1, enriching: 2, profiling: 3, scoring: 4, done: 4 };
const TOTAL_STEPS = 4;

export default function ProgressBar({ status }) {
  const [now, setNow] = useState(() => Date.now());
  const startedAtRef = useRef(null);
  const stageRef = useRef(null);
  const stageStartRef = useRef(null);
  const maxPercentRef = useRef(0);

  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    if (!status) {
      startedAtRef.current = null;
      stageRef.current = null;
      stageStartRef.current = null;
      maxPercentRef.current = 0;
      return;
    }
    if (startedAtRef.current === null) startedAtRef.current = Date.now();
    if (stageRef.current !== status.stage) {
      stageRef.current = status.stage;
      stageStartRef.current = Date.now();
    }
  }, [status]);

  if (!status) return null;
  const { stage, message } = status;

  const stageElapsedMs = stageStartRef.current ? now - stageStartRef.current : 0;
  const totalElapsedSec = startedAtRef.current ? (now - startedAtRef.current) / 1000 : 0;

  const rawPercent = computePercent(status, { stageElapsedMs });
  const percent = monotonicPercent(rawPercent, maxPercentRef.current);
  maxPercentRef.current = percent;

  const etaSec = stage === "cancelled" || stage === "error" ? null : computeEtaSec(status, { stageElapsedMs });
  const step = STEP_INDEX[stage] || 0;

  return (
    <div className="progress-wrap" role="status" aria-live="polite">
      <div className="progress-label">
        {step > 0 && <span className="progress-step">Step {step}/{TOTAL_STEPS}</span>}
        <span>{STAGE_LABELS[stage] || stage}</span>
        <span className="progress-count">{Math.round(percent)}%</span>
      </div>
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${percent}%` }} />
      </div>
      {stage !== "error" && (
        <div className="progress-meta">
          <span>Elapsed {formatClock(totalElapsedSec)}</span>
          {etaSec !== null && <span> · ~{formatClock(etaSec)} left</span>}
        </div>
      )}
      {stage === "scraping" && (
        <div className="progress-note">
          Letterboxd throttles scraping — roughly 3–4s per film, longer for bigger profiles.
        </div>
      )}
      {message && stage === "error" && <div className="progress-error">{message}</div>}
    </div>
  );
}
```

Note the prop is renamed `progress` → `status` to match what `useRefresh()` exposes. Callers are updated in Tasks 3.

- [ ] **Step 7: Run full frontend test suite and build**

Run: `cd frontend && npx vitest run && npm run build`
Expected: all vitest tests pass; build succeeds (RecommendationsPage still passes the old `progress` prop name at this point — harmless, React just gets an extra unused prop — fixed in Task 3).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/lib/progressMath.js frontend/src/lib/progressMath.test.js frontend/src/components/ProgressBar.jsx frontend/package.json frontend/package-lock.json
git commit -m "feat: replace jumpy progress bar with monotonic percent/ETA model"
```

---

## Task 3: Wire pages to `RefreshContext`, data-aware button, cancel, `UsernameField` layout (Phases 1 cont'd, 3)

**Files:**
- Modify: `frontend/src/RecommendationsPage.jsx`
- Modify: `frontend/src/TasteProfilePage.jsx`
- Modify: `frontend/src/components/RefreshButton.jsx`
- Modify: `frontend/src/components/UsernameField.jsx`
- Modify: `frontend/src/index.css`

- [ ] **Step 1: Rewrite `RecommendationsPage.jsx` to consume context**

Modify `frontend/src/RecommendationsPage.jsx` (replace entire file):

```jsx
import { useEffect, useState } from "react";
import { getRecommendations, getLastUpdated } from "./api";
import { useRefresh } from "./context/RefreshContext";
import RefreshButton from "./components/RefreshButton";
import RecommendationCard from "./components/RecommendationCard";
import ProgressBar from "./components/ProgressBar";
import MarqueeTrio from "./components/MarqueeTrio";
import FilmDetailModal from "./components/FilmDetailModal";
import LastUpdated from "./components/LastUpdated";

function SkeletonGrid({ count = 6 }) {
  return (
    <div className="grid" aria-hidden="true">
      {Array.from({ length: count }).map((_, i) => (
        <div className="skeleton-card" key={i}>
          <div className="skeleton-block skeleton-poster" />
          <div className="skeleton-block skeleton-line" />
          <div className="skeleton-block skeleton-line short" />
        </div>
      ))}
    </div>
  );
}

export default function RecommendationsPage({ username }) {
  const [recs, setRecs] = useState(null);
  const [error, setError] = useState(null);
  const [selectedFilm, setSelectedFilm] = useState(null);
  const [updatedAt, setUpdatedAt] = useState(null);
  const { status, isRunning, start, cancel, lastCompletedAt } = useRefresh();

  const load = async () => {
    if (!username) return;
    try {
      setRecs(await getRecommendations(username));
    } catch {
      setError("Couldn't load recommendations. Is the backend running?");
    }
    try {
      setUpdatedAt((await getLastUpdated(username)).last_updated);
    } catch {
      // non-critical, skip silently
    }
  };

  useEffect(() => {
    setRecs(null);
    setUpdatedAt(null);
    load();
  }, [username]);

  useEffect(() => {
    if (lastCompletedAt) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastCompletedAt]);

  useEffect(() => {
    if (status?.stage === "error") {
      setError(`Refresh failed — ${status.message || "check your TMDB key and username, then try again."}`);
    }
  }, [status]);

  const onRefresh = async () => {
    if (!username) {
      setError("Enter your Letterboxd username above before refreshing.");
      return;
    }
    setError(null);
    await start();
  };

  const LONG_SHOT_THRESHOLD = 70;
  const PAGE_SIZE = 25;

  const trio = recs ? recs.slice(0, 3) : [];
  const remaining = recs ? recs.slice(3) : [];
  const mainList = remaining.filter((r) => r.match_pct >= LONG_SHOT_THRESHOLD);
  const longShots = remaining.filter((r) => r.match_pct < LONG_SHOT_THRESHOLD);
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const visibleMain = mainList.slice(0, visibleCount);
  const [showLongShots, setShowLongShots] = useState(false);

  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
    setShowLongShots(false);
  }, [recs]);

  const hasData = !!(recs && recs.length > 0);

  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 20 }}>
        <h2 style={{ fontSize: 15, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--muted)", fontFamily: "var(--font-body)" }}>
          Recommendations
        </h2>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <LastUpdated iso={updatedAt} />
          <RefreshButton loading={isRunning} hasData={hasData} onClick={onRefresh} onCancel={cancel} />
        </div>
      </div>

      {isRunning && <ProgressBar status={status} />}

      {error && (
        <div className="error-banner">
          <span className="error-mark">!</span>
          <span>{error}</span>
        </div>
      )}

      {!username && (
        <div className="empty-state">
          <h3>Enter your Letterboxd username</h3>
          <p>Add it above, then click "Load my data" to generate recommendations.</p>
        </div>
      )}

      {username && recs === null && <SkeletonGrid />}

      {username && recs !== null && recs.length === 0 && !isRunning && (
        <div className="empty-state">
          <h3>No recommendations yet</h3>
          <p>Click "Load my data" to scrape your Letterboxd ratings and generate picks.</p>
        </div>
      )}

      <MarqueeTrio recs={trio} onSelect={setSelectedFilm} />

      {visibleMain.length > 0 && (
        <div className="grid">
          {visibleMain.map((r, i) => (
            <RecommendationCard rec={r} index={i} key={r.tmdb_id} onSelect={setSelectedFilm} />
          ))}
        </div>
      )}

      {visibleCount < mainList.length && (
        <button className="show-more-button" onClick={() => setVisibleCount((c) => c + PAGE_SIZE)}>
          Show {Math.min(PAGE_SIZE, mainList.length - visibleCount)} more
        </button>
      )}

      {longShots.length > 0 && (
        <div className="long-shots-section">
          <button className="long-shots-toggle" onClick={() => setShowLongShots((s) => !s)}>
            {showLongShots ? "Hide" : "Show"} long shots ({longShots.length} below {LONG_SHOT_THRESHOLD}% match)
          </button>
          {showLongShots && (
            <div className="grid">
              {longShots.map((r, i) => (
                <RecommendationCard rec={r} index={i} key={r.tmdb_id} onSelect={setSelectedFilm} />
              ))}
            </div>
          )}
        </div>
      )}

      {selectedFilm && (
        <FilmDetailModal film={selectedFilm} onClose={() => setSelectedFilm(null)} />
      )}
    </div>
  );
}
```

Note `recs === null && <SkeletonGrid />` intentionally stays ungated by `isRunning` — it's the initial-load skeleton, not the stale refresh CTA. Only the "No recommendations yet" empty-state (the one the spec calls out) is gated on `!isRunning`.

- [ ] **Step 2: Rewrite `TasteProfilePage.jsx` to consume context**

Modify `frontend/src/TasteProfilePage.jsx:68-99` (the component function and its early returns):

```jsx
import { useEffect, useState } from "react";
import { getTasteProfile, getLastUpdated } from "./api";
import { useRefresh } from "./context/RefreshContext";
import GenreRadar from "./components/GenreRadar";
import LastUpdated from "./components/LastUpdated";
import ProgressBar from "./components/ProgressBar";

// ...StatTile, RatingHistogram, PeopleWall, AffinityBars unchanged...

export default function TasteProfilePage({ username }) {
  const [dash, setDash] = useState(null);
  const [updatedAt, setUpdatedAt] = useState(null);
  const { status, isRunning, lastCompletedAt } = useRefresh();

  const load = () => {
    if (!username) return;
    getTasteProfile(username).then(setDash);
    getLastUpdated(username).then((r) => setUpdatedAt(r.last_updated)).catch(() => {});
  };

  useEffect(() => {
    if (!username) return;
    setDash(null);
    setUpdatedAt(null);
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [username]);

  useEffect(() => {
    if (lastCompletedAt) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [lastCompletedAt]);

  if (!username) {
    return (
      <div className="empty-state">
        <h3>Enter your Letterboxd username</h3>
        <p>Add it above to see your taste profile.</p>
      </div>
    );
  }

  if (dash === null) {
    return isRunning ? <ProgressBar status={status} /> : null;
  }

  if (dash.total_rated === 0) {
    return (
      <div>
        {isRunning && <ProgressBar status={status} />}
        <div className="empty-state">
          <h3>No taste profile yet</h3>
          <p>Refresh your data from the Recommendations tab to build your taste profile.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="taste-dashboard">
      {isRunning && <ProgressBar status={status} />}
      <div className="dashboard-eyebrow-row">
        <div className="dashboard-eyebrow">Your Taste Fingerprint</div>
        <LastUpdated iso={updatedAt} />
      </div>

      <div className="stat-row">
        <StatTile value={dash.total_rated} label="Films rated" />
        <StatTile value={dash.average_rating.toFixed(1) + "★"} label="Avg you give" />
        <StatTile value={dash.favorite_decade ? `${dash.favorite_decade}s` : "—"} label="Favorite decade" />
        <StatTile value={dash.top_directors[0]?.name ?? "—"} label="Top director" />
      </div>

      <div className="dashboard-grid">
        <div>
          <p className="section-title">How you rate</p>
          <RatingHistogram distribution={dash.rating_distribution} />
          <div className="signature-line">{dash.signature}</div>
        </div>
        <div>
          <p className="section-title">Strongest affinities</p>
          <AffinityBars genres={dash.genre_affinities} />
          {dash.top_keywords.length > 0 && (
            <div className="keyword-chips">
              {dash.top_keywords.map((k) => (
                <span className="keyword-chip" key={k}>{k}</span>
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="dashboard-grid">
        <div>
          <p className="section-title">Genre radar</p>
          <GenreRadar genres={dash.genre_affinities} />
        </div>
        <div>
          <PeopleWall title="Top directors" people={dash.top_directors} />
          <PeopleWall title="Top actors" people={dash.top_actors} />
        </div>
      </div>
    </div>
  );
}
```

Keep `StatTile`, `RatingHistogram`, `PeopleWall`, `AffinityBars` (`TasteProfilePage.jsx:8-66`) exactly as they are — only the default-exported component and its imports change.

- [ ] **Step 3: Data-aware `RefreshButton` with Cancel affordance**

Modify `frontend/src/components/RefreshButton.jsx` (replace entire file):

```jsx
export default function RefreshButton({ loading, hasData, onClick, onCancel }) {
  return (
    <span className="refresh-controls">
      <button
        className={`refresh-btn${loading ? " loading" : ""}`}
        onClick={onClick}
        disabled={loading}
        aria-busy={loading}
      >
        {loading ? "Refreshing…" : hasData ? "Refresh my data" : "Load my data"}
      </button>
      {loading && (
        <button type="button" className="cancel-btn" onClick={onCancel}>
          Cancel
        </button>
      )}
    </span>
  );
}
```

- [ ] **Step 4: `UsernameField` single-row layout**

Modify `frontend/src/components/UsernameField.jsx` (JSX unchanged — layout is CSS-only per the spec; only the class names need the new styling hook, and there isn't a code change here beyond what already exists). Confirm no JS change is needed: the existing markup (`frontend/src/components/UsernameField.jsx:17-33`) already has `label` before `input` in one `.username-field` container — the flex row and font-size upgrade are pure CSS (Step 5).

- [ ] **Step 5: CSS — cancel button, username row/type, done**

Modify `frontend/src/index.css`:

Add after `.refresh-btn:disabled` block (`index.css:335-337`):

```css
.refresh-controls {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.cancel-btn {
  min-height: 44px;
  padding: 10px 16px;
  border-radius: 999px;
  border: 1px solid var(--border);
  background: transparent;
  color: var(--muted);
  font-size: 13px;
  cursor: pointer;
  transition: border-color var(--dur-micro) var(--ease-out-expo),
    color var(--dur-micro) var(--ease-out-expo);
}

.cancel-btn:hover {
  border-color: var(--accent-dim);
  color: var(--ink);
}
```

Replace the `.username-field input` typography (`index.css:94-104`) to bump the value's font size relative to the label (the row is already `display: flex; align-items: center` at `index.css:79-84`, satisfying the single-row requirement):

```css
.username-field input {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--ink);
  padding: 8px 12px;
  min-height: 40px;
  font-size: 16px;
  min-width: 200px;
  transition: border-color var(--dur-micro) var(--ease-out-expo);
}
```

(`font-size` raised from `14px` to `16px`, larger than the label's `11px` at `index.css:87`.)

- [ ] **Step 6: Build and manually verify**

Run: `cd frontend && npm run build`
Expected: build succeeds.

Manual check (dev server): `npm run dev`, open the app —
- First-time username (no recs) → button reads "Load my data".
- After a refresh completes → button reads "Refresh my data".
- Click refresh → button reads "Refreshing…", a Cancel button appears beside it.
- Switch to Taste Profile tab mid-refresh → progress bar is visible there too, still advancing.
- Switch back to Recommendations → progress bar still there, not reset.
- Reload the page mid-refresh → progress bar re-attaches within one poll interval.
- The "Click 'Load my data'/'Refresh my data' to…" empty-state text disappears the instant a run starts.
- Username row is a single line; the username value text is visibly larger than the "Letterboxd username" label.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/RecommendationsPage.jsx frontend/src/TasteProfilePage.jsx frontend/src/components/RefreshButton.jsx frontend/src/index.css
git commit -m "feat: data-aware refresh button, cancel affordance, cross-tab progress"
```

---

## Task 4: Backend cancel — truly abort (Phase 4)

**Files:**
- Create: `backend/app/errors.py`
- Modify: `backend/app/scraper.py`
- Modify: `backend/app/pipeline.py`
- Modify: `backend/app/api.py`
- Test: `backend/tests/test_scraper.py`, `backend/tests/test_pipeline.py`, `backend/tests/test_api.py`

- [ ] **Step 1: Shared `Cancelled` exception**

Create `backend/app/errors.py`:

```python
class Cancelled(Exception):
    """Raised when a refresh run is cancelled mid-flight by the user."""
```

- [ ] **Step 2: Write failing scraper cancel tests**

Add to `backend/tests/test_scraper.py`:

```python
from app.errors import Cancelled

def test_scrape_profile_raises_cancelled_before_films_page_fetch():
    def fake_get(url):
        raise AssertionError("get_html should not be called once cancelled")
    with pytest.raises(Cancelled):
        scrape_profile("alice", fake_get, delay=0, should_cancel=lambda: True)

def test_scrape_profile_raises_cancelled_mid_film_detail_loop():
    page1 = (FIX / "films_page.html").read_text()  # 3 films
    detail = (FIX / "film_detail.html").read_text()
    calls = {"n": 0}
    def fake_get(url):
        if url.endswith("/films/"):
            return page1
        calls["n"] += 1
        return detail
    def should_cancel():
        return calls["n"] >= 1  # cancel after the first film-detail fetch
    with pytest.raises(Cancelled):
        scrape_profile("alice", fake_get, delay=0, should_cancel=should_cancel)

def test_scrape_profile_closes_browser_on_cancel(monkeypatch):
    closed = {"browser": False, "pw": False}
    class _FakeBrowser:
        def close(self):
            closed["browser"] = True
    class _FakePw:
        def stop(self):
            closed["pw"] = True
    monkeypatch.setattr(scraper._thread_local, "page", object(), raising=False)
    monkeypatch.setattr(scraper._thread_local, "browser", _FakeBrowser(), raising=False)
    monkeypatch.setattr(scraper._thread_local, "pw", _FakePw(), raising=False)

    def fake_get(url):
        raise AssertionError("unreachable")
    with pytest.raises(Cancelled):
        scrape_profile("alice", fake_get, delay=0, should_cancel=lambda: True)
    assert closed == {"browser": True, "pw": True}
```

Also update every `_FakePage` construction in `test_scraper.py` (`test_scraper.py:90-104` and the Task 0 additions) to keep working — no changes needed there since `should_cancel` defaults to `None` and doesn't touch `_get_page`.

- [ ] **Step 3: Run to confirm failure**

Run: `cd backend && .venv/bin/pytest tests/test_scraper.py -k cancel -v`
Expected: FAIL — `scrape_profile() got an unexpected keyword argument 'should_cancel'` / `ImportError: cannot import name 'Cancelled'`.

- [ ] **Step 4: Implement scraper cancel checkpoints + teardown**

Modify `backend/app/scraper.py` — add the import and a `_close_page` helper after `_get_page` (`scraper.py:62-75`):

```python
from app.errors import Cancelled

def _close_page():
    if hasattr(_thread_local, "browser"):
        try:
            _thread_local.browser.close()
        finally:
            _thread_local.pw.stop()
        del _thread_local.page
        del _thread_local.browser
        del _thread_local.pw
```

Rewrite `scrape_profile` (`scraper.py:93-126`):

```python
def scrape_profile(
    username: str, get_html=default_get, delay: float = 1.0, on_progress=None, should_cancel=None
) -> list[dict]:
    films = []
    total_seen = 0
    url = f"{BASE}/{username}/films/"
    try:
        while url:
            if should_cancel and should_cancel():
                raise Cancelled()
            html = get_html(url)
            page_entries = parse_films_page(html)
            total_seen += len(page_entries)
            for entry in page_entries:
                if should_cancel and should_cancel():
                    raise Cancelled()
                detail = get_html(f"{BASE}/film/{entry['slug']}/")
                entry["tmdb_id"] = parse_tmdb_id(detail)
                # Films Letterboxd can't link to TMDB can never be produced as a
                # recommendation candidate (candidates always come from TMDB), so
                # they're safe to drop here — nothing to exclude them from.
                if entry["tmdb_id"] is not None:
                    films.append(entry)
                if on_progress:
                    on_progress(len(films))
                if delay:
                    time.sleep(delay)
            nxt = parse_next_page_url(html)
            url = f"{BASE}{nxt}" if nxt else None

        profile_html = get_html(f"{BASE}/{username}/")
        declared = parse_declared_film_count(profile_html)
        if declared is not None and total_seen < declared:
            raise RuntimeError(
                f"Incomplete scrape: found {total_seen} films but {username}'s "
                f"Letterboxd profile reports {declared}. The crawl was likely "
                f"blocked partway through — try refreshing again."
            )
        return films
    finally:
        _close_page()
```

(This applies whatever Task 0 fix landed — merge rather than overwrite if Task 0 already changed `delay` default or `default_get`.)

- [ ] **Step 5: Run scraper tests**

Run: `cd backend && .venv/bin/pytest tests/test_scraper.py -v`
Expected: PASS, all tests including the 3 new ones.

- [ ] **Step 6: Write failing pipeline cancel test**

Add to `backend/tests/test_pipeline.py`:

```python
import threading
from app.errors import Cancelled

def test_run_refresh_raises_cancelled_when_event_set_before_enrich_loop(tmp_path):
    conn = connect(str(tmp_path / "t.db"))
    init_schema(conn)
    cfg = Config(username="alice", tmdb_api_key="k", db_path="t.db")

    scraped = [{"slug": "parasite", "title": "Parasite", "rating": 5.0, "tmdb_id": 1}]
    cancel_event = threading.Event()
    cancel_event.set()  # already cancelled before run starts
    deps = Deps(
        scrape_fn=lambda user, on_progress=None, should_cancel=None: scraped,
        enrich_fn=lambda tid, key: (_ for _ in ()).throw(AssertionError("enrich_fn should not run")),
        related_fn=lambda tid, key: [],
    )
    with pytest.raises(Cancelled):
        run_refresh(conn, cfg, deps, cancel_event=cancel_event)

def test_run_refresh_raises_cancelled_mid_scoring_loop(tmp_path):
    conn = connect(str(tmp_path / "t.db"))
    init_schema(conn)
    cfg = Config(username="alice", tmdb_api_key="k", db_path="t.db")

    scraped = [{"slug": "parasite", "title": "Parasite", "rating": 5.0, "tmdb_id": 1}]
    meta = {
        1: {"tmdb_id": 1, "title": "Parasite", "year": 2019, "decade": 2010,
            "director": "Bong", "genres": ["Thriller"], "cast": ["Song"],
            "keywords": [], "poster_path": "/p.jpg", "vote_avg": 8.5,
            "director_id": 1001, "director_person": {"person_id": 1001, "name": "Bong", "profile_path": "/bong.jpg"},
            "cast_people": [], "backdrop_path": "/p_bd.jpg", "overview": "...", "runtime": 132},
        99: {"tmdb_id": 99, "title": "Rec", "year": 2018, "decade": 2010,
             "director": "Bong", "genres": ["Thriller"], "cast": [],
             "keywords": [], "poster_path": "/r.jpg", "vote_avg": 7.9,
             "director_id": 1001, "director_person": {"person_id": 1001, "name": "Bong", "profile_path": "/bong.jpg"},
             "cast_people": [], "backdrop_path": "/r_bd.jpg", "overview": "...", "runtime": 118},
        100: {"tmdb_id": 100, "title": "Rec 2", "year": 2017, "decade": 2010,
              "director": "Bong", "genres": ["Thriller"], "cast": [],
              "keywords": [], "poster_path": "/r2.jpg", "vote_avg": 7.5,
              "director_id": 1001, "director_person": {"person_id": 1001, "name": "Bong", "profile_path": "/bong.jpg"},
              "cast_people": [], "backdrop_path": "/r2_bd.jpg", "overview": "...", "runtime": 100},
    }
    cancel_event = threading.Event()
    calls = {"n": 0}
    def enrich_fn(tid, key):
        calls["n"] += 1
        if calls["n"] == 2:  # 1st call is the enrich stage; this is the scoring loop's 1st call
            cancel_event.set()
        return meta[tid]
    deps = Deps(
        scrape_fn=lambda user, on_progress=None, should_cancel=None: scraped,
        enrich_fn=enrich_fn,
        related_fn=lambda tid, key: [99, 100],  # pool of 2, so a 2nd scoring iteration exists to catch the flag
    )
    with pytest.raises(Cancelled):
        run_refresh(conn, cfg, deps, cancel_event=cancel_event)
    recs = conn.execute("SELECT * FROM recommendations").fetchall()
    assert recs == []  # cancelled before the commit at the end
```

Now update every existing `Deps(...)` construction in `test_pipeline.py` whose `scrape_fn` lambda has signature `lambda user, on_progress=None: ...` (lines `34`, `61`, `93`, `136`, `145`) to accept the new kwarg:

```python
        scrape_fn=lambda user, on_progress=None, should_cancel=None: scraped,
```

(same pattern at each of the 5 sites — just append `, should_cancel=None` to each lambda's parameter list; the bodies are unchanged).

- [ ] **Step 7: Run to confirm failure**

Run: `cd backend && .venv/bin/pytest tests/test_pipeline.py -k cancel -v`
Expected: FAIL — `run_refresh() got an unexpected keyword argument 'cancel_event'`.

- [ ] **Step 8: Implement pipeline cancel checkpoints**

Modify `backend/app/pipeline.py`:

Add the import at the top (after existing imports, `pipeline.py:1-7`):

```python
from app.errors import Cancelled
```

Add a helper after `_noop` (`pipeline.py:21-22`):

```python
def _check_cancel(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise Cancelled()
```

Update `Deps.scrape_fn`'s docstring comment (`pipeline.py:15`):

```python
    scrape_fn: callable   # (username, on_progress=None, should_cancel=None) -> list[{slug,title,rating,tmdb_id}]
```

Update `run_refresh`'s signature and body (`pipeline.py:65-133`):

```python
def run_refresh(conn, cfg, deps: Deps, on_progress=None, cancel_event=None) -> None:
    on_progress = on_progress or _noop

    on_progress({"stage": "scraping", "current": 0, "total": None,
                 "message": "Scraping your Letterboxd ratings..."})
    scraped = deps.scrape_fn(
        cfg.username,
        on_progress=lambda n: on_progress({
            "stage": "scraping", "current": n, "total": None,
            "message": f"Scraping your Letterboxd ratings... {n} found",
        }),
        should_cancel=lambda: cancel_event is not None and cancel_event.is_set(),
    )

    rated_meta = []
    conn.execute("DELETE FROM ratings WHERE username=?", (cfg.username,))
    conn.execute("DELETE FROM watched WHERE username=?", (cfg.username,))
    total = len(scraped)
    for i, f in enumerate(scraped):
        _check_cancel(cancel_event)
        on_progress({"stage": "enriching", "current": i, "total": total,
                     "message": f"Fetching film details... {i}/{total}"})
        m = deps.enrich_fn(f["tmdb_id"], cfg.tmdb_api_key)
        _persist_film(conn, m)
        conn.execute("INSERT OR REPLACE INTO watched (username,film_id) VALUES (?,?)",
                     (cfg.username, f["tmdb_id"]))
        if f["rating"] is not None:
            conn.execute(
                "INSERT OR REPLACE INTO ratings (username,film_id,your_rating) VALUES (?,?,?)",
                (cfg.username, f["tmdb_id"], f["rating"]))
            rm = dict(m); rm["rating"] = f["rating"]
            rated_meta.append(rm)

    on_progress({"stage": "profiling", "current": 0, "total": None,
                 "message": "Building your taste profile..."})
    profile = build_taste_profile(rated_meta)
    watched_ids = {f["tmdb_id"] for f in scraped}
    pool = build_candidate_pool(_liked_ids(rated_meta), watched_ids,
                                cfg.tmdb_api_key, related_fn=deps.related_fn)

    if deps.person_search_fn and deps.person_discover_fn:
        on_progress({"stage": "profiling", "current": 0, "total": None,
                     "message": "Finding films by your favorite directors and actors..."})
        pool |= build_person_candidate_pool(
            _top_people(profile), watched_ids, cfg.tmdb_api_key,
            search_person_fn=deps.person_search_fn, discover_fn=deps.person_discover_fn,
        )

    cand_total = len(pool)
    cand_meta = []
    for i, cid in enumerate(pool):
        _check_cancel(cancel_event)
        on_progress({"stage": "scoring", "current": i, "total": cand_total,
                     "message": f"Scoring candidates... {i}/{cand_total}"})
        cand_meta.append(deps.enrich_fn(cid, cfg.tmdb_api_key))
    for m in cand_meta:
        _persist_film(conn, m)

    results = score_candidates(cand_meta, profile, rated_meta)

    now = datetime.now(timezone.utc).isoformat()
    conn.execute("DELETE FROM recommendations WHERE username=?", (cfg.username,))
    for r in results:
        conn.execute(
            "INSERT INTO recommendations (username,film_id,match_pct,predicted_rating,why,computed_at)"
            " VALUES (?,?,?,?,?,?)",
            (cfg.username, r["tmdb_id"], r["match_pct"], r["predicted_rating"],
             json.dumps(r["why"]), now))
    conn.commit()
    on_progress({"stage": "done", "current": total, "total": total,
                 "message": "Done"})
```

- [ ] **Step 9: Run pipeline tests**

Run: `cd backend && .venv/bin/pytest tests/test_pipeline.py -v`
Expected: PASS, all tests including the 2 new ones.

- [ ] **Step 10: Write failing API cancel tests**

Add to `backend/tests/test_api.py`:

```python
def test_post_refresh_cancel_sets_event_and_stage_becomes_cancelled(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn)
    started = threading.Event()
    from app.errors import Cancelled
    def fake_refresh(c, username=None, on_progress=None, cancel_event=None):
        started.set()
        while not cancel_event.is_set():
            time.sleep(0.01)
        raise Cancelled()
    app = create_app(conn_factory=lambda: conn, refresh_fn=fake_refresh)
    client = TestClient(app)
    client.post("/api/refresh", json={"username": "alice"})
    assert started.wait(timeout=1)

    resp = client.post("/api/refresh/cancel", json={"username": "alice"})
    assert resp.status_code == 200

    body = {}
    def check():
        nonlocal body
        body = client.get("/api/refresh/status", params={"username": "alice"}).json()
        return body.get("stage") == "cancelled"
    _wait_until(check)
    assert body["stage"] == "cancelled"

def test_cancel_event_cleared_when_new_run_starts(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn)
    seen_cancel_states = []
    def fake_refresh(c, username=None, on_progress=None, cancel_event=None):
        seen_cancel_states.append(cancel_event.is_set())
    app = create_app(conn_factory=lambda: conn, refresh_fn=fake_refresh)
    client = TestClient(app)

    client.post("/api/refresh", json={"username": "alice"})
    _wait_until(lambda: len(seen_cancel_states) == 1)
    client.post("/api/refresh/cancel", json={"username": "alice"})

    client.post("/api/refresh", json={"username": "alice"})
    _wait_until(lambda: len(seen_cancel_states) == 2)
    assert seen_cancel_states[1] is False  # fresh event for the new run, not the old cancelled one
```

Now update every existing fake `refresh_fn` in `test_api.py` whose signature is `def fake_refresh(c, username=None, on_progress=None):` or the inline lambda equivalents (`test_api.py:30,44,59,76,87,101,110,121,132,152,165`) to accept `cancel_event=None` too — e.g.:

```python
    app = create_app(conn_factory=lambda: conn, refresh_fn=lambda conn, username=None, on_progress=None, cancel_event=None: None)
```

and for the named `def fake_refresh(c, username=None, on_progress=None):` functions, add `cancel_event=None` to the parameter list.

- [ ] **Step 11: Run to confirm failure**

Run: `cd backend && .venv/bin/pytest tests/test_api.py -k cancel -v`
Expected: FAIL — `404` on `/api/refresh/cancel` / `TypeError` on unexpected kwarg.

- [ ] **Step 12: Implement the cancel endpoint and wiring**

Modify `backend/app/api.py`:

Add the import (`api.py:1-13`):

```python
from app.errors import Cancelled
```

Update `_real_refresh` (`api.py:22-33`):

```python
def _real_refresh(conn, username=None, on_progress=None, cancel_event=None):
    cfg = load_config()
    if username:
        cfg = dataclasses.replace(cfg, username=username)
    deps = Deps(
        scrape_fn=lambda user, on_progress=None, should_cancel=None: scrape_profile(
            user, on_progress=on_progress, should_cancel=should_cancel),
        enrich_fn=lambda tid, key: enrich(tid, key),
        related_fn=lambda tid, key: related_ids(tid, key, pages=3),
        person_search_fn=lambda name, key: search_person(name, key),
        person_discover_fn=lambda pid, key: discover_by_person(pid, key),
    )
    run_refresh(conn, cfg, deps, on_progress=on_progress, cancel_event=cancel_event)
```

Update the app body (`api.py:44-112`) — add a `cancel_events` store next to `progress_by_user`, clear it on new-run start, wire it into the thread, catch `Cancelled` separately, and add the endpoint:

```python
    progress_lock = threading.Lock()
    progress_by_user = {}
    cancel_events = {}

    def make_set_progress(username):
        def set_progress(p):
            with progress_lock:
                progress_by_user.setdefault(username, {}).update(p)
        return set_progress
```

```python
    ACTIVE_STAGES = {"starting", "scraping", "enriching", "profiling", "scoring"}

    @app.post("/api/refresh")
    def refresh(body: RefreshRequest | None = None):
        username = body.username if body else None
        set_progress = make_set_progress(username)

        with progress_lock:
            if progress_by_user.get(username, {}).get("stage") in ACTIVE_STAGES:
                return {"status": "already_running"}
            cancel_events[username] = threading.Event()
            progress_by_user.setdefault(username, {}).update(
                {"stage": "starting", "current": 0, "total": None, "message": "Starting refresh..."})

        cancel_event = cancel_events[username]

        def run():
            conn = get_conn()
            try:
                refresh_fn(conn, username, on_progress=set_progress, cancel_event=cancel_event)
            except Cancelled:
                conn.rollback()
                set_progress({"stage": "cancelled", "current": 0, "total": None, "message": "Refresh cancelled."})
            except Exception as e:
                conn.rollback()
                set_progress({"stage": "error", "current": 0, "total": None, "message": str(e)})

        threading.Thread(target=run, daemon=True).start()
        return {"status": "started"}

    @app.post("/api/refresh/cancel")
    def refresh_cancel(body: RefreshRequest | None = None):
        username = body.username if body else None
        with progress_lock:
            ev = cancel_events.get(username)
            if ev is None:
                ev = threading.Event()
                cancel_events[username] = ev
            ev.set()
        return {"status": "cancelling"}

    @app.get("/api/refresh/status")
    def refresh_status(username: str | None = None):
        with progress_lock:
            return progress_by_user.get(
                username, {"stage": "idle", "current": 0, "total": None, "message": ""})
```

- [ ] **Step 13: Run API tests**

Run: `cd backend && .venv/bin/pytest tests/test_api.py -v`
Expected: PASS, all tests including the 2 new ones.

- [ ] **Step 14: Run the entire backend suite**

Run: `cd backend && .venv/bin/pytest -q`
Expected: all tests pass, no regressions.

- [ ] **Step 15: Manual end-to-end cancel check**

With the backend and frontend dev servers running: start a refresh, click Cancel mid-scrape. Expected: within ~1s the button returns to its data-aware idle label, no error banner appears, and `GET /api/refresh/status?username=...` shows `{"stage": "cancelled", ...}`.

- [ ] **Step 16: Commit**

```bash
git add backend/app/errors.py backend/app/scraper.py backend/app/pipeline.py backend/app/api.py backend/tests/test_scraper.py backend/tests/test_pipeline.py backend/tests/test_api.py
git commit -m "feat: add backend cancel — per-user cancel flag, checkpoints, and endpoint"
```

---

## Final Verification (whole spec, end to end)

- [ ] Run: `cd backend && .venv/bin/pytest -q` — full suite green.
- [ ] Run: `cd frontend && npx vitest run` — full suite green.
- [ ] Run: `cd frontend && npm run build` — succeeds.
- [ ] Run: `cd frontend && npm run lint` — no new warnings introduced by this change.
- [ ] Manual, with both dev servers running (`cd backend && .venv/bin/uvicorn app.api:app --reload` and `cd frontend && npm run dev`), against a real or throwaway username:
  - Start refresh → switch tabs → progress still shown and advancing on both tabs.
  - Reload the page mid-run → progress re-attaches within one poll interval (≤800ms).
  - Percent climbs monotonically start to finish; elapsed clock ticks every second; an ETA is shown once a determinate stage begins.
  - Cancel mid-run → UI returns to a clean, data-aware idle state within ~1s, no error banner, no orphaned browser process (`ps aux | grep chromium` shows nothing lingering after a few seconds).
  - First-time username sees "Load my data"; after data exists, "Refresh my data"; the stale "Click Refresh…" text disappears the instant a run starts.
  - Username row is single-line, username value text visibly larger than its label.
  - A full scrape of `moviefan` completes with no 403.
