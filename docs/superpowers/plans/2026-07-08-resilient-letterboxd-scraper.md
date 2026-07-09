# Resilient Letterboxd Scraper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the deterministic 403 on >72-film profiles by resolving TMDB ids through a layered cascade (DB cache → RSS → TMDB search → capped detail fallback) instead of one Letterboxd detail page per film, plus a CSV-export upload escape hatch.

**Architecture:** `scrape_profile` keeps its public contract but is split into `crawl_films_list` (list pages only, ~1–10 Letterboxd requests) + a pluggable `resolve_ids` cascade built in `resolver.py`. New `rss.py` supplies exact ids for recent films; `tmdb.search_movie` resolves the rest off-Letterboxd; a `film_slug_tmdb` table makes re-runs free. `POST /api/refresh/upload` accepts a Letterboxd export and reuses `run_refresh` unchanged via a pre-resolved `entries` injection.

**Tech Stack:** FastAPI + sqlite3 + BeautifulSoup + Playwright (backend), pytest + responses; React 19 + Vite (frontend).

**Spec:** `docs/superpowers/specs/2026-07-08-resilient-letterboxd-scraper-design.md`

---

## File Map

| File | Responsibility |
|---|---|
| `backend/app/scraper.py` (modify) | List-page crawl, HTML parsing, `scrape_profile` orchestration. No longer resolves ids itself. |
| `backend/app/resolver.py` (new) | The id-resolution cascade: cache → rss → search → capped detail. Pure logic, all I/O injected. |
| `backend/app/rss.py` (new) | Fetch + parse the Letterboxd RSS feed into `slug → tmdb_id`. Never fatal. |
| `backend/app/tmdb.py` (modify) | Add `search_movie(title, year, api_key)`. |
| `backend/app/db.py` (modify) | Add `film_slug_tmdb` cache table + lookup/store helpers. |
| `backend/app/csv_import.py` (new) | Parse a Letterboxd export zip/csv into scrape-shaped entries. |
| `backend/app/api.py` (modify) | Wire the live cascade in `_real_refresh`; add `POST /api/refresh/upload`; share the launch gate. |
| `backend/scripts/live_acceptance.py` (new) | Live acceptance gate against a real profile. |
| `frontend/src/api.js`, `context/RefreshContext.jsx`, `components/RefreshButton.jsx`, `RecommendationsPage.jsx`, `index.css` (modify) | Import-from-export affordance. |

---

### Task 1: Parse year from the films-list page

The films grid carries `data-item-name="Parasite (2019)"`. Year is required for accurate TMDB search. Title should come from `data-item-name` too (img alt is a lazy-load artifact), with alt as fallback.

**Files:**
- Modify: `backend/app/scraper.py:17-30`
- Test: `backend/tests/test_scraper.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_scraper.py`:

```python
def test_parse_films_page_extracts_year_from_item_name():
    html = (FIX / "films_page.html").read_text()
    by_slug = {e["slug"]: e for e in parse_films_page(html)}
    assert by_slug["parasite"]["year"] == 2019
    assert by_slug["parasite"]["title"] == "Parasite"
    assert by_slug["cats"]["year"] == 2019

def test_parse_films_page_handles_item_name_without_year():
    html = '''<html><body><ul class="grid">
      <li class="griditem">
        <div data-item-name="Some Film" data-item-slug="some-film" data-item-link="/film/some-film/">
          <img class="image" alt="Some Film"/>
        </div>
      </li></ul></body></html>'''
    entries = parse_films_page(html)
    assert entries[0]["title"] == "Some Film"
    assert entries[0]["year"] is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && .venv/bin/python -m pytest tests/test_scraper.py -k year -v`
Expected: FAIL with `KeyError: 'year'`

- [ ] **Step 3: Implement**

In `backend/app/scraper.py`, replace `parse_films_page` with:

```python
_NAME_YEAR_RE = re.compile(r"^(.*?)\s+\((\d{4})\)$")

def _split_item_name(name: str | None) -> tuple[str | None, int | None]:
    if not name:
        return None, None
    m = _NAME_YEAR_RE.match(name)
    if m:
        return m.group(1), int(m.group(2))
    return name, None

def parse_films_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    entries = []
    for li in soup.select("li.griditem"):
        poster = li.select_one("div[data-item-slug]")
        if poster is None:
            continue
        img = poster.select_one("img")
        title, year = _split_item_name(poster.get("data-item-name"))
        if title is None:
            title = img.get("alt") if img else None
        entries.append({
            "slug": poster.get("data-item-slug"),
            "title": title,
            "year": year,
            "rating": _rating_from_class(li.select_one("span.rating")),
        })
    return entries
```

- [ ] **Step 4: Run full scraper tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_scraper.py -v`
Expected: ALL PASS (old tests still pass — title values match the fixture's `data-item-name`)

- [ ] **Step 5: Commit**

```bash
git add backend/app/scraper.py backend/tests/test_scraper.py
git commit -m "feat: parse title and year from films-list data-item-name"
```

---

### Task 2: `tmdb.search_movie`

Resolve a TMDB id from title+year via TMDB's own API — no Cloudflare. Match rule per spec: exact case-insensitive title (+ matching year when known) → that id; else any result whose year matches → its id; else `None`.

**Files:**
- Modify: `backend/app/tmdb.py`
- Test: `backend/tests/test_tmdb.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_tmdb.py` (this suite already uses the `responses` library — follow its existing pattern for activating mocks):

```python
SEARCH_URL = "https://api.themoviedb.org/3/search/movie"

@responses.activate
def test_search_movie_exact_title_and_year_match():
    responses.add(responses.GET, SEARCH_URL, json={"results": [
        {"id": 11, "title": "The Thing", "release_date": "2011-10-14"},
        {"id": 42, "title": "The Thing", "release_date": "1982-06-25"},
    ]})
    assert search_movie("the thing", 1982, "KEY") == 42

@responses.activate
def test_search_movie_falls_back_to_year_only_match():
    responses.add(responses.GET, SEARCH_URL, json={"results": [
        {"id": 7, "title": "Parasite: Special Edition", "release_date": "2019-05-30"},
    ]})
    assert search_movie("Parasite", 2019, "KEY") == 7

@responses.activate
def test_search_movie_no_match_returns_none():
    responses.add(responses.GET, SEARCH_URL, json={"results": [
        {"id": 7, "title": "Wrong Film", "release_date": "1999-01-01"},
    ]})
    assert search_movie("Parasite", 2019, "KEY") is None

@responses.activate
def test_search_movie_without_year_requires_exact_title():
    responses.add(responses.GET, SEARCH_URL, json={"results": [
        {"id": 7, "title": "Parasite", "release_date": "2019-05-30"},
    ]})
    assert search_movie("parasite", None, "KEY") == 7

