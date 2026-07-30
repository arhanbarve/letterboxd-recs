# Plan: replace scraping with user-side Letterboxd export import

Date: 2026-07-30

## Goal

Data enters the app from the official Letterboxd export zip that the user downloads
themselves (Settings -> Data -> Export Your Data). The recommendation/analysis
pipeline is preserved. The Playwright/Cloudflare/proxy scrape path is deleted.

## Non-goals

- No watchlist or diary import (no recency weighting, no rewatch signal).
- No scorer/algorithm changes beyond the seed/pool caps needed for scale.
- No hosting migration. Feature is host-agnostic; deployment decided later.
- No Postgres migration.

## Decisions (settled in grilling, 2026-07-30)

| # | Decision |
|---|----------|
| 1 | Input = official export **zip** upload. |
| 2 | Read `ratings.csv` (ratings) + `watched.csv` (exclusion set) + `profile.csv` (username). No watchlist/diary. |
| 3 | Resolution touches **zero** Letterboxd: cache -> TMDB title+year search only. Unmatched films dropped. |
| 4 | Deterministic caps: <=50 seed films (rating desc, then rated-date desc), pool hard-capped at 5000. |
| 5 | **Two-step**: `POST /api/import` stores rows; refresh scores from stored rows. Re-score needs no re-upload. |
| 6 | Username read from `profile.csv`, returned to frontend, written into localStorage. |
| 7 | Scraper path **deleted** (scraper.py, rss.py, their tests, probe script, playwright dep, chromium build step). |
| 8 | TMDB id resolution **deferred to refresh** (import returns instantly, stores raw rows in new `imported_films` table). |
| 9 | Import **replaces** that username's imported rows (export is a full snapshot). |
| 10 | UI = guided empty state with 3-step instructions + drop zone; collapses to compact "Re-import" beside Refresh. Refresh disabled until data exists. |
| 11 | Upload validation strict: zip only, <=25MB, legible 400s. |
| 12 | Unmatched films: **count only**, reported in the refresh done-message. |
| 13 | Tests: full — unit + endpoint + Playwright E2E, using a **synthetic** fixture zip (no personal data committed). |
| 14 | Progress stage `scraping` -> **`resolving`**, made determinate (total = imported row count). |
| 15 | Persistence: needs a Railway volume + `DB_PATH=/data/letterboxd.db` **if** it stays on Railway (user-side dashboard steps). |
| 16 | CORS: harden code only (origin regex), defer live diagnosis — see Open questions. |

## Verified facts (measured against the real export, 2026-07-30)

Export `letterboxd-moviefan-2026-07-30-19-33-utc.zip`, 7.2 KB:

- `ratings.csv` — 92 rows, cols `Date, Name, Year, Letterboxd URI, Rating`.
  Rating is a 0.5-step decimal **string** ("3.5"), range 0.5-5.
- `watched.csv` — 92 rows, cols `Date, Name, Year, Letterboxd URI`. Zero
  unrated-watched films today, so it contributes nothing right now; still read,
  because that changes the moment one film is logged without a rating.
- `profile.csv` — 1 row, has `Username`. (Also has `Email Address` — never
  logged, never returned by the API, never committed.)
- `watchlist.csv` 0 rows, `diary.csv` 30 rows, `likes/films.csv` 15 rows (a real
  taste signal, deliberately out of scope).
- **`Letterboxd URI` is a `https://boxd.it/<code>` shortlink, NOT a
  `letterboxd.com/film/<slug>/` URL.** The original plan assumed otherwise. So
  there is no slug, and resolution is title+year TMDB search only. Resolving a
  shortcode to a slug would need an HTTP redirect through Letterboxd, which
  decision 3 rules out.
- **Match rate: 90/92 (97.8%)** with the current `search_movie`. Both misses
  (`Insidious` 2010, `Goodnight Mommy` 2014) are Letterboxd-premiere-year vs
  TMDB-release-year off-by-ones — TMDB has them at 2011-03-31 and 2015-01-08.
  A year-tolerance retry resolves both -> **92/92 (100%)**, verified live.
- 52 films rated 4-plus, so the 50-seed cap barely bites at today's size. Kept
  as cheap insurance against a growing history.

## Assumptions

- `profile.csv` always carries `Username`. If absent, import falls back to the
  username sent alongside the file.
- Exact-title matching keeps year tolerance safe (a remake released one year
  from the original with a byte-identical title would collide; none in this data).

## Blast radius

**Deleted:** `backend/app/scraper.py`, `backend/app/rss.py`,
`backend/tests/test_scraper.py`, `backend/tests/test_rss.py`,
`backend/scripts/probe_403.py`, and `backend/scripts/live_acceptance.py` if it is
scraper-dependent (checked in step 5; rewritten against the import path if
cheaply salvageable).

**New (backend):** `app/importer.py`, `tests/test_importer.py`,
`tests/fixtures/letterboxd-export-sample.zip`, `scripts/make_sample_export.py`.

