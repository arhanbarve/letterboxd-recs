# Resilient Letterboxd Scraper — Design

**Date:** 2026-07-08
**Status:** Approved for planning

## 1. Problem & Root Cause

The scraper cannot reliably pull a user's rated films. It fails deterministically
on profiles with more than ~72 rated films.

**Root cause (re-diagnosed):** it is an *architecture* problem, not an IP problem.
The current `scrape_profile` fetches **one Letterboxd detail page per film** solely
to read that film's TMDB id (`parse_tmdb_id` on `/film/{slug}/`). A 72-film profile
therefore costs:

```
1 films-list page  +  72 detail pages  +  1 profile page  ≈  74 Letterboxd requests
```

Letterboxd serves **72 posters per list page**, so films-list page 2 is request #74.
Cloudflare rate-limits the source IP right around there, so page 2 returns 403 every
time. The prior investigation (`docs/.../2026-07-08-refresh-and-progress-overhaul-plan.md`,
Task 0) correctly observed the 403 is IP/velocity-driven but never questioned the
**request count itself** — it treated 74 requests as fixed and tried to sneak them
past Cloudflare (pacing, stealth, context rotation), which cannot work.

**The fix:** stop reading TMDB ids from Letterboxd detail pages. Get them from sources
that are *not* behind Cloudflare (TMDB's own API, the RSS feed) and cache them. This
collapses Letterboxd traffic from ~74 requests to `ceil(N/72)` list pages — 1–10 for
almost every real user — which never approaches the rate limit.

## 2. Architecture — Layered Resolver

A film needs a TMDB id to enter the pipeline. We resolve ids through an ordered
cascade; each layer only handles what the layers above it could not, so a single
layer failing never sinks the run.

```
Source of the film list (pick one entry point):
  A. Live scrape  → crawl films-LIST pages only (title, year, slug, rating)   [1–10 LB hits]
  B. CSV upload   → user's Letterboxd export zip/csv (complete, 0 LB hits)

TMDB-id resolution cascade, per film, first hit wins:
  1. DB cache          slug → tmdb_id            (0 network; free on re-runs)
  2. RSS feed          exact tmdb:movieId        (1 LB request total, recent films)
  3. TMDB search       /search/movie by title+year (TMDB API, no Cloudflare)
  4. Detail-page       /film/{slug}/ parse_tmdb_id (LB, LAST resort, hard-capped)

Everything resolved (including "no TMDB id exists") is written back to the cache.
```

**Why layered rather than one method:** each layer covers the previous layer's blind
spot. RSS is exact but shallow (recent ~50). TMDB search is broad but fuzzy on
remakes/foreign titles. The detail page is authoritative but rate-limited — so it is
last and capped. The cache makes all of it free the second time. This is the
"multiple fallbacks" requirement.

## 3. Components & Interfaces

### 3.1 `scraper.py` — restructured

Public contract is **unchanged** (pipeline keeps working):
`scrape_profile(username, get_html=..., on_progress=None, should_cancel=None) -> list[dict]`
where each dict is `{slug, title, year, rating, tmdb_id}`. `year` is newly populated;
`tmdb_id` is now produced by the cascade instead of per-film detail scraping.

New/changed internals:
- `parse_films_page(html)` — extend to also parse **year** from `data-item-name`
  (`"Parasite (2019)"` → title `Parasite`, year `2019`). Already have slug, rating.
- `crawl_films_list(username, get_html, should_cancel, on_progress)` — fetch only the
  paginated list pages; return raw entries (no tmdb id yet). This is the only
  Letterboxd HTML crawl on the happy path.
- `resolve_tmdb_ids(entries, resolver)` — apply the cascade, mutate `tmdb_id` in place,
  report progress. Detail-page fallback is invoked through `get_html` and hard-capped
  by `MAX_DETAIL_FALLBACKS` (default 40) so a run can never approach the 72 wall.
- `scrape_profile` becomes: `crawl_films_list` → `resolve_tmdb_ids` → completeness log.

### 3.2 `rss.py` — new, small

- `fetch_rss(username, get=...) -> str` — GET `https://letterboxd.com/{username}/rss/`.
  Try a plain `requests` GET first (RSS is a feed-reader path, frequently *not*
  JS-challenged → no Playwright, no cost); on 403 fall back to `get_html` (Playwright).
- `parse_rss_tmdb_map(xml) -> dict[str, int]` — map `slug → tmdb_id` from
  `<tmdb:movieId>` + the entry `<link>`/`letterboxd:` fields. Missing feed or parse
  failure returns `{}` (pure fallback, never fatal).

### 3.3 `tmdb.py` — add search resolution

- `search_movie(title, year, api_key, session=None) -> int | None`
  GET `/search/movie?query={title}&primary_release_year={year}`. Match rule:
  exact case-insensitive title + year → that id; else a result whose year matches →
  its id; else `None`. `None` falls through to the detail-page layer.

### 3.4 DB — cache table

New table (added to `SCHEMA`, idempotent like the rest):
```sql
CREATE TABLE IF NOT EXISTS film_slug_tmdb (
    slug TEXT PRIMARY KEY,
    tmdb_id INTEGER,           -- NULL = confirmed "no TMDB id exists for this film"
    resolved_via TEXT          -- 'rss' | 'search' | 'detail' | 'none'
);
```
A present row (even with NULL `tmdb_id`) means "already resolved, do not re-fetch its
detail page" — this is what makes detail fallback a one-time cost per film.

### 3.5 CSV upload path

- `csv_import.py` — `parse_export(file_bytes) -> list[{slug,title,year,rating}]`.
  Accept a `.zip` (Letterboxd export) or a raw `ratings.csv`/`watched.csv`. Columns:
  `Name, Year, Letterboxd URI, Rating` (+ `Date`). Slug from the URI. This produces the
  same entry shape as `crawl_films_list`, then runs the **same** resolution cascade
  **with the detail-page layer disabled** (CSV mode is meant to be fully un-rate-limitable).
- `POST /api/refresh/upload` (multipart) — parse → build entries → inject a
  `scrape_fn` that returns the pre-resolved entries → reuse `run_refresh` unchanged.
- Frontend: a small "Import from Letterboxd export" control on the refresh UI with a
  one-line instruction (Settings → Data → Export) and a file picker. Shown as the
  escape hatch, not the primary action.

### 3.6 Wiring (`api.py`)

`_real_refresh` builds the resolver bound to `conn` (for the cache) and
`cfg.tmdb_api_key`, and passes it into `scrape_profile`. No pipeline changes.

## 4. Control Flow (live refresh, happy path)

```
crawl_films_list         → N entries, ~ceil(N/72) LB requests
fetch_rss (best-effort)  → exact ids for recent films
for each entry:          resolve via cache → rss → tmdb-search → (detail if under cap)
  write result to cache
completeness             → compare entry count vs profile's declared films count
pipeline enrich/score    → unchanged
```

## 5. Error Handling & Edge Cases

- **List crawl blocked** (still possible for 700+ film users at ~10 pages): keep the
  existing declared-vs-found completeness check, but its message now points users to
  the CSV import escape hatch, not just "try again."
- **Film with no TMDB link** (obscure titles): cascade ends at detail → NULL cached →
  film dropped (pipeline already drops tmdb-less films). Not an error.
- **Detail-fallback cap exceeded:** resolve what we can, cache it, finish the run with
  the successfully-resolved films, and surface a non-fatal notice recommending a re-run
  (cache makes the next run cheap) or CSV import. Never hard-fail a mostly-good run.
- **RSS/plain-requests 403:** silently fall back to Playwright, then to search. Never fatal.
- **Cancel:** `should_cancel` checked at the list-page loop and the resolution loop
  (preserves Task 4's cancel semantics).

## 6. Testing Strategy (both, per decision)

**Fixtures / TDD (offline, deterministic):**
- `parse_films_page` extracts year from `data-item-name` (extend existing fixture).
- `parse_rss_tmdb_map` on a saved RSS sample → correct slug→id map; empty/garbage → `{}`.
- `search_movie` matching rule (exact/year/none) against saved TMDB search JSON.
- Resolution cascade priority: cache > rss > search > detail; cap enforced; results cached.
- `parse_export` on a sample zip and a sample csv.
- Cancel raises at both checkpoints.

**Live acceptance gate (the real proof):**
- Run the new scraper against a real 72+ film profile (`moviefan`) with a real TMDB key.
- Assert: films found ≈ profile's declared count; TMDB resolution hit-rate high
  (target ≥ 95% of films with a real TMDB link); **Letterboxd request count < 15**
  (instrumented) — proving we no longer approach the rate limit.
- This run is the acceptance criterion. "Should work" is not acceptance.

## 7. Out of Scope

- Residential/rotating proxies (paid dependency; the architecture change removes the need).
- Official Letterboxd API (invite-only).
- Backfilling watch history beyond what the profile/export exposes.

## 8. Files

- Modify: `backend/app/scraper.py`, `backend/app/tmdb.py`, `backend/app/db.py`,
  `backend/app/api.py`, `backend/app/pipeline.py` (only if scrape_fn signature needs
  the cache), frontend refresh UI.
- New: `backend/app/rss.py`, `backend/app/csv_import.py`,
  `backend/tests/fixtures/{rss_feed.xml, tmdb_search.json, export_sample.csv}`,
  matching tests.
