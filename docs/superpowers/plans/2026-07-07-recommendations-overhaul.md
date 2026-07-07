# Recommendations Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the watched-film recommendation leak, replace generic recommendation reasons with per-film specifics, make match % absolute and meaningful, and redesign the Top Pick and Taste Profile surfaces.

**Architecture:** Backend changes are surgical modifications to the existing `scraper → pipeline → scorer → db → api` chain plus one new module (`taste_dashboard.py`). Frontend changes replace the hero band and taste page with new components inside the existing React + plain-CSS "Marquee Noir" system. No new services, no LLM calls.

**Tech Stack:** Python/FastAPI/sqlite3/Playwright/BeautifulSoup (backend), React 19 + Vite, no new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-07-recommendations-overhaul-design.md`

---

## Important context before you start

- Backend tests live in `backend/tests/`, run with `cd backend && python -m pytest -q`.
- Frontend has **no unit test framework** (`frontend/package.json` has no test script). Frontend verification = `npm run build` + manual check via a running dev server (use a browser tool if available).
- Real Letterboxd markup was fetched live during planning and confirmed:
  - `/{username}/films/` — film grid entries as `li.griditem`; pagination as `div.paginate-nextprev a.next`.
  - `/{username}/` (profile root, **different URL**) — total film count lives at:
    ```html
    <h4 class="profile-statistic statistic"><a href="/moviefan/films/"><span class="value">87</span><span class="definition title-all-caps -small">Films</span></a></h4>
    ```
    Verified against the real account `moviefan` (87 declared, 72 on page 1 + 15 on page 2 — matches).
- **Design decision (deviation from spec wording):** the spec's "record every watched film even when tmdb_id is missing" defensive item is dropped. Candidates only ever come from TMDB (`related_ids`, `discover_by_person`), so a film with no resolvable TMDB id can never be produced as a candidate — there is nothing for it to leak into. Storing it as watched would require a schema change (matching by slug) for zero behavioral benefit. The real fix for the leak is the completeness check (Tasks 1–3) below.
- **Design decision (concrete absolute-% formula):** `WEIGHTS` in `scorer.py` already sum to exactly `1.0`. Today `_contributions` **sums** every genre/keyword/cast-member match, so raw scores are unbounded (a film tagged with 10 keywords can score far above 1.0) — that's why min-max normalization was needed. Switching each feature family to its **mean** affinity (instead of sum) bounds the max possible raw score to exactly `sum(WEIGHTS.values()) == 1.0`, giving a fixed, stable denominator. `match_pct = raw / 1.0 * 100`, clamped to `[0, 100]`. This does not change the two existing tests that use one item per family (mean == sum there) but does change one test with an under-matched candidate — that test is updated in Task 4 with the reasoning inline.

---

### Task 1: Scraper — raise instead of silently truncating on repeated blocks

**Files:**
- Modify: `backend/app/scraper.py:67-77` (`default_get`)
- Test: `backend/tests/test_scraper.py`

- [ ] **Step 1: Write the failing tests**

Add to the top of `backend/tests/test_scraper.py`:

```python
import pytest
```

Append at the end of the file:

```python
from app import scraper

class _FakeResp:
    def __init__(self, status):
        self.status = status

class _FakePage:
    def __init__(self, statuses, content="<html>ok</html>"):
        self._statuses = list(statuses)
        self._content = content
    def goto(self, url, wait_until=None, timeout=None):
        return _FakeResp(self._statuses.pop(0))
    def wait_for_timeout(self, ms):
        pass
    def content(self):
        return self._content

def test_default_get_returns_content_on_first_success(monkeypatch):
    monkeypatch.setattr(scraper, "_get_page", lambda: _FakePage([200]))
    monkeypatch.setattr(scraper.time, "sleep", lambda s: None)
    assert scraper.default_get("https://letterboxd.com/alice/films/") == "<html>ok</html>"

def test_default_get_raises_after_exhausting_retries_on_403(monkeypatch):
    # 1 initial attempt + 3 backoffs = 4 attempts, all blocked
    monkeypatch.setattr(scraper, "_get_page", lambda: _FakePage([403, 403, 403, 403], content="<html>challenge</html>"))
    monkeypatch.setattr(scraper.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="Blocked"):
        scraper.default_get("https://letterboxd.com/alice/films/")