**Edited (backend):** `app/tmdb.py` (`search_movie` year tolerance — see below),
`app/db.py` (new `imported_films` table + helpers),
`app/api.py` (`POST /api/import`, `GET /api/import/status`, scraper deps removed,
`ACTIVE_STAGES`), `app/pipeline.py` (import source, `resolving` stage, caps,
enrich-rated-only, unmatched count, friendly "no data" error),
`app/candidates.py` (pool cap param), `app/config.py` (cors origin regex),
`requirements.txt` (drop `playwright`, add `python-multipart`), `railway.json`
(drop chromium install), `tests/test_api.py`, `tests/test_pipeline.py`,
`tests/test_db.py`, `README.md`.

`app/resolver.py` is untouched — its `detail_fn`/RSS layers are already optional
and simply go unused (`detail_fn=None`, `max_detail=0`).

**New (frontend):** `src/components/ImportPanel.jsx`,
`tests/e2e/fixtures/letterboxd-export-sample.zip`.

**Edited (frontend):** `src/api.js` (`importExport`, `getImportStatus`),
`src/App.jsx`, `src/RecommendationsPage.jsx`, `src/components/RefreshButton.jsx`,
`src/lib/progressMath.js` (+ its test), `src/context/RefreshContext.jsx`,
`tests/e2e/*`.

## Schema

```sql
CREATE TABLE IF NOT EXISTS imported_films (
    username TEXT, boxd_id TEXT, title TEXT, year INTEGER,
    rating REAL,          -- NULL = watched but unrated
    rated_date TEXT,      -- ratings.csv Date, drives seed ordering
    tmdb_id INTEGER,      -- filled during refresh; NULL = unmatched
    imported_at TEXT,
    PRIMARY KEY (username, boxd_id)
);
```

`boxd_id` is the shortlink code (`293w` from `https://boxd.it/293w`) — the only
stable film identifier the export gives us.

Added via the existing idempotent `init_schema` pattern. No existing table changes.

**Resolution cache:** the existing `film_slug_tmdb` table is reused, with the
`boxd_id` stored in its `slug` column and `resolved_via` set to `"search"`. The
column name becomes a slight misnomer (documented in a comment) but the table's
job — "Letterboxd film identifier -> tmdb_id, don't re-resolve" — is unchanged,
so `lookup_slug_tmdb`/`store_slug_tmdb` and their tests keep working untouched.
Effect: the second and later refreshes skip all 92 TMDB searches.

## API

- `POST /api/import` — multipart `file` (+ optional `username` fallback).
  Returns `{"username": "...", "imported": 412, "rated": 388}`.
  400s: not a zip / no `ratings.csv` / unexpected columns / over 25MB.
- `GET /api/import/status?username=` — `{"imported": 412, "rated": 388,
  "unmatched": 9, "imported_at": "..."}`. Drives empty-state vs compact UI and
  the Refresh button's disabled state.
- `POST /api/refresh` — unchanged contract; now sources from `imported_films`
  and errors with "No imported data — upload your Letterboxd export first."
  when there is none.

## `search_movie` year tolerance

Required, not optional: without it 2 of 92 films (2.2%) are silently dropped for a
reason that has nothing to do with the film — Letterboxd records premiere year,
TMDB records primary release year.

New order inside `search_movie`, first exact-title hit wins:
`year` -> `year + 1` -> `year - 1` -> no year filter. Existing exact-title and
matching-year behavior is preserved as the first step, so every current
`test_tmdb.py` expectation still holds; the fallbacks only fire where it used to
return `None`.

## Pipeline changes

1. `resolving` stage (was `scraping`): determinate, `total` = imported row count,
   message "Matching films to TMDB... n/total". Resolved ids written back to
   `imported_films.tmdb_id` and to the `film_slug_tmdb` cache (keyed by `boxd_id`).
2. Enrich **rated** films only. Unrated-watched films contribute their tmdb_id to
   the exclusion set and nothing else — verified safe: `taste_dashboard.py` joins
   `ratings -> films` only, never `watched -> films`.
3. Seed cap: `_liked_ids` takes at most 50, ordered rating desc then rated_date desc.
4. Pool cap: `build_candidate_pool` / `build_person_candidate_pool` stop at 5000.
5. Done-message: "Done — 403 films matched, 9 skipped".

## Build order

