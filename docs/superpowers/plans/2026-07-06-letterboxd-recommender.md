# Letterboxd Personal Recommender Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Scrape one Letterboxd profile's ratings, enrich with TMDB metadata, and serve ranked film recommendations (predicted ★ + match % + why) to a React UI.

**Architecture:** Python + FastAPI backend runs a linear pipeline (scrape → enrich → profile → candidates → score → cache in SQLite) triggered by one `POST /api/refresh`. React frontend reads cached results via `GET` endpoints. Single-user, local, no auth.

**Tech Stack:** Python 3.11, FastAPI, uvicorn, requests, BeautifulSoup4, numpy, pytest, responses (HTTP mocking); stdlib sqlite3; React + Vite (JS).

---

## File Structure

```
backend/
  app/
    __init__.py
    config.py            # loads username + TMDB key from .env
    db.py                # sqlite connect + schema init
    scraper.py           # Letterboxd scraping + HTML parsing
    tmdb.py              # TMDB API client + enrichment
    profile.py           # taste affinity dicts
    candidates.py        # candidate pool from TMDB similar/recommendations
    scorer.py            # match %, predicted ★, why-tags
    pipeline.py          # orchestrates full refresh
    api.py               # FastAPI app + endpoints
  tests/
    fixtures/
      films_page.html
      film_detail.html
    test_scraper.py
    test_tmdb.py
    test_profile.py
    test_candidates.py
    test_scorer.py
  requirements.txt
  .env.example
frontend/
  (Vite React app — scaffolded in Task 10)
.gitignore
```

Each backend module has one responsibility. `pipeline.py` is the only module that imports several others; everything else is independently testable.

---

## Task 0: Project scaffold

**Files:**
- Create: `.gitignore`, `backend/requirements.txt`, `backend/.env.example`, `backend/app/__init__.py`, `backend/tests/__init__.py`

- [ ] **Step 1: Create `.gitignore`**

```
__pycache__/
*.pyc
.env
*.db
.venv/
node_modules/
dist/
```

- [ ] **Step 2: Create `backend/requirements.txt`**

```
fastapi==0.115.0
uvicorn==0.30.6
requests==2.32.3
beautifulsoup4==4.12.3
numpy==2.1.1
python-dotenv==1.0.1
pytest==8.3.3
responses==0.25.3
httpx==0.27.2
```

- [ ] **Step 3: Create `backend/.env.example`**

```
LETTERBOXD_USERNAME=your_username
TMDB_API_KEY=your_tmdb_v3_key
DB_PATH=letterboxd.db
```

- [ ] **Step 4: Create empty `backend/app/__init__.py` and `backend/tests/__init__.py`**

Both files: empty.

- [ ] **Step 5: Create venv and install**

Run:
```bash
cd backend && python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
```
Expected: installs without error.

- [ ] **Step 6: Commit**

```bash
git add .gitignore backend/requirements.txt backend/.env.example backend/app/__init__.py backend/tests/__init__.py
git commit -m "chore: scaffold backend project"
```

---

## Task 1: Config loader

**Files:**
- Create: `backend/app/config.py`
- Test: `backend/tests/test_config.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_config.py`:
```python
from app.config import load_config

def test_load_config_reads_env(monkeypatch):
    monkeypatch.setenv("LETTERBOXD_USERNAME", "alice")
    monkeypatch.setenv("TMDB_API_KEY", "key123")
    monkeypatch.setenv("DB_PATH", "test.db")
    cfg = load_config()
    assert cfg.username == "alice"
    assert cfg.tmdb_api_key == "key123"
    assert cfg.db_path == "test.db"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.config'`

- [ ] **Step 3: Write minimal implementation**

`backend/app/config.py`:
```python
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Config:
    username: str
    tmdb_api_key: str
    db_path: str

def load_config() -> Config:
    return Config(
        username=os.environ["LETTERBOXD_USERNAME"],
        tmdb_api_key=os.environ["TMDB_API_KEY"],
        db_path=os.environ.get("DB_PATH", "letterboxd.db"),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/config.py backend/tests/test_config.py
git commit -m "feat: config loader from env"
```

---

## Task 2: SQLite storage layer

**Files:**
- Create: `backend/app/db.py`
- Test: `backend/tests/test_db.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_db.py`:
```python
from app.db import connect, init_schema

def test_init_schema_creates_tables(tmp_path):
    db = str(tmp_path / "t.db")
    conn = connect(db)
    init_schema(conn)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert {"films", "film_genres", "film_keywords",
            "film_cast", "ratings", "watched", "recommendations"} <= tables

def test_insert_and_read_rating(tmp_path):
    conn = connect(str(tmp_path / "t.db"))
    init_schema(conn)
    conn.execute("INSERT INTO films (tmdb_id, title, year) VALUES (1, 'X', 2000)")
    conn.execute("INSERT INTO ratings (film_id, your_rating) VALUES (1, 4.5)")
    conn.commit()
    row = conn.execute("SELECT your_rating FROM ratings WHERE film_id=1").fetchone()
    assert row[0] == 4.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.db'`

- [ ] **Step 3: Write minimal implementation**

`backend/app/db.py`:
```python
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS films (
    tmdb_id INTEGER PRIMARY KEY,
    title TEXT, year INTEGER, decade INTEGER,
    director TEXT, poster_path TEXT, tmdb_vote_avg REAL
);
CREATE TABLE IF NOT EXISTS film_genres (film_id INTEGER, genre TEXT);
CREATE TABLE IF NOT EXISTS film_keywords (film_id INTEGER, keyword TEXT);
CREATE TABLE IF NOT EXISTS film_cast (film_id INTEGER, actor TEXT);
CREATE TABLE IF NOT EXISTS ratings (film_id INTEGER PRIMARY KEY, your_rating REAL, watched_date TEXT);
CREATE TABLE IF NOT EXISTS watched (film_id INTEGER PRIMARY KEY);
CREATE TABLE IF NOT EXISTS recommendations (
    film_id INTEGER PRIMARY KEY, match_pct REAL,
    predicted_rating REAL, why_tags TEXT, computed_at TEXT
);
"""

def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_db.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/db.py backend/tests/test_db.py
git commit -m "feat: sqlite schema + storage layer"
```