@responses.activate
def test_search_movie_empty_results_returns_none():
    responses.add(responses.GET, SEARCH_URL, json={"results": []})
    assert search_movie("Nothing", 2020, "KEY") is None
```

Add `search_movie` to the file's imports from `app.tmdb`.

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/bin/python -m pytest tests/test_tmdb.py -k search_movie -v`
Expected: FAIL with `ImportError: cannot import name 'search_movie'`

- [ ] **Step 3: Implement**

Append to `backend/app/tmdb.py`:

```python
def search_movie(title: str, year: int | None, api_key: str, session=None) -> int | None:
    """Resolve a TMDB id from title+year. Exact title (+year) wins; else any
    result with a matching year; else None (caller falls through to the next
    resolution layer)."""
    params = {"api_key": api_key, "query": title}
    if year:
        params["primary_release_year"] = year
    data = _get(session, f"{API}/search/movie", params)
    results = data.get("results", [])

    def _year(r):
        rd = r.get("release_date") or ""
        return int(rd[:4]) if len(rd) >= 4 and rd[:4].isdigit() else None

    for r in results:
        if r.get("title", "").lower() == title.lower() and (year is None or _year(r) == year):
            return r["id"]
    if year is not None:
        for r in results:
            if _year(r) == year:
                return r["id"]
    return None
```

- [ ] **Step 4: Run tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_tmdb.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/tmdb.py backend/tests/test_tmdb.py
git commit -m "feat: add TMDB title+year search for off-Letterboxd id resolution"
```

---

### Task 3: `rss.py` — exact ids for recent films

`https://letterboxd.com/{user}/rss/` carries `<tmdb:movieId>` per entry. Plain `requests` first (feed path is often unchallenged — no Playwright cost); Playwright `get_html` on failure; `None`/`{}` on any error. Pure fallback layer, never fatal. Regex parsing on purpose: no new XML deps, and namespaced tags trip up html.parser.

**Files:**
- Create: `backend/app/rss.py`
- Create: `backend/tests/fixtures/rss_feed.xml`
- Test: `backend/tests/test_rss.py`

- [ ] **Step 1: Create the fixture**

`backend/tests/fixtures/rss_feed.xml`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:letterboxd="https://letterboxd.com" xmlns:tmdb="https://themoviedb.org" version="2.0">
<channel>
  <title>Letterboxd - alice</title>
  <item>
    <title>Parasite, 2019 - ★★★★★</title>
    <link>https://letterboxd.com/alice/film/parasite/</link>
    <tmdb:movieId>496243</tmdb:movieId>
  </item>
  <item>
    <title>Cats, 2019 - ★</title>
    <link>https://letterboxd.com/alice/film/cats/</link>
    <tmdb:movieId>440249</tmdb:movieId>
  </item>
  <item>
    <title>Some List Entry Without A Film</title>
    <link>https://letterboxd.com/alice/list/some-list/</link>
  </item>
</channel>
</rss>
```

- [ ] **Step 2: Write the failing tests**

`backend/tests/test_rss.py`:

```python
from pathlib import Path

import responses

from app.rss import RSS_URL_TEMPLATE, fetch_rss, parse_rss_tmdb_map

FIX = Path(__file__).parent / "fixtures"

def test_parse_rss_maps_slug_to_tmdb_id():
    xml = (FIX / "rss_feed.xml").read_text()
    assert parse_rss_tmdb_map(xml) == {"parasite": 496243, "cats": 440249}

def test_parse_rss_garbage_returns_empty():
    assert parse_rss_tmdb_map("<not>even</rss>") == {}
    assert parse_rss_tmdb_map("") == {}

@responses.activate
def test_fetch_rss_uses_plain_requests_first():
    responses.add(responses.GET, RSS_URL_TEMPLATE.format(username="alice"),
                  body="<rss>feed</rss>", status=200)
    def get_html(url):
        raise AssertionError("Playwright fallback should not be used on 200")
    assert fetch_rss("alice", get_html=get_html) == "<rss>feed</rss>"

@responses.activate
def test_fetch_rss_falls_back_to_get_html_on_403():
    responses.add(responses.GET, RSS_URL_TEMPLATE.format(username="alice"), status=403)
    assert fetch_rss("alice", get_html=lambda url: "<rss>via-playwright</rss>") == "<rss>via-playwright</rss>"

@responses.activate
def test_fetch_rss_returns_none_when_everything_fails():
    responses.add(responses.GET, RSS_URL_TEMPLATE.format(username="alice"), status=403)
    def get_html(url):
        raise RuntimeError("blocked")
    assert fetch_rss("alice", get_html=get_html) is None
    assert fetch_rss("alice", get_html=None) is None
```

- [ ] **Step 3: Run to verify failure**

Run: `cd backend && .venv/bin/python -m pytest tests/test_rss.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.rss'`

- [ ] **Step 4: Implement**

`backend/app/rss.py`:

```python
"""Letterboxd RSS feed: exact tmdb ids for a user's ~50 most recent films.
A pure fallback layer for the id-resolution cascade — every failure path
returns None/{} rather than raising."""
import re

import requests

from app.scraper import USER_AGENT

RSS_URL_TEMPLATE = "https://letterboxd.com/{username}/rss/"

_ITEM_RE = re.compile(r"<item>(.*?)</item>", re.S)
_SLUG_RE = re.compile(r"letterboxd\.com/[^/]+/film/([^/]+)/")
_TMDB_RE = re.compile(r"<tmdb:movieId>(\d+)</tmdb:movieId>")

def fetch_rss(username: str, get_html=None) -> str | None:
    url = RSS_URL_TEMPLATE.format(username=username)
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
        if resp.status_code == 200:
            return resp.text
    except requests.RequestException:
        pass
    if get_html is None:
        return None
    try:
        return get_html(url)
    except Exception:
        return None

def parse_rss_tmdb_map(xml: str) -> dict[str, int]:
    out = {}
    for item in _ITEM_RE.findall(xml or ""):
        slug_m = _SLUG_RE.search(item)
        tmdb_m = _TMDB_RE.search(item)
        if slug_m and tmdb_m:
            out[slug_m.group(1)] = int(tmdb_m.group(1))
    return out
```

- [ ] **Step 5: Run tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_rss.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/rss.py backend/tests/test_rss.py backend/tests/fixtures/rss_feed.xml
git commit -m "feat: RSS feed fetch/parse for exact TMDB ids on recent films"
```

---

### Task 4: DB cache table + helpers

`slug → tmdb_id` persistence. A present row with NULL `tmdb_id` means "authoritatively confirmed no TMDB link" — never re-fetch. `store` commits immediately so the cache survives a run that later fails.

**Files:**
- Modify: `backend/app/db.py`
- Test: `backend/tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_db.py` (follow its existing in-memory-connection pattern; add imports for the two new helpers):

```python
def test_slug_tmdb_cache_roundtrip():
    conn = connect(":memory:")
    init_schema(conn)
    assert lookup_slug_tmdb(conn, "parasite") is None  # no row yet
    store_slug_tmdb(conn, "parasite", 496243, "search")
    assert lookup_slug_tmdb(conn, "parasite") == (496243,)

