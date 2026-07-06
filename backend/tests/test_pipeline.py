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
        scrape_fn=lambda user, on_progress=None: scraped,
        enrich_fn=lambda tid, key: meta[tid],
        related_fn=lambda tid, key: [99],  # only liked film (1) yields candidate 99
    )
    run_refresh(conn, cfg, deps)

    recs = conn.execute("SELECT film_id, match_pct FROM recommendations").fetchall()
    ids = {r["film_id"] for r in recs}
    assert 99 in ids            # recommended
    assert 1 not in ids         # already watched, excluded
    assert 2 not in ids         # already watched, excluded

def test_run_refresh_reports_progress_through_stages(tmp_path):
    conn = connect(str(tmp_path / "t.db"))
    init_schema(conn)
    cfg = Config(username="alice", tmdb_api_key="k", db_path="t.db")

    scraped = [{"slug": "parasite", "title": "Parasite", "rating": 5.0, "tmdb_id": 1}]
    meta = {
        1: {"tmdb_id": 1, "title": "Parasite", "year": 2019, "decade": 2010,
            "director": "Bong", "genres": ["Thriller"], "cast": ["Song"],
            "keywords": ["class conflict"], "poster_path": "/p.jpg", "vote_avg": 8.5},
    }
    deps = Deps(
        scrape_fn=lambda user, on_progress=None: scraped,
        enrich_fn=lambda tid, key: meta[tid],
        related_fn=lambda tid, key: [],
    )
    seen_stages = []
    run_refresh(conn, cfg, deps, on_progress=lambda p: seen_stages.append(p["stage"]))

    assert seen_stages[0] == "scraping"
    assert "enriching" in seen_stages
    assert "profiling" in seen_stages
    assert seen_stages[-1] == "done"

def test_run_refresh_includes_person_candidates_when_deps_provided(tmp_path):
    conn = connect(str(tmp_path / "t.db"))
    init_schema(conn)
    cfg = Config(username="alice", tmdb_api_key="k", db_path="t.db")

    scraped = [{"slug": "goodfellas", "title": "Goodfellas", "rating": 5.0, "tmdb_id": 1}]
    meta = {
        1: {"tmdb_id": 1, "title": "Goodfellas", "year": 1990, "decade": 1990,
            "director": "Scorsese", "genres": ["Crime"], "cast": ["De Niro"],
            "keywords": [], "poster_path": "/g.jpg", "vote_avg": 8.7},
        769: {"tmdb_id": 769, "title": "Taxi Driver", "year": 1976, "decade": 1970,
              "director": "Scorsese", "genres": ["Crime"], "cast": ["De Niro"],
              "keywords": [], "poster_path": "/t.jpg", "vote_avg": 8.3},
    }
    deps = Deps(
        scrape_fn=lambda user, on_progress=None: scraped,
        enrich_fn=lambda tid, key: meta[tid],
        related_fn=lambda tid, key: [],  # no similar-movie candidates at all
        person_search_fn=lambda name, key: 1032 if name == "Scorsese" else None,
        person_discover_fn=lambda pid, key: [769],
    )
    run_refresh(conn, cfg, deps)

    recs = conn.execute("SELECT film_id FROM recommendations").fetchall()
    ids = {r["film_id"] for r in recs}
    assert 769 in ids  # surfaced only via the director-based supplemental pool

def test_run_refresh_is_isolated_per_username(tmp_path):
    conn = connect(str(tmp_path / "t.db"))
    init_schema(conn)

    meta = {
        1: {"tmdb_id": 1, "title": "Parasite", "year": 2019, "decade": 2010,
            "director": "Bong", "genres": ["Thriller"], "cast": ["Song"],
            "keywords": [], "poster_path": "/p.jpg", "vote_avg": 8.5},
        2: {"tmdb_id": 2, "title": "Oldboy", "year": 2003, "decade": 2000,
            "director": "Park", "genres": ["Thriller"], "cast": [],
            "keywords": [], "poster_path": "/o.jpg", "vote_avg": 8.0},
        99: {"tmdb_id": 99, "title": "Rec A", "year": 2018, "decade": 2010,
             "director": "Bong", "genres": ["Thriller"], "cast": ["Song"],
             "keywords": [], "poster_path": "/r.jpg", "vote_avg": 7.9},
        100: {"tmdb_id": 100, "title": "Rec B", "year": 2018, "decade": 2010,
              "director": "Park", "genres": ["Thriller"], "cast": [],
              "keywords": [], "poster_path": "/r2.jpg", "vote_avg": 7.9},
    }

    alice_cfg = Config(username="alice", tmdb_api_key="k", db_path="t.db")
    alice_deps = Deps(
        scrape_fn=lambda user, on_progress=None: [
            {"slug": "parasite", "title": "Parasite", "rating": 5.0, "tmdb_id": 1}],
        enrich_fn=lambda tid, key: meta[tid],
        related_fn=lambda tid, key: [99],
    )
    run_refresh(conn, alice_cfg, alice_deps)

    bob_cfg = Config(username="bob", tmdb_api_key="k", db_path="t.db")
    bob_deps = Deps(
        scrape_fn=lambda user, on_progress=None: [
            {"slug": "oldboy", "title": "Oldboy", "rating": 5.0, "tmdb_id": 2}],
        enrich_fn=lambda tid, key: meta[tid],
        related_fn=lambda tid, key: [100],
    )
    run_refresh(conn, bob_cfg, bob_deps)

    alice_recs = {r["film_id"] for r in conn.execute(
        "SELECT film_id FROM recommendations WHERE username='alice'")}
    bob_recs = {r["film_id"] for r in conn.execute(
        "SELECT film_id FROM recommendations WHERE username='bob'")}
    assert alice_recs == {99}
    assert bob_recs == {100}

    alice_watched = {r["film_id"] for r in conn.execute(
        "SELECT film_id FROM watched WHERE username='alice'")}
    bob_watched = {r["film_id"] for r in conn.execute(
        "SELECT film_id FROM watched WHERE username='bob'")}
    assert alice_watched == {1}
    assert bob_watched == {2}