---

## Task 3: Letterboxd scraper — parse listing page

**Files:**
- Create: `backend/app/scraper.py`, `backend/tests/fixtures/films_page.html`
- Test: `backend/tests/test_scraper.py`

> Note: selectors below target Letterboxd's current markup (`div.film-poster[data-film-slug]`, `span.rating.rated-N` where stars = N/2). During real runs, capture a live page into the fixture to confirm selectors; the test fixture below is self-consistent with the parser.

- [ ] **Step 1: Create fixture `backend/tests/fixtures/films_page.html`**

```html
<html><body>
<ul class="poster-list">
  <li class="poster-container">
    <div class="film-poster" data-film-slug="parasite" data-film-id="426406">
      <img alt="Parasite"/>
    </div>
    <p class="poster-viewingdata">
      <span class="rating rated-10">★★★★★</span>
    </p>
  </li>
  <li class="poster-container">
    <div class="film-poster" data-film-slug="cats" data-film-id="99">
      <img alt="Cats"/>
    </div>
    <p class="poster-viewingdata">
      <span class="rating rated-2">★</span>
    </p>
  </li>
  <li class="poster-container">
    <div class="film-poster" data-film-slug="unrated-film" data-film-id="55">
      <img alt="Unrated Film"/>
    </div>
    <p class="poster-viewingdata"></p>
  </li>
</ul>
<div class="paginate-nextprev"><a class="next" href="/alice/films/page/2/">Next</a></div>
</body></html>
```

- [ ] **Step 2: Write the failing test**

`backend/tests/test_scraper.py`:
```python
from pathlib import Path
from app.scraper import parse_films_page

FIX = Path(__file__).parent / "fixtures"

def test_parse_films_page_extracts_slug_title_rating():
    html = (FIX / "films_page.html").read_text()
    entries = parse_films_page(html)
    by_slug = {e["slug"]: e for e in entries}
    assert by_slug["parasite"]["title"] == "Parasite"
    assert by_slug["parasite"]["rating"] == 5.0
    assert by_slug["cats"]["rating"] == 1.0
    # unrated film present but rating is None
    assert by_slug["unrated-film"]["rating"] is None

def test_parse_films_page_finds_next_page():
    html = (FIX / "films_page.html").read_text()
    assert parse_next_page_url(html) == "/alice/films/page/2/"

from app.scraper import parse_next_page_url  # noqa: E402
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_scraper.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_films_page'`

- [ ] **Step 4: Write minimal implementation**

`backend/app/scraper.py`:
```python
from bs4 import BeautifulSoup

def _rating_from_class(rating_span) -> float | None:
    if rating_span is None:
        return None
    for cls in rating_span.get("class", []):
        if cls.startswith("rated-"):
            return int(cls.split("-")[1]) / 2.0
    return None

def parse_films_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    entries = []
    for li in soup.select("li.poster-container"):
        poster = li.select_one("div.film-poster")
        if poster is None:
            continue
        img = poster.select_one("img")
        entries.append({
            "slug": poster.get("data-film-slug"),
            "title": img.get("alt") if img else None,
            "rating": _rating_from_class(li.select_one("span.rating")),
        })
    return entries

def parse_next_page_url(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    nxt = soup.select_one("div.paginate-nextprev a.next")
    return nxt.get("href") if nxt else None
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_scraper.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/scraper.py backend/tests/test_scraper.py backend/tests/fixtures/films_page.html
git commit -m "feat: parse Letterboxd films listing page"
```

---

## Task 4: Letterboxd scraper — extract TMDB id from film page

**Files:**
- Modify: `backend/app/scraper.py`
- Create: `backend/tests/fixtures/film_detail.html`
- Modify: `backend/tests/test_scraper.py`

> Letterboxd film pages link to TMDB via `a[data-track-action="TMDb"]` with an href like `https://www.themoviedb.org/movie/496243/`. We parse the numeric id from that href.

- [ ] **Step 1: Create fixture `backend/tests/fixtures/film_detail.html`**

```html
<html><body>
<p class="text-link">
  <a href="https://www.themoviedb.org/movie/496243/" data-track-action="TMDb">TMDb</a>
</p>
<small class="number"><a href="/films/year/2019/">2019</a></small>
</body></html>
```

- [ ] **Step 2: Add failing test**

Append to `backend/tests/test_scraper.py`:
```python
from app.scraper import parse_tmdb_id

def test_parse_tmdb_id_from_film_page():
    html = (FIX / "film_detail.html").read_text()
    assert parse_tmdb_id(html) == 496243

def test_parse_tmdb_id_missing_returns_none():
    assert parse_tmdb_id("<html><body>no link</body></html>") is None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_scraper.py -k tmdb_id -v`
Expected: FAIL — `ImportError: cannot import name 'parse_tmdb_id'`

- [ ] **Step 4: Add implementation to `backend/app/scraper.py`**