def test_slug_tmdb_cache_stores_negative_result():
    conn = connect(":memory:")
    init_schema(conn)
    store_slug_tmdb(conn, "obscure-film", None, "none")
    # row exists (don't re-fetch) but the id is None
    assert lookup_slug_tmdb(conn, "obscure-film") == (None,)

def test_slug_tmdb_cache_upsert_overwrites():
    conn = connect(":memory:")
    init_schema(conn)
    store_slug_tmdb(conn, "parasite", None, "none")
    store_slug_tmdb(conn, "parasite", 496243, "detail")
    assert lookup_slug_tmdb(conn, "parasite") == (496243,)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/bin/python -m pytest tests/test_db.py -k slug_tmdb -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement**

In `backend/app/db.py`, add to `SCHEMA` (before the closing `"""`):

```sql
CREATE TABLE IF NOT EXISTS film_slug_tmdb (
    slug TEXT PRIMARY KEY,
    tmdb_id INTEGER,
    resolved_via TEXT
);
```

Append helpers:

```python
def lookup_slug_tmdb(conn: sqlite3.Connection, slug: str) -> tuple | None:
    """Returns None when the slug was never resolved, or a 1-tuple (tmdb_id,)
    when it was — tmdb_id may itself be None, meaning 'confirmed no TMDB link,
    do not re-fetch'."""
    row = conn.execute(
        "SELECT tmdb_id FROM film_slug_tmdb WHERE slug = ?", (slug,)).fetchone()
    return None if row is None else (row["tmdb_id"],)

def store_slug_tmdb(conn: sqlite3.Connection, slug: str, tmdb_id: int | None, via: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO film_slug_tmdb (slug, tmdb_id, resolved_via) VALUES (?,?,?)",
        (slug, tmdb_id, via))
    conn.commit()  # cache must survive a later run failure
```

- [ ] **Step 4: Run tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_db.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/db.py backend/tests/test_db.py
git commit -m "feat: slug-to-tmdb-id cache table with negative-result support"
```

---

### Task 5: `resolver.py` — the cascade

Heart of the fix. Ordered layers, first hit wins: cache → rss → search → detail (hard-capped). Rules:
- Layer exceptions are swallowed → fall through to the next layer (a broken layer never sinks the run).
- Negative results are cached **only** when the detail page authoritatively returned no id (`via="none"`). Cap-hit/exception leaves the film uncached → retried next run.
- Cancel checked at every entry.
- `on_progress(resolved_count)` preserves the pipeline's existing `on_progress(n)` contract.

**Files:**
- Create: `backend/app/resolver.py`
- Test: `backend/tests/test_resolver.py`

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_resolver.py`:

```python
import pytest

from app.errors import Cancelled
from app.resolver import make_resolver

def entry(slug="parasite", title="Parasite", year=2019):
    return {"slug": slug, "title": title, "year": year, "rating": 5.0}

def test_cache_hit_wins_and_skips_all_other_layers():
    def boom(*a, **k):
        raise AssertionError("layer should not be called on cache hit")
    resolve = make_resolver(
        cache_get=lambda slug: (496243,),
        cache_put=boom, search_fn=boom, detail_fn=boom, rss_map={"parasite": 1})
    e = entry()
    resolve([e])
    assert e["tmdb_id"] == 496243

def test_cached_negative_result_skips_refetch():
    def boom(*a, **k):
        raise AssertionError("no layer should run for a cached negative")
    resolve = make_resolver(cache_get=lambda slug: (None,), search_fn=boom, detail_fn=boom)
    e = entry()
    resolve([e])
    assert e["tmdb_id"] is None

def test_rss_beats_search():
    resolve = make_resolver(
        rss_map={"parasite": 496243},
        search_fn=lambda t, y: 999)
    e = entry()
    resolve([e])
    assert e["tmdb_id"] == 496243

def test_search_used_when_rss_misses_and_result_is_cached():
    stored = []
    resolve = make_resolver(
        cache_get=lambda slug: None,
        cache_put=lambda slug, tid, via: stored.append((slug, tid, via)),
        rss_map={}, search_fn=lambda t, y: 496243)
    e = entry()
    resolve([e])
    assert e["tmdb_id"] == 496243
    assert stored == [("parasite", 496243, "search")]

def test_search_miss_falls_to_detail_and_caches_via_detail():
    stored = []
    resolve = make_resolver(
        cache_put=lambda slug, tid, via: stored.append((slug, tid, via)),
        search_fn=lambda t, y: None,
        detail_fn=lambda slug: 496243)
    e = entry()
    resolve([e])
    assert e["tmdb_id"] == 496243
    assert stored == [("parasite", 496243, "detail")]

def test_detail_none_is_cached_as_authoritative_negative():
    stored = []
    resolve = make_resolver(
        cache_put=lambda slug, tid, via: stored.append((slug, tid, via)),
        detail_fn=lambda slug: None)
    e = entry()
    resolve([e])
    assert e["tmdb_id"] is None
    assert stored == [("parasite", None, "none")]

def test_detail_cap_limits_letterboxd_hits_and_leaves_rest_uncached():
    stored, detail_calls = [], []
    def detail_fn(slug):
        detail_calls.append(slug)
        return None
    resolve = make_resolver(
        cache_put=lambda slug, tid, via: stored.append(slug),
        detail_fn=detail_fn, max_detail=1)
    entries = [entry(slug=f"film-{i}", title=f"Film {i}") for i in range(3)]
    stats = resolve(entries)
    assert len(detail_calls) == 1
    assert stored == ["film-0"]          # only the attempted one is cached
    assert stats.unresolved == 2          # the capped-out ones retry next run

def test_search_exception_falls_through_to_detail():
    def search_fn(t, y):
        raise RuntimeError("tmdb down")
    resolve = make_resolver(search_fn=search_fn, detail_fn=lambda slug: 496243)
    e = entry()
    resolve([e])
    assert e["tmdb_id"] == 496243

def test_detail_exception_leaves_film_unresolved_and_uncached():
    stored = []
    def detail_fn(slug):
        raise RuntimeError("403")
    resolve = make_resolver(
        cache_put=lambda slug, tid, via: stored.append(slug), detail_fn=detail_fn)
    e = entry()
    stats = resolve([e])
    assert e["tmdb_id"] is None
    assert stored == []
    assert stats.unresolved == 1

def test_resolver_raises_cancelled():
    resolve = make_resolver(rss_map={"parasite": 1})
    with pytest.raises(Cancelled):
        resolve([entry()], should_cancel=lambda: True)

def test_on_progress_reports_running_resolved_count():
    counts = []
    resolve = make_resolver(rss_map={"a": 1, "c": 3})
    resolve([entry(slug="a"), entry(slug="b"), entry(slug="c")],
            on_progress=counts.append)
    assert counts == [1, 1, 2]  # b unresolved, count doesn't advance
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/bin/python -m pytest tests/test_resolver.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.resolver'`