| Step | Work | Verification |
|---|---|---|
| 0 | `tmdb.py`: `search_movie` year tolerance | `pytest tests/test_tmdb.py` (new cases: year+1 hit, year-1 hit, no-year fallback, still-None) |
| 1 | `db.py`: `imported_films` + `replace_imported_films` / `load_imported_films` / status helpers | `pytest tests/test_db.py` |
| 2 | `importer.py`: zip -> `{username, films}`, all validation branches | `pytest tests/test_importer.py` (in-memory zips) |
| 3 | `POST /api/import`, `GET /api/import/status` | `pytest tests/test_api.py` (TestClient multipart, incl. every 400) |
| 4 | `pipeline.py` + `candidates.py`: import source, `resolving`, caps, enrich-rated-only, unmatched count | `pytest tests/test_pipeline.py` |
| 5 | Delete scraper/rss/probe + prune `requirements.txt`, `railway.json`, `api.py` imports | full `pytest` green; `grep -r playwright backend/` clean |
| 6 | Frontend: `api.js`, `ImportPanel`, `App.jsx` wiring, `RefreshButton` gating, `progressMath` rename to determinate `resolving` | `npm test` (vitest) |
| 7 | Playwright E2E: real file upload of fixture zip, empty state -> imported transition | `npx playwright test` |
| 8 | Live local run: uvicorn + real TMDB/OMDB keys + the real export zip at `~/Downloads/letterboxd-moviefan-2026-07-30-19-33-utc.zip` (never committed) -> upload through the actual UI, run refresh, confirm 92/92 matched and recs render | Playwright screenshots + reported match count / runtime |
| 9 | `config.py` cors origin regex + README rewrite (export flow, env vars, volume note) | `pytest tests/test_config.py` |
| 10 | Commit to `main` (per project CLAUDE.md) | `git log` |

## Test plan

- **Unit (`test_importer.py`)**: valid zip; missing `ratings.csv`; not-a-zip bytes;
  wrong columns; `profile.csv` absent -> username fallback; `boxd.it` URI ->
  `boxd_id` extraction (and a non-boxd.it URI still yielding a usable key);
  rating parse of the 0.5-step strings; watched-only film -> rating None;
  ratings/watched overlap merges to one row; oversized upload rejected;
  extra zip members (`deleted/`, `likes/`, `orphaned/`) ignored.
- **DB (`test_db.py`)**: replace semantics wipe prior rows for that username only;
  status counts including unmatched.
- **API (`test_api.py`)**: multipart happy path returns username + counts; each
  400 message; `/api/import/status` shape; refresh with no import -> friendly error.
- **Pipeline (`test_pipeline.py`)**: sources from `imported_films`, never calls a
  scraper; `resolving` progress is determinate; seed cap honored at >50 liked;
  pool cap honored; only rated films enriched; unmatched count in done message;
  cancel still works mid-resolve.
- **Frontend unit**: `progressMath` bands/ETA for `resolving`; determinate math.
- **E2E**: seeded username, upload fixture zip via real file input, assert count
  message, assert Refresh becomes enabled, assert panel collapses.
- **Live**: step 8 above.

## Risks / rollback

- Scraper deletion is recoverable from git (last scraper state: `7b2a303`).
- Export format is now measured, not assumed, so `importer.py` is written against
  real column names and the real shortlink URI form.
- Match rate is no longer an unknown: 92/92 with the year-tolerance fix. Any
  future misses are still surfaced as a count rather than hidden.
- Year tolerance could in principle mis-resolve a same-titled remake one year
  apart. Exact-title matching is still required, and no such case exists in this
  data.
- Caps could omit good recommendations; both constants live in one place each.

## Outcome (built 2026-07-30)

Live acceptance run through the real UI with the real export:

- `POST /api/import` -> `{"imported": 92, "rated": 92}`
- refresh -> `{"stage": "done", "message": "Done — 92 films matched"}` (nothing skipped)
- `/api/recommendations` -> 3605 recommendations, cards rendered
- wall clock: 6.9 minutes for the first refresh after import (all 92 resolutions
  are cache misses on a first run; later refreshes skip that stage entirely)

Suites: backend 163 passed, frontend unit 25 passed, Playwright 9 passed.

Deltas from the plan as written:

1. `GET /api/import/status` returns `{imported, rated, imported_at}` with no
   `unmatched` field. Before a refresh has run every `tmdb_id` is NULL, so an
   unmatched count there would read as "all of them" — and decision 12 already
   put that number in the refresh done-message, which knows the real answer.
2. No `backend/tests/fixtures/*.zip` was committed: the backend tests build their
   zips in memory. Only the E2E needs a file on disk, at
   `frontend/tests/e2e/fixtures/`, generated by `scripts/make_sample_export.py`.
3. `beautifulsoup4` was dropped alongside `playwright` — it existed solely for the
   scraper/rss HTML parsers.
4. `UsernameField` needed a one-line fix: it seeded a local draft from `value`
   once and never re-synced, so the username read out of `profile.csv` never
   reached the input. Caught by the new E2E, not by inspection.
5. One pre-existing E2E assertion (`.expand-hero` visible on the first card) was
   relaxed to `.expand-title`. The hero only renders when TMDB has a backdrop,
   and 231 of the 3605 recommendations have none, so the old assertion was
   asserting a property of the data rather than of the UI.

## Open questions

1. **CORS diagnosis is blocked.** You chose "diagnose + harden", but the prod
   frontend URL is unknown and Railway may be suspended, so live diagnosis has
   nothing stable to test against. Plan does the code-only half (origin regex +
   README) and defers the live check to whenever hosting is settled.
2. **Prod DB is empty** (`/api/last-updated` -> `null`, recs -> `[]`), confirming
   ephemeral disk. Volume/`DB_PATH` are dashboard steps only you can do — and
   moot until the Railway shutdown notice is resolved.
3. Resolved: real export zip located and inspected.