```python
import re

def parse_tmdb_id(html: str) -> int | None:
    soup = BeautifulSoup(html, "html.parser")
    link = soup.select_one('a[data-track-action="TMDb"]')
    if link is None:
        return None
    m = re.search(r"/movie/(\d+)", link.get("href", ""))
    return int(m.group(1)) if m else None
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_scraper.py -v`
Expected: PASS (all scraper tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/scraper.py backend/tests/test_scraper.py backend/tests/fixtures/film_detail.html
git commit -m "feat: extract TMDB id from Letterboxd film page"
```

---

## Task 5: Letterboxd scraper — fetch orchestration

**Files:**
- Modify: `backend/app/scraper.py`
- Modify: `backend/tests/test_scraper.py`

> Adds `scrape_profile(username, get_html, delay=...)` where `get_html` is an injected fetcher (real one uses `requests`; tests inject a fake). This keeps network out of the unit tests.

- [ ] **Step 1: Add failing test**

Append to `backend/tests/test_scraper.py`:
```python
from app.scraper import scrape_profile

def test_scrape_profile_paginates_and_resolves_tmdb_ids():
    page1 = (FIX / "films_page.html").read_text()
    # page 2 has no films and no next link -> terminates
    page2 = '<html><body><ul class="poster-list"></ul></body></html>'
    detail = (FIX / "film_detail.html").read_text()

    def fake_get(url):
        if url.endswith("/films/") or url.endswith("/films/page/1/"):
            return page1
        if url.endswith("/films/page/2/"):
            return page2
        return detail  # any film page

    films = scrape_profile("alice", fake_get, delay=0)
    rated = {f["slug"]: f for f in films}
    assert rated["parasite"]["tmdb_id"] == 496243
    assert rated["parasite"]["rating"] == 5.0
    # every returned film has a tmdb_id resolved
    assert all(f["tmdb_id"] == 496243 for f in films)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_scraper.py -k scrape_profile -v`
Expected: FAIL — `ImportError: cannot import name 'scrape_profile'`

- [ ] **Step 3: Add implementation to `backend/app/scraper.py`**

```python
import time

BASE = "https://letterboxd.com"

def default_get(url: str) -> str:
    import requests
    resp = requests.get(url, headers={"User-Agent": "personal-recommender"})
    resp.raise_for_status()
    return resp.text

def scrape_profile(username: str, get_html=default_get, delay: float = 1.0) -> list[dict]:
    films = []
    url = f"{BASE}/{username}/films/"
    while url:
        html = get_html(url)
        for entry in parse_films_page(html):
            detail = get_html(f"{BASE}/film/{entry['slug']}/")
            entry["tmdb_id"] = parse_tmdb_id(detail)
            if entry["tmdb_id"] is not None:
                films.append(entry)
            if delay:
                time.sleep(delay)
        nxt = parse_next_page_url(html)
        url = f"{BASE}{nxt}" if nxt else None
    return films
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_scraper.py -v`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add backend/app/scraper.py backend/tests/test_scraper.py
git commit -m "feat: scrape_profile paginates and resolves TMDB ids"
```

---

## Task 6: TMDB enrichment client

**Files:**
- Create: `backend/app/tmdb.py`
- Test: `backend/tests/test_tmdb.py`

> `enrich(tmdb_id, api_key, session)` returns a normalized dict. Tests mock HTTP with the `responses` library.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_tmdb.py`:
```python
import responses
from app.tmdb import enrich

@responses.activate
def test_enrich_normalizes_movie():
    responses.add(
        responses.GET,
        "https://api.themoviedb.org/3/movie/496243",
        json={
            "title": "Parasite", "release_date": "2019-05-30",
            "poster_path": "/p.jpg", "vote_average": 8.5,
            "genres": [{"name": "Thriller"}, {"name": "Comedy"}],
            "credits": {
                "crew": [{"job": "Director", "name": "Bong Joon-ho"}],
                "cast": [{"name": "Song Kang-ho"}, {"name": "Lee Sun-kyun"}],
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
    assert m["genres"] == ["Thriller", "Comedy"]
    assert m["cast"] == ["Song Kang-ho", "Lee Sun-kyun"]
    assert m["keywords"] == ["class conflict"]
    assert m["vote_avg"] == 8.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_tmdb.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.tmdb'`

- [ ] **Step 3: Write minimal implementation**

`backend/app/tmdb.py`:
```python
import requests

API = "https://api.themoviedb.org/3"

def _get(session, url, params):
    s = session or requests
    resp = s.get(url, params=params)
    resp.raise_for_status()
    return resp.json()

def enrich(tmdb_id: int, api_key: str, session=None) -> dict:
    data = _get(session, f"{API}/movie/{tmdb_id}", {
        "api_key": api_key,
        "append_to_response": "credits,keywords",
    })
    year = int(data["release_date"][:4]) if data.get("release_date") else None
    crew = data.get("credits", {}).get("crew", [])
    director = next((c["name"] for c in crew if c.get("job") == "Director"), None)
    cast = [c["name"] for c in data.get("credits", {}).get("cast", [])[:5]]
    keywords = [k["name"] for k in data.get("keywords", {}).get("keywords", [])]
    return {
        "tmdb_id": tmdb_id,
        "title": data.get("title"),
        "year": year,
        "decade": (year // 10) * 10 if year else None,
        "director": director,
        "genres": [g["name"] for g in data.get("genres", [])],
        "cast": cast,
        "keywords": keywords,
        "poster_path": data.get("poster_path"),
        "vote_avg": data.get("vote_average"),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_tmdb.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/tmdb.py backend/tests/test_tmdb.py
git commit -m "feat: TMDB enrichment client"
```

---

## Task 7: TMDB candidate pool (similar + recommendations)

**Files:**
- Modify: `backend/app/tmdb.py`
- Create: `backend/app/candidates.py`
- Test: `backend/tests/test_candidates.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_candidates.py`:
```python
from app.candidates import build_candidate_pool

def test_pool_unions_dedupes_and_excludes_watched():
    # fake fetcher: film 1 -> {10, 11}, film 2 -> {11, 12}
    def fake_related(tmdb_id, api_key):
        return {1: [10, 11], 2: [11, 12]}[tmdb_id]

    watched = {12}
    pool = build_candidate_pool(
        liked_ids=[1, 2], watched_ids=watched,
        api_key="k", related_fn=fake_related,
    )
    assert pool == {10, 11}  # 12 excluded (watched), 11 deduped
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_candidates.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.candidates'`

- [ ] **Step 3: Add `related_ids` to `backend/app/tmdb.py`**

```python
def related_ids(tmdb_id: int, api_key: str, session=None) -> list[int]:
    ids = []
    for endpoint in ("recommendations", "similar"):
        data = _get(session, f"{API}/movie/{tmdb_id}/{endpoint}", {"api_key": api_key})
        ids.extend(r["id"] for r in data.get("results", []))
    return ids
```

- [ ] **Step 4: Write `backend/app/candidates.py`**

```python
from app.tmdb import related_ids

def build_candidate_pool(liked_ids, watched_ids, api_key, related_fn=related_ids) -> set:
    pool = set()
    for fid in liked_ids:
        pool.update(related_fn(fid, api_key))
    return pool - set(watched_ids)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_candidates.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/tmdb.py backend/app/candidates.py backend/tests/test_candidates.py
git commit -m "feat: TMDB candidate pool builder"
```

---

## Task 8: Taste profile (affinity dicts)

**Files:**
- Create: `backend/app/profile.py`
- Test: `backend/tests/test_profile.py`

> A rated film is a dict with `rating` and feature lists (`genres`, `keywords`, `cast`) plus scalar `director`, `decade`. Affinity per value = Σ(rating − 2.5), then each dict normalized by its max absolute value.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_profile.py`:
```python
from app.profile import build_taste_profile

def test_affinity_sums_rating_minus_midpoint_then_normalizes():
    films = [
        {"rating": 4.5, "genres": ["Thriller"], "keywords": [], "cast": [],
         "director": "Bong", "decade": 2010},
        {"rating": 1.0, "genres": ["Thriller"], "keywords": [], "cast": [],
         "director": "Other", "decade": 2000},
    ]
    prof = build_taste_profile(films)
    # Thriller raw = (4.5-2.5) + (1.0-2.5) = 2.0 - 1.5 = 0.5; it's the only genre
    # normalized by max abs (0.5) -> 1.0
    assert prof["genre"]["Thriller"] == 1.0
    # Bong raw = 2.0 (max abs among directors), Other raw = -1.5
    assert prof["director"]["Bong"] == 1.0
    assert round(prof["director"]["Other"], 3) == -0.75
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_profile.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.profile'`

- [ ] **Step 3: Write minimal implementation**

`backend/app/profile.py`:
```python
from collections import defaultdict

MIDPOINT = 2.5

def _normalize(d: dict) -> dict:
    if not d:
        return {}
    m = max(abs(v) for v in d.values()) or 1.0
    return {k: v / m for k, v in d.items()}

def build_taste_profile(films: list[dict]) -> dict:
    raw = {ft: defaultdict(float) for ft in
           ("genre", "director", "actor", "keyword", "decade")}
    for f in films:
        w = f["rating"] - MIDPOINT
        for g in f.get("genres", []):
            raw["genre"][g] += w
        for k in f.get("keywords", []):
            raw["keyword"][k] += w
        for a in f.get("cast", []):
            raw["actor"][a] += w
        if f.get("director"):
            raw["director"][f["director"]] += w
        if f.get("decade") is not None:
            raw["decade"][f["decade"]] += w
    return {ft: _normalize(dict(d)) for ft, d in raw.items()}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_profile.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/profile.py backend/tests/test_profile.py
git commit -m "feat: taste profile affinity builder"
```

---

## Task 9: Scorer (match %, predicted ★, why-tags)

**Files:**
- Create: `backend/app/scorer.py`
- Test: `backend/tests/test_scorer.py`

> Match raw score = weighted sum of candidate feature affinities (genre .25, keyword .25, director .20, actor .20, decade .10). Match % = min-max over the pool → 0–100. Predicted ★ = k-NN cosine over a genre+keyword one-hot vector vs rated films, similarity-weighted average rating. Why-tags = top contributing feature values.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_scorer.py`:
```python
import math
from app.scorer import match_raw_score, predict_rating, why_tags, score_candidates

PROFILE = {
    "genre": {"Thriller": 1.0, "Comedy": 0.5},
    "keyword": {"class conflict": 1.0},
    "director": {"Bong Joon-ho": 1.0},
    "actor": {"Song Kang-ho": 1.0},
    "decade": {2010: 1.0},
}

CAND = {
    "tmdb_id": 999, "genres": ["Thriller"], "keywords": ["class conflict"],
    "director": "Bong Joon-ho", "cast": ["Song Kang-ho"], "decade": 2010,
}

def test_match_raw_score_weighted_sum():
    # .25*1 + .25*1 + .20*1 + .20*1 + .10*1 = 1.0
    assert round(match_raw_score(CAND, PROFILE), 4) == 1.0

def test_match_raw_score_partial():
    weak = {"tmdb_id": 1, "genres": ["Comedy"], "keywords": [],
            "director": "X", "cast": [], "decade": 1990}
    # only genre contributes: .25 * 0.5 = 0.125
    assert round(match_raw_score(weak, PROFILE), 4) == 0.125

def test_predict_rating_knn_weighted_average():
    rated = [
        {"rating": 5.0, "genres": ["Thriller"], "keywords": ["class conflict"]},
        {"rating": 2.0, "genres": ["Romance"], "keywords": []},
    ]
    pred = predict_rating(CAND, rated, k=2)
    # candidate is identical to first film, orthogonal to second -> ~5.0
    assert pred > 4.5

def test_why_tags_returns_top_features():
    tags = why_tags(CAND, PROFILE, n=2)
    assert len(tags) == 2
    assert "Bong Joon-ho" in tags or "Thriller" in tags

def test_score_candidates_normalizes_and_ranks():
    cands = [CAND, {"tmdb_id": 2, "genres": ["Comedy"], "keywords": [],
                    "director": "X", "cast": [], "decade": 1990}]
    rated = [{"rating": 5.0, "genres": ["Thriller"], "keywords": ["class conflict"]}]
    results = score_candidates(cands, PROFILE, rated, k=1)
    assert results[0]["tmdb_id"] == 999          # ranked first
    assert results[0]["match_pct"] == 100.0       # top of pool
    assert results[-1]["match_pct"] == 0.0        # bottom of pool
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_scorer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.scorer'`

- [ ] **Step 3: Write minimal implementation**

`backend/app/scorer.py`:
```python
import numpy as np

WEIGHTS = {"genre": 0.25, "keyword": 0.25, "director": 0.20,
           "actor": 0.20, "decade": 0.10}

def _contributions(cand: dict, profile: dict) -> list[tuple[str, float]]:
    out = []
    for g in cand.get("genres", []):
        out.append((g, WEIGHTS["genre"] * profile["genre"].get(g, 0.0)))
    for k in cand.get("keywords", []):
        out.append((k, WEIGHTS["keyword"] * profile["keyword"].get(k, 0.0)))
    if cand.get("director"):
        out.append((cand["director"],
                    WEIGHTS["director"] * profile["director"].get(cand["director"], 0.0)))
    for a in cand.get("cast", []):
        out.append((a, WEIGHTS["actor"] * profile["actor"].get(a, 0.0)))
    if cand.get("decade") is not None:
        out.append((str(cand["decade"]),
                    WEIGHTS["decade"] * profile["decade"].get(cand["decade"], 0.0)))
    return out

def match_raw_score(cand: dict, profile: dict) -> float:
    return sum(v for _, v in _contributions(cand, profile))

def why_tags(cand: dict, profile: dict, n: int = 3) -> list[str]:
    contrib = sorted(_contributions(cand, profile), key=lambda x: x[1], reverse=True)
    return [name for name, val in contrib if val > 0][:n]

def _feature_vector(film: dict, vocab: list[str]) -> np.ndarray:
    tokens = set(film.get("genres", [])) | set(film.get("keywords", []))
    return np.array([1.0 if t in tokens else 0.0 for t in vocab])

def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))

def predict_rating(cand: dict, rated: list[dict], k: int = 10) -> float:
    vocab = sorted({t for f in rated + [cand]
                    for t in set(f.get("genres", [])) | set(f.get("keywords", []))})
    cv = _feature_vector(cand, vocab)
    sims = [(_cosine(cv, _feature_vector(f, vocab)), f["rating"]) for f in rated]
    sims = [s for s in sims if s[0] > 0]
    sims.sort(reverse=True)
    top = sims[:k]
    if not top:
        return float(np.mean([f["rating"] for f in rated])) if rated else 0.0
    wsum = sum(w for w, _ in top)
    return sum(w * r for w, r in top) / wsum

def score_candidates(cands, profile, rated, k: int = 10) -> list[dict]:
    raws = [(c, match_raw_score(c, profile)) for c in cands]
    vals = [r for _, r in raws]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    results = []
    for c, raw in raws:
        results.append({
            "tmdb_id": c["tmdb_id"],
            "match_pct": round((raw - lo) / span * 100.0, 1),
            "predicted_rating": round(predict_rating(c, rated, k), 2),
            "why_tags": why_tags(c, profile),
        })
    results.sort(key=lambda r: r["match_pct"], reverse=True)
    return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_scorer.py -v`
Expected: PASS (all 5)

- [ ] **Step 5: Commit**

```bash
git add backend/app/scorer.py backend/tests/test_scorer.py
git commit -m "feat: scorer with match %, predicted rating, why-tags"
```

---

## Task 10: Pipeline orchestration + persistence

**Files:**
- Create: `backend/app/pipeline.py`
- Test: `backend/tests/test_pipeline.py`

> `run_refresh(conn, cfg, deps)` wires the modules. `deps` bundles injectable functions (`scrape_fn`, `enrich_fn`, `related_fn`) so the test runs fully offline. Persists films/ratings/watched/recommendations to SQLite. `LIKED_THRESHOLD=4.0`; if fewer than 3 liked films, fall back to 3.5.

- [ ] **Step 1: Write the failing test**

`backend/tests/test_pipeline.py`:
```python
from app.db import connect, init_schema
from app.pipeline import run_refresh, Deps
from app.config import Config

def test_run_refresh_persists_recommendations(tmp_path):
    conn = connect(str(tmp_path / "t.db"))
    init_schema(conn)
    cfg = Config(username="alice", tmdb_api_key="k", db_path="t.db")

    scraped = [
        {"slug": "parasite", "title": "Parasite", "rating": 5.0, "tmdb_id": 1},
        {"slug": "meh", "title": "Meh", "rating": 1.0, "tmdb_id": 2},
    ]
    meta = {
        1: {"tmdb_id": 1, "title": "Parasite", "year": 2019, "decade": 2010,
            "director": "Bong", "genres": ["Thriller"], "cast": ["Song"],
            "keywords": ["class conflict"], "poster_path": "/p.jpg", "vote_avg": 8.5},
        2: {"tmdb_id": 2, "title": "Meh", "year": 1990, "decade": 1990,
            "director": "X", "genres": ["Comedy"], "cast": [], "keywords": [],
            "poster_path": None, "vote_avg": 5.0},
        99: {"tmdb_id": 99, "title": "Rec", "year": 2018, "decade": 2010,
             "director": "Bong", "genres": ["Thriller"], "cast": ["Song"],
             "keywords": ["class conflict"], "poster_path": "/r.jpg", "vote_avg": 7.9},
    }
    deps = Deps(
        scrape_fn=lambda user: scraped,
        enrich_fn=lambda tid, key: meta[tid],
        related_fn=lambda tid, key: [99],  # only liked film (1) yields candidate 99
    )
    run_refresh(conn, cfg, deps)

    recs = conn.execute("SELECT film_id, match_pct FROM recommendations").fetchall()
    ids = {r["film_id"] for r in recs}
    assert 99 in ids            # recommended
    assert 1 not in ids         # already watched, excluded
    assert 2 not in ids         # already watched, excluded
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.pipeline'`

- [ ] **Step 3: Write minimal implementation**

`backend/app/pipeline.py`:
```python
import json
from dataclasses import dataclass
from datetime import datetime, timezone

from app.candidates import build_candidate_pool
from app.profile import build_taste_profile
from app.scorer import score_candidates

LIKED_THRESHOLD = 4.0
FALLBACK_THRESHOLD = 3.5

@dataclass
class Deps:
    scrape_fn: callable   # (username) -> list[{slug,title,rating,tmdb_id}]
    enrich_fn: callable   # (tmdb_id, api_key) -> metadata dict
    related_fn: callable  # (tmdb_id, api_key) -> list[int]

def _liked_ids(rated_meta):
    liked = [m["tmdb_id"] for m in rated_meta if m["rating"] >= LIKED_THRESHOLD]
    if len(liked) < 3:
        liked = [m["tmdb_id"] for m in rated_meta if m["rating"] >= FALLBACK_THRESHOLD]
    return liked

def _persist_film(conn, m):
    conn.execute(
        "INSERT OR REPLACE INTO films (tmdb_id,title,year,decade,director,poster_path,tmdb_vote_avg)"
        " VALUES (?,?,?,?,?,?,?)",
        (m["tmdb_id"], m["title"], m["year"], m["decade"], m["director"],
         m["poster_path"], m["vote_avg"]))
    conn.execute("DELETE FROM film_genres WHERE film_id=?", (m["tmdb_id"],))
    conn.execute("DELETE FROM film_keywords WHERE film_id=?", (m["tmdb_id"],))
    conn.execute("DELETE FROM film_cast WHERE film_id=?", (m["tmdb_id"],))
    conn.executemany("INSERT INTO film_genres VALUES (?,?)",
                     [(m["tmdb_id"], g) for g in m["genres"]])
    conn.executemany("INSERT INTO film_keywords VALUES (?,?)",
                     [(m["tmdb_id"], k) for k in m["keywords"]])
    conn.executemany("INSERT INTO film_cast VALUES (?,?)",
                     [(m["tmdb_id"], a) for a in m["cast"]])

def run_refresh(conn, cfg, deps: Deps) -> None:
    scraped = deps.scrape_fn(cfg.username)

    rated_meta = []
    conn.execute("DELETE FROM ratings")
    conn.execute("DELETE FROM watched")
    for f in scraped:
        m = deps.enrich_fn(f["tmdb_id"], cfg.tmdb_api_key)
        _persist_film(conn, m)
        conn.execute("INSERT OR REPLACE INTO watched VALUES (?)", (f["tmdb_id"],))
        if f["rating"] is not None:
            conn.execute("INSERT OR REPLACE INTO ratings (film_id,your_rating) VALUES (?,?)",
                         (f["tmdb_id"], f["rating"]))
            rm = dict(m); rm["rating"] = f["rating"]
            rated_meta.append(rm)

    profile = build_taste_profile(rated_meta)
    watched_ids = {f["tmdb_id"] for f in scraped}
    pool = build_candidate_pool(_liked_ids(rated_meta), watched_ids,
                                cfg.tmdb_api_key, related_fn=deps.related_fn)

    cand_meta = [deps.enrich_fn(cid, cfg.tmdb_api_key) for cid in pool]
    for m in cand_meta:
        _persist_film(conn, m)

    results = score_candidates(cand_meta, profile, rated_meta)

    now = datetime.now(timezone.utc).isoformat()
    conn.execute("DELETE FROM recommendations")
    for r in results:
        conn.execute(
            "INSERT INTO recommendations (film_id,match_pct,predicted_rating,why_tags,computed_at)"
            " VALUES (?,?,?,?,?)",
            (r["tmdb_id"], r["match_pct"], r["predicted_rating"],
             json.dumps(r["why_tags"]), now))
    conn.commit()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_pipeline.py -v`
Expected: PASS

- [ ] **Step 5: Run full backend suite**

Run: `cd backend && .venv/bin/python -m pytest -v`
Expected: PASS (all tests across all modules)

- [ ] **Step 6: Commit**

```bash
git add backend/app/pipeline.py backend/tests/test_pipeline.py
git commit -m "feat: refresh pipeline orchestration + persistence"
```

---

## Task 11: FastAPI endpoints

**Files:**
- Create: `backend/app/api.py`
- Test: `backend/tests/test_api.py`

- [ ] **Step 1: Write the failing test**

`backend/tests/test_api.py`:
```python
import json
from fastapi.testclient import TestClient
from app.api import create_app
from app.db import connect, init_schema

def _seed(conn):
    conn.execute("INSERT INTO films (tmdb_id,title,year,poster_path) VALUES (99,'Rec',2018,'/r.jpg')")
    conn.execute("INSERT INTO film_genres VALUES (99,'Thriller')")
    conn.execute("INSERT INTO recommendations VALUES (99, 92.0, 4.3, ?, 'now')",
                 (json.dumps(["Thriller", "Bong"]),))
    conn.execute("INSERT INTO ratings (film_id,your_rating) VALUES (99,0)")  # unused row
    conn.commit()

def test_get_recommendations_returns_cards(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn); _seed(conn)
    app = create_app(conn_factory=lambda: conn, refresh_fn=lambda conn: None)
    client = TestClient(app)
    resp = client.get("/api/recommendations")
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["title"] == "Rec"
    assert body[0]["match_pct"] == 92.0
    assert body[0]["predicted_rating"] == 4.3
    assert body[0]["why_tags"] == ["Thriller", "Bong"]
    assert body[0]["poster_path"] == "/r.jpg"

def test_post_refresh_invokes_refresh_fn(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn)
    called = {"n": 0}
    def fake_refresh(c):
        called["n"] += 1
    app = create_app(conn_factory=lambda: conn, refresh_fn=fake_refresh)
    client = TestClient(app)
    resp = client.post("/api/refresh")
    assert resp.status_code == 200
    assert called["n"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && .venv/bin/python -m pytest tests/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.api'`

- [ ] **Step 3: Write minimal implementation**

`backend/app/api.py`:
```python
import json
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import load_config
from app.db import connect, init_schema
from app.pipeline import run_refresh, Deps
from app.scraper import scrape_profile
from app.tmdb import enrich, related_ids

def _real_refresh(conn):
    cfg = load_config()
    deps = Deps(
        scrape_fn=lambda user: scrape_profile(user),
        enrich_fn=lambda tid, key: enrich(tid, key),
        related_fn=lambda tid, key: related_ids(tid, key),
    )
    run_refresh(conn, cfg, deps)

def create_app(conn_factory=None, refresh_fn=_real_refresh) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware, allow_origins=["http://localhost:5173"],
        allow_methods=["*"], allow_headers=["*"])

    def get_conn():
        if conn_factory:
            return conn_factory()
        cfg = load_config()
        conn = connect(cfg.db_path)
        init_schema(conn)
        return conn

    @app.get("/api/recommendations")
    def recommendations():
        conn = get_conn()
        rows = conn.execute(
            "SELECT f.tmdb_id, f.title, f.year, f.poster_path,"
            " r.match_pct, r.predicted_rating, r.why_tags"
            " FROM recommendations r JOIN films f ON f.tmdb_id = r.film_id"
            " ORDER BY r.match_pct DESC").fetchall()
        return [{
            "tmdb_id": r["tmdb_id"], "title": r["title"], "year": r["year"],
            "poster_path": r["poster_path"], "match_pct": r["match_pct"],
            "predicted_rating": r["predicted_rating"],
            "why_tags": json.loads(r["why_tags"]),
        } for r in rows]

    @app.get("/api/taste-profile")
    def taste_profile():
        conn = get_conn()
        def top(table, col):
            rows = conn.execute(
                f"SELECT {col} v, COUNT(*) c FROM {table}"
                f" JOIN ratings ra ON ra.film_id = {table}.film_id"
                f" GROUP BY {col} ORDER BY c DESC LIMIT 10").fetchall()
            return [{"name": str(r["v"]), "count": r["c"]} for r in rows]
        return {
            "genres": top("film_genres", "genre"),
            "actors": top("film_cast", "actor"),
        }

    @app.post("/api/refresh")
    def refresh():
        conn = get_conn()
        refresh_fn(conn)
        return {"status": "ok"}

    return app

app = create_app()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && .venv/bin/python -m pytest tests/test_api.py -v`
Expected: PASS (both)

- [ ] **Step 5: Manual smoke — start server**

Run: `cd backend && .venv/bin/uvicorn app.api:app --reload`
Expected: server boots on `http://127.0.0.1:8000`; visit `/docs`, confirm three endpoints listed. Stop with Ctrl-C.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api.py backend/tests/test_api.py
git commit -m "feat: FastAPI endpoints for recs, taste profile, refresh"
```

---

## Task 12: Frontend scaffold + API client

**Files:**
- Create: `frontend/` (Vite React), `frontend/src/api.js`

- [ ] **Step 1: Scaffold Vite React app**

Run:
```bash
cd ~/letterboxd-recommenation && npm create vite@latest frontend -- --template react
cd frontend && npm install
```
Expected: `frontend/` created with React template; deps installed.

- [ ] **Step 2: Create `frontend/src/api.js`**

```javascript
const BASE = "http://127.0.0.1:8000";

export async function getRecommendations() {
  const r = await fetch(`${BASE}/api/recommendations`);
  return r.json();
}

export async function getTasteProfile() {
  const r = await fetch(`${BASE}/api/taste-profile`);
  return r.json();
}

export async function refresh() {
  const r = await fetch(`${BASE}/api/refresh`, { method: "POST" });
  return r.json();
}
```

- [ ] **Step 3: Verify dev server boots**

Run: `cd frontend && npm run dev`
Expected: Vite serves on `http://localhost:5173`. Stop with Ctrl-C.

- [ ] **Step 4: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/index.html frontend/vite.config.js frontend/src/api.js
git commit -m "chore: scaffold Vite React frontend + API client"
```

---

## Task 13: Recommendations page

**Files:**
- Create: `frontend/src/RecommendationsPage.jsx`
- Modify: `frontend/src/App.jsx`

> TMDB posters load from `https://image.tmdb.org/t/p/w200{poster_path}`.

- [ ] **Step 1: Create `frontend/src/RecommendationsPage.jsx`**

```jsx
import { useEffect, useState } from "react";
import { getRecommendations, refresh } from "./api";

const IMG = "https://image.tmdb.org/t/p/w200";

export default function RecommendationsPage() {
  const [recs, setRecs] = useState([]);
  const [loading, setLoading] = useState(false);

  const load = () => getRecommendations().then(setRecs);
  useEffect(() => { load(); }, []);

  const onRefresh = async () => {
    setLoading(true);
    await refresh();
    await load();
    setLoading(false);
  };

  return (
    <div>
      <button onClick={onRefresh} disabled={loading}>
        {loading ? "Refreshing…" : "Refresh my data"}
      </button>
      <div className="rec-grid">
        {recs.map((r) => (
          <div key={r.tmdb_id} className="rec-card">
            {r.poster_path && <img src={IMG + r.poster_path} alt={r.title} />}
            <h3>{r.title} ({r.year})</h3>
            <p>{r.predicted_rating}★ predicted · {r.match_pct}% match</p>
            <p className="why">Because you like: {r.why_tags.join(", ")}</p>
          </div>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Wire into `frontend/src/App.jsx`**

Replace file contents:
```jsx
import { useState } from "react";
import RecommendationsPage from "./RecommendationsPage";
import TasteProfilePage from "./TasteProfilePage";

export default function App() {
  const [tab, setTab] = useState("recs");
  return (
    <div>
      <nav>
        <button onClick={() => setTab("recs")}>Recommendations</button>
        <button onClick={() => setTab("taste")}>Taste Profile</button>
      </nav>
      {tab === "recs" ? <RecommendationsPage /> : <TasteProfilePage />}
    </div>
  );
}
```

> `TasteProfilePage` is created in Task 14; the import will error until then — build it next before running.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/RecommendationsPage.jsx frontend/src/App.jsx
git commit -m "feat: recommendations page + refresh button"
```

---

## Task 14: Taste Profile page

**Files:**
- Create: `frontend/src/TasteProfilePage.jsx`

- [ ] **Step 1: Create `frontend/src/TasteProfilePage.jsx`**

```jsx
import { useEffect, useState } from "react";
import { getTasteProfile } from "./api";

function Bars({ title, items }) {
  const max = Math.max(1, ...items.map((i) => i.count));
  return (
    <div>
      <h2>{title}</h2>
      {items.map((i) => (
        <div key={i.name} className="bar-row">
          <span className="bar-label">{i.name}</span>
          <span className="bar" style={{ width: `${(i.count / max) * 100}%` }} />
          <span className="bar-count">{i.count}</span>
        </div>
      ))}
    </div>
  );
}

export default function TasteProfilePage() {
  const [profile, setProfile] = useState({ genres: [], actors: [] });
  useEffect(() => { getTasteProfile().then(setProfile); }, []);
  return (
    <div>
      <Bars title="Top Genres" items={profile.genres} />
      <Bars title="Top Actors" items={profile.actors} />
    </div>
  );
}
```

- [ ] **Step 2: Run both servers + manual end-to-end check**

Run backend: `cd backend && .venv/bin/uvicorn app.api:app --reload`
Run frontend (new terminal): `cd frontend && npm run dev`
Open `http://localhost:5173`. With a real `.env` (your username + TMDB key), click "Refresh my data", wait for scrape+score, confirm recommendation cards render with posters/scores and the Taste Profile tab shows genre/actor bars.
Expected: recommendations appear; no console errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/TasteProfilePage.jsx
git commit -m "feat: taste profile page"
```

---

## Task 15: README + run instructions

**Files:**
- Create: `README.md`

- [ ] **Step 1: Create `README.md`**

````markdown
# Letterboxd Personal Recommender

Scrapes one public Letterboxd profile, enriches with TMDB, and recommends unwatched films with predicted ★ + match %.

## Setup

1. Backend:
   ```bash
   cd backend
   python3.11 -m venv .venv && .venv/bin/pip install -r requirements.txt
   cp .env.example .env   # fill in LETTERBOXD_USERNAME + TMDB_API_KEY
   ```
   Get a free TMDB v3 API key at https://www.themoviedb.org/settings/api

2. Frontend:
   ```bash
   cd frontend && npm install
   ```

## Run

- Backend: `cd backend && .venv/bin/uvicorn app.api:app --reload`
- Frontend: `cd frontend && npm run dev`
- Open http://localhost:5173 and click "Refresh my data".

## Test

```bash
cd backend && .venv/bin/python -m pytest -v
```
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: setup and run instructions"
```

---

## Self-Review Notes

- **Spec coverage:** scraper (Tasks 3-5), TMDB id extraction (Task 4), enrichment+cache (Task 6, `INSERT OR REPLACE` + candidate reuse), affinity profile (Task 8), hybrid candidate pool (Task 7), match %/predicted ★/why-tags (Task 9), exclusion of watched (Tasks 7 & 10), ≥4★ threshold + 3.5 fallback (Task 10), SQLite schema (Task 2), three endpoints (Task 11), recs page + taste profile + refresh button (Tasks 13-14). All spec sections mapped.
- **Injectable deps** (`get_html`, `session`, `related_fn`, `enrich_fn`, `scrape_fn`, `conn_factory`, `refresh_fn`) keep every unit test offline; real network only in manual smoke steps.
- **Naming consistency:** metadata dict keys (`tmdb_id`, `genres`, `keywords`, `cast`, `director`, `decade`, `rating`, `vote_avg`, `poster_path`) are identical across enrich → profile → scorer → pipeline.
- **Known limitation:** match % is pool-relative (top of a given run = 100%), as specified. Selectors in Tasks 3-4 target current Letterboxd markup; if the live site differs, update the fixture from a real capture and the parser follows.