- [ ] **Step 3: Implement**

`backend/app/resolver.py`:

```python
"""Layered TMDB-id resolution for scraped Letterboxd films.

Order, first hit wins:  cache -> rss -> tmdb search -> letterboxd detail page.
The detail layer is the only one that touches Letterboxd and is hard-capped so
a run can never approach Cloudflare's ~72-request wall (the root cause of the
old deterministic 403 — see the 2026-07-08 resilient-scraper design spec).
"""
from dataclasses import dataclass

from app.errors import Cancelled

MAX_DETAIL_FALLBACKS = 40

@dataclass
class ResolverStats:
    cache: int = 0
    rss: int = 0
    search: int = 0
    detail: int = 0
    unresolved: int = 0

def make_resolver(cache_get=None, cache_put=None, rss_map=None, search_fn=None,
                  detail_fn=None, max_detail=MAX_DETAIL_FALLBACKS):
    """Returns resolve_all(entries, on_progress=None, should_cancel=None) -> ResolverStats.
    Mutates each entry's "tmdb_id" in place. Every layer is optional; layer
    exceptions fall through to the next layer. Negative results are cached only
    when the detail page authoritatively confirmed there is no TMDB link."""
    rss_map = rss_map or {}

    def resolve_all(entries, on_progress=None, should_cancel=None) -> ResolverStats:
        stats = ResolverStats()
        detail_used = 0
        resolved = 0
        for entry in entries:
            if should_cancel and should_cancel():
                raise Cancelled()
            entry.setdefault("tmdb_id", None)
            slug = entry.get("slug")
            via = None

            if slug and cache_get:
                try:
                    hit = cache_get(slug)
                except Exception:
                    hit = None
                if hit is not None:
                    entry["tmdb_id"] = hit[0]
                    stats.cache += 1
                    via = "cache"

            if via is None and slug and slug in rss_map:
                entry["tmdb_id"] = rss_map[slug]
                stats.rss += 1
                via = "rss"

            if via is None and search_fn and entry.get("title"):
                try:
                    tid = search_fn(entry["title"], entry.get("year"))
                except Exception:
                    tid = None
                if tid is not None:
                    entry["tmdb_id"] = tid
                    stats.search += 1
                    via = "search"

            if via is None and detail_fn and slug and detail_used < max_detail:
                detail_used += 1
                try:
                    tid = detail_fn(slug)
                except Exception:
                    pass  # not authoritative — leave uncached, retry next run
                else:
                    entry["tmdb_id"] = tid
                    stats.detail += 1
                    via = "detail" if tid is not None else "none"

            if via is None:
                stats.unresolved += 1
            elif via != "cache" and slug and cache_put:
                cache_put(slug, entry["tmdb_id"], via)

            if entry["tmdb_id"] is not None:
                resolved += 1
            if on_progress:
                on_progress(resolved)
        return stats

    return resolve_all
```

- [ ] **Step 4: Run tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_resolver.py -v`
Expected: ALL PASS (12 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/resolver.py backend/tests/test_resolver.py
git commit -m "feat: layered TMDB-id resolution cascade with capped detail fallback"
```

---

### Task 6: Restructure `scrape_profile` around the cascade

Split into `crawl_films_list` (list pages only) + injected `resolve_ids`. When no resolver is injected, a detail-only cascade preserves the legacy behavior (probe script, standalone use) — the live path always injects the full cascade (Task 7). Completeness error now points to CSV import.

**Files:**
- Modify: `backend/app/scraper.py:116-156`
- Test: `backend/tests/test_scraper.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_scraper.py`:

```python
from app.scraper import crawl_films_list

def test_crawl_films_list_paginates_without_detail_pages():
    page1 = (FIX / "films_page.html").read_text()  # 3 films + next link
    page2 = '<html><body><ul class="poster-list"></ul></body></html>'
    urls = []
    def fake_get(url):
        urls.append(url)
        return page2 if "/page/2/" in url else page1
    entries = crawl_films_list("alice", fake_get, delay=0)
    assert len(entries) == 3
    assert entries[0]["year"] == 2019
    assert all("/film/" not in u for u in urls)  # list pages only

def test_scrape_profile_with_injected_resolver_never_touches_detail_pages():
    page1 = (FIX / "films_page.html").read_text()
    page2 = '<html><body><ul class="poster-list"></ul></body></html>'
    stats = '<html><body><h4 class="profile-statistic"><a href="/alice/films/"><span class="value">3</span></a></h4></body></html>'
    urls = []
    def fake_get(url):
        urls.append(url)
        if "/page/2/" in url:
            return page2
        if url.endswith("/alice/"):
            return stats
        return page1
    def resolve_ids(entries, on_progress=None, should_cancel=None):
        for e in entries:
            e["tmdb_id"] = 496243
    films = scrape_profile("alice", fake_get, delay=0, resolve_ids=resolve_ids)
    assert len(films) == 3
    assert all("/film/" not in u for u in urls)

def test_scrape_profile_drops_films_the_resolver_could_not_resolve():
    page1 = (FIX / "films_page.html").read_text()
    stats = '<html><body><h4 class="profile-statistic"><a href="/alice/films/"><span class="value">3</span></a></h4></body></html>'
    def fake_get(url):
        return stats if url.endswith("/alice/") else page1.replace(
            '<a class="next" href="/alice/films/page/2/">Older</a>', "")
    def resolve_ids(entries, on_progress=None, should_cancel=None):
        for e in entries:
            e["tmdb_id"] = 496243 if e["slug"] == "parasite" else None
    films = scrape_profile("alice", fake_get, delay=0, resolve_ids=resolve_ids)
    assert [f["slug"] for f in films] == ["parasite"]

def test_incomplete_scrape_error_mentions_export_import():
    page1 = (FIX / "films_page.html").read_text()
    page2 = '<html><body></body></html>'
    stats = '<html><body><h4 class="profile-statistic"><a href="/alice/films/"><span class="value">87</span></a></h4></body></html>'
    def fake_get(url):
        if "/page/2/" in url:
            return page2
        if url.endswith("/alice/"):
            return stats
        return page1
    def resolve_ids(entries, on_progress=None, should_cancel=None):
        for e in entries:
            e["tmdb_id"] = 1
    with pytest.raises(RuntimeError, match="Letterboxd export"):
        scrape_profile("alice", fake_get, delay=0, resolve_ids=resolve_ids)
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/bin/python -m pytest tests/test_scraper.py -v`
Expected: new tests FAIL (`ImportError: crawl_films_list` / unexpected `resolve_ids` kwarg); all old tests still PASS.