def test_default_get_recovers_after_one_retry(monkeypatch):
    monkeypatch.setattr(scraper, "_get_page", lambda: _FakePage([429, 200]))
    monkeypatch.setattr(scraper.time, "sleep", lambda s: None)
    assert scraper.default_get("https://letterboxd.com/alice/films/") == "<html>ok</html>"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && python -m pytest tests/test_scraper.py -k default_get -v`
Expected: `test_default_get_raises_after_exhausting_retries_on_403` FAILS (current code returns `page.content()` instead of raising). The other two pass already (no behavior change needed for the success paths).

- [ ] **Step 3: Fix `default_get`**

Replace `backend/app/scraper.py:67-77`:

```python
def default_get(url: str) -> str:
    page = _get_page()
    backoffs = [2, 5, 10]
    last_status = None
    for wait in [0] + backoffs:
        if wait:
            time.sleep(wait)
        resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2500)
        last_status = resp.status
        if last_status not in (403, 429):
            return page.content()
    raise RuntimeError(
        f"Blocked fetching {url}: status {last_status} after {len(backoffs)} retries"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd backend && python -m pytest tests/test_scraper.py -k default_get -v`
Expected: all 3 PASS

- [ ] **Step 5: Commit**

```bash
cd ~/letterboxd-recommenation
git add backend/app/scraper.py backend/tests/test_scraper.py
git commit -m "fix: raise instead of silently truncating scrape on repeated 403/429"
```

---

### Task 2: Scraper — parse declared film count from profile page

**Files:**
- Modify: `backend/app/scraper.py` (add function near `parse_next_page_url`)
- Create: `backend/tests/fixtures/profile_stats.html`
- Test: `backend/tests/test_scraper.py`

- [ ] **Step 1: Create the fixture**

`backend/tests/fixtures/profile_stats.html`:

```html
<html><body>
<div class="profile-stats">
  <h4 class="profile-statistic statistic"><a href="/alice/films/"><span class="value">1,234</span><span class="definition title-all-caps -small">Films</span></a></h4>
  <h4 class="profile-statistic statistic"><a href="/alice/following/"><span class="value">5</span><span class="definition title-all-caps -small">Following</span></a></h4>
</div>
</body></html>
```

- [ ] **Step 2: Write the failing tests**

Append to `backend/tests/test_scraper.py`:

```python
from app.scraper import parse_declared_film_count

def test_parse_declared_film_count_strips_thousands_comma():
    html = (FIX / "profile_stats.html").read_text()
    assert parse_declared_film_count(html) == 1234

def test_parse_declared_film_count_missing_returns_none():
    assert parse_declared_film_count("<html><body>no stats</body></html>") is None
```

- [ ] **Step 3: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_scraper.py -k declared_film_count -v`
Expected: FAIL — `parse_declared_film_count` not defined

- [ ] **Step 4: Implement**

Add to `backend/app/scraper.py` (after `parse_next_page_url`, before `parse_tmdb_id`):

```python
def parse_declared_film_count(html: str) -> int | None:
    soup = BeautifulSoup(html, "html.parser")
    for h4 in soup.select("h4.profile-statistic"):
        link = h4.select_one("a")
        if link and link.get("href", "").rstrip("/").endswith("/films"):
            value = h4.select_one("span.value")
            if value:
                return int(value.get_text(strip=True).replace(",", ""))
    return None
```

- [ ] **Step 5: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_scraper.py -k declared_film_count -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/scraper.py backend/tests/test_scraper.py backend/tests/fixtures/profile_stats.html
git commit -m "feat: parse declared film total from Letterboxd profile stats"
```

---

### Task 3: Scraper — enforce completeness in `scrape_profile`

**Files:**
- Modify: `backend/app/scraper.py:79-97` (`scrape_profile`)
- Test: `backend/tests/test_scraper.py`

- [ ] **Step 1: Update the existing test's fake_get to serve the profile-stats page**

Replace the existing `test_scrape_profile_paginates_and_resolves_tmdb_ids` (lines 31-51 of `backend/tests/test_scraper.py`) with:

```python
from app.scraper import scrape_profile

def test_scrape_profile_paginates_and_resolves_tmdb_ids():
    page1 = (FIX / "films_page.html").read_text()  # 3 films: parasite, cats, unrated-film
    page2 = '<html><body><ul class="poster-list"></ul></body></html>'
    detail = (FIX / "film_detail.html").read_text()
    stats = '<html><body><h4 class="profile-statistic statistic"><a href="/alice/films/"><span class="value">3</span></a></h4></body></html>'

    def fake_get(url):
        if url.endswith("/films/") or url.endswith("/films/page/1/"):
            return page1
        if url.endswith("/films/page/2/"):
            return page2
        if url.endswith("/alice/"):
            return stats
        return detail  # any film page

    films = scrape_profile("alice", fake_get, delay=0)
    rated = {f["slug"]: f for f in films}
    assert rated["parasite"]["tmdb_id"] == 496243
    assert rated["parasite"]["rating"] == 5.0
    assert all(f["tmdb_id"] == 496243 for f in films)

def test_scrape_profile_raises_when_scraped_count_is_below_declared_total():
    page1 = (FIX / "films_page.html").read_text()  # 3 films
    page2 = '<html><body><ul class="poster-list"></ul></body></html>'
    detail = (FIX / "film_detail.html").read_text()
    # profile claims 87 films but only 3 were ever seen -> crawl was cut short
    stats = '<html><body><h4 class="profile-statistic statistic"><a href="/alice/films/"><span class="value">87</span></a></h4></body></html>'

    def fake_get(url):
        if url.endswith("/films/") or url.endswith("/films/page/1/"):
            return page1
        if url.endswith("/films/page/2/"):
            return page2
        if url.endswith("/alice/"):
            return stats
        return detail

    with pytest.raises(RuntimeError, match="Incomplete scrape"):
        scrape_profile("alice", fake_get, delay=0)
```

- [ ] **Step 2: Run to verify the new test fails and the updated one still passes structurally**

Run: `cd backend && python -m pytest tests/test_scraper.py -k scrape_profile -v`
Expected: `test_scrape_profile_raises_when_scraped_count_is_below_declared_total` FAILS (no completeness check exists yet); the paginate test still passes (behavior unchanged so far) — it exercises the new `fake_get` shape which is now required.

- [ ] **Step 3: Implement the completeness check**

Replace `backend/app/scraper.py:79-97`:

```python
def scrape_profile(
    username: str, get_html=default_get, delay: float = 1.0, on_progress=None
) -> list[dict]:
    films = []
    total_seen = 0
    url = f"{BASE}/{username}/films/"
    while url:
        html = get_html(url)
        page_entries = parse_films_page(html)
        total_seen += len(page_entries)
        for entry in page_entries:
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
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_scraper.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/scraper.py backend/tests/test_scraper.py
git commit -m "fix: raise when scrape stops short of the profile's declared film count

This is the actual fix for watched films (Silence of the Lambs, Godfather
Part II, Taxi Driver, etc.) being recommended back to users — a Cloudflare
challenge mid-crawl was silently truncating pagination, so those films never
entered the watched set and were eligible as candidates again."
```

---

### Task 4: Scorer — mean-based contributions + absolute match %

**Files:**
- Modify: `backend/app/scorer.py:1-27` (`_contributions`, `match_raw_score`)
- Test: `backend/tests/test_scorer.py`

- [ ] **Step 1: Update `_contributions` and add `THEORETICAL_MAX`**

Replace `backend/app/scorer.py:1-23`:

```python
import numpy as np

WEIGHTS = {"genre": 0.25, "keyword": 0.25, "director": 0.20,
           "actor": 0.20, "decade": 0.10}
THEORETICAL_MAX = sum(WEIGHTS.values())  # 1.0 — fixed ceiling for absolute match %

def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0

def _contributions(cand: dict, profile: dict) -> list[tuple[str, float]]:
    out = []
    genres = cand.get("genres", [])
    if genres:
        out.append(("genre", WEIGHTS["genre"] * _avg([profile["genre"].get(g, 0.0) for g in genres])))
    keywords = cand.get("keywords", [])
    if keywords:
        out.append(("keyword", WEIGHTS["keyword"] * _avg([profile["keyword"].get(k, 0.0) for k in keywords])))
    if cand.get("director"):
        out.append(("director", WEIGHTS["director"] * profile["director"].get(cand["director"], 0.0)))
    cast = cand.get("cast", [])
    if cast:
        out.append(("actor", WEIGHTS["actor"] * _avg([profile["actor"].get(a, 0.0) for a in cast])))
    if cand.get("decade") is not None:
        out.append(("decade", WEIGHTS["decade"] * profile["decade"].get(cand["decade"], 0.0)))
    return out

def match_raw_score(cand: dict, profile: dict) -> float:
    return sum(v for _, v in _contributions(cand, profile))
```

This changes each family from a **sum** over all matching genres/keywords/cast to a **mean** — a film tagged with 5 genres no longer scores 5x a film with 1 genre for that family. It bounds `match_raw_score` to at most `THEORETICAL_MAX` (1.0), which is what makes an absolute percentage meaningful. The two existing single-item-per-family tests (`test_match_raw_score_weighted_sum`, `test_match_raw_score_partial`) are unaffected since mean == sum when there's one item.

- [ ] **Step 2: Run existing raw-score tests to confirm no regression**

Run: `cd backend && python -m pytest tests/test_scorer.py -k match_raw_score -v`
Expected: both PASS unchanged

- [ ] **Step 3: Update `score_candidates` to use absolute normalization**

In `backend/app/scorer.py`, replace the `score_candidates` function (was lines 52-68, now shifted — find it at the bottom of the file):

```python
def score_candidates(cands, profile, rated, k: int = 10) -> list[dict]:
    if not cands:
        return []
    results = []
    for c in cands:
        raw = match_raw_score(c, profile)
        match_pct = round(max(0.0, min(raw, THEORETICAL_MAX)) / THEORETICAL_MAX * 100.0, 1)
        results.append({
            "tmdb_id": c["tmdb_id"],
            "match_pct": match_pct,
            "predicted_rating": round(predict_rating(c, rated, k), 2),
            "why": why_for(c, rated),
        })
    results.sort(key=lambda r: r["match_pct"], reverse=True)
    return results
```

(`why_for` doesn't exist yet — added in Task 5. This step will not run standalone; do Step 3 and Task 5 together before testing. Continue to Task 5's Step 1 before running anything.)

- [ ] **Step 4: Update `test_score_candidates_normalizes_and_ranks` for the new absolute scale**

Replace it in `backend/tests/test_scorer.py`:

```python
def test_score_candidates_normalizes_and_ranks():
    cands = [CAND, {"tmdb_id": 2, "genres": ["Comedy"], "keywords": [],
                    "director": "X", "cast": [], "decade": 1990}]
    rated = [{"rating": 5.0, "title": "Snowpiercer", "genres": ["Thriller"], "keywords": ["class conflict"]}]
    results = score_candidates(cands, PROFILE, rated, k=1)
    assert results[0]["tmdb_id"] == 999          # ranked first
    assert results[0]["match_pct"] == 100.0       # perfect match on every weighted family == THEORETICAL_MAX
    # weak cand: only genre family contributes (Comedy affinity 0.5) -> 0.25*0.5 = 0.125 raw -> 12.5%
    assert results[-1]["match_pct"] == 12.5
```

This is a **behavior change from relative to absolute** percentages — the old test asserted `0.0` for the worst-in-pool film, which was only ever true because of min-max normalization, not because the film was actually a 0% match.

- [ ] **Step 5: Commit is deferred to the end of Task 5** (the two tasks share one non-runnable intermediate state)

---

### Task 5: Scorer — per-film reasons (`top_neighbors`, `connection_phrase`, `why_for`)

**Files:**
- Modify: `backend/app/scorer.py` (remove `why_tags`, add new functions)
- Test: `backend/tests/test_scorer.py`

- [ ] **Step 1: Remove `why_tags` and add the neighbor/connection/why functions**

In `backend/app/scorer.py`, delete the `why_tags` function (was lines 25-27):

```python
def why_tags(cand: dict, profile: dict, n: int = 3) -> list[str]:
    contrib = sorted(_contributions(cand, profile), key=lambda x: x[1], reverse=True)
    return [name for name, val in contrib if val > 0][:n]
```

Add, right after `_cosine` and before `predict_rating`:

```python
def _nearest_rated(cand: dict, rated: list[dict], vocab: list[str], limit: int) -> list[dict]:
    sims = [(_cosine(_feature_vector(cand, vocab), _feature_vector(f, vocab)), f) for f in rated]
    sims = [s for s in sims if s[0] > 0]
    sims.sort(key=lambda s: s[0], reverse=True)
    return [f for _, f in sims[:limit]]

def top_neighbors(cand: dict, rated: list[dict], k: int = 2) -> list[dict]:
    """The rated films most like `cand`, preferring the ones the user rated highest."""
    vocab = sorted({t for f in rated + [cand]
                    for t in set(f.get("genres", [])) | set(f.get("keywords", []))})
    nearest = _nearest_rated(cand, rated, vocab, limit=5)
    nearest.sort(key=lambda f: f["rating"], reverse=True)
    return nearest[:k]

def connection_phrase(cand: dict, neighbors: list[dict]) -> str | None:
    if cand.get("director") and any(n.get("director") == cand["director"] for n in neighbors):
        return f"directed by {cand['director']}"
    cand_cast = set(cand.get("cast", []))
    for n in neighbors:
        shared = cand_cast & set(n.get("cast", []))
        if shared:
            return f"starring {sorted(shared)[0]}"
    cand_kw = set(cand.get("keywords", []))
    for n in neighbors:
        shared = cand_kw & set(n.get("keywords", []))
        if shared:
            return f"a shared thread of {sorted(shared)[0]}"
    cand_genre = set(cand.get("genres", []))
    for n in neighbors:
        shared = cand_genre & set(n.get("genres", []))
        if shared:
            return f"the same {sorted(shared)[0].lower()} sensibility"
    return None

def why_for(cand: dict, rated: list[dict]) -> dict:
    neighbors = top_neighbors(cand, rated, k=2)
    if not neighbors:
        return {"neighbors": [], "connection": None}
    return {
        "neighbors": [{"title": n["title"], "rating": n["rating"]} for n in neighbors],
        "connection": connection_phrase(cand, neighbors),
    }
```

- [ ] **Step 2: Replace the `why_tags` test with tests for the new functions**

In `backend/tests/test_scorer.py`, replace `test_why_tags_returns_top_features` (lines 36-39) and update the two `rated` lists used by `score_candidates` tests to include `"title"`:

```python
from app.scorer import (
    match_raw_score, predict_rating, score_candidates,
    top_neighbors, connection_phrase, why_for,
)

RATED_SNOWPIERCER = {"rating": 5.0, "title": "Snowpiercer",
                     "genres": ["Thriller"], "keywords": ["class conflict"]}

def test_top_neighbors_prefers_higher_rated_among_similar():
    rated = [
        RATED_SNOWPIERCER,
        {"rating": 2.0, "title": "Random Comedy", "genres": ["Comedy"], "keywords": []},
    ]
    neighbors = top_neighbors(CAND, rated, k=1)
    assert neighbors[0]["title"] == "Snowpiercer"

def test_connection_phrase_prefers_director_over_cast_and_keywords():
    neighbor = {"title": "Snowpiercer", "rating": 5.0, "director": "Bong Joon-ho",
                "cast": ["Song Kang-ho"], "keywords": ["class conflict"], "genres": ["Thriller"]}
    assert connection_phrase(CAND, [neighbor]) == "directed by Bong Joon-ho"

def test_connection_phrase_falls_back_to_shared_keyword():
    neighbor = {"title": "Other Film", "rating": 4.0, "director": "Someone Else",
                "cast": [], "keywords": ["class conflict"], "genres": []}
    assert connection_phrase(CAND, [neighbor]) == "a shared thread of class conflict"

def test_connection_phrase_returns_none_when_nothing_shared():
    neighbor = {"title": "Unrelated", "rating": 4.0, "director": "Someone Else",
                "cast": [], "keywords": [], "genres": []}
    assert connection_phrase(CAND, [neighbor]) is None

def test_why_for_names_the_specific_neighbor_films():
    why = why_for(CAND, [RATED_SNOWPIERCER])
    assert why["neighbors"] == [{"title": "Snowpiercer", "rating": 5.0}]
    assert why["connection"] == "a shared thread of class conflict"

def test_why_for_empty_when_no_rated_films_are_similar():
    unrelated = {"rating": 3.0, "title": "Nothing Alike", "genres": ["Romance"], "keywords": []}
    assert why_for(CAND, [unrelated]) == {"neighbors": [], "connection": None}
```

Update `test_score_candidates_normalizes_and_ranks` and `test_score_candidates_empty_pool_returns_empty_list` — the `rated` argument in both now needs `"title"`:

```python
def test_score_candidates_empty_pool_returns_empty_list():
    assert score_candidates([], PROFILE, [{"rating": 5.0, "title": "X", "genres": ["Thriller"]}]) == []
```

(`test_score_candidates_normalizes_and_ranks` was already updated with a titled `rated` list in Task 4 Step 4.)

- [ ] **Step 3: Run full scorer test suite**

Run: `cd backend && python -m pytest tests/test_scorer.py -v`
Expected: all PASS

- [ ] **Step 4: Commit (Tasks 4 + 5 together)**

```bash
git add backend/app/scorer.py backend/tests/test_scorer.py
git commit -m "feat: absolute match % and per-film reasons naming specific rated neighbors

Replaces the global 'why_tags' (same generic Drama/novel tags on every film)
with why_for(), which names the 1-2 specific rated films that made a
candidate score well and the concrete feature they share."
```

---

### Task 6: DB schema — new columns and `people` table

**Files:**
- Modify: `backend/app/db.py`
- Test: `backend/tests/test_db.py`

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_db.py`:

```python
def test_init_schema_creates_people_table_and_new_columns(tmp_path):
    conn = connect(str(tmp_path / "t.db"))
    init_schema(conn)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "people" in tables

    film_cols = {r[1] for r in conn.execute("PRAGMA table_info(films)")}
    assert {"backdrop_path", "overview", "runtime", "director_id"} <= film_cols

    cast_cols = {r[1] for r in conn.execute("PRAGMA table_info(film_cast)")}
    assert "person_id" in cast_cols

    rec_cols = {r[1] for r in conn.execute("PRAGMA table_info(recommendations)")}
    assert "why" in rec_cols

def test_init_schema_is_idempotent_on_existing_db(tmp_path):
    db = str(tmp_path / "t.db")
    conn = connect(db)
    init_schema(conn)
    init_schema(conn)  # must not raise on second call
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "people" in tables
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_db.py -v`
Expected: the two new tests FAIL

- [ ] **Step 3: Implement the schema change**

Replace `backend/app/db.py` in full:

```python
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS films (
    tmdb_id INTEGER PRIMARY KEY,
    title TEXT, year INTEGER, decade INTEGER,
    director TEXT, director_id INTEGER,
    poster_path TEXT, backdrop_path TEXT, overview TEXT, runtime INTEGER,
    tmdb_vote_avg REAL
);
CREATE TABLE IF NOT EXISTS film_genres (film_id INTEGER, genre TEXT);
CREATE TABLE IF NOT EXISTS film_keywords (film_id INTEGER, keyword TEXT);
CREATE TABLE IF NOT EXISTS film_cast (film_id INTEGER, actor TEXT, person_id INTEGER);
CREATE TABLE IF NOT EXISTS people (person_id INTEGER PRIMARY KEY, name TEXT, profile_path TEXT);
CREATE TABLE IF NOT EXISTS ratings (
    username TEXT, film_id INTEGER, your_rating REAL, watched_date TEXT,
    PRIMARY KEY (username, film_id)
);
CREATE TABLE IF NOT EXISTS watched (username TEXT, film_id INTEGER, PRIMARY KEY (username, film_id));
CREATE TABLE IF NOT EXISTS recommendations (
    username TEXT, film_id INTEGER, match_pct REAL,
    predicted_rating REAL, why TEXT, computed_at TEXT,
    PRIMARY KEY (username, film_id)
);
"""

# sqlite has no "ADD COLUMN IF NOT EXISTS" - applied idempotently by catching
# the duplicate-column error so init_schema is safe to call on every startup.
_MIGRATIONS = [
    "ALTER TABLE films ADD COLUMN director_id INTEGER",
    "ALTER TABLE films ADD COLUMN backdrop_path TEXT",
    "ALTER TABLE films ADD COLUMN overview TEXT",
    "ALTER TABLE films ADD COLUMN runtime INTEGER",
    "ALTER TABLE film_cast ADD COLUMN person_id INTEGER",
    "ALTER TABLE recommendations ADD COLUMN why TEXT",
]

def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for stmt in _MIGRATIONS:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.commit()
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_db.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/db.py backend/tests/test_db.py
git commit -m "feat: add people table, film backdrop/overview/runtime, recommendations.why

Schema change - existing installs need a fresh refresh to populate the new
columns (accepted; documented in the design spec)."
```

---

### Task 7: TMDB enrich — retain runtime, overview, backdrop, person ids

**Files:**
- Modify: `backend/app/tmdb.py:11-32` (`enrich`)
- Test: `backend/tests/test_tmdb.py`

- [ ] **Step 1: Write the failing test**

Replace `test_enrich_normalizes_movie` in `backend/tests/test_tmdb.py`:

```python
@responses.activate
def test_enrich_normalizes_movie():
    responses.add(
        responses.GET,
        "https://api.themoviedb.org/3/movie/496243",
        json={
            "title": "Parasite", "release_date": "2019-05-30",
            "poster_path": "/p.jpg", "backdrop_path": "/b.jpg",
            "overview": "Greed and class discrimination threaten a family.",
            "runtime": 132, "vote_average": 8.5,
            "genres": [{"name": "Thriller"}, {"name": "Comedy"}],
            "credits": {
                "crew": [{"job": "Director", "name": "Bong Joon-ho", "id": 21684, "profile_path": "/d.jpg"}],
                "cast": [
                    {"name": "Song Kang-ho", "id": 1523, "profile_path": "/a1.jpg"},
                    {"name": "Lee Sun-kyun", "id": 21686, "profile_path": None},
                ],
            },
            "keywords": {"keywords": [{"name": "class conflict"}]},
        },
        status=200,
    )
    m = enrich(496243, "key", session=None)
    assert m["tmdb_id"] == 496243
    assert m["title"] == "Parasite"
    assert m["year"] == 2019
    assert m["decade"] == 2010
    assert m["director"] == "Bong Joon-ho"
    assert m["director_id"] == 21684
    assert m["genres"] == ["Thriller", "Comedy"]
    assert m["cast"] == ["Song Kang-ho", "Lee Sun-kyun"]
    assert m["cast_people"] == [
        {"person_id": 1523, "name": "Song Kang-ho", "profile_path": "/a1.jpg"},
        {"person_id": 21686, "name": "Lee Sun-kyun", "profile_path": None},
    ]
    assert m["director_person"] == {"person_id": 21684, "name": "Bong Joon-ho", "profile_path": "/d.jpg"}
    assert m["keywords"] == ["class conflict"]
    assert m["poster_path"] == "/p.jpg"
    assert m["backdrop_path"] == "/b.jpg"
    assert m["overview"] == "Greed and class discrimination threaten a family."
    assert m["runtime"] == 132
    assert m["vote_avg"] == 8.5
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_tmdb.py -k enrich -v`
Expected: FAIL (missing keys)

- [ ] **Step 3: Implement**

Replace `backend/app/tmdb.py:11-32`:

```python
def enrich(tmdb_id: int, api_key: str, session=None) -> dict:
    data = _get(session, f"{API}/movie/{tmdb_id}", {
        "api_key": api_key,
        "append_to_response": "credits,keywords",
    })
    year = int(data["release_date"][:4]) if data.get("release_date") else None
    crew = data.get("credits", {}).get("crew", [])
    director_entry = next((c for c in crew if c.get("job") == "Director"), None)
    cast_entries = data.get("credits", {}).get("cast", [])[:5]
    keywords = [k["name"] for k in data.get("keywords", {}).get("keywords", [])]
    return {
        "tmdb_id": tmdb_id,
        "title": data.get("title"),
        "year": year,
        "decade": (year // 10) * 10 if year else None,
        "director": director_entry["name"] if director_entry else None,
        "director_id": director_entry["id"] if director_entry else None,
        "director_person": ({
            "person_id": director_entry["id"], "name": director_entry["name"],
            "profile_path": director_entry.get("profile_path"),
        } if director_entry else None),
        "genres": [g["name"] for g in data.get("genres", [])],
        "cast": [c["name"] for c in cast_entries],
        "cast_people": [
            {"person_id": c["id"], "name": c["name"], "profile_path": c.get("profile_path")}
            for c in cast_entries
        ],
        "keywords": keywords,
        "poster_path": data.get("poster_path"),
        "backdrop_path": data.get("backdrop_path"),
        "overview": data.get("overview"),
        "runtime": data.get("runtime"),
        "vote_avg": data.get("vote_average"),
    }
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_tmdb.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/tmdb.py backend/tests/test_tmdb.py
git commit -m "feat: retain runtime/overview/backdrop/person ids from TMDB enrich"
```

---

### Task 8: Pipeline — persist people, new film columns, and `why`

**Files:**
- Modify: `backend/app/pipeline.py:36-51` (`_persist_film`) and `:107-117` (recommendations insert)
- Test: `backend/tests/test_pipeline.py`

- [ ] **Step 1: Update pipeline test fixtures with the new `enrich()` shape**

`backend/tests/test_pipeline.py` builds `meta` dicts by hand to stand in for `enrich()` output. Every `meta` entry across all 4 tests needs the new keys. Update each film dict in `backend/tests/test_pipeline.py` to add `director_id`, `director_person`, `cast_people`, `backdrop_path`, `overview`, `runtime`. Example for the first test's `meta`:

```python
    meta = {
        1: {"tmdb_id": 1, "title": "Parasite", "year": 2019, "decade": 2010,
            "director": "Bong", "director_id": 21684,
            "director_person": {"person_id": 21684, "name": "Bong", "profile_path": "/d.jpg"},
            "genres": ["Thriller"], "cast": ["Song"],
            "cast_people": [{"person_id": 1523, "name": "Song", "profile_path": "/a.jpg"}],
            "keywords": ["class conflict"], "poster_path": "/p.jpg",
            "backdrop_path": "/pb.jpg", "overview": "A family schemes.", "runtime": 132,
            "vote_avg": 8.5},
        2: {"tmdb_id": 2, "title": "Meh", "year": 1990, "decade": 1990,
            "director": "X", "director_id": 2, "director_person": {"person_id": 2, "name": "X", "profile_path": None},
            "genres": ["Comedy"], "cast": [], "cast_people": [],
            "keywords": [], "poster_path": None, "backdrop_path": None, "overview": None, "runtime": 95,
            "vote_avg": 5.0},
        99: {"tmdb_id": 99, "title": "Rec", "year": 2018, "decade": 2010,
             "director": "Bong", "director_id": 21684,
             "director_person": {"person_id": 21684, "name": "Bong", "profile_path": "/d.jpg"},
             "genres": ["Thriller"], "cast": ["Song"],
             "cast_people": [{"person_id": 1523, "name": "Song", "profile_path": "/a.jpg"}],
             "keywords": ["class conflict"], "poster_path": "/r.jpg",
             "backdrop_path": "/rb.jpg", "overview": "A pitch.", "runtime": 108,
             "vote_avg": 7.9},
    }
```

Apply the same additive pattern (director_id/director_person/cast_people/backdrop_path/overview/runtime) to every other `meta` dict in the file (`test_run_refresh_reports_progress_through_stages`, `test_run_refresh_includes_person_candidates_when_deps_provided`, `test_run_refresh_is_isolated_per_username` — 6 more film dicts total). Use `None`/`[]`/plausible placeholder values consistent with the pattern above; exact values don't matter for these tests since none of them assert on the new columns — they just need `_persist_film` to not `KeyError`.

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_pipeline.py -v`
Expected: FAIL — `_persist_film` doesn't yet read/write the new columns, but since the meta dicts already carry them harmlessly, the actual failure here is that `_persist_film` still does `INSERT ... VALUES (?,?,?,?,?,?,?)` with 7 placeholders while nothing new is being inserted yet, so tests should still PASS at this point. This step is a checkpoint, not expected to fail — confirm still green before continuing:

Expected: PASS (updating meta dicts alone doesn't break anything; proceed to Step 3)

- [ ] **Step 3: Implement `_persist_film` with people upsert and new columns**

Replace `backend/app/pipeline.py:36-51`:

```python
def _persist_person(conn, person):
    if person is None:
        return
    conn.execute(
        "INSERT OR REPLACE INTO people (person_id, name, profile_path) VALUES (?,?,?)",
        (person["person_id"], person["name"], person["profile_path"]))

def _persist_film(conn, m):
    _persist_person(conn, m.get("director_person"))
    for p in m.get("cast_people", []):
        _persist_person(conn, p)

    conn.execute(
        "INSERT OR REPLACE INTO films"
        " (tmdb_id,title,year,decade,director,director_id,poster_path,backdrop_path,overview,runtime,tmdb_vote_avg)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (m["tmdb_id"], m["title"], m["year"], m["decade"], m["director"], m.get("director_id"),
         m["poster_path"], m.get("backdrop_path"), m.get("overview"), m.get("runtime"), m["vote_avg"]))
    conn.execute("DELETE FROM film_genres WHERE film_id=?", (m["tmdb_id"],))
    conn.execute("DELETE FROM film_keywords WHERE film_id=?", (m["tmdb_id"],))
    conn.execute("DELETE FROM film_cast WHERE film_id=?", (m["tmdb_id"],))
    conn.executemany("INSERT INTO film_genres VALUES (?,?)",
                     [(m["tmdb_id"], g) for g in m["genres"]])
    conn.executemany("INSERT INTO film_keywords VALUES (?,?)",
                     [(m["tmdb_id"], k) for k in m["keywords"]])
    cast_people_by_name = {p["name"]: p["person_id"] for p in m.get("cast_people", [])}
    conn.executemany("INSERT INTO film_cast VALUES (?,?,?)",
                     [(m["tmdb_id"], a, cast_people_by_name.get(a)) for a in m["cast"]])
