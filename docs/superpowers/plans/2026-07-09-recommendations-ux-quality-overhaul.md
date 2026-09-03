# Recommendations UX + Quality Overhaul Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a critical-quality signal to recommendations, recalibrate match% to be honest and high, and rebuild the front end (routing, header, list, expand-to-center cards, taste profile) into a snappy, futuristic UI.

**Architecture:** Backend gains an OMDb rating fetch + TMDB-vote quality gate/factor and an anchored-absolute match% in `scorer.py`; the API enriches its payloads. Frontend adds `react-router-dom` for real URLs, a marquee-bulb header, a partitioned recommendation list with expand-to-center flip cards, and a centered, richer taste profile.

**Tech Stack:** FastAPI + SQLite + numpy (backend), React 19 + Vite + react-router-dom (frontend), pytest + vitest + Playwright (tests).

**Working policy:** Commit to `main` (per repo `CLAUDE.md`). No branches.

---

## File Structure

**Backend**
- Create `backend/app/omdb.py` — OMDb IMDb/RT fetch (isolated HTTP unit).
- Modify `backend/app/config.py` — add `omdb_api_key`.
- Modify `backend/app/db.py` — `films` columns `vote_count`, `imdb_rating`, `rt_score`.
- Modify `backend/app/tmdb.py` — capture `imdb_id`, `vote_count` in `enrich`.
- Modify `backend/app/scorer.py` — quality gate/factor + anchored match%.
- Modify `backend/app/pipeline.py` — persist `vote_count`; OMDb top-80 after scoring.
- Modify `backend/app/api.py` — richer `/api/recommendations`; wire OMDb dep.
- Modify `backend/app/taste_dashboard.py` — half-star histogram, per-person `top_films`.

**Frontend**
- Modify `frontend/package.json` — add `react-router-dom`.
- Modify `frontend/src/main.jsx` — `BrowserRouter`.
- Modify `frontend/src/App.jsx` — routes + shell (header, one-line controls).
- Create `frontend/src/components/BulbSign.jsx` — marquee-bulb header.
- Create `frontend/src/lib/recList.js` (+ `.test.js`) — list partition (pure).
- Modify `frontend/src/RecommendationsPage.jsx` — partition, pagination, expand state.
- Modify `frontend/src/components/RecommendationCard.jsx` — tilt + flip + starring + badges.
- Create `frontend/src/components/ExpandedFilmCard.jsx` — expand-to-center detail (replaces modal).
- Delete `frontend/src/components/FilmDetailModal.jsx`.
- Modify `frontend/src/components/MarqueeTrio.jsx` — rename copy + predicted ★.
- Modify `frontend/src/TasteProfilePage.jsx` — centering, headers, half-star, people reveal.
- Modify `frontend/src/components/GenreRadar.jsx` — 10 axes, rings, fill, hover.
- Create `frontend/src/components/PersonCard.jsx` — face + hover/tap top-films popover.
- Modify `frontend/src/index.css` — tokens, tilt/flip/expand, typography, centering.
- Create `frontend/tests/e2e/*.spec.js` + Playwright config.

---

# Phase 1 — Backend: quality signal + scoring

## Task 1: Config — OMDb key

**Files:** Modify `backend/app/config.py`; Modify `backend/tests/test_config.py`

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_config.py`:

```python
def test_load_config_reads_omdb_key(monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "tmdb")
    monkeypatch.setenv("OMDB_API_KEY", "omdb")
    from app.config import load_config
    cfg = load_config()
    assert cfg.omdb_api_key == "omdb"

def test_load_config_omdb_key_optional(monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "tmdb")
    monkeypatch.delenv("OMDB_API_KEY", raising=False)
    from app.config import load_config
    assert load_config().omdb_api_key == ""
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd backend && python -m pytest tests/test_config.py -q`
Expected: FAIL (`omdb_api_key` missing).

- [ ] **Step 3: Implement**

In `backend/app/config.py`, add field to `Config` and read it:

```python
@dataclass
class Config:
    username: str
    tmdb_api_key: str
    db_path: str
    omdb_api_key: str = ""
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:5173"])
```

In `load_config()` add `omdb_api_key=os.environ.get("OMDB_API_KEY", ""),` before `cors_origins`.

- [ ] **Step 4: Run — expect PASS**

Run: `cd backend && python -m pytest tests/test_config.py -q` → PASS.

- [ ] **Step 5: Update `.env.example`**

Append to `backend/.env.example`: `OMDB_API_KEY=`  (with a `# free key from https://www.omdbapi.com/apikey.aspx` comment).

- [ ] **Step 6: Commit**

```bash
git add backend/app/config.py backend/tests/test_config.py backend/.env.example
git commit -m "feat(config): optional OMDB_API_KEY"
```

## Task 2: DB — quality columns

**Files:** Modify `backend/app/db.py`; Modify `backend/tests/test_db.py`

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_db.py`:

```python
def test_schema_has_quality_columns(tmp_path):
    from app.db import connect, init_schema
    conn = connect(str(tmp_path / "t.db"))
    init_schema(conn)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(films)").fetchall()}
    assert {"vote_count", "imdb_rating", "rt_score"} <= cols
```

- [ ] **Step 2: Run — expect FAIL**

Run: `cd backend && python -m pytest tests/test_db.py -q` → FAIL.

- [ ] **Step 3: Implement**

In `db.py` `SCHEMA`, add to the `films` table definition: `tmdb_vote_avg REAL, vote_count INTEGER, imdb_rating REAL, rt_score INTEGER` (append the three new columns after `tmdb_vote_avg`). Add to `_MIGRATIONS`:

```python
    "ALTER TABLE films ADD COLUMN vote_count INTEGER",
    "ALTER TABLE films ADD COLUMN imdb_rating REAL",
    "ALTER TABLE films ADD COLUMN rt_score INTEGER",
```

- [ ] **Step 4: Run — expect PASS** → `python -m pytest tests/test_db.py -q`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db.py backend/tests/test_db.py
git commit -m "feat(db): films quality columns (vote_count, imdb_rating, rt_score)"
```

## Task 3: TMDB enrich — imdb_id + vote_count

**Files:** Modify `backend/app/tmdb.py`; Modify `backend/tests/test_tmdb.py`

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_tmdb.py` (follow the file's existing fake-session pattern; a minimal inline fake shown here):

```python
def test_enrich_captures_imdb_id_and_vote_count():
    from app.tmdb import enrich
    class FakeResp:
        def raise_for_status(self): pass
        def json(self):
            return {
                "title": "X", "release_date": "2010-01-01",
                "vote_average": 7.5, "vote_count": 1234,
                "genres": [], "credits": {"crew": [], "cast": []},
                "keywords": {"keywords": []},
                "external_ids": {"imdb_id": "tt0111161"},
            }
    class FakeSession:
        def get(self, url, params=None, timeout=None): return FakeResp()
    m = enrich(1, "key", session=FakeSession())
    assert m["imdb_id"] == "tt0111161"
    assert m["vote_count"] == 1234
```

- [ ] **Step 2: Run — expect FAIL** → `python -m pytest tests/test_tmdb.py::test_enrich_captures_imdb_id_and_vote_count -q`.

- [ ] **Step 3: Implement**

In `tmdb.enrich`, change `append_to_response` to `"credits,keywords,external_ids"`. Add to the returned dict:

```python
        "vote_count": data.get("vote_count"),
        "imdb_id": data.get("external_ids", {}).get("imdb_id") or data.get("imdb_id"),
```

- [ ] **Step 4: Run — expect PASS**. Also run the whole tmdb suite: `python -m pytest tests/test_tmdb.py -q`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/tmdb.py backend/tests/test_tmdb.py
git commit -m "feat(tmdb): capture imdb_id and vote_count in enrich"
```

## Task 4: OMDb module