- [ ] **Step 3: Implement**

In `backend/app/scraper.py`, add `from app.resolver import make_resolver` below the `app.errors` import, then replace `scrape_profile` with:

```python
def crawl_films_list(username, get_html, delay: float = 1.0, should_cancel=None) -> list[dict]:
    """Fetch only the paginated films-LIST pages (72 films each) — the entire
    Letterboxd HTML crawl on the happy path. TMDB ids come from the resolver
    cascade afterwards, not from per-film detail pages (which is what used to
    blow the ~72-request Cloudflare budget and 403 every >72-film profile)."""
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

def scrape_profile(
    username: str, get_html=default_get, delay: float = 1.0,
    on_progress=None, should_cancel=None, resolve_ids=None,
) -> list[dict]:
    try:
        entries = crawl_films_list(username, get_html, delay=delay, should_cancel=should_cancel)

        if resolve_ids is None:
            # Standalone/legacy mode: detail-page-only cascade. The live API path
            # always injects the full cache->rss->search->detail cascade instead.
            def detail_fn(slug):
                html = get_html(f"{BASE}/film/{slug}/")
                if delay:
                    time.sleep(delay)
                return parse_tmdb_id(html)
            resolve_ids = make_resolver(detail_fn=detail_fn, max_detail=len(entries))

        resolve_ids(entries, on_progress=on_progress, should_cancel=should_cancel)

        # Films without a TMDB id can never be produced as recommendation
        # candidates (candidates always come from TMDB), so they're safe to drop.
        films = [e for e in entries if e.get("tmdb_id") is not None]

        profile_html = get_html(f"{BASE}/{username}/")
        declared = parse_declared_film_count(profile_html)
        if declared is not None and len(entries) < declared:
            raise RuntimeError(
                f"Incomplete scrape: found {len(entries)} films but {username}'s "
                f"Letterboxd profile reports {declared}. The crawl was likely "
                f"blocked partway through — try refreshing again, or import your "
                f"Letterboxd export (Settings → Data → Export) instead."
            )
        return films
    finally:
        _close_page()
```

- [ ] **Step 4: Run the full scraper suite**

Run: `cd backend && .venv/bin/python -m pytest tests/test_scraper.py -v`
Expected: ALL PASS. The pre-existing tests keep passing because the default (no `resolve_ids`) path still resolves via detail pages through `get_html`, cancel is still checked per list page (crawl) and per entry (resolver), and `_close_page` still runs in `finally`.

- [ ] **Step 5: Run the whole backend suite**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: ALL PASS (pipeline/api tests unaffected — `scrape_profile` contract unchanged)

- [ ] **Step 6: Commit**

```bash
git add backend/app/scraper.py backend/tests/test_scraper.py
git commit -m "refactor: scrape list pages only; TMDB ids via injected resolver cascade"
```

---### Task 7: Wire the live cascade in `_real_refresh`

The API layer builds the real cascade: DB cache bound to `conn`, RSS best-effort, TMDB search with the configured key, Playwright detail fallback.

**Files:**
- Modify: `backend/app/api.py:23-35`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_api.py`:

```python
def test_real_refresh_builds_cascade_and_scrapes_without_detail_pages(monkeypatch, tmp_path):
    """_real_refresh must inject a resolve_ids cascade into scrape_profile:
    cache + rss + search + detail. We stub every network layer and assert the
    scrape resolves via rss/search and persists to the slug cache."""
    import app.api as api_mod
    from app.config import Config
    from app.db import connect, init_schema, lookup_slug_tmdb

    conn = connect(":memory:")
    init_schema(conn)

    monkeypatch.setattr(api_mod, "load_config", lambda: Config(
        username="alice", tmdb_api_key="KEY", db_path=str(tmp_path / "x.db")))
    monkeypatch.setattr(api_mod, "fetch_rss", lambda user, get_html=None: "<rss/>")
    monkeypatch.setattr(api_mod, "parse_rss_tmdb_map", lambda xml: {"parasite": 496243})
    monkeypatch.setattr(api_mod, "search_movie", lambda title, year, key: 555)

    captured = {}
    def fake_scrape_profile(user, get_html=None, delay=1.0, on_progress=None,
                            should_cancel=None, resolve_ids=None):
        entries = [
            {"slug": "parasite", "title": "Parasite", "year": 2019, "rating": 5.0},
            {"slug": "cats", "title": "Cats", "year": 2019, "rating": 1.0},
        ]
        resolve_ids(entries, on_progress=on_progress, should_cancel=should_cancel)
        captured["entries"] = entries
        return [e for e in entries if e["tmdb_id"] is not None]
    monkeypatch.setattr(api_mod, "scrape_profile", fake_scrape_profile)

    def fake_run_refresh(conn_, cfg, deps, on_progress=None, cancel_event=None):
        deps.scrape_fn(cfg.username, on_progress=None, should_cancel=None)
    monkeypatch.setattr(api_mod, "run_refresh", fake_run_refresh)

    api_mod._real_refresh(conn, "alice")

    by_slug = {e["slug"]: e for e in captured["entries"]}
    assert by_slug["parasite"]["tmdb_id"] == 496243   # via rss
    assert by_slug["cats"]["tmdb_id"] == 555          # via search
    assert lookup_slug_tmdb(conn, "cats") == (555,)   # persisted to cache
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/bin/python -m pytest tests/test_api.py -k cascade -v`
Expected: FAIL with `AttributeError: module 'app.api' has no attribute 'fetch_rss'`

- [ ] **Step 3: Implement**

In `backend/app/api.py`, extend the imports:

```python
from app.db import connect, init_schema, lookup_slug_tmdb, store_slug_tmdb
from app.resolver import make_resolver
from app.rss import fetch_rss, parse_rss_tmdb_map
from app.scraper import BASE, default_get, parse_tmdb_id, scrape_profile
from app.tmdb import (enrich, related_ids, search_movie, watch_providers,
                      search_person, discover_by_person)
```

Replace `_real_refresh` with:

```python
def _real_refresh(conn, username=None, on_progress=None, cancel_event=None):
    cfg = load_config()
    if username:
        cfg = dataclasses.replace(cfg, username=username)

    def scrape(user, on_progress=None, should_cancel=None):
        rss_xml = fetch_rss(user, get_html=default_get)
        resolve_ids = make_resolver(
            cache_get=lambda slug: lookup_slug_tmdb(conn, slug),
            cache_put=lambda slug, tid, via: store_slug_tmdb(conn, slug, tid, via),
            rss_map=parse_rss_tmdb_map(rss_xml) if rss_xml else {},
            search_fn=lambda title, year: search_movie(title, year, cfg.tmdb_api_key),
            detail_fn=lambda slug: parse_tmdb_id(default_get(f"{BASE}/film/{slug}/")),
        )
        return scrape_profile(user, on_progress=on_progress,
                              should_cancel=should_cancel, resolve_ids=resolve_ids)

    deps = Deps(
        scrape_fn=scrape,
        enrich_fn=lambda tid, key: enrich(tid, key),
        related_fn=lambda tid, key: related_ids(tid, key, pages=3),
        person_search_fn=lambda name, key: search_person(name, key),
        person_discover_fn=lambda pid, key: discover_by_person(pid, key),
    )
    run_refresh(conn, cfg, deps, on_progress=on_progress, cancel_event=cancel_event)