```

- [ ] **Step 4: Update the recommendations insert to store `why`**

In `run_refresh` (`backend/app/pipeline.py:107-117`), replace:

```python
    for r in results:
        conn.execute(
            "INSERT INTO recommendations (username,film_id,match_pct,predicted_rating,why_tags,computed_at)"
            " VALUES (?,?,?,?,?,?)",
            (cfg.username, r["tmdb_id"], r["match_pct"], r["predicted_rating"],
             json.dumps(r["why_tags"]), now))
```

with:

```python
    for r in results:
        conn.execute(
            "INSERT INTO recommendations (username,film_id,match_pct,predicted_rating,why,computed_at)"
            " VALUES (?,?,?,?,?,?)",
            (cfg.username, r["tmdb_id"], r["match_pct"], r["predicted_rating"],
             json.dumps(r["why"]), now))
```

- [ ] **Step 5: Run full pipeline test suite**

Run: `cd backend && python -m pytest tests/test_pipeline.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/pipeline.py backend/tests/test_pipeline.py
git commit -m "feat: persist people/backdrop/overview/runtime and structured why on refresh"
```

---

### Task 9: API — recommendations return `why` + `backdrop_path`; new film-detail endpoint

**Files:**
- Modify: `backend/app/api.py:60-74` (`recommendations`), add new `film_detail` route
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Update the seed helper and existing recommendations test**

Replace `_seed` and `test_get_recommendations_returns_cards` in `backend/tests/test_api.py`:

```python
def _seed(conn):
    conn.execute(
        "INSERT INTO films (tmdb_id,title,year,poster_path,backdrop_path,overview,runtime,director)"
        " VALUES (99,'Rec',2018,'/r.jpg','/rb.jpg','A pitch.',108,'Bong')")
    conn.execute("INSERT INTO film_genres VALUES (99,'Thriller')")
    conn.execute("INSERT INTO film_cast VALUES (99,'Song Kang-ho',1523)")
    why = {"neighbors": [{"title": "Snowpiercer", "rating": 5.0}], "connection": "directed by Bong"}
    conn.execute("INSERT INTO recommendations VALUES ('alice', 99, 92.0, 4.3, ?, 'now')",
                 (json.dumps(why),))
    conn.execute("INSERT INTO ratings (username,film_id,your_rating) VALUES ('alice',99,0)")  # unused row
    conn.commit()