**Files:** Create `backend/app/omdb.py`; Create `backend/tests/test_omdb.py`

- [ ] **Step 1: Write failing test**

Create `backend/tests/test_omdb.py`:

```python
from app.omdb import fetch_ratings

class _Resp:
    def __init__(self, payload): self._p = payload
    def raise_for_status(self): pass
    def json(self): return self._p

class _Session:
    def __init__(self, payload): self._p = payload
    def get(self, url, params=None, timeout=None): return _Resp(self._p)

def test_fetch_ratings_parses_imdb_and_rt():
    payload = {"Response": "True", "imdbRating": "8.1",
               "Ratings": [{"Source": "Rotten Tomatoes", "Value": "94%"}]}
    out = fetch_ratings("tt1", "key", session=_Session(payload))
    assert out == {"imdb_rating": 8.1, "rt_score": 94}

def test_fetch_ratings_handles_missing_fields():
    payload = {"Response": "True", "imdbRating": "N/A", "Ratings": []}
    assert fetch_ratings("tt1", "key", session=_Session(payload)) == {"imdb_rating": None, "rt_score": None}

def test_fetch_ratings_response_false():
    assert fetch_ratings("tt1", "key", session=_Session({"Response": "False"})) == {"imdb_rating": None, "rt_score": None}

def test_fetch_ratings_no_key_or_id_short_circuits():
    assert fetch_ratings("", "key") == {"imdb_rating": None, "rt_score": None}
    assert fetch_ratings("tt1", "") == {"imdb_rating": None, "rt_score": None}
```

- [ ] **Step 2: Run — expect FAIL** → `python -m pytest tests/test_omdb.py -q`.

- [ ] **Step 3: Implement**

Create `backend/app/omdb.py`:

```python
import time
import requests

API = "https://www.omdbapi.com/"
TIMEOUT = 15
MAX_RETRIES = 3

def _get(session, params):
    s = session or requests
    for attempt in range(MAX_RETRIES):
        if attempt:
            time.sleep(2 ** (attempt - 1))
        try:
            resp = s.get(API, params=params, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if attempt == MAX_RETRIES - 1:
                raise

def fetch_ratings(imdb_id: str, api_key: str, session=None) -> dict:
    """IMDb rating + Rotten Tomatoes % for an imdb_id. Never raises; returns
    {"imdb_rating": float|None, "rt_score": int|None}."""
    empty = {"imdb_rating": None, "rt_score": None}
    if not imdb_id or not api_key:
        return empty
    try:
        data = _get(session, {"apikey": api_key, "i": imdb_id})
    except Exception:
        return empty
    if not data or data.get("Response") == "False":
        return empty
    imdb_rating = None
    try:
        imdb_rating = float(data["imdbRating"])
    except (KeyError, ValueError, TypeError):
        pass
    rt_score = None
    for r in data.get("Ratings", []):
        if r.get("Source") == "Rotten Tomatoes":
            v = str(r.get("Value", "")).rstrip("%")
            if v.isdigit():
                rt_score = int(v)
    return {"imdb_rating": imdb_rating, "rt_score": rt_score}
```

- [ ] **Step 4: Run — expect PASS** → `python -m pytest tests/test_omdb.py -q`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/omdb.py backend/tests/test_omdb.py
git commit -m "feat(omdb): IMDb + Rotten Tomatoes rating fetch"
```

## Task 5: Scorer — quality gate/factor + anchored match%

**Files:** Modify `backend/app/scorer.py`; Modify `backend/tests/test_scorer.py`

- [ ] **Step 1: Update the two existing tests that assume the old formula**

In `backend/tests/test_scorer.py`, replace `test_score_candidates_normalizes_and_ranks` with:

```python
def test_score_candidates_anchors_best_high_and_ranks():
    cands = [CAND, {"tmdb_id": 2, "genres": ["Comedy"], "keywords": [],
                    "director": "X", "cast": [], "decade": 1990}]
    rated = [{"rating": 5.0, "title": "Snowpiercer", "genres": ["Thriller"], "keywords": ["class conflict"]}]
    results = score_candidates(cands, PROFILE, rated, k=1)
    assert results[0]["tmdb_id"] == 999           # perfect match ranked first
    assert results[0]["match_pct"] >= 90.0         # anchored: best reads high, not ~50%
    assert results[-1]["match_pct"] < results[0]["match_pct"]
```

- [ ] **Step 2: Add new behavior tests**

```python
def test_quality_floor_excludes_panned_films():
    good = dict(CAND); good["vote_avg"] = 7.0; good["vote_count"] = 500
    panned = {"tmdb_id": 7, "genres": ["Thriller"], "keywords": ["class conflict"],
              "director": "Bong Joon-ho", "cast": ["Song Kang-ho"], "decade": 2010,
              "vote_avg": 3.2, "vote_count": 400}
    rated = [{"rating": 5.0, "genres": ["Thriller"], "keywords": ["class conflict"]}]
    ids = {r["tmdb_id"] for r in score_candidates([good, panned], PROFILE, rated)}
    assert 7 not in ids and 999 in ids

def test_sparse_votes_not_excluded():
    obscure = {"tmdb_id": 8, "genres": ["Thriller"], "keywords": ["class conflict"],
               "director": "Bong Joon-ho", "cast": ["Song Kang-ho"], "decade": 2010,
               "vote_avg": 3.0, "vote_count": 4}
    rated = [{"rating": 5.0, "genres": ["Thriller"], "keywords": ["class conflict"]}]
    ids = {r["tmdb_id"] for r in score_candidates([obscure], PROFILE, rated)}
    assert 8 in ids

def test_quality_factor_tilts_ranking_between_equal_taste():
    a = {"tmdb_id": 10, "genres": ["Thriller"], "keywords": ["class conflict"],
         "vote_avg": 8.4, "vote_count": 900}
    b = {"tmdb_id": 11, "genres": ["Thriller"], "keywords": ["class conflict"],
         "vote_avg": 5.2, "vote_count": 900}
    rated = [{"rating": 5.0, "genres": ["Thriller"], "keywords": ["class conflict"]}]
    results = score_candidates([b, a], PROFILE, rated)
    assert results[0]["tmdb_id"] == 10   # acclaimed ranks above equal-taste mediocre
```

- [ ] **Step 3: Run — expect FAIL** → `python -m pytest tests/test_scorer.py -q`.

- [ ] **Step 4: Implement**

In `backend/app/scorer.py`, add constants + helpers and rewrite `score_candidates`:

```python
ANCHOR_PCT = 95.0
MAX_PCT = 99.0
FLOOR_VOTES = 50
FLOOR_AVG = 5.0
QF_LO_AVG, QF_HI_AVG = 5.0, 8.5
QF_LO, QF_HI = 0.85, 1.12

def quality_factor(vote_avg, vote_count) -> float:
    if vote_avg is None or (vote_count or 0) < FLOOR_VOTES:
        return 1.0
    t = max(0.0, min(1.0, (vote_avg - QF_LO_AVG) / (QF_HI_AVG - QF_LO_AVG)))
    return QF_LO + t * (QF_HI - QF_LO)

def _below_floor(cand) -> bool:
    va, vc = cand.get("vote_avg"), cand.get("vote_count") or 0
    return va is not None and vc >= FLOOR_VOTES and va < FLOOR_AVG