```

- [ ] **Step 4: Run the API suite**

Run: `cd backend && .venv/bin/python -m pytest tests/test_api.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api.py backend/tests/test_api.py
git commit -m "feat: wire live cache/rss/search/detail cascade into refresh"
```

---

### Task 8: `csv_import.py` — parse a Letterboxd export

Export zip contains `watched.csv` (Date,Name,Year,Letterboxd URI) and `ratings.csv` (…,Rating). The URI is a boxd.it short link — no slug — so CSV entries carry `slug: None` and resolve via TMDB search only (cache/rss/detail layers self-skip on missing slug; detail is deliberately never wired for uploads). Rated rows win over watched-only rows for the same film.

**Files:**
- Create: `backend/app/csv_import.py`
- Test: `backend/tests/test_csv_import.py`

- [ ] **Step 1: Write the failing tests**

`backend/tests/test_csv_import.py`:

```python
import io
import zipfile

import pytest

from app.csv_import import parse_export

RATINGS_CSV = """Date,Name,Year,Letterboxd URI,Rating
2024-01-01,Parasite,2019,https://boxd.it/abc,5
2024-01-02,Cats,2019,https://boxd.it/def,0.5
"""

WATCHED_CSV = """Date,Name,Year,Letterboxd URI
2024-01-01,Parasite,2019,https://boxd.it/abc
2024-01-03,Unrated Film,2020,https://boxd.it/ghi
"""