def test_get_recommendations_returns_cards(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn); _seed(conn)
    app = create_app(conn_factory=lambda: conn, refresh_fn=lambda conn, username=None, on_progress=None: None)
    client = TestClient(app)
    resp = client.get("/api/recommendations", params={"username": "alice"})
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["title"] == "Rec"
    assert body[0]["match_pct"] == 92.0
    assert body[0]["predicted_rating"] == 4.3
    assert body[0]["why"] == {"neighbors": [{"title": "Snowpiercer", "rating": 5.0}], "connection": "directed by Bong"}
    assert body[0]["poster_path"] == "/r.jpg"
    assert body[0]["backdrop_path"] == "/rb.jpg"
```

- [ ] **Step 2: Add a test for the new film-detail endpoint**

Append to `backend/tests/test_api.py`:

```python
def test_get_film_detail_returns_full_metadata(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn)
    conn.execute(
        "INSERT INTO films (tmdb_id,title,year,poster_path,backdrop_path,overview,runtime,director)"
        " VALUES (99,'Rec',2018,'/r.jpg','/rb.jpg','A pitch.',108,'Bong')")
    conn.execute("INSERT INTO film_genres VALUES (99,'Thriller')")
    conn.execute("INSERT INTO film_genres VALUES (99,'Drama')")
    conn.execute("INSERT INTO film_cast VALUES (99,'Song Kang-ho',1523)")
    conn.commit()
    app = create_app(conn_factory=lambda: conn, refresh_fn=lambda conn, username=None, on_progress=None: None)
    client = TestClient(app)
    resp = client.get("/api/films/99")
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Rec"
    assert body["year"] == 2018
    assert body["runtime"] == 108
    assert body["director"] == "Bong"
    assert body["overview"] == "A pitch."
    assert body["backdrop_path"] == "/rb.jpg"
    assert body["poster_path"] == "/r.jpg"
    assert sorted(body["genres"]) == ["Drama", "Thriller"]
    assert body["cast"] == ["Song Kang-ho"]