def _anchor_raw(rated, profile):
    """Raw score a beloved film earns against this profile -> maps to ANCHOR_PCT."""
    highs = [f for f in rated if f.get("rating", 0) >= 4.5]
    if len(highs) < 3:
        highs = [f for f in rated if f.get("rating", 0) >= 4.0]
    raws = sorted(match_raw_score(f, profile) for f in highs)
    if not raws:
        return None
    return raws[len(raws) // 2]  # median

def score_candidates(cands, profile, rated, k: int = 10) -> list[dict]:
    if not cands:
        return []
    anchor = _anchor_raw(rated, profile)
    if not anchor or anchor <= 0:
        anchor = max((match_raw_score(c, profile) for c in cands), default=1.0) or 1.0
    results = []
    for c in cands:
        if _below_floor(c):
            continue
        raw = match_raw_score(c, profile)
        eff = raw * quality_factor(c.get("vote_avg"), c.get("vote_count"))
        pct = max(0.0, min(MAX_PCT, (eff / anchor) * ANCHOR_PCT))
        results.append({
            "tmdb_id": c["tmdb_id"],
            "match_pct": round(pct, 1),
            "predicted_rating": round(predict_rating(c, rated, k), 2),
            "why": why_for(c, rated),
            "_eff": eff,
        })
    results.sort(key=lambda r: r["_eff"], reverse=True)
    for r in results:
        del r["_eff"]
    return results
```

- [ ] **Step 5: Run — expect PASS** → `python -m pytest tests/test_scorer.py -q`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/scorer.py backend/tests/test_scorer.py
git commit -m "feat(scorer): quality gate/factor + anchored-absolute match%"
```

## Task 6: Pipeline — persist vote_count + OMDb top-80

**Files:** Modify `backend/app/pipeline.py`; Modify `backend/tests/test_pipeline.py`

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_pipeline.py` (reuse the module's existing fake `Deps`/conn harness; the assertion is what matters):

```python
def test_refresh_stores_omdb_ratings_for_top_results(pipeline_env):
    # pipeline_env is the existing fixture that wires fakes + an in-memory conn.
    env = pipeline_env
    env.deps.omdb_fn = lambda imdb_id: {"imdb_rating": 8.0, "rt_score": 90}
    run_refresh(env.conn, env.cfg, env.deps)
    row = env.conn.execute(
        "SELECT imdb_rating, rt_score FROM films WHERE imdb_rating IS NOT NULL LIMIT 1").fetchone()
    assert row["imdb_rating"] == 8.0 and row["rt_score"] == 90
```

> If `test_pipeline.py` has no shared fixture, add `omdb_fn` to the `Deps` construction in the existing happy-path test and assert the stored values there instead. Match the file's established style.

- [ ] **Step 2: Run — expect FAIL** → `python -m pytest tests/test_pipeline.py -q`.

- [ ] **Step 3: Implement**

In `pipeline.py`:

1. Add to `Deps`: `omdb_fn: callable = None  # (imdb_id) -> {"imdb_rating","rt_score"}`.
2. Add constant near the top: `OMDB_TOP_N = 80`.
3. In `_persist_film`, include `vote_count`: extend the `films` INSERT column list and values with `m.get("vote_count")` (place it right after `tmdb_vote_avg`). Keep `imdb_rating`/`rt_score` untouched here (updated later).
4. After `results = score_candidates(...)` and before writing recommendations, add:

```python
    if deps.omdb_fn:
        imdb_by_id = {m["tmdb_id"]: m.get("imdb_id") for m in cand_meta}
        for r in results[:OMDB_TOP_N]:
            _check_cancel(cancel_event)
            imdb_id = imdb_by_id.get(r["tmdb_id"])
            if not imdb_id:
                continue
            ratings = deps.omdb_fn(imdb_id)
            conn.execute(
                "UPDATE films SET imdb_rating=?, rt_score=? WHERE tmdb_id=?",
                (ratings.get("imdb_rating"), ratings.get("rt_score"), r["tmdb_id"]))
```

- [ ] **Step 4: Run — expect PASS** → `python -m pytest tests/test_pipeline.py -q`.

- [ ] **Step 5: Wire the real OMDb dep in `api.py`**

In `backend/app/api.py`, import `from app.omdb import fetch_ratings`, and in `_real_refresh`'s `Deps(...)` add:

```python
        omdb_fn=lambda imdb_id: fetch_ratings(imdb_id, cfg.omdb_api_key),
```

- [ ] **Step 6: Run full backend suite** → `cd backend && python -m pytest -q` (all green).

- [ ] **Step 7: Commit**

```bash
git add backend/app/pipeline.py backend/app/api.py backend/tests/test_pipeline.py
git commit -m "feat(pipeline): store vote_count + OMDb ratings for top recs"
```

## Task 7: API — richer recommendations payload

**Files:** Modify `backend/app/api.py`; Modify `backend/tests/test_api.py`

- [ ] **Step 1: Write failing test**

Add to `backend/tests/test_api.py` (follow existing seeding helpers; illustrative):

```python
def test_recommendations_include_starring_and_ratings(api_client_with_seed):
    client, seed = api_client_with_seed
    seed.film(tmdb_id=1, title="A", imdb_rating=8.1, rt_score=90, vote_avg=7.9,
              cast=["Actor One", "Actor Two", "Actor Three", "Actor Four"])
    seed.recommendation(username="u", film_id=1, match_pct=92.0)
    row = client.get("/api/recommendations?username=u").json()[0]
    assert row["starring"] == ["Actor One", "Actor Two", "Actor Three"]
    assert row["imdb_rating"] == 8.1 and row["rt_score"] == 90 and row["vote_avg"] == 7.9
```

> Adapt to `test_api.py`'s actual seeding utilities; if it seeds via raw SQL, insert into `film_cast`, `films` (with the new columns), and `recommendations` directly.

- [ ] **Step 2: Run — expect FAIL** → `python -m pytest tests/test_api.py -q`.

- [ ] **Step 3: Implement**

In `api.py` `recommendations()`, change the SELECT to include the new columns and build `starring`:

```python
        rows = conn.execute(
            "SELECT f.tmdb_id, f.title, f.year, f.poster_path, f.backdrop_path,"
            " f.imdb_rating, f.rt_score, f.tmdb_vote_avg,"
            " r.match_pct, r.predicted_rating, r.why"
            " FROM recommendations r JOIN films f ON f.tmdb_id = r.film_id"
            " WHERE r.username = ?"
            " ORDER BY r.match_pct DESC", (username,)).fetchall()
        def starring(fid):
            return [c["actor"] for c in conn.execute(
                "SELECT actor FROM film_cast WHERE film_id = ? LIMIT 3", (fid,)).fetchall()]
        return [{
            "tmdb_id": r["tmdb_id"], "title": r["title"], "year": r["year"],
            "poster_path": r["poster_path"], "backdrop_path": r["backdrop_path"],
            "match_pct": r["match_pct"], "predicted_rating": r["predicted_rating"],
            "imdb_rating": r["imdb_rating"], "rt_score": r["rt_score"],
            "vote_avg": r["tmdb_vote_avg"],
            "starring": starring(r["tmdb_id"]),
            "why": json.loads(r["why"]) if r["why"] else {"neighbors": [], "connection": None},
        } for r in rows]
```

Also add `imdb_rating`, `rt_score` to the `/api/films/{tmdb_id}` SELECT + response dict (same columns) so the expanded card can read them.

- [ ] **Step 4: Run — expect PASS** → `python -m pytest tests/test_api.py -q`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api.py backend/tests/test_api.py
git commit -m "feat(api): recommendations expose starring, imdb/rt/tmdb ratings"
```

## Task 8: Taste dashboard — half-star histogram + per-person top films

**Files:** Modify `backend/app/taste_dashboard.py`; Modify `backend/tests/test_taste_dashboard.py`

- [ ] **Step 1: Write failing tests**

Add to `backend/tests/test_taste_dashboard.py`:

```python
def test_rating_distribution_uses_half_star_buckets():
    from app.taste_dashboard import _rating_distribution
    rows = [{"your_rating": 4.5}, {"your_rating": 4.5}, {"your_rating": 3.0}, {"your_rating": 0.5}]
    dist = _rating_distribution(rows)
    assert [b["star"] for b in dist] == [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]
    by = {b["star"]: b["count"] for b in dist}
    assert by[4.5] == 2 and by[3.0] == 1 and by[0.5] == 1

def test_top_directors_include_top_films(dashboard_seed):
    # dashboard_seed: existing helper that seeds a user with rated films + people.
    dash = dashboard_seed_build()  # returns build_dashboard(conn, "u")
    d0 = dash["top_directors"][0]
    assert "top_films" in d0 and len(d0["top_films"]) <= 3
    assert d0["top_films"] == sorted(d0["top_films"], key=lambda f: f["rating"], reverse=True)
```

> Adapt the second test to the file's existing seeding harness. The essential assertions: `top_films` present, length ≤ 3, sorted by rating desc, each item has `title, year, rating, poster_path`.

- [ ] **Step 2: Run — expect FAIL** → `python -m pytest tests/test_taste_dashboard.py -q`.

- [ ] **Step 3: Implement**

Rewrite `_rating_distribution`:

```python
def _rating_distribution(rows):
    buckets = {round(0.5 * i, 1): 0 for i in range(1, 11)}  # 0.5 .. 5.0
    for r in rows:
        star = round(r["your_rating"] * 2) / 2
        star = max(0.5, min(5.0, star))
        buckets[star] += 1
    return [{"star": s, "count": c} for s, c in sorted(buckets.items())]
```

Add a top-films helper and attach it in `_top_directors` / `_top_people`:

```python
def _person_top_films(conn, username, id_col, id_value, cast_join=False):
    if cast_join:
        sql = ("SELECT f.title, f.year, f.poster_path, r.your_rating AS rating"
               " FROM film_cast t JOIN films f ON f.tmdb_id = t.film_id"
               " JOIN ratings r ON r.film_id = t.film_id"
               " WHERE r.username = ? AND t.person_id = ?"
               " ORDER BY r.your_rating DESC LIMIT 3")
    else:
        sql = ("SELECT f.title, f.year, f.poster_path, r.your_rating AS rating"
               " FROM films f JOIN ratings r ON r.film_id = f.tmdb_id"
               " WHERE r.username = ? AND f.director_id = ?"
               " ORDER BY r.your_rating DESC LIMIT 3")
    return [{"title": x["title"], "year": x["year"], "poster_path": x["poster_path"],
             "rating": x["rating"]} for x in conn.execute(sql, (username, id_value)).fetchall()]
```

In `_top_directors`, add `f.director_id AS pid` to the SELECT and include in each result:
`"top_films": _person_top_films(conn, username, "director_id", r["pid"], cast_join=False)`.

In `_top_people`, add `t.{person_col} AS pid` to the SELECT and include:
`"top_films": _person_top_films(conn, username, person_col, r["pid"], cast_join=True)`.

- [ ] **Step 4: Run — expect PASS** → `python -m pytest tests/test_taste_dashboard.py -q`.

- [ ] **Step 5: Full backend suite** → `cd backend && python -m pytest -q` (all green).

- [ ] **Step 6: Commit**

```bash
git add backend/app/taste_dashboard.py backend/tests/test_taste_dashboard.py
git commit -m "feat(taste): half-star histogram + per-person top films"
```

---

# Phase 2 — Frontend: routing, header, shell

## Task 9: Add react-router + BrowserRouter

**Files:** Modify `frontend/package.json`, `frontend/src/main.jsx`

- [ ] **Step 1: Install**

Run: `cd frontend && npm install react-router-dom`
Expected: `react-router-dom` added to `dependencies`.

- [ ] **Step 2: Wrap app in BrowserRouter**

In `frontend/src/main.jsx`, import `{ BrowserRouter }` from `react-router-dom` and wrap `<App />`:

```jsx
import { BrowserRouter } from "react-router-dom";
// ...
<BrowserRouter>
  <App />
</BrowserRouter>
```

- [ ] **Step 3: Verify build** → `cd frontend && npm run build` → succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/main.jsx
git commit -m "feat(fe): add react-router-dom + BrowserRouter"
```

## Task 10: BulbSign header

**Files:** Create `frontend/src/components/BulbSign.jsx`; Modify `frontend/src/index.css`

- [ ] **Step 1: Component**

Create `frontend/src/components/BulbSign.jsx`:

```jsx
export default function BulbSign() {
  return (
    <div className="bulb-sign" aria-label="REEL — recommendations by Arhan">
      <div className="bulb-row" aria-hidden="true">
        {Array.from({ length: 14 }).map((_, i) => (
          <span className="bulb" style={{ "--i": i }} key={i} />
        ))}
      </div>
      <div className="bulb-wordmark">
        <span className="bulb-title">REEL</span>
        <span className="bulb-sub">by arhan</span>
      </div>
      <div className="bulb-row" aria-hidden="true">
        {Array.from({ length: 14 }).map((_, i) => (
          <span className="bulb" style={{ "--i": i }} key={i} />
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: CSS** — add to `index.css`:

```css
.bulb-sign { text-align: center; padding: 20px 0 8px; }
.bulb-row { display: flex; justify-content: center; gap: 10px; }
.bulb {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 6px var(--accent), 0 0 12px var(--accent-dim);
  animation: bulb-flicker 2.4s var(--ease-out-expo) infinite;
  animation-delay: calc(var(--i) * -0.16s);
}
@keyframes bulb-flicker { 0%,100% { opacity: 1; } 45% { opacity: 0.35; } }
.bulb-wordmark { padding: 8px 0; }
.bulb-title {
  font-family: var(--font-display); font-size: clamp(40px, 11vw, 72px);
  letter-spacing: 0.14em; color: var(--ink); line-height: 1;
  text-shadow: 0 0 18px rgba(212,169,74,0.35);
}
.bulb-sub {
  display: block; font-family: var(--font-body); letter-spacing: 0.42em;
  text-transform: uppercase; font-size: 11px; color: var(--muted); margin-top: 6px;
}
@media (prefers-reduced-motion: reduce) { .bulb { animation: none; } }
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/BulbSign.jsx frontend/src/index.css
git commit -m "feat(fe): marquee bulb-sign header (REEL)"
```

## Task 11: App shell — routes + one-line controls

**Files:** Modify `frontend/src/App.jsx`; Modify `frontend/src/index.css`

- [ ] **Step 1: Rewrite App.jsx**

```jsx
import { NavLink, Routes, Route } from "react-router-dom";
import RecommendationsPage from "./RecommendationsPage";
import TasteProfilePage from "./TasteProfilePage";
import BulbSign from "./components/BulbSign";
import UsernameField from "./components/UsernameField";
import RefreshButton from "./components/RefreshButton";
import { useLocalStorage } from "./lib/useLocalStorage";
import { RefreshProvider, useRefresh } from "./context/RefreshContext";

function ControlBar({ username, setUsername }) {
  const { isRunning, cancel, start } = useRefresh();
  return (
    <div className="control-bar">
      <UsernameField value={username} onChange={setUsername} />
      <RefreshButton loading={isRunning} hasData onClick={start} onCancel={cancel} />
    </div>
  );
}

export default function App() {
  const [username, setUsername] = useLocalStorage("letterboxd_username", "");
  return (
    <div className="app">
      <BulbSign />
      <nav className="tabs">
        <NavLink to="/" end className={({ isActive }) => `tab${isActive ? " active" : ""}`}>Recommendations</NavLink>
        <NavLink to="/taste" className={({ isActive }) => `tab${isActive ? " active" : ""}`}>Taste Profile</NavLink>
      </nav>
      <RefreshProvider username={username}>
        <ControlBar username={username} setUsername={setUsername} />
        <div className="page">
          <Routes>
            <Route path="/" element={<RecommendationsPage username={username} />} />
            <Route path="/taste" element={<TasteProfilePage username={username} />} />
          </Routes>
        </div>
      </RefreshProvider>
    </div>
  );
}
```

> Note: `RecommendationsPage` currently owns the refresh trigger via its own `RefreshButton`. Since the button moves to `ControlBar`, remove the header row's `RefreshButton`/`LastUpdated` block from `RecommendationsPage` in Task 13 (keep `LastUpdated` there, above the grid). `onRefresh`'s "enter username first" guard moves into `ControlBar.start` — wrap `start` so it no-ops with an error when `!username` (surface via existing error banner state lifted or a lightweight alert). Keep it minimal.

- [ ] **Step 2: CSS**

```css
.control-bar {
  display: flex; align-items: center; justify-content: space-between;
  gap: 16px; flex-wrap: wrap; margin: 8px 0 40px;
  padding: 14px 16px; border: 1px solid var(--border);
  border-radius: 12px; background: var(--surface);
}
.control-bar .username-field { padding: 0; }
```

- [ ] **Step 3: Verify** → `npm run build` succeeds; `npm run dev` shows header + one-line control bar; `/taste` loads via URL.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/App.jsx frontend/src/index.css
git commit -m "feat(fe): routed shell with one-line username+refresh control bar"
```

---

# Phase 3 — Frontend: recommendations

## Task 12: List partition (pure lib + tests)

**Files:** Create `frontend/src/lib/recList.js`, `frontend/src/lib/recList.test.js`

- [ ] **Step 1: Write failing test**

Create `frontend/src/lib/recList.test.js`:

```js
import { describe, it, expect } from "vitest";
import { partitionRecs } from "./recList";

const mk = (n, pct) => Array.from({ length: n }, (_, i) => ({ tmdb_id: i, match_pct: pct }));

describe("partitionRecs", () => {
  it("hero is the first three", () => {
    const { hero } = partitionRecs(mk(30, 80));
    expect(hero.map((r) => r.tmdb_id)).toEqual([0, 1, 2]);
  });
  it("main holds all >=60% after the hero", () => {
    const recs = [...mk(3, 95), ...mk(10, 72), ...mk(40, 30)];
    const { main, longShots } = partitionRecs(recs);
    expect(main.length).toBe(10);
    expect(longShots.length).toBe(40);
  });
  it("main is padded to at least 20 when few clear the bar", () => {
    const recs = [...mk(3, 95), ...mk(2, 72), ...mk(40, 30)];
    const { main } = partitionRecs(recs);
    expect(main.length).toBe(20);
  });
  it("never exceeds available when total is small", () => {
    const recs = mk(8, 40);
    const { hero, main, longShots } = partitionRecs(recs);
    expect(hero.length + main.length + longShots.length).toBe(8);
    expect(main.length).toBe(5); // 8 - 3 hero, min(20, 5)
  });
});
```

- [ ] **Step 2: Run — expect FAIL** → `cd frontend && npx vitest run src/lib/recList.test.js`.

- [ ] **Step 3: Implement**

Create `frontend/src/lib/recList.js`:

```js
export function partitionRecs(recs, { mainThreshold = 60, minMain = 20 } = {}) {
  const hero = recs.slice(0, 3);
  const rest = recs.slice(3);
  let n = rest.filter((r) => r.match_pct >= mainThreshold).length;
  n = Math.max(n, Math.min(minMain, rest.length));
  return { hero, main: rest.slice(0, n), longShots: rest.slice(n) };
}
```

- [ ] **Step 4: Run — expect PASS** → `npx vitest run src/lib/recList.test.js`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/recList.js frontend/src/lib/recList.test.js
git commit -m "feat(fe): pure list-partition (hero / main >=60% min-20 / long shots)"
```

## Task 13: RecommendationsPage — partition, pagination, expand state

**Files:** Modify `frontend/src/RecommendationsPage.jsx`

- [ ] **Step 1: Rewrite the body** to use `partitionRecs`, a 50-at-a-time long-shots reveal, and lifted expanded-film state. Key structure:

```jsx
import { partitionRecs } from "./lib/recList";
import ExpandedFilmCard from "./components/ExpandedFilmCard";
// ...
const LONG_SHOT_PAGE = 50;
// inside component:
const [selectedFilm, setSelectedFilm] = useState(null);
const { hero, main, longShots } = recs ? partitionRecs(recs) : { hero: [], main: [], longShots: [] };
const [longShown, setLongShown] = useState(0);        // start collapsed
useEffect(() => { setLongShown(0); }, [recs]);
```

Render order: `LastUpdated` (above grid) → `MarqueeTrio recs={hero}` → main `grid` of `RecommendationCard` → `longShots` section: a button `Load long shots (${longShots.length})` that sets `longShown` to 50; once open, render `longShots.slice(0, longShown)` and a `Load 50 more` button while `longShown < longShots.length`.

Replace the old `FilmDetailModal` usage with:

```jsx
{selectedFilm && <ExpandedFilmCard film={selectedFilm} onClose={() => setSelectedFilm(null)} />}
```

Remove the header `RefreshButton` (moved to `ControlBar`); keep the error banner + empty/skeleton states. Keep `onSelect={setSelectedFilm}` on all cards (hero + main + long shots).

- [ ] **Step 2: Verify pagination + partition** with `npm run dev`: at least 20 cards show; long shots reveal 50 per click. (Full E2E in Task 19.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/RecommendationsPage.jsx
git commit -m "feat(fe): partitioned list + 50-at-a-time long shots + expand state"
```

## Task 14: RecommendationCard — tilt, flip, starring, badges

**Files:** Modify `frontend/src/components/RecommendationCard.jsx`; Modify `frontend/src/index.css`

- [ ] **Step 1: Add a rating badge helper** (shared with hero + expanded card). Create `frontend/src/lib/ratingBadge.js`:

```js
// Prefer IMDb, else RT, else TMDB fallback. Returns {label, value} or null.
export function ratingBadge({ imdb_rating, rt_score, vote_avg }) {
  if (imdb_rating != null) return { label: "IMDb", value: imdb_rating.toFixed(1) };
  if (rt_score != null) return { label: "RT", value: `${rt_score}%` };
  if (vote_avg != null) return { label: "TMDB", value: vote_avg.toFixed(1) };
  return null;
}
```

- [ ] **Step 2: Rewrite the card** with a tilt handler and a two-face flip that expands on click:

```jsx
import { useRef, useState } from "react";
import { useCountUp } from "../lib/useCountUp";
import { ratingBadge } from "../lib/ratingBadge";

const IMG = "https://image.tmdb.org/t/p/w300";

export default function RecommendationCard({ rec, index = 0, onSelect }) {
  const match = useCountUp(rec.match_pct);
  const [imgFailed, setImgFailed] = useState(false);
  const ref = useRef(null);
  const badge = ratingBadge(rec);

  const onMove = (e) => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width - 0.5;
    const py = (e.clientY - r.top) / r.height - 0.5;
    el.style.setProperty("--rx", `${(-py * 8).toFixed(2)}deg`);
    el.style.setProperty("--ry", `${(px * 10).toFixed(2)}deg`);
  };
  const onLeave = () => {
    const el = ref.current;
    if (!el) return;
    el.style.setProperty("--rx", "0deg");
    el.style.setProperty("--ry", "0deg");
  };

  return (
    <div
      ref={ref}
      className="card tilt"
      style={{ animationDelay: `${index * 50}ms` }}
      role="button"
      tabIndex={0}
      onMouseMove={onMove}
      onMouseLeave={onLeave}
      onClick={() => onSelect(rec)}
      onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onSelect(rec))}
    >
      <div className="card-inner">
        <div className="card-poster">
          {rec.poster_path && !imgFailed ? (
            <img src={IMG + rec.poster_path} alt={rec.title} loading="lazy" onError={() => setImgFailed(true)} />
          ) : (
            <div className="card-poster-placeholder">No poster</div>
          )}
          {badge && <span className="rating-badge">{badge.label} {badge.value}</span>}
        </div>
        <div className="card-body">
          <h3 className="card-title">{rec.title} <span className="card-meta">({rec.year})</span></h3>
          {rec.starring?.length > 0 && (
            <p className="card-starring">{rec.starring.join(", ")}</p>
          )}
          <div className="card-stats">
            <span className="card-match">{Math.round(match)}% match</span>
            <span className="card-predicted">{rec.predicted_rating?.toFixed(1)}★ predicted</span>
          </div>
        </div>
      </div>
    </div>
  );
}
```

> Design note: the click-to-flip-and-expand is realized by `onSelect` opening `ExpandedFilmCard` (Task 15) as a centered, flipped, shared-element overlay. The in-grid `.tilt` gives the 3D hover; the expand gives the flip. This keeps grid cards light (no per-card flip DOM) while delivering the flip on the expand transition.

- [ ] **Step 3: CSS** — add:

```css
.card { perspective: 900px; }
.card-inner {
  transform: rotateX(var(--rx, 0deg)) rotateY(var(--ry, 0deg));
  transform-style: preserve-3d;
  transition: transform 120ms var(--ease-out-expo);
}
.card:hover { box-shadow: 0 18px 40px -12px rgba(212,169,74,0.35); border-color: var(--accent); }
.card-poster { position: relative; }
.rating-badge {
  position: absolute; top: 8px; left: 8px; font-size: 11px; font-weight: 700;
  padding: 3px 7px; border-radius: 6px; background: rgba(0,0,0,0.72);
  color: var(--accent); backdrop-filter: blur(4px);
}
.card-starring { font-size: 12px; color: var(--muted); margin-top: 4px; line-height: 1.3; }
@media (prefers-reduced-motion: reduce) {
  .card-inner { transform: none !important; transition: none; }
}
```

Remove the now-unused `card-why` block usage from the grid card (why moves to the expanded card). Leave the `.card-why` CSS in place only if still referenced; otherwise delete it.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/RecommendationCard.jsx frontend/src/lib/ratingBadge.js frontend/src/index.css
git commit -m "feat(fe): tilt card + starring line + IMDb/RT/TMDB badge"
```

## Task 15: ExpandedFilmCard — grow-to-center flip detail (replaces modal)

**Files:** Create `frontend/src/components/ExpandedFilmCard.jsx`; Modify `frontend/src/index.css`; Delete `frontend/src/components/FilmDetailModal.jsx`

- [ ] **Step 1: Component** — reuse `getFilmDetail` + `getWatchProviders`, fixed backdrop (no negative margin), scores incl. IMDb/RT, why, overview, genres, providers:

```jsx
import { useEffect, useState } from "react";
import { getFilmDetail, getWatchProviders } from "../api";
import { ratingBadge } from "../lib/ratingBadge";

const BACKDROP = "https://image.tmdb.org/t/p/w780";
const LOGO = "https://image.tmdb.org/t/p/w45";

function ProviderRow({ label, providers }) {
  if (!providers || providers.length === 0) return null;
  return (
    <div className="provider-row">
      <div className="provider-label">{label}</div>
      <div className="provider-logos">
        {providers.map((p) => <img key={p.name} src={LOGO + p.logo_path} alt={p.name} title={p.name} />)}
      </div>
    </div>
  );
}

export default function ExpandedFilmCard({ film, onClose }) {
  const [detail, setDetail] = useState(null);
  const [providers, setProviders] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setDetail(null); setProviders(null); setFailed(false);
    getFilmDetail(film.tmdb_id).then(setDetail).catch(() => {});
    getWatchProviders(film.tmdb_id).then(setProviders).catch(() => setFailed(true));
  }, [film.tmdb_id]);

  useEffect(() => {
    const onKey = (e) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const badge = ratingBadge({ ...film, ...(detail || {}) });
  const hasProviders = providers && (providers.flatrate.length || providers.rent.length || providers.buy.length);

  return (
    <div className="expand-backdrop" onClick={onClose}>
      <div className="expand-card" role="dialog" aria-modal="true" aria-label={`${film.title} details`}
           onClick={(e) => e.stopPropagation()}>
        <button className="expand-close" onClick={onClose} aria-label="Close">×</button>
        {(detail?.backdrop_path || film.backdrop_path) && (
          <div className="expand-hero" style={{ backgroundImage: `url(${BACKDROP}${detail?.backdrop_path || film.backdrop_path})` }} />
        )}
        <div className="expand-body">
          <h3 className="expand-title">{film.title} <span>({film.year})</span></h3>
          {film.starring?.length > 0 && <p className="expand-starring">Starring {film.starring.join(", ")}</p>}
          <div className="expand-stats">
            <span className="expand-match">{Math.round(film.match_pct)}% match</span>
            <span>{film.predicted_rating?.toFixed(1)}★ predicted</span>
            {badge && <span className="expand-rating">{badge.label} {badge.value}</span>}
            {film.rt_score != null && <span className="expand-rating">RT {film.rt_score}%</span>}
          </div>
          {film.why?.neighbors?.length > 0 && (
            <p className="expand-why">
              Because you loved{" "}
              {film.why.neighbors.map((n, i) => (
                <span key={n.title}>{i > 0 && " and "}<b>{n.title}</b> ({n.rating}★)</span>
              ))}
              {film.why.connection ? ` — ${film.why.connection}.` : "."}
            </p>
          )}
          {detail?.runtime && <p className="expand-meta">{detail.runtime} min · {detail.director}</p>}
          {detail?.overview && <p className="expand-overview">{detail.overview}</p>}
          {detail?.genres?.length > 0 && <p className="expand-genres">{detail.genres.join(" · ")}</p>}
          <p className="section-title" style={{ marginTop: 18 }}>Where to watch</p>
          {providers === null && !failed && <p className="modal-loading">Loading…</p>}
          {failed && <p className="modal-loading">Couldn't load streaming info.</p>}
          {providers && !hasProviders && <p className="modal-loading">Not currently available to stream, rent, or buy (US).</p>}
          {providers && hasProviders && (
            <>
              <ProviderRow label="Stream" providers={providers.flatrate} />
              <ProviderRow label="Rent" providers={providers.rent} />
              <ProviderRow label="Buy" providers={providers.buy} />
            </>
          )}
          {providers?.link && <a className="modal-link" href={providers.link} target="_blank" rel="noreferrer">View all options →</a>}
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 2: CSS** — the fix for the black-bar/cutoff + the grow-to-center flip:

```css
.expand-backdrop {
  position: fixed; inset: 0; z-index: var(--z-modal-backdrop);
  background: rgba(0,0,0,0.72); display: flex; align-items: center; justify-content: center;
  padding: 24px; animation: modal-fade-in 200ms var(--ease-out-expo) both;
}
.expand-card {
  position: relative; z-index: var(--z-modal);
  width: min(720px, 100%); max-height: 88vh; overflow-y: auto;
  background: var(--surface); border: 1px solid var(--border); border-radius: 16px;
  transform-origin: center;
  animation: expand-grow 320ms var(--ease-out-expo) both;
}
@keyframes expand-grow {
  from { opacity: 0; transform: rotateY(-12deg) scale(0.86); }
  to { opacity: 1; transform: rotateY(0) scale(1); }
}
.expand-hero {
  height: 240px; background-size: cover; background-position: center;
  border-radius: 16px 16px 0 0;
  -webkit-mask-image: linear-gradient(180deg, #000 55%, transparent);
  mask-image: linear-gradient(180deg, #000 55%, transparent);
}
.expand-body { padding: 0 28px 28px; margin-top: -40px; position: relative; }
.expand-title { font-family: var(--font-display); font-size: 40px; line-height: 1; }
.expand-title span { font-size: 22px; color: var(--muted); }
.expand-starring { color: var(--muted); font-size: 13px; margin-top: 6px; }
.expand-stats { display: flex; gap: 14px; flex-wrap: wrap; align-items: baseline; margin: 14px 0; }
.expand-match { color: var(--accent); font-weight: 700; font-size: 18px; }
.expand-rating { font-size: 13px; color: var(--ink); border: 1px solid var(--border); border-radius: 6px; padding: 2px 8px; }
.expand-why { font-size: 15px; margin-bottom: 12px; }
.expand-meta { color: var(--muted); font-size: 13px; margin-bottom: 10px; }
.expand-overview { font-size: 14px; line-height: 1.55; margin-bottom: 10px; }
.expand-genres { color: var(--muted); font-size: 13px; }
.expand-close {
  position: absolute; top: 14px; right: 14px; z-index: 2; width: 36px; height: 36px;
  border-radius: 50%; border: none; background: rgba(0,0,0,0.6); color: var(--ink);
  font-size: 22px; cursor: pointer;
}
@media (prefers-reduced-motion: reduce) { .expand-card { animation: none; } }
```

- [ ] **Step 3: Delete the old modal + its dead CSS**

```bash
git rm frontend/src/components/FilmDetailModal.jsx
```

Remove `.modal-backdrop-image`, `.modal-meta`, `.modal-why`, `.modal-stats`, `.modal-overview`, `.modal-genres`, `.modal-cast` and the `.film-detail-modal` rules from `index.css` (the `.modal-*` provider/close rules used by nothing else may also go — verify no other references with grep first). Keep `.modal-loading`, `.modal-link`, `.provider-*`, `.section-title` (reused).

Run: `grep -rn "FilmDetailModal\|film-detail-modal\|modal-backdrop-image" frontend/src` → expect no matches.

- [ ] **Step 4: Verify** → `npm run build` + `npm run dev`: clicking any card grows a centered card, backdrop clean (no black bar), scrolls internally, ✕/Esc/backdrop-click close.

- [ ] **Step 5: Commit**

```bash
git add -A frontend/src frontend/src/index.css
git commit -m "feat(fe): expand-to-center film card replaces glitched modal"
```

## Task 16: MarqueeTrio → "Tonight's Feature" + predicted ★

**Files:** Modify `frontend/src/components/MarqueeTrio.jsx`; Modify `frontend/src/index.css`

- [ ] **Step 1: Edit copy + add predicted** — change eyebrow text to `Tonight's Feature`, and in `TrioPanel` add a predicted line beside match:

```jsx
        <div className="trio-match">
          {Math.round(rec.match_pct)}% match · {rec.predicted_rating?.toFixed(1)}★ predicted
        </div>
```

- [ ] **Step 2: Verify** predicted ★ shows on all three hero panels (`npm run dev`).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/MarqueeTrio.jsx frontend/src/index.css
git commit -m "feat(fe): rename hero to Tonight's Feature + show predicted rating"
```

---

# Phase 4 — Frontend: taste profile

## Task 17: Centering, typography, half-star histogram

**Files:** Modify `frontend/src/TasteProfilePage.jsx`; Modify `frontend/src/index.css`

- [ ] **Step 1: Center + enlarge** — in `index.css`:

```css
.taste-dashboard { max-width: 960px; margin: 0 auto; }
.dashboard-eyebrow-row { margin: 28px 0 28px; }
.dashboard-eyebrow { font-size: 30px; letter-spacing: 0.14em; }
.section-title { font-size: 15px; letter-spacing: 0.12em; margin-bottom: 16px; }
.people-wall-section .section-title, .taste-dashboard .section-title { color: var(--ink); }
```

- [ ] **Step 2: Half-star histogram** — the backend already returns 10 buckets (Task 8). Update `RatingHistogram` in `TasteProfilePage.jsx` so labels render half-stars and bars stay legible at 10 wide:

```jsx
function RatingHistogram({ distribution }) {
  const max = Math.max(...distribution.map((b) => b.count), 1);
  return (
    <div className="rating-histogram">
      {distribution.map((b) => (
        <div key={b.star} className="histogram-bar" style={{ height: `${(b.count / max) * 100}%` }}>
          <span>{b.star}</span>
        </div>
      ))}
    </div>
  );
}
```

Add CSS so 10 labels don't collide:

```css
.rating-histogram { gap: 5px; }
.histogram-bar span { font-size: 9px; bottom: -18px; }
```

- [ ] **Step 3: Verify** → `/taste` is horizontally centered; "Your Taste Fingerprint" is large; histogram shows 10 half-star bars.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/TasteProfilePage.jsx frontend/src/index.css
git commit -m "feat(fe): center taste profile, enlarge headers, half-star histogram"
```

## Task 18: Richer GenreRadar + people top-films reveal

**Files:** Modify `frontend/src/components/GenreRadar.jsx`; Create `frontend/src/components/PersonCard.jsx`; Modify `frontend/src/TasteProfilePage.jsx`; Modify `frontend/src/index.css`

- [ ] **Step 1: GenreRadar → 10 axes, rings, gradient fill, hover value**

```jsx
import { useState } from "react";

function pointFor(angle, radius, cx, cy) {
  return [cx + radius * Math.cos(angle), cy + radius * Math.sin(angle)];
}

export default function GenreRadar({ genres }) {
  const top = genres.slice(0, 10);
  const [hover, setHover] = useState(null);
  if (top.length < 3) return null;

  const size = 300, cx = size / 2, cy = size / 2, maxRadius = size / 2 - 40;
  const step = (2 * Math.PI) / top.length;
  const maxAff = Math.max(...top.map((g) => Math.max(g.affinity, 0)), 0.01);
  const pts = top.map((g, i) => {
    const a = -Math.PI / 2 + i * step;
    return pointFor(a, (Math.max(g.affinity, 0) / maxAff) * maxRadius, cx, cy);
  });
  const polygon = pts.map(([x, y]) => `${x},${y}`).join(" ");

  return (
    <svg viewBox={`0 0 ${size} ${size}`} className="genre-radar" role="img" aria-label="Genre affinity radar">
      <defs>
        <radialGradient id="radar-fill">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.45" />
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0.08" />
        </radialGradient>
      </defs>
      {[0.25, 0.5, 0.75, 1].map((f) => (
        <polygon key={f} className="radar-grid"
          points={top.map((_, i) => pointFor(-Math.PI / 2 + i * step, maxRadius * f, cx, cy).join(",")).join(" ")} />
      ))}
      {top.map((_, i) => {
        const [x, y] = pointFor(-Math.PI / 2 + i * step, maxRadius, cx, cy);
        return <line key={i} x1={cx} y1={cy} x2={x} y2={y} className="radar-spoke" />;
      })}
      <polygon points={polygon} className="radar-shape" fill="url(#radar-fill)" />
      {top.map((g, i) => {
        const [px, py] = pts[i];
        const [lx, ly] = pointFor(-Math.PI / 2 + i * step, maxRadius + 18, cx, cy);
        return (
          <g key={g.name}>
            <circle cx={px} cy={py} r={hover === i ? 5 : 3} className="radar-vertex"
              onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} />
            <text x={lx} y={ly} className="radar-label" textAnchor="middle">
              {hover === i ? `${g.name} ${g.affinity.toFixed(2)}` : g.name}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
```

Add CSS:

```css
.genre-radar { width: 100%; max-width: 320px; }
.radar-spoke { stroke: var(--border); stroke-width: 1; opacity: 0.5; }
.radar-vertex { fill: var(--accent); cursor: pointer; }
.radar-label { fill: var(--muted); font-size: 10px; font-family: var(--font-body); }
```

- [ ] **Step 2: PersonCard** with hover (desktop) / tap (mobile) top-films popover:

```jsx
import { useState } from "react";

const FACE = "https://image.tmdb.org/t/p/w185";
const POSTER = "https://image.tmdb.org/t/p/w154";

export default function PersonCard({ person }) {
  const [open, setOpen] = useState(false);
  const films = person.top_films || [];
  return (
    <div className="person-face" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}
         onClick={() => setOpen((o) => !o)}>
      {person.profile_path ? <img src={FACE + person.profile_path} alt={person.name} />
        : <div className="person-face-placeholder">{person.name[0]}</div>}
      <div className="person-name">{person.name}</div>
      {open && films.length > 0 && (
        <div className="person-popover" role="dialog" aria-label={`Top films with ${person.name}`}>
          {films.map((f) => (
            <div className="person-pop-film" key={f.title}>
              {f.poster_path && <img src={POSTER + f.poster_path} alt={f.title} />}
              <div className="person-pop-meta"><b>{f.title}</b><span>{f.rating}★</span></div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

Replace `PeopleWall`'s inline `.person-face` markup in `TasteProfilePage.jsx` with `<PersonCard person={p} key={p.name} />`, and center names (`.people-wall { justify-content: center; }`). Add CSS:

```css
.people-wall { justify-content: center; }
.person-face { position: relative; }
.person-name { text-align: center; }
.person-popover {
  position: absolute; bottom: calc(100% + 8px); left: 50%; transform: translateX(-50%);
  z-index: var(--z-overlay); width: 220px; padding: 10px; border-radius: 10px;
  background: var(--surface-raised); border: 1px solid var(--border);
  box-shadow: 0 16px 40px -12px rgba(0,0,0,0.6);
  display: flex; flex-direction: column; gap: 8px;
}
.person-pop-film { display: flex; gap: 8px; align-items: center; }
.person-pop-film img { width: 34px; border-radius: 4px; }
.person-pop-meta { display: flex; flex-direction: column; font-size: 12px; }
.person-pop-meta span { color: var(--accent); }
```

- [ ] **Step 3: Verify** → radar shows 10 spokes + rings + fill, hover reveals values; hovering a director/actor pops their top-3 films.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/GenreRadar.jsx frontend/src/components/PersonCard.jsx frontend/src/TasteProfilePage.jsx frontend/src/index.css
git commit -m "feat(fe): 10-axis genre radar + person top-films hover reveal"
```

---

# Phase 5 — End-to-end verification (Playwright)

## Task 19: Playwright E2E

**Files:** Create `frontend/playwright.config.js`, `frontend/tests/e2e/app.spec.js`

- [ ] **Step 1: Install** → `cd frontend && npm install -D @playwright/test && npx playwright install chromium`.

- [ ] **Step 2: Config** — create `frontend/playwright.config.js`:

```js
import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests/e2e",
  webServer: { command: "npm run dev", url: "http://localhost:5173", reuseExistingServer: true },
  use: { baseURL: "http://localhost:5173" },
});
```

- [ ] **Step 3: Spec** — create `frontend/tests/e2e/app.spec.js`. Precondition: a backend running with seeded data for a known username (document the seed command in the spec header; reuse the existing local DB the dev has refreshed). Cover:

```js
import { test, expect } from "@playwright/test";

const USER = process.env.E2E_USERNAME || "moviefan";

test.beforeEach(async ({ page }) => {
  await page.addInitScript((u) => localStorage.setItem("letterboxd_username", JSON.stringify(u)), USER);
});

test("header + one-line control bar render", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".bulb-title")).toHaveText("REEL");
  const bar = page.locator(".control-bar");
  await expect(bar.locator(".username-field")).toBeVisible();
  await expect(bar.locator(".refresh-btn")).toBeVisible();
});

test("at least 20 recommendations render and hero shows predicted", async ({ page }) => {
  await page.goto("/");
  await expect(page.locator(".trio-match").first()).toContainText("predicted");
  await expect(page.locator(".card")).toHaveCount(20, { timeout: 15000 }).catch(async () => {
    expect(await page.locator(".card").count()).toBeGreaterThanOrEqual(20);
  });
});

test("clicking a card expands to center; Esc closes", async ({ page }) => {
  await page.goto("/");
  await page.locator(".card").first().click();
  await expect(page.locator(".expand-card")).toBeVisible();
  await expect(page.locator(".expand-hero")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.locator(".expand-card")).toHaveCount(0);
});

test("long shots reveal 50 at a time and open without reload", async ({ page }) => {
  await page.goto("/");
  const toggle = page.locator(".long-shots-toggle");
  if (await toggle.count()) {
    await toggle.click();
    const longCards = page.locator(".long-shots-section .card");
    expect(await longCards.count()).toBeLessThanOrEqual(50);
    await longCards.first().click();
    await expect(page.locator(".expand-card")).toBeVisible();  // regression: opened without reload
  }
});

test("taste profile is its own URL, centered, half-star histogram, 10-axis radar", async ({ page }) => {
  await page.goto("/taste");
  await expect(page).toHaveURL(/\/taste$/);
  await expect(page.locator(".dashboard-eyebrow")).toBeVisible();
  await expect(page.locator(".histogram-bar")).toHaveCount(10);
  await expect(page.locator(".genre-radar .radar-vertex")).toHaveCount(10);
});

test("hovering a director reveals top films", async ({ page }) => {
  await page.goto("/taste");
  await page.locator(".person-face").first().hover();
  await expect(page.locator(".person-popover").first()).toBeVisible();
});
```

- [ ] **Step 4: Run** → `npx playwright test`. Fix any failures (especially the long-shots open-without-reload regression, which is the bug from the spec — if it reproduces, debug with `superpowers:systematic-debugging` before patching).

- [ ] **Step 5: Add script + commit**

Add to `frontend/package.json` scripts: `"e2e": "playwright test"`.

```bash
git add frontend/playwright.config.js frontend/tests/e2e frontend/package.json frontend/package-lock.json
git commit -m "test(fe): Playwright E2E for header, list, expand, taste profile"
```

## Task 20: Full-suite green + manual polish pass

- [ ] **Step 1: Backend** → `cd backend && python -m pytest -q` (all green).
- [ ] **Step 2: Frontend unit** → `cd frontend && npm run test` (all green).
- [ ] **Step 3: Lint** → `cd frontend && npm run lint` (clean).
- [ ] **Step 4: Build** → `cd frontend && npm run build` (succeeds).
- [ ] **Step 5: Playwright** → `npm run e2e` (all green).
- [ ] **Step 6: Manual pass** with `npm run dev` against a live refreshed account: verify tilt feel, expand animation, reduced-motion (toggle OS setting), mobile widths (control bar wraps, radar/popovers fit). Screenshot key screens via Playwright for the record.
- [ ] **Step 7: Commit any polish**

```bash
git add -A
git commit -m "chore: polish pass — motion, responsive, reduced-motion"
```

---

## Self-review — spec coverage map

| Spec requirement | Task |
|---|---|
| Critical-quality score + gate | 1–7 (config, db, tmdb, omdb, scorer, pipeline, api) |
| Match% recalibrated (~90% top, honest) | 5 |
| ≥20 shown even if <70% | 12, 13 |
| Long shots paginated 50 | 13 |
| Predicted ★ on hero | 16 |
| Rename "Tonight's Marquee" → "Tonight's Feature" | 16 |
| Starring on cards | 7, 14 |
| Card tilt/flip/expand, snappy futuristic | 14, 15 |
| Rebuilt detail (black bar, cutoff, back, links, richer) | 15 |
| Long-shot card open-without-reload bug | 13, 19 (regression test) |
| One-line username + refresh | 11 |
| Taste profile own URL | 9, 11 |
| Creative header | 10 |
| Taste profile centered | 17 |
| Half-star histogram | 8, 17 |
| Bigger headers + more gap | 11, 17 |
| More genres + complex radar | 8, 18 |
| People names centered | 18 |
| People hover reveals top-3 films | 8, 18 |

No placeholders remain; type/name consistency checked (`partitionRecs`, `ratingBadge`, `quality_factor`, `_anchor_raw`, `fetch_ratings`, `omdb_fn`, `top_films` used consistently across tasks).