def _zip_bytes(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return buf.getvalue()

def test_parse_raw_ratings_csv():
    entries = parse_export(RATINGS_CSV.encode())
    by_title = {e["title"]: e for e in entries}
    assert by_title["Parasite"] == {
        "slug": None, "title": "Parasite", "year": 2019, "rating": 5.0}
    assert by_title["Cats"]["rating"] == 0.5

def test_parse_zip_merges_watched_and_ratings():
    data = _zip_bytes({"watched.csv": WATCHED_CSV, "ratings.csv": RATINGS_CSV})
    entries = parse_export(data)
    by_title = {e["title"]: e for e in entries}
    assert len(entries) == 3
    assert by_title["Parasite"]["rating"] == 5.0      # rated row wins
    assert by_title["Unrated Film"]["rating"] is None  # watched-only

def test_parse_zip_without_expected_csvs_raises():
    with pytest.raises(ValueError, match="watched.csv or ratings.csv"):
        parse_export(_zip_bytes({"diary.csv": "Date,Name\n"}))

def test_parse_garbage_raises():
    with pytest.raises(ValueError):
        parse_export(b"\x00\x01\x02 not a csv or zip")

def test_parse_empty_csv_raises():
    with pytest.raises(ValueError, match="No films"):
        parse_export(b"Date,Name,Year,Letterboxd URI\n")
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && .venv/bin/python -m pytest tests/test_csv_import.py -v`
Expected: FAIL with ModuleNotFoundError

- [ ] **Step 3: Implement**

`backend/app/csv_import.py`:

```python
"""Parse a Letterboxd data export (zip or single csv) into scrape-shaped
entries. The export's Letterboxd URI is a boxd.it short link with no slug, so
entries carry slug=None and are resolved by TMDB search only — which is the
point: the upload path must be fully un-rate-limitable, zero Letterboxd hits."""
import csv
import io
import zipfile

def _entries_from_csv_text(text: str) -> list[dict]:
    entries = []
    for row in csv.DictReader(io.StringIO(text)):
        name = (row.get("Name") or "").strip()
        if not name:
            continue
        year = (row.get("Year") or "").strip()
        rating = (row.get("Rating") or "").strip()
        entries.append({
            "slug": None,
            "title": name,
            "year": int(year) if year.isdigit() else None,
            "rating": float(rating) if rating else None,
        })
    return entries

def parse_export(data: bytes) -> list[dict]:
    """Raises ValueError for anything that isn't a usable export."""
    if zipfile.is_zipfile(io.BytesIO(data)):
        zf = zipfile.ZipFile(io.BytesIO(data))
        names = zf.namelist()
        merged = {}
        found_any = False
        # watched first so a rated row for the same film overwrites it
        for target in ("watched.csv", "ratings.csv"):
            member = next((n for n in names if n.split("/")[-1] == target), None)
            if member is None:
                continue
            found_any = True
            for e in _entries_from_csv_text(zf.read(member).decode("utf-8")):
                key = (e["title"], e["year"])
                if key not in merged or e["rating"] is not None:
                    merged[key] = e
        if not found_any:
            raise ValueError("Zip has no watched.csv or ratings.csv — is this a Letterboxd export?")
        entries = list(merged.values())
    else:
        try:
            entries = _entries_from_csv_text(data.decode("utf-8"))
        except UnicodeDecodeError:
            raise ValueError("Expected a Letterboxd export zip or a CSV file")
    if not entries:
        raise ValueError("No films found in the export")
    return entries
```

- [ ] **Step 4: Run tests**

Run: `cd backend && .venv/bin/python -m pytest tests/test_csv_import.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/csv_import.py backend/tests/test_csv_import.py
git commit -m "feat: parse Letterboxd export zip/csv into scrape-shaped entries"
```

---

### Task 9: `POST /api/refresh/upload` endpoint

Upload → parse → run the normal pipeline with pre-resolved-shape `entries` (search-only resolution). Shares the launch gate with `/api/refresh` via a factored helper. Needs `python-multipart` for FastAPI file uploads.

**Files:**
- Modify: `backend/app/api.py`, `backend/requirements.txt`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Install the multipart dependency**

```bash
cd backend && .venv/bin/pip install python-multipart==0.0.20
```

Append to `backend/requirements.txt`:

```
python-multipart==0.0.20
```

- [ ] **Step 2: Write the failing tests**

Append to `backend/tests/test_api.py` (match the file's existing pattern for building a TestClient with a stub `refresh_fn`; the stub MUST set a terminal stage via `on_progress` so the ACTIVE_STAGES gate releases):

```python
CSV_BYTES = b"Date,Name,Year,Letterboxd URI,Rating\n2024-01-01,Parasite,2019,https://boxd.it/abc,5\n"

def test_upload_endpoint_parses_and_launches_refresh_with_entries():
    import threading as _threading
    done = _threading.Event()
    calls = {}
    def stub_refresh(conn, username=None, on_progress=None, cancel_event=None, entries=None):
        calls["username"] = username
        calls["entries"] = entries
        on_progress({"stage": "done", "current": 1, "total": 1, "message": "Done"})
        done.set()
    client = TestClient(create_app(conn_factory=lambda: _mem_conn(), refresh_fn=stub_refresh))
    r = client.post("/api/refresh/upload", data={"username": "alice"},
                    files={"file": ("ratings.csv", CSV_BYTES, "text/csv")})
    assert r.status_code == 200
    assert r.json() == {"status": "started"}
    assert done.wait(timeout=2)
    assert calls["username"] == "alice"
    assert calls["entries"][0]["title"] == "Parasite"
    assert calls["entries"][0]["rating"] == 5.0

def test_upload_endpoint_rejects_unusable_file_with_400():
    def stub_refresh(conn, username=None, on_progress=None, cancel_event=None, entries=None):
        raise AssertionError("refresh must not launch for a bad file")
    client = TestClient(create_app(conn_factory=lambda: _mem_conn(), refresh_fn=stub_refresh))
    r = client.post("/api/refresh/upload", data={"username": "alice"},
                    files={"file": ("junk.bin", b"\x00\x01", "application/octet-stream")})
    assert r.status_code == 400

def test_upload_endpoint_respects_already_running_gate():
    import threading as _threading
    release = _threading.Event()
    def stub_refresh(conn, username=None, on_progress=None, cancel_event=None, entries=None):
        on_progress({"stage": "scraping", "current": 0, "total": None, "message": ""})
        release.wait(timeout=2)
        on_progress({"stage": "done", "current": 1, "total": 1, "message": "Done"})
    client = TestClient(create_app(conn_factory=lambda: _mem_conn(), refresh_fn=stub_refresh))
    files = {"file": ("ratings.csv", CSV_BYTES, "text/csv")}
    assert client.post("/api/refresh/upload", data={"username": "alice"}, files=files).json() == {"status": "started"}
    assert client.post("/api/refresh/upload", data={"username": "alice"}, files=files).json() == {"status": "already_running"}
    release.set()
```

(If `test_api.py` names its in-memory-conn helper differently, use that name instead of `_mem_conn` — mirror whatever the adjacent refresh tests use.)

- [ ] **Step 3: Run to verify failure**

Run: `cd backend && .venv/bin/python -m pytest tests/test_api.py -k upload -v`
Expected: FAIL with 404 (route doesn't exist)

- [ ] **Step 4: Implement**

In `backend/app/api.py`:

1. Extend imports:

```python
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from app.csv_import import parse_export
```

2. Give `_real_refresh` the `entries` parameter — add to its signature `entries=None`, and at the top of its inner `scrape` function:

```python
    def scrape(user, on_progress=None, should_cancel=None):
        if entries is not None:
            # Upload path: pre-parsed export rows, TMDB-search-only resolution —
            # zero Letterboxd requests, physically un-rate-limitable.
            resolve_ids = make_resolver(
                search_fn=lambda title, year: search_movie(title, year, cfg.tmdb_api_key))
            resolve_ids(entries, on_progress=on_progress, should_cancel=should_cancel)
            return [e for e in entries if e.get("tmdb_id") is not None]
        rss_xml = fetch_rss(user, get_html=default_get)
        ...  # (existing live-cascade body unchanged)
```

3. Inside `create_app`, factor the launch gate out of `refresh` and reuse it (replace the body of the existing `/api/refresh` handler too):

```python
    def _launch_refresh(username, starting_message, entries=None):
        set_progress = make_set_progress(username)
        with progress_lock:
            if progress_by_user.get(username, {}).get("stage") in ACTIVE_STAGES:
                return {"status": "already_running"}
            cancel_event = threading.Event()
            cancel_events[username] = cancel_event
            progress_by_user.setdefault(username, {}).update(
                {"stage": "starting", "current": 0, "total": None, "message": starting_message})

        def run():
            conn = get_conn()
            try:
                if entries is not None:
                    refresh_fn(conn, username, on_progress=set_progress,
                               cancel_event=cancel_event, entries=entries)
                else:
                    refresh_fn(conn, username, on_progress=set_progress,
                               cancel_event=cancel_event)
            except Cancelled:
                conn.rollback()
                set_progress({"stage": "cancelled", "current": 0, "total": None, "message": "Refresh cancelled."})
            except Exception as e:
                conn.rollback()
                set_progress({"stage": "error", "current": 0, "total": None, "message": str(e)})

        threading.Thread(target=run, daemon=True).start()
        return {"status": "started"}

    @app.post("/api/refresh")
    def refresh(body: RefreshRequest | None = None):
        username = body.username if body else None
        return _launch_refresh(username, "Starting refresh...")

    @app.post("/api/refresh/upload")
    async def refresh_upload(file: UploadFile = File(...), username: str | None = Form(None)):
        data = await file.read()
        try:
            entries = parse_export(data)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        return _launch_refresh(username, "Importing your Letterboxd export...", entries=entries)
```

Note: only pass `entries` through when non-None so existing stub `refresh_fn` signatures without an `entries` kwarg keep working.

- [ ] **Step 5: Run the full backend suite**

Run: `cd backend && .venv/bin/python -m pytest -q`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/api.py backend/tests/test_api.py backend/requirements.txt
git commit -m "feat: CSV-export upload endpoint reusing the refresh pipeline"
```

---

### Task 10: Frontend import affordance

Small "Import from Letterboxd export" control next to the refresh button (single call site: `RecommendationsPage.jsx:102`). Uses the shared RefreshContext so progress/polling behave exactly like a normal refresh.

**Files:**
- Modify: `frontend/src/api.js`, `frontend/src/context/RefreshContext.jsx`, `frontend/src/components/RefreshButton.jsx`, `frontend/src/RecommendationsPage.jsx:102`, `frontend/src/index.css`

- [ ] **Step 1: Add the API call**

Append to `frontend/src/api.js`:

```javascript
export async function uploadExport(username, file) {
  const form = new FormData();
  form.append("file", file);
  form.append("username", username);
  const r = await fetch(`${BASE}/api/refresh/upload`, { method: "POST", body: form });
  return r.json();
}
```

- [ ] **Step 2: Add `startFromUpload` to RefreshContext**

In `frontend/src/context/RefreshContext.jsx`: import `uploadExport` from `../api`, add below the existing `start` callback, and expose it in the provider value (`{ status, isRunning, start, startFromUpload, cancel, lastCompletedAt, timing }`):

```javascript
  const startFromUpload = useCallback(async (file) => {
    if (!username) return { status: "no_username" };
    applyStatus({ stage: "starting", current: 0, total: null, message: "Importing your Letterboxd export..." });
    let res;
    try {
      res = await uploadExport(username, file);
    } catch {
      applyStatus({ stage: "error", current: 0, total: null, message: "Couldn't reach the backend to import the export. Is it running?" });
      return { status: "error" };
    }
    if (res.status === "started" || res.status === "already_running") {
      startPolling(username);
    } else {
      // 400s come back as {detail: "..."}
      applyStatus({ stage: "error", current: 0, total: null, message: res.detail || "Couldn't read that export file." });
    }
    return res;
  }, [username, applyStatus, startPolling]);
```

- [ ] **Step 3: Add the control to RefreshButton**

Replace `frontend/src/components/RefreshButton.jsx` with:

```jsx
import { useRef } from "react";

export default function RefreshButton({ loading, hasData, onClick, onCancel, onImport }) {
  const fileRef = useRef(null);
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
      {!loading && onImport && (
        <>
          <button
            type="button"
            className="import-link"
            title="Blocked by Letterboxd? Export your data (Settings → Data → Export) and import the zip here."
            onClick={() => fileRef.current?.click()}
          >
            Import from Letterboxd export
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".zip,.csv"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) onImport(f);
              e.target.value = "";
            }}
          />
        </>
      )}
    </span>
  );
}
```

- [ ] **Step 4: Wire the call site**

In `frontend/src/RecommendationsPage.jsx`: add `startFromUpload` to the `useRefresh()` destructuring on line 30, and update line 102:

```jsx
          <RefreshButton loading={isRunning} hasData={hasData} onClick={onRefresh} onCancel={cancel} onImport={startFromUpload} />
```

- [ ] **Step 5: Style the link**

Append to `frontend/src/index.css` (near the existing `.cancel-btn` rules, matching their visual language):

```css
.import-link {
  background: none;
  border: none;
  padding: 0;
  margin-left: 12px;
  font-size: 0.8rem;
  color: var(--text-muted, #9ab);
  text-decoration: underline;
  cursor: pointer;
}
.import-link:hover {
  color: var(--text, #def);
}
```

(If `index.css` doesn't define `--text-muted`/`--text` variables, use the literal colors already used by adjacent muted text.)

- [ ] **Step 6: Verify tests and build**

Run: `cd frontend && npm test -- --run && npm run build`
Expected: 17/17 vitest tests pass, clean build

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api.js frontend/src/context/RefreshContext.jsx frontend/src/components/RefreshButton.jsx frontend/src/RecommendationsPage.jsx frontend/src/index.css
git commit -m "feat: import-from-Letterboxd-export escape hatch in refresh UI"
```

---

### Task 11: Live acceptance gate

The real proof — run against a real 72+ film profile. Requires `TMDB_API_KEY` in `backend/.env` (currently empty — ask the user). Target: films found ≈ declared count, ≥95% id resolution, **<15 Letterboxd requests**.

**Files:**
- Create: `backend/scripts/live_acceptance.py`

- [ ] **Step 1: Write the script**

`backend/scripts/live_acceptance.py`:

```python
"""Live acceptance gate for the layered scraper.
Run manually: `cd backend && .venv/bin/python scripts/live_acceptance.py moviefan`
Hits real Letterboxd + TMDB. Requires TMDB_API_KEY in .env.
Not part of the test suite."""
import functools
import os
import sys
import tempfile

from dotenv import load_dotenv
load_dotenv()

from app.db import connect, init_schema, lookup_slug_tmdb, store_slug_tmdb
from app.resolver import make_resolver
from app.rss import fetch_rss, parse_rss_tmdb_map
from app.scraper import BASE, default_get, parse_tmdb_id, scrape_profile
from app.tmdb import search_movie

def main(username):
    api_key = os.environ["TMDB_API_KEY"]
    lb_events = []
    def log(event):
        lb_events.append(event)
        print(f"LB[{len(lb_events)}] {event['status']} {event['url']}")
    get_html = functools.partial(default_get, on_request=log)

    conn = connect(os.path.join(tempfile.mkdtemp(), "acceptance.db"))
    init_schema(conn)

    rss_xml = fetch_rss(username, get_html=get_html)
    rss_map = parse_rss_tmdb_map(rss_xml) if rss_xml else {}
    print(f"RSS: {len(rss_map)} exact ids")

    resolve_ids = make_resolver(
        cache_get=lambda slug: lookup_slug_tmdb(conn, slug),
        cache_put=lambda slug, tid, via: store_slug_tmdb(conn, slug, tid, via),
        rss_map=rss_map,
        search_fn=lambda title, year: search_movie(title, year, api_key),
        detail_fn=lambda slug: parse_tmdb_id(get_html(f"{BASE}/film/{slug}/")),
    )

    box = {}
    def resolve_and_capture(entries, **kw):
        box["total"] = len(entries)
        box["stats"] = resolve_ids(entries, **kw)

    films = scrape_profile(username, get_html=get_html, delay=1.0,
                           resolve_ids=resolve_and_capture)

    total, stats = box["total"], box["stats"]
    rate = len(films) / total if total else 0
    print("\n=== ACCEPTANCE ===")
    print(f"films on profile grid : {total}")
    print(f"tmdb ids resolved     : {len(films)} ({rate:.0%})")
    print(f"via                   : {stats}")
    print(f"letterboxd requests   : {len(lb_events)}")
    ok = len(lb_events) < 15 and rate >= 0.95
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "moviefan"))
```

- [ ] **Step 2: Confirm TMDB_API_KEY is set**

Check `backend/.env` has a non-empty `TMDB_API_KEY`. If empty, STOP and ask the user for their key before running.

- [ ] **Step 3: Run the gate**

Run: `cd backend && .venv/bin/python scripts/live_acceptance.py moviefan`
Expected output ends with:

```
films on profile grid : 7x
tmdb ids resolved     : 7x (≥95%)
letterboxd requests   : ≤ ~5   (2 list pages + 1 profile page + maybe RSS + few details)
PASS
```

If FAIL: this is the acceptance criterion — debug (which layer under-resolved? did list page 2 still 403?), fix, re-run. Do not proceed to Step 4 until PASS.

- [ ] **Step 4: Re-run to prove the cache**

Run the same command again pointing at the same temp db is not possible (fresh tmpdir per run) — instead verify cache behavior in-run: the `via` stats line from Step 3 shows cache=0; that's expected for a cold run. Cache efficacy is already unit-tested (Task 5); the live gate's job is request count + resolution rate.

- [ ] **Step 5: Run both full suites one last time**

Run: `cd backend && .venv/bin/python -m pytest -q && cd ../frontend && npm test -- --run && npm run build`
Expected: ALL PASS, clean build

- [ ] **Step 6: Commit**

```bash
git add backend/scripts/live_acceptance.py
git commit -m "test: live acceptance gate for the layered scraper"
```

---

## Acceptance Criteria (from spec §6)

1. Backend + frontend suites green.
2. Live run against `moviefan`: films ≈ declared count, ≥95% TMDB resolution, <15 Letterboxd requests, exit PASS.
3. Upload path: a real ratings.csv drives a full refresh with zero Letterboxd requests.