def test_get_film_detail_404_for_unknown_film(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn)
    app = create_app(conn_factory=lambda: conn, refresh_fn=lambda conn, username=None, on_progress=None: None)
    client = TestClient(app)
    resp = client.get("/api/films/999999")
    assert resp.status_code == 404
```

- [ ] **Step 3: Run to verify failures**

Run: `cd backend && python -m pytest tests/test_api.py -k "recommendations or film_detail" -v`
Expected: FAIL — `why` key doesn't exist yet, `backdrop_path` missing, `/api/films/{id}` route doesn't exist

- [ ] **Step 4: Implement**

Replace the `recommendations` route in `backend/app/api.py:60-74`:

```python
    @app.get("/api/recommendations")
    def recommendations(username: str):
        conn = get_conn()
        rows = conn.execute(
            "SELECT f.tmdb_id, f.title, f.year, f.poster_path, f.backdrop_path,"
            " r.match_pct, r.predicted_rating, r.why"
            " FROM recommendations r JOIN films f ON f.tmdb_id = r.film_id"
            " WHERE r.username = ?"
            " ORDER BY r.match_pct DESC", (username,)).fetchall()
        return [{
            "tmdb_id": r["tmdb_id"], "title": r["title"], "year": r["year"],
            "poster_path": r["poster_path"], "backdrop_path": r["backdrop_path"],
            "match_pct": r["match_pct"],
            "predicted_rating": r["predicted_rating"],
            "why": json.loads(r["why"]) if r["why"] else {"neighbors": [], "connection": None},
        } for r in rows]
```

Add a new route, placed after the `film_watch_providers` route (`backend/app/api.py:120-123`):

```python
    @app.get("/api/films/{tmdb_id}")
    def film_detail(tmdb_id: int):
        conn = get_conn()
        row = conn.execute(
            "SELECT tmdb_id, title, year, runtime, director, overview,"
            " poster_path, backdrop_path, tmdb_vote_avg"
            " FROM films WHERE tmdb_id = ?", (tmdb_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Film not found")
        genres = [r["genre"] for r in conn.execute(
            "SELECT genre FROM film_genres WHERE film_id = ?", (tmdb_id,)).fetchall()]
        cast = [r["actor"] for r in conn.execute(
            "SELECT actor FROM film_cast WHERE film_id = ?", (tmdb_id,)).fetchall()]
        return {
            "tmdb_id": row["tmdb_id"], "title": row["title"], "year": row["year"],
            "runtime": row["runtime"], "director": row["director"], "overview": row["overview"],
            "poster_path": row["poster_path"], "backdrop_path": row["backdrop_path"],
            "vote_avg": row["tmdb_vote_avg"], "genres": genres, "cast": cast,
        }
```

Add the `HTTPException` import at the top of `backend/app/api.py`:

```python
from fastapi import FastAPI, HTTPException
```

- [ ] **Step 5: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_api.py -v`
Expected: all PASS (some `taste-profile` tests will fail here — that's expected, fixed in Task 10)

- [ ] **Step 6: Commit**

```bash
git add backend/app/api.py backend/tests/test_api.py
git commit -m "feat: recommendations return why+backdrop_path; add GET /api/films/{id}"
```

---

### Task 10: Taste dashboard — new module + rewritten `/api/taste-profile`

**Files:**
- Create: `backend/app/taste_dashboard.py`
- Modify: `backend/app/api.py:76-89` (`taste_profile`)
- Test: Create `backend/tests/test_taste_dashboard.py`; modify `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_taste_dashboard.py`:

```python
from app.db import connect, init_schema
from app.taste_dashboard import build_dashboard

def _seed_alice(conn):
    films = [
        (1, "Parasite", 2019, 2010, "Bong Joon-ho", 21684),
        (2, "Snowpiercer", 2013, 2010, "Bong Joon-ho", 21684),
        (3, "Rom Com", 2015, 2010, "Someone Else", 2),
    ]
    for tmdb_id, title, year, decade, director, director_id in films:
        conn.execute(
            "INSERT INTO films (tmdb_id,title,year,decade,director,director_id) VALUES (?,?,?,?,?,?)",
            (tmdb_id, title, year, decade, director, director_id))
    conn.execute("INSERT INTO people VALUES (21684,'Bong Joon-ho','/d.jpg')")
    conn.execute("INSERT INTO people VALUES (1523,'Song Kang-ho','/a.jpg')")
    conn.execute("INSERT INTO film_genres VALUES (1,'Thriller')")
    conn.execute("INSERT INTO film_genres VALUES (2,'Thriller')")
    conn.execute("INSERT INTO film_genres VALUES (3,'Romance')")
    conn.execute("INSERT INTO film_cast VALUES (1,'Song Kang-ho',1523)")
    conn.execute("INSERT INTO film_cast VALUES (2,'Song Kang-ho',1523)")
    conn.execute("INSERT INTO ratings (username,film_id,your_rating) VALUES ('alice',1,5.0)")
    conn.execute("INSERT INTO ratings (username,film_id,your_rating) VALUES ('alice',2,4.5)")
    conn.execute("INSERT INTO ratings (username,film_id,your_rating) VALUES ('alice',3,2.0)")
    conn.commit()

def test_build_dashboard_totals_and_average(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn); _seed_alice(conn)
    dash = build_dashboard(conn, "alice")
    assert dash["total_rated"] == 3
    assert round(dash["average_rating"], 2) == round((5.0 + 4.5 + 2.0) / 3, 2)

def test_build_dashboard_favorite_decade(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn); _seed_alice(conn)
    dash = build_dashboard(conn, "alice")
    assert dash["favorite_decade"] == 2010

def test_build_dashboard_rating_distribution_buckets_by_whole_star(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn); _seed_alice(conn)
    dash = build_dashboard(conn, "alice")
    dist = {b["star"]: b["count"] for b in dash["rating_distribution"]}
    assert dist[5] == 2  # 5.0 and 4.5 both round up into the 5-star bucket
    assert dist[2] == 1

def test_build_dashboard_top_director_has_headshot(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn); _seed_alice(conn)
    dash = build_dashboard(conn, "alice")
    top = dash["top_directors"][0]
    assert top["name"] == "Bong Joon-ho"
    assert top["profile_path"] == "/d.jpg"

def test_build_dashboard_top_actor_has_headshot(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn); _seed_alice(conn)
    dash = build_dashboard(conn, "alice")
    top = dash["top_actors"][0]
    assert top["name"] == "Song Kang-ho"
    assert top["profile_path"] == "/a.jpg"

def test_build_dashboard_genre_affinities_for_radar(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn); _seed_alice(conn)
    dash = build_dashboard(conn, "alice")
    genres = {g["name"] for g in dash["genre_affinities"]}
    assert genres == {"Thriller", "Romance"}

def test_build_dashboard_signature_is_a_nonempty_sentence(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn); _seed_alice(conn)
    dash = build_dashboard(conn, "alice")
    assert isinstance(dash["signature"], str) and dash["signature"].endswith(".")

def test_build_dashboard_empty_for_user_with_no_ratings(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn)
    dash = build_dashboard(conn, "nobody")
    assert dash["total_rated"] == 0
    assert dash["top_directors"] == []
    assert dash["top_actors"] == []
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && python -m pytest tests/test_taste_dashboard.py -v`
Expected: FAIL — module doesn't exist

- [ ] **Step 3: Implement `taste_dashboard.py`**

Create `backend/app/taste_dashboard.py`:

```python
from app.profile import build_taste_profile

TOUGH_GRADER_THRESHOLD = 3.3

def _rated_films(conn, username):
    rows = conn.execute(
        "SELECT f.tmdb_id, f.decade, r.your_rating"
        " FROM ratings r JOIN films f ON f.tmdb_id = r.film_id"
        " WHERE r.username = ?", (username,)).fetchall()
    return rows

def _rating_distribution(rows):
    buckets = {star: 0 for star in range(1, 6)}
    for r in rows:
        star = max(1, min(5, round(r["your_rating"])))
        buckets[star] += 1
    return [{"star": s, "count": c} for s, c in sorted(buckets.items())]

def _favorite_decade(rows):
    counts = {}
    for r in rows:
        if r["decade"] is not None:
            counts[r["decade"]] = counts.get(r["decade"], 0) + 1
    return max(counts, key=counts.get) if counts else None

def _top_people(conn, username, role_table, role_col, person_col):
    rows = conn.execute(
        f"SELECT p.name, p.profile_path, COUNT(*) c"
        f" FROM {role_table} t"
        f" JOIN ratings r ON r.film_id = t.film_id"
        f" JOIN people p ON p.person_id = t.{person_col}"
        f" WHERE r.username = ? AND t.{person_col} IS NOT NULL"
        f" GROUP BY t.{person_col} ORDER BY c DESC LIMIT 6", (username,)).fetchall()
    return [{"name": r["name"], "profile_path": r["profile_path"], "count": r["c"]} for r in rows]

def _top_directors(conn, username):
    rows = conn.execute(
        "SELECT p.name, p.profile_path, COUNT(*) c"
        " FROM films f"
        " JOIN ratings r ON r.film_id = f.tmdb_id"
        " JOIN people p ON p.person_id = f.director_id"
        " WHERE r.username = ? AND f.director_id IS NOT NULL"
        " GROUP BY f.director_id ORDER BY c DESC LIMIT 6", (username,)).fetchall()
    return [{"name": r["name"], "profile_path": r["profile_path"], "count": r["c"]} for r in rows]

def _genre_affinities(profile):
    return [{"name": g, "affinity": round(v, 3)} for g, v in
            sorted(profile["genre"].items(), key=lambda kv: kv[1], reverse=True)]

def _top_keywords(profile, n=8):
    return [k for k, _ in sorted(profile["keyword"].items(), key=lambda kv: kv[1], reverse=True)[:n]]

def _build_signature(avg_rating, top_genre, top_decade):
    tone = "a tough grader" if avg_rating and avg_rating < TOUGH_GRADER_THRESHOLD else "a generous grader"
    parts = [tone[0].upper() + tone[1:]]
    if top_genre:
        parts.append(f"drawn to {top_genre.lower()}")
    if top_decade:
        parts.append(f"with a soft spot for the {top_decade}s")
    return " ".join(parts) + "."

def build_dashboard(conn, username: str) -> dict:
    rated_rows = _rated_films(conn, username)
    total_rated = len(rated_rows)
    average_rating = (sum(r["your_rating"] for r in rated_rows) / total_rated) if total_rated else 0.0

    rated_meta = []
    for r in rated_rows:
        genres = [g["genre"] for g in conn.execute(
            "SELECT genre FROM film_genres WHERE film_id = ?", (r["tmdb_id"],)).fetchall()]
        keywords = [k["keyword"] for k in conn.execute(
            "SELECT keyword FROM film_keywords WHERE film_id = ?", (r["tmdb_id"],)).fetchall()]
        cast = [c["actor"] for c in conn.execute(
            "SELECT actor FROM film_cast WHERE film_id = ?", (r["tmdb_id"],)).fetchall()]
        director_row = conn.execute(
            "SELECT director FROM films WHERE tmdb_id = ?", (r["tmdb_id"],)).fetchone()
        rated_meta.append({
            "rating": r["your_rating"], "genres": genres, "keywords": keywords,
            "cast": cast, "director": director_row["director"] if director_row else None,
            "decade": r["decade"],
        })
    profile = build_taste_profile(rated_meta)
    genre_affinities = _genre_affinities(profile)
    top_genre = genre_affinities[0]["name"] if genre_affinities else None
    favorite_decade = _favorite_decade(rated_rows)

    return {
        "total_rated": total_rated,
        "average_rating": round(average_rating, 2),
        "favorite_decade": favorite_decade,
        "rating_distribution": _rating_distribution(rated_rows),
        "genre_affinities": genre_affinities,
        "top_directors": _top_directors(conn, username),
        "top_actors": _top_people(conn, username, "film_cast", "actor", "person_id"),
        "top_keywords": _top_keywords(profile),
        "signature": _build_signature(average_rating, top_genre, favorite_decade),
    }
```

- [ ] **Step 4: Run to verify pass**

Run: `cd backend && python -m pytest tests/test_taste_dashboard.py -v`
Expected: all PASS

- [ ] **Step 5: Rewrite the `/api/taste-profile` endpoint and its tests**

Replace `test_get_taste_profile_scoped_by_username` in `backend/tests/test_api.py`:

```python
def test_get_taste_profile_scoped_by_username(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn)
    conn.execute("INSERT INTO films (tmdb_id,title,year,decade) VALUES (1,'X',2000,2000)")
    conn.execute("INSERT INTO film_genres VALUES (1,'Thriller')")
    conn.execute("INSERT INTO ratings (username,film_id,your_rating) VALUES ('alice',1,5.0)")
    conn.commit()
    app = create_app(conn_factory=lambda: conn, refresh_fn=lambda conn, username=None, on_progress=None: None)
    client = TestClient(app)
    resp = client.get("/api/taste-profile", params={"username": "alice"})
    body = resp.json()
    assert body["total_rated"] == 1
    assert body["genre_affinities"][0]["name"] == "Thriller"
    resp_bob = client.get("/api/taste-profile", params={"username": "bob"})
    assert resp_bob.json()["total_rated"] == 0
```

Replace the `taste_profile` route in `backend/app/api.py:76-89`:

```python
    @app.get("/api/taste-profile")
    def taste_profile(username: str):
        conn = get_conn()
        return build_dashboard(conn, username)
```

Add the import at the top of `backend/app/api.py`:

```python
from app.taste_dashboard import build_dashboard
```

- [ ] **Step 6: Run full API test suite**

Run: `cd backend && python -m pytest tests/test_api.py -v`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/taste_dashboard.py backend/tests/test_taste_dashboard.py backend/app/api.py backend/tests/test_api.py
git commit -m "feat: taste-profile dashboard (totals, distribution, radar, headshots, signature)"
```

---

### Task 11: Full backend regression check

**Files:** none (verification-only)

- [ ] **Step 1: Run the entire backend suite**

Run: `cd backend && python -m pytest -q`
Expected: all tests PASS, no warnings about missing fixtures

- [ ] **Step 2: If anything fails, fix before proceeding to frontend work.** Do not move to Task 12 with a red backend suite.

---

### Task 12: Frontend — `api.js` additions

**Files:**
- Modify: `frontend/src/api.js`

- [ ] **Step 1: Add `getFilmDetail`**

Append to `frontend/src/api.js`:

```js
export async function getFilmDetail(tmdbId) {
  const r = await fetch(`${BASE}/api/films/${tmdbId}`);
  return r.json();
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/api.js
git commit -m "feat: add getFilmDetail API call"
```

---

### Task 13: Frontend — `RecommendationCard` renders specific reasons

**Files:**
- Modify: `frontend/src/components/RecommendationCard.jsx:40-42`

- [ ] **Step 1: Replace the why-tags rendering**

Replace `frontend/src/components/RecommendationCard.jsx:40-42`:

```jsx
        {rec.why_tags?.length > 0 && (
          <p className="card-why">Because you like: {rec.why_tags.join(", ")}</p>
        )}
```

with:

```jsx
        {rec.why?.neighbors?.length > 0 && (
          <p className="card-why">
            Because you loved{" "}
            {rec.why.neighbors.map((n, i) => (
              <span key={n.title}>
                {i > 0 && " and "}
                <b>{n.title}</b> ({n.rating}★)
              </span>
            ))}
            {rec.why.connection ? ` — ${rec.why.connection}.` : "."}
          </p>
        )}
```

- [ ] **Step 2: Verify build**

Run: `cd frontend && npm run build`
Expected: build succeeds

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/RecommendationCard.jsx
git commit -m "feat: card shows specific rated-film reasons instead of generic tags"
```

---

### Task 14: Frontend — `MarqueeTrio` component (Top Pick redesign)

**Files:**
- Create: `frontend/src/components/MarqueeTrio.jsx`
- Modify: `frontend/src/RecommendationsPage.jsx`

- [ ] **Step 1: Create the component**

`frontend/src/components/MarqueeTrio.jsx`:

```jsx
const BACKDROP = "https://image.tmdb.org/t/p/w1280";

function TrioPanel({ rec, rank, onSelect }) {
  return (
    <div
      className={`trio-panel trio-rank-${rank}`}
      style={rec.backdrop_path ? { backgroundImage: `url(${BACKDROP}${rec.backdrop_path})` } : undefined}
      role="button"
      tabIndex={0}
      onClick={() => onSelect(rec)}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onSelect(rec))}
    >
      <div className="trio-scrim" />
      <div className="trio-content">
        <div className="trio-rank-label">#{rank}</div>
        <div className="trio-title">
          {rec.title} <span className="trio-year">({rec.year})</span>
        </div>
        <div className="trio-match">{Math.round(rec.match_pct)}% match</div>
      </div>
    </div>
  );
}

export default function MarqueeTrio({ recs, onSelect }) {
  if (!recs || recs.length === 0) return null;
  return (
    <div className="marquee-trio-section">
      <div className="marquee-eyebrow">Tonight's Marquee</div>
      <div className="marquee-trio">
        {recs.map((rec, i) => (
          <TrioPanel key={rec.tmdb_id} rec={rec} rank={i + 1} onSelect={onSelect} />
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Replace the single hero band in `RecommendationsPage.jsx`**

Remove `HeroPoster` (lines 8-20) and the entire `{top && (...)}` hero-band block (lines 136-164) from `frontend/src/RecommendationsPage.jsx`. Add the import:

```jsx
import MarqueeTrio from "./components/MarqueeTrio";
```

Replace:

```jsx
  const top = recs && recs.length > 0 ? recs[0] : null;
  const rest = recs && recs.length > 0 ? recs.slice(1) : [];
```

with (full capping/long-shots logic used by Task 15 too):

```jsx
  const LONG_SHOT_THRESHOLD = 70;
  const PAGE_SIZE = 25;

  const trio = recs ? recs.slice(0, 3) : [];
  const remaining = recs ? recs.slice(3) : [];
  const mainList = remaining.filter((r) => r.match_pct >= LONG_SHOT_THRESHOLD);
  const longShots = remaining.filter((r) => r.match_pct < LONG_SHOT_THRESHOLD);
  const [visibleCount, setVisibleCount] = useState(PAGE_SIZE);
  const visibleMain = mainList.slice(0, visibleCount);
  const [showLongShots, setShowLongShots] = useState(false);
```

(`useState` is already imported at the top of the file.)

Replace the hero-band JSX block with:

```jsx
      <MarqueeTrio recs={trio} onSelect={setSelectedFilm} />
```

Replace the `{rest.length > 0 && (...)}` grid block with:

```jsx
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
```

- [ ] **Step 3: Reset `visibleCount`/`showLongShots` when `recs` changes**

Add to the existing `useEffect` that resets `recs` on username change (`frontend/src/RecommendationsPage.jsx:53-56`) — no change needed there since `visibleCount`/`showLongShots` are local state re-initialized to their defaults only on mount, not on `recs` change. Add a dedicated effect right after the `visibleCount`/`showLongShots` declarations:

```jsx
  useEffect(() => {
    setVisibleCount(PAGE_SIZE);
    setShowLongShots(false);
  }, [recs]);
```

- [ ] **Step 4: Verify build**

Run: `cd frontend && npm run build`
Expected: build succeeds, no unused-import errors (confirm `HeroPoster` and its usages are fully removed)

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/MarqueeTrio.jsx frontend/src/RecommendationsPage.jsx
git commit -m "feat: Tonight's Marquee spotlight trio replaces single hero band; cap list at 25 with long shots"
```

---

### Task 15: Frontend — `FilmDetailModal` (replaces `WatchProvidersModal`)

**Files:**
- Create: `frontend/src/components/FilmDetailModal.jsx`
- Delete: `frontend/src/components/WatchProvidersModal.jsx`
- Modify: `frontend/src/RecommendationsPage.jsx` (import + usage)

- [ ] **Step 1: Create the new modal**

`frontend/src/components/FilmDetailModal.jsx`:

```jsx
import { useEffect, useState } from "react";
import { getFilmDetail, getWatchProviders } from "../api";

const BACKDROP = "https://image.tmdb.org/t/p/w780";
const LOGO = "https://image.tmdb.org/t/p/w45";

function ProviderRow({ label, providers }) {
  if (!providers || providers.length === 0) return null;
  return (
    <div className="provider-row">
      <div className="provider-label">{label}</div>
      <div className="provider-logos">
        {providers.map((p) => (
          <img key={p.name} src={LOGO + p.logo_path} alt={p.name} title={p.name} />
        ))}
      </div>
    </div>
  );
}

export default function FilmDetailModal({ film, onClose }) {
  const [detail, setDetail] = useState(null);
  const [providers, setProviders] = useState(null);
  const [providersFailed, setProvidersFailed] = useState(false);

  useEffect(() => {
    setDetail(null);
    setProviders(null);
    setProvidersFailed(false);
    getFilmDetail(film.tmdb_id).then(setDetail);
    getWatchProviders(film.tmdb_id).then(setProviders).catch(() => setProvidersFailed(true));
  }, [film.tmdb_id]);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const hasProviders = providers && (providers.flatrate.length || providers.rent.length || providers.buy.length);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal film-detail-modal"
        role="dialog"
        aria-modal="true"
        aria-label={`${film.title} details`}
        onClick={(e) => e.stopPropagation()}
      >
        <button className="modal-close" onClick={onClose} aria-label="Close">
          ×
        </button>

        {detail?.backdrop_path && (
          <div className="modal-backdrop-image" style={{ backgroundImage: `url(${BACKDROP}${detail.backdrop_path})` }} />
        )}

        <h3>{film.title} ({film.year})</h3>
        {detail?.runtime && <p className="modal-meta">{detail.runtime} min · {detail.director}</p>}

        {film.why?.neighbors?.length > 0 && (
          <p className="modal-why">
            Because you loved{" "}
            {film.why.neighbors.map((n, i) => (
              <span key={n.title}>
                {i > 0 && " and "}
                <b>{n.title}</b> ({n.rating}★)
              </span>
            ))}
            {film.why.connection ? ` — ${film.why.connection}.` : "."}
          </p>
        )}

        <div className="modal-stats">
          <span>{Math.round(film.match_pct)}% match</span>
          <span>{film.predicted_rating?.toFixed(1)}★ predicted</span>
        </div>

        {detail?.overview && <p className="modal-overview">{detail.overview}</p>}
        {detail?.genres?.length > 0 && <p className="modal-genres">{detail.genres.join(" · ")}</p>}
        {detail?.cast?.length > 0 && <p className="modal-cast">Starring {detail.cast.join(", ")}</p>}

        <p className="modal-subtitle">Where to watch</p>
        {providers === null && !providersFailed && <p className="modal-loading">Loading...</p>}
        {providersFailed && <p className="modal-loading">Couldn't load streaming info.</p>}
        {providers && !hasProviders && <p className="modal-loading">Not currently available to stream, rent, or buy (US).</p>}
        {providers && hasProviders && (
          <>
            <ProviderRow label="Stream" providers={providers.flatrate} />
            <ProviderRow label="Rent" providers={providers.rent} />
            <ProviderRow label="Buy" providers={providers.buy} />
          </>
        )}
        {providers?.link && (
          <a className="modal-link" href={providers.link} target="_blank" rel="noreferrer">
            View all options →
          </a>
        )}
        <p className="modal-attribution">Streaming data via JustWatch</p>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Delete the old modal**

```bash
rm ~/letterboxd-recommenation/frontend/src/components/WatchProvidersModal.jsx
```

- [ ] **Step 3: Update `RecommendationsPage.jsx` to use the new modal**

Replace the import:

```jsx
import WatchProvidersModal from "./components/WatchProvidersModal";
```

with:

```jsx
import FilmDetailModal from "./components/FilmDetailModal";
```

Replace the render at the bottom of the file:

```jsx
      {selectedFilm && (
        <WatchProvidersModal film={selectedFilm} onClose={() => setSelectedFilm(null)} />
      )}
```

with:

```jsx
      {selectedFilm && (
        <FilmDetailModal film={selectedFilm} onClose={() => setSelectedFilm(null)} />
      )}
```

- [ ] **Step 4: Verify build**

Run: `cd frontend && npm run build`
Expected: build succeeds, no reference to the deleted `WatchProvidersModal` remains (grep to confirm):

```bash
grep -rn "WatchProvidersModal" frontend/src
```
Expected: no output

- [ ] **Step 5: Commit**

```bash
git add -A frontend/src/components/FilmDetailModal.jsx frontend/src/RecommendationsPage.jsx
git rm frontend/src/components/WatchProvidersModal.jsx
git commit -m "feat: rich film detail modal (synopsis, cast, runtime, reason) replaces watch-providers-only popup"
```

---

### Task 16: Frontend — Taste Profile dashboard redesign

**Files:**
- Rewrite: `frontend/src/TasteProfilePage.jsx`
- Create: `frontend/src/components/GenreRadar.jsx`
- Delete: `frontend/src/components/TicketStub.jsx` (superseded)

- [ ] **Step 1: Create the radar chart component**

`frontend/src/components/GenreRadar.jsx`:

```jsx
function pointFor(angle, radius, cx, cy) {
  return [cx + radius * Math.cos(angle), cy + radius * Math.sin(angle)];
}

export default function GenreRadar({ genres }) {
  const top = genres.slice(0, 6);
  if (top.length < 3) return null;

  const size = 220;
  const cx = size / 2;
  const cy = size / 2;
  const maxRadius = size / 2 - 24;
  const step = (2 * Math.PI) / top.length;

  const maxAffinity = Math.max(...top.map((g) => Math.max(g.affinity, 0)), 0.01);
  const points = top.map((g, i) => {
    const angle = -Math.PI / 2 + i * step;
    const r = (Math.max(g.affinity, 0) / maxAffinity) * maxRadius;
    return pointFor(angle, r, cx, cy);
  });
  const polygon = points.map(([x, y]) => `${x},${y}`).join(" ");

  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="genre-radar" role="img" aria-label="Genre affinity radar">
      {[0.33, 0.66, 1].map((f) => (
        <polygon
          key={f}
          points={top.map((_, i) => pointFor(-Math.PI / 2 + i * step, maxRadius * f, cx, cy).join(",")).join(" ")}
          className="radar-grid"
        />
      ))}
      <polygon points={polygon} className="radar-shape" />
      {top.map((g, i) => {
        const [lx, ly] = pointFor(-Math.PI / 2 + i * step, maxRadius + 14, cx, cy);
        return (
          <text key={g.name} x={lx} y={ly} className="radar-label" textAnchor="middle">
            {g.name}
          </text>
        );
      })}
    </svg>
  );
}
```

- [ ] **Step 2: Rewrite `TasteProfilePage.jsx`**

Replace `frontend/src/TasteProfilePage.jsx` in full:

```jsx
import { useEffect, useState } from "react";
import { getTasteProfile } from "./api";
import GenreRadar from "./components/GenreRadar";

const FACE = "https://image.tmdb.org/t/p/w185";

function StatTile({ value, label }) {
  return (
    <div className="stat-tile">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  );
}

function RatingHistogram({ distribution }) {
  const max = Math.max(...distribution.map((b) => b.count), 1);
  return (
    <div className="rating-histogram">
      {distribution.map((b) => (
        <div key={b.star} className="histogram-bar" style={{ height: `${(b.count / max) * 100}%` }}>
          <span>{b.star}★</span>
        </div>
      ))}
    </div>
  );
}

function PeopleWall({ title, people }) {
  if (!people || people.length === 0) return null;
  return (
    <div className="people-wall-section">
      <p className="section-title">{title}</p>
      <div className="people-wall">
        {people.map((p) => (
          <div className="person-face" key={p.name}>
            {p.profile_path ? (
              <img src={FACE + p.profile_path} alt={p.name} />
            ) : (
              <div className="person-face-placeholder">{p.name[0]}</div>
            )}
            <div className="person-name">{p.name}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function AffinityBars({ genres }) {
  const top = genres.slice(0, 6);
  const max = Math.max(...top.map((g) => Math.abs(g.affinity)), 0.01);
  return (
    <div className="affinity-bars">
      {top.map((g) => (
        <div className="affinity-row" key={g.name}>
          <span className="affinity-name">{g.name}</span>
          <span className="affinity-track">
            <span className="affinity-fill" style={{ width: `${(Math.max(g.affinity, 0) / max) * 100}%` }} />
          </span>
        </div>
      ))}
    </div>
  );
}

export default function TasteProfilePage({ username }) {
  const [dash, setDash] = useState(null);

  useEffect(() => {
    if (!username) return;
    setDash(null);
    getTasteProfile(username).then(setDash);
  }, [username]);

  if (!username) {
    return (
      <div className="empty-state">
        <h3>Enter your Letterboxd username</h3>
        <p>Add it above to see your taste profile.</p>
      </div>
    );
  }

  if (dash === null) return null;

  if (dash.total_rated === 0) {
    return (
      <div className="empty-state">
        <h3>No taste profile yet</h3>
        <p>Refresh your data from the Recommendations tab to build your taste profile.</p>
      </div>
    );
  }

  return (
    <div className="taste-dashboard">
      <div className="dashboard-eyebrow">Your Taste Fingerprint</div>

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

`dash.top_keywords` (a plain list of strings from the backend) surfaces the signature keywords from the approved mockup (e.g. "neo-noir") as chips beneath the affinity bars — otherwise the field would be computed by `build_dashboard` and never displayed.

- [ ] **Step 3: Delete the superseded component**

```bash
rm ~/letterboxd-recommenation/frontend/src/components/TicketStub.jsx
```

- [ ] **Step 4: Verify build**

Run: `cd frontend && npm run build`
Expected: build succeeds; confirm no remaining references:

```bash
grep -rn "TicketStub" frontend/src
```
Expected: no output

- [ ] **Step 5: Commit**

```bash
git add -A frontend/src/TasteProfilePage.jsx frontend/src/components/GenreRadar.jsx
git rm frontend/src/components/TicketStub.jsx
git commit -m "feat: redesign Taste Profile as a full dashboard (stats, histogram, radar, headshot wall, affinities, signature)"
```

---

### Task 17: CSS for all new components

**Files:**
- Modify: `frontend/src/index.css`

- [ ] **Step 1: Append new styles**

Add to the end of `frontend/src/index.css` (uses the existing `--bg`, `--surface`, `--border`, `--ink`, `--muted`, `--accent`, `--font-display`, `--font-body` tokens):

```css
/* Marquee spotlight trio */
.marquee-trio-section { margin-bottom: 32px; }
.marquee-eyebrow {
  font-family: var(--font-display); letter-spacing: 0.22em; font-size: 14px;
  color: var(--accent); margin-bottom: 12px;
}
.marquee-trio { display: grid; grid-template-columns: 1.4fr 1fr 1fr; gap: 4px; }
.trio-panel {
  position: relative; height: 280px; background-size: cover; background-position: center;
  background-color: var(--surface); display: flex; align-items: flex-end; cursor: pointer;
  border-radius: 8px; overflow: hidden;
}
.trio-scrim {
  position: absolute; inset: 0;
  background: linear-gradient(0deg, rgba(0,0,0,0.9) 0%, rgba(0,0,0,0) 65%);
}
.trio-content { position: relative; z-index: 2; padding: 18px; }
.trio-rank-label { font-family: var(--font-display); color: var(--accent); font-size: 18px; letter-spacing: 0.1em; }
.trio-title { font-family: var(--font-display); font-size: 28px; line-height: 0.95; margin: 2px 0; color: var(--ink); }
.trio-year { font-size: 16px; color: var(--muted); }
.trio-match { color: var(--accent); font-size: 13px; font-weight: 600; }

/* List caps */
.show-more-button, .long-shots-toggle {
  display: block; margin: 20px auto; padding: 10px 20px; border-radius: 8px;
  border: 1px solid var(--border); background: var(--surface); color: var(--ink);
  font-family: var(--font-body); cursor: pointer;
}
.show-more-button:hover, .long-shots-toggle:hover { border-color: var(--accent); }
.long-shots-section { margin-top: 24px; }

/* Film detail modal additions */
.modal-backdrop-image {
  width: calc(100% + 48px); margin: -24px -24px 16px; height: 200px;
  background-size: cover; background-position: center; border-radius: 8px 8px 0 0;
}
.modal-meta { color: var(--muted); font-size: 13px; margin: 4px 0 12px; }
.modal-why { font-size: 14px; color: var(--ink); margin-bottom: 12px; }
.modal-stats { display: flex; gap: 16px; font-size: 14px; color: var(--accent); margin-bottom: 12px; }
.modal-overview { font-size: 14px; line-height: 1.5; color: var(--ink); margin-bottom: 10px; }
.modal-genres, .modal-cast { font-size: 13px; color: var(--muted); margin-bottom: 6px; }

/* Taste dashboard */
.taste-dashboard { max-width: 900px; }
.dashboard-eyebrow {
  font-family: var(--font-display); letter-spacing: 0.22em; font-size: 15px;
  color: var(--accent); margin-bottom: 18px;
}
.stat-row { display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin-bottom: 28px; }
.stat-tile { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
.stat-value { font-family: var(--font-display); font-size: 36px; color: var(--accent); line-height: 1; }
.stat-label { color: var(--muted); font-size: 12px; letter-spacing: 0.08em; text-transform: uppercase; margin-top: 4px; }

.dashboard-grid { display: grid; grid-template-columns: 1fr 1.2fr; gap: 28px; margin-bottom: 28px; }
.section-title { font-size: 12px; letter-spacing: 0.1em; text-transform: uppercase; color: var(--muted); margin: 0 0 12px; }

.rating-histogram { display: flex; align-items: flex-end; gap: 8px; height: 110px; }
.histogram-bar {
  flex: 1; background: linear-gradient(180deg, var(--accent), var(--accent-dim));
  border-radius: 3px 3px 0 0; position: relative; min-height: 4px;
}
.histogram-bar span {
  position: absolute; bottom: -20px; left: 0; right: 0; text-align: center;
  font-size: 11px; color: var(--muted);
}
.signature-line {
  margin-top: 26px; padding: 14px 16px; border-left: 3px solid var(--accent);
  background: var(--surface); font-size: 15px; font-style: italic; color: var(--ink);
}

.affinity-row { display: flex; align-items: center; gap: 10px; margin-bottom: 9px; font-size: 13px; }
.affinity-name { width: 110px; color: var(--ink); flex-shrink: 0; }
.affinity-track { flex: 1; height: 9px; background: var(--surface-raised); border-radius: 6px; overflow: hidden; }
.affinity-fill { display: block; height: 100%; background: var(--accent); border-radius: 6px; }

.keyword-chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 16px; }
.keyword-chip {
  font-size: 12px; padding: 4px 10px; border-radius: 20px; border: 1px solid var(--border);
  color: var(--muted); background: var(--surface);
}

.genre-radar { width: 100%; max-width: 230px; }
.radar-grid { fill: none; stroke: var(--border); }
.radar-shape { fill: color-mix(in srgb, var(--accent) 28%, transparent); stroke: var(--accent); stroke-width: 2; }
.radar-label { fill: var(--muted); font-size: 9px; font-family: var(--font-body); }

.people-wall-section { margin-bottom: 20px; }
.people-wall { display: flex; flex-wrap: wrap; gap: 14px; }
.person-face { text-align: center; width: 78px; }
.person-face img, .person-face-placeholder {
  width: 64px; height: 64px; border-radius: 50%; object-fit: cover; border: 2px solid var(--accent);
}
.person-face-placeholder {
  display: flex; align-items: center; justify-content: center; background: var(--surface);
  color: var(--accent); font-family: var(--font-display); font-size: 22px;
}
.person-name { font-size: 11px; color: var(--ink); margin-top: 6px; }

@media (max-width: 720px) {
  .marquee-trio { grid-template-columns: 1fr; }
  .dashboard-grid { grid-template-columns: 1fr; }
  .stat-row { grid-template-columns: 1fr 1fr; }
}
```

- [ ] **Step 2: Verify build**

Run: `cd frontend && npm run build`
Expected: build succeeds

- [ ] **Step 3: Commit**

```bash
git add frontend/src/index.css
git commit -m "style: CSS for spotlight trio, list caps, rich modal, taste dashboard"
```

---

### Task 18: Live verification

**Files:** none (verification-only)

- [ ] **Step 1: Full backend suite**

Run: `cd backend && python -m pytest -q`
Expected: all PASS

- [ ] **Step 2: Frontend build**

Run: `cd frontend && npm run build`
Expected: succeeds with no errors

- [ ] **Step 3: Manual browser check**

Start both servers:
```bash
cd backend && uvicorn app.api:app --reload &
cd frontend && npm run dev &
```

Open the app, enter username `moviefan`, click refresh, and wait for it to complete. Confirm:
- The refresh completes without an "Incomplete scrape" error (or, if it does error, that's the scraper correctly catching a real block — retry).
- Silence of the Lambs, The Godfather Part II, and Taxi Driver do **not** appear anywhere in the recommendations list.
- The Tonight's Marquee trio renders with real backdrop images.
- Clicking any film opens the rich detail modal with synopsis, runtime, cast, and a specific "Because you loved X and Y — <reason>" line that differs between films.
- The Taste Profile tab renders the stat row, histogram, radar, headshot wall, affinity bars, and signature line with real data.
- The recommendations list shows at most 25 in the main section, with a working "Show more" and a "Long shots" toggle for anything under 70%.

- [ ] **Step 4: Stop the dev servers**

```bash
kill %1 %2
```

- [ ] **Step 5: Report results to the user** — do not claim success without having actually completed Step 3.
