import pytest

from app.db import connect, init_schema
from app.pipeline import run_refresh, Deps
from app.config import Config

def test_run_refresh_persists_recommendations(tmp_path):
    conn = connect(TEST_DSN)
    init_schema(conn)
    cfg = Config(username="alice", tmdb_api_key="k", database_url="postgresql:///unused")

    scraped = [
        {"slug": "parasite", "title": "Parasite", "rating": 5.0, "tmdb_id": 1},
        {"slug": "meh", "title": "Meh", "rating": 1.0, "tmdb_id": 2},
    ]
    meta = {
        1: {"tmdb_id": 1, "title": "Parasite", "year": 2019, "decade": 2010,
            "director": "Bong", "genres": ["Thriller"], "cast": ["Song"],
            "keywords": ["class conflict"], "poster_path": "/p.jpg", "vote_avg": 8.5,
            "director_id": 1001, "director_person": {"person_id": 1001, "name": "Bong", "profile_path": "/bong.jpg"},
            "cast_people": [{"person_id": 2001, "name": "Song", "profile_path": "/song.jpg"}],
            "backdrop_path": "/p_bd.jpg", "overview": "A poor family schemes.", "runtime": 132},
        2: {"tmdb_id": 2, "title": "Meh", "year": 1990, "decade": 1990,
            "director": "X", "genres": ["Comedy"], "cast": [], "keywords": [],
            "poster_path": None, "vote_avg": 5.0,
            "director_id": 1002, "director_person": {"person_id": 1002, "name": "X", "profile_path": None},
            "cast_people": [], "backdrop_path": None, "overview": "", "runtime": None},
        99: {"tmdb_id": 99, "title": "Rec", "year": 2018, "decade": 2010,
             "director": "Bong", "genres": ["Thriller"], "cast": ["Song"],
             "keywords": ["class conflict"], "poster_path": "/r.jpg", "vote_avg": 7.9,
             "director_id": 1001, "director_person": {"person_id": 1001, "name": "Bong", "profile_path": "/bong.jpg"},
             "cast_people": [{"person_id": 2001, "name": "Song", "profile_path": "/song.jpg"}],
             "backdrop_path": "/r_bd.jpg", "overview": "A recommended film.", "runtime": 118},
    }
    deps = Deps(
        load_films_fn=lambda user: scraped,
        enrich_fn=lambda tid, key: meta[tid],
        related_fn=lambda tid, key: [99],  # only liked film (1) yields candidate 99
    )
    run_refresh(conn, cfg, deps)

    recs = conn.execute("SELECT film_id, match_pct FROM recommendations").fetchall()
    ids = {r["film_id"] for r in recs}
    assert 99 in ids            # recommended
    assert 1 not in ids         # already watched, excluded
    assert 2 not in ids         # already watched, excluded

def test_run_refresh_stores_omdb_ratings_for_top_results(tmp_path):
    conn = connect(TEST_DSN)
    init_schema(conn)
    cfg = Config(username="alice", tmdb_api_key="k", database_url="postgresql:///unused")

    scraped = [{"slug": "parasite", "title": "Parasite", "rating": 5.0, "tmdb_id": 1}]
    meta = {
        1: {"tmdb_id": 1, "title": "Parasite", "year": 2019, "decade": 2010,
            "director": "Bong", "genres": ["Thriller"], "cast": ["Song"],
            "keywords": ["class conflict"], "poster_path": "/p.jpg", "vote_avg": 8.5,
            "director_id": 1001, "director_person": {"person_id": 1001, "name": "Bong", "profile_path": "/bong.jpg"},
            "cast_people": [{"person_id": 2001, "name": "Song", "profile_path": "/song.jpg"}],
            "backdrop_path": "/p_bd.jpg", "overview": "A poor family schemes.", "runtime": 132},
        99: {"tmdb_id": 99, "title": "Rec", "year": 2018, "decade": 2010,
             "director": "Bong", "genres": ["Thriller"], "cast": ["Song"],
             "keywords": ["class conflict"], "poster_path": "/r.jpg", "vote_avg": 7.9,
             "imdb_id": "tt0111161",
             "director_id": 1001, "director_person": {"person_id": 1001, "name": "Bong", "profile_path": "/bong.jpg"},
             "cast_people": [{"person_id": 2001, "name": "Song", "profile_path": "/song.jpg"}],
             "backdrop_path": "/r_bd.jpg", "overview": "A recommended film.", "runtime": 118},
    }
    deps = Deps(
        load_films_fn=lambda user: scraped,
        enrich_fn=lambda tid, key: meta[tid],
        related_fn=lambda tid, key: [99],
        omdb_fn=lambda imdb_id: {"imdb_rating": 8.0, "rt_score": 90},
    )
    run_refresh(conn, cfg, deps)

    row = conn.execute(
        "SELECT imdb_rating, rt_score FROM films WHERE imdb_rating IS NOT NULL LIMIT 1").fetchone()
    assert row["imdb_rating"] == 8.0 and row["rt_score"] == 90

def test_run_refresh_reports_progress_through_stages(tmp_path):
    conn = connect(TEST_DSN)
    init_schema(conn)
    cfg = Config(username="alice", tmdb_api_key="k", database_url="postgresql:///unused")

    scraped = [{"slug": "parasite", "title": "Parasite", "rating": 5.0, "tmdb_id": 1}]
    meta = {
        1: {"tmdb_id": 1, "title": "Parasite", "year": 2019, "decade": 2010,
            "director": "Bong", "genres": ["Thriller"], "cast": ["Song"],
            "keywords": ["class conflict"], "poster_path": "/p.jpg", "vote_avg": 8.5,
            "director_id": 1001, "director_person": {"person_id": 1001, "name": "Bong", "profile_path": "/bong.jpg"},
            "cast_people": [{"person_id": 2001, "name": "Song", "profile_path": "/song.jpg"}],
            "backdrop_path": "/p_bd.jpg", "overview": "A poor family schemes.", "runtime": 132},
    }
    deps = Deps(
        load_films_fn=lambda user: scraped,
        enrich_fn=lambda tid, key: meta[tid],
        related_fn=lambda tid, key: [],
    )
    seen_stages = []
    run_refresh(conn, cfg, deps, on_progress=lambda p: seen_stages.append(p["stage"]))

    assert seen_stages[0] == "resolving"
    assert "enriching" in seen_stages
    assert "profiling" in seen_stages
    assert seen_stages[-1] == "done"

def test_run_refresh_includes_person_candidates_when_deps_provided(tmp_path):
    conn = connect(TEST_DSN)
    init_schema(conn)
    cfg = Config(username="alice", tmdb_api_key="k", database_url="postgresql:///unused")

    scraped = [{"slug": "goodfellas", "title": "Goodfellas", "rating": 5.0, "tmdb_id": 1}]
    meta = {
        1: {"tmdb_id": 1, "title": "Goodfellas", "year": 1990, "decade": 1990,
            "director": "Scorsese", "genres": ["Crime"], "cast": ["De Niro"],
            "keywords": [], "poster_path": "/g.jpg", "vote_avg": 8.7,
            "director_id": 1032, "director_person": {"person_id": 1032, "name": "Scorsese", "profile_path": "/scorsese.jpg"},
            "cast_people": [{"person_id": 3001, "name": "De Niro", "profile_path": "/deniro.jpg"}],
            "backdrop_path": "/g_bd.jpg", "overview": "A mob associate rises.", "runtime": 146},
        769: {"tmdb_id": 769, "title": "Taxi Driver", "year": 1976, "decade": 1970,
              "director": "Scorsese", "genres": ["Crime"], "cast": ["De Niro"],
              "keywords": [], "poster_path": "/t.jpg", "vote_avg": 8.3,
              "director_id": 1032, "director_person": {"person_id": 1032, "name": "Scorsese", "profile_path": "/scorsese.jpg"},
              "cast_people": [{"person_id": 3001, "name": "De Niro", "profile_path": "/deniro.jpg"}],
              "backdrop_path": "/t_bd.jpg", "overview": "A troubled veteran drives at night.", "runtime": 114},
    }
    deps = Deps(
        load_films_fn=lambda user: scraped,
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
    conn = connect(TEST_DSN)
    init_schema(conn)

    meta = {
        1: {"tmdb_id": 1, "title": "Parasite", "year": 2019, "decade": 2010,
            "director": "Bong", "genres": ["Thriller"], "cast": ["Song"],
            "keywords": [], "poster_path": "/p.jpg", "vote_avg": 8.5,
            "director_id": 1001, "director_person": {"person_id": 1001, "name": "Bong", "profile_path": "/bong.jpg"},
            "cast_people": [{"person_id": 2001, "name": "Song", "profile_path": "/song.jpg"}],
            "backdrop_path": "/p_bd.jpg", "overview": "A poor family schemes.", "runtime": 132},
        2: {"tmdb_id": 2, "title": "Oldboy", "year": 2003, "decade": 2000,
            "director": "Park", "genres": ["Thriller"], "cast": [],
            "keywords": [], "poster_path": "/o.jpg", "vote_avg": 8.0,
            "director_id": 1003, "director_person": {"person_id": 1003, "name": "Park", "profile_path": "/park.jpg"},
            "cast_people": [], "backdrop_path": "/o_bd.jpg", "overview": "A man seeks revenge.", "runtime": 120},
        99: {"tmdb_id": 99, "title": "Rec A", "year": 2018, "decade": 2010,
             "director": "Bong", "genres": ["Thriller"], "cast": ["Song"],
             "keywords": [], "poster_path": "/r.jpg", "vote_avg": 7.9,
             "director_id": 1001, "director_person": {"person_id": 1001, "name": "Bong", "profile_path": "/bong.jpg"},
             "cast_people": [{"person_id": 2001, "name": "Song", "profile_path": "/song.jpg"}],
             "backdrop_path": "/ra_bd.jpg", "overview": "A recommended film A.", "runtime": 110},
        100: {"tmdb_id": 100, "title": "Rec B", "year": 2018, "decade": 2010,
              "director": "Park", "genres": ["Thriller"], "cast": [],
              "keywords": [], "poster_path": "/r2.jpg", "vote_avg": 7.9,
              "director_id": 1003, "director_person": {"person_id": 1003, "name": "Park", "profile_path": "/park.jpg"},
              "cast_people": [], "backdrop_path": "/rb_bd.jpg", "overview": "A recommended film B.", "runtime": 108},
    }

    alice_cfg = Config(username="alice", tmdb_api_key="k", database_url="postgresql:///unused")
    alice_deps = Deps(
        load_films_fn=lambda user: [
            {"slug": "parasite", "title": "Parasite", "rating": 5.0, "tmdb_id": 1}],
        enrich_fn=lambda tid, key: meta[tid],
        related_fn=lambda tid, key: [99],
    )
    run_refresh(conn, alice_cfg, alice_deps)

    bob_cfg = Config(username="bob", tmdb_api_key="k", database_url="postgresql:///unused")
    bob_deps = Deps(
        load_films_fn=lambda user: [
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

def _meta(tmdb_id, title="Film", year=2019, rating_hint=None):
    return {"tmdb_id": tmdb_id, "title": title, "year": year, "decade": (year // 10) * 10,
            "director": "Bong", "genres": ["Thriller"], "cast": ["Song"], "keywords": ["k"],
            "poster_path": None, "vote_avg": 7.5, "director_id": 1001,
            "director_person": {"person_id": 1001, "name": "Bong", "profile_path": None},
            "cast_people": [{"person_id": 2001, "name": "Song", "profile_path": None}],
            "backdrop_path": None, "overview": "", "runtime": 100}

def _cfg():
    return Config(username="alice", tmdb_api_key="k", database_url="postgresql:///unused")

def _conn():
    conn = connect(TEST_DSN)
    init_schema(conn)
    return conn

def test_run_refresh_errors_when_nothing_has_been_imported():
    deps = Deps(load_films_fn=lambda user: [],
                enrich_fn=lambda tid, key: _meta(tid),
                related_fn=lambda tid, key: [])
    with pytest.raises(RuntimeError, match="export"):
        run_refresh(_conn(), _cfg(), deps)

def test_run_refresh_resolves_ids_and_reports_a_determinate_stage():
    films = [{"slug": "aaa", "title": "Parasite", "year": 2019, "rating": 5.0,
              "rated_date": "2026-02-05", "tmdb_id": None}]

    def resolve(entries, on_progress=None, should_cancel=None):
        for entry in entries:
            entry["tmdb_id"] = 1
        on_progress(1)

    deps = Deps(load_films_fn=lambda user: films, resolve_fn=resolve,
                enrich_fn=lambda tid, key: _meta(tid), related_fn=lambda tid, key: [99])
    updates = []
    run_refresh(_conn(), _cfg(), deps, on_progress=updates.append)

    resolving = [u for u in updates if u["stage"] == "resolving"]
    assert resolving[-1]["current"] == 1 and resolving[-1]["total"] == 1
    assert "TMDB" in resolving[-1]["message"]

def test_run_refresh_drops_unmatched_films_and_counts_them():
    films = [
        {"slug": "aaa", "title": "Matched", "year": 2019, "rating": 5.0, "rated_date": None, "tmdb_id": 1},
        {"slug": "bbb", "title": "Unmatched", "year": 1970, "rating": 4.0, "rated_date": None, "tmdb_id": None},
    ]
    conn = _conn()
    deps = Deps(load_films_fn=lambda user: films,
                enrich_fn=lambda tid, key: _meta(tid), related_fn=lambda tid, key: [99])
    updates = []
    run_refresh(conn, _cfg(), deps, on_progress=updates.append)

    assert updates[-1]["message"] == "Done — 1 films matched, 1 skipped"
    watched = {r["film_id"] for r in conn.execute("SELECT film_id FROM watched")}
    assert watched == {1}

def test_run_refresh_done_message_omits_skipped_when_everything_matched():
    films = [{"slug": "aaa", "title": "M", "year": 2019, "rating": 5.0, "rated_date": None, "tmdb_id": 1}]
    deps = Deps(load_films_fn=lambda user: films,
                enrich_fn=lambda tid, key: _meta(tid), related_fn=lambda tid, key: [])
    updates = []
    run_refresh(_conn(), _cfg(), deps, on_progress=updates.append)
    assert updates[-1]["message"] == "Done — 1 films matched"

def test_run_refresh_enriches_rated_films_only():
    films = [
        {"slug": "aaa", "title": "Rated", "year": 2019, "rating": 5.0, "rated_date": None, "tmdb_id": 1},
        {"slug": "bbb", "title": "Unrated", "year": 2020, "rating": None, "rated_date": None, "tmdb_id": 2},
    ]
    conn = _conn()
    enriched = []
    def enrich(tid, key):
        enriched.append(tid)
        return _meta(tid)
    deps = Deps(load_films_fn=lambda user: films, enrich_fn=enrich,
                related_fn=lambda tid, key: [])
    run_refresh(conn, _cfg(), deps)

    assert enriched == [1]  # film 2 was watched-but-unrated: id only, no API call
    watched = {r["film_id"] for r in conn.execute("SELECT film_id FROM watched")}
    assert watched == {1, 2}  # still excluded from recommendations
    rated = {r["film_id"] for r in conn.execute("SELECT film_id FROM ratings")}
    assert rated == {1}

def test_run_refresh_caps_the_number_of_seed_films():
    from app.pipeline import MAX_SEED_FILMS
    films = [{"slug": f"s{i}", "title": f"Film {i}", "year": 2000, "rating": 5.0,
              "rated_date": f"2026-01-{i % 28 + 1:02d}", "tmdb_id": i}
             for i in range(1, MAX_SEED_FILMS + 21)]
    seeds = []
    def related(tid, key):
        seeds.append(tid)
        return []
    deps = Deps(load_films_fn=lambda user: films,
                enrich_fn=lambda tid, key: _meta(tid), related_fn=related)
    run_refresh(_conn(), _cfg(), deps)
    assert len(seeds) == MAX_SEED_FILMS

def test_seed_order_prefers_highest_rated_then_most_recent():
    from app.pipeline import _liked_ids
    rated_meta = [
        {"tmdb_id": 1, "rating": 4.0, "rated_date": "2026-01-01"},
        {"tmdb_id": 2, "rating": 5.0, "rated_date": "2020-01-01"},
        {"tmdb_id": 3, "rating": 5.0, "rated_date": "2026-06-01"},
        {"tmdb_id": 4, "rating": 4.0, "rated_date": "2026-05-01"},
    ]
    assert _liked_ids(rated_meta) == [3, 2, 4, 1]

def test_seed_selection_tolerates_missing_rated_dates():
    from app.pipeline import _liked_ids
    rated_meta = [
        {"tmdb_id": 1, "rating": 5.0, "rated_date": None},
        {"tmdb_id": 2, "rating": 5.0, "rated_date": "2026-06-01"},
        {"tmdb_id": 3, "rating": 4.5},
    ]
    assert _liked_ids(rated_meta) == [2, 1, 3]

def test_run_refresh_caps_the_candidate_pool():
    from app.pipeline import MAX_CANDIDATE_POOL
    films = [{"slug": f"s{i}", "title": f"Film {i}", "year": 2000, "rating": 5.0,
              "rated_date": None, "tmdb_id": i} for i in range(1, 21)]
    # each seed alone already fills the pool, so only the first may fan out
    batch = list(range(10_000, 10_000 + MAX_CANDIDATE_POOL))
    calls = []
    def related(tid, key):
        calls.append(tid)
        return batch
    deps = Deps(load_films_fn=lambda user: films,
                enrich_fn=lambda tid, key: _meta(tid), related_fn=related)
    scored = []
    run_refresh(_conn(), _cfg(), deps,
                on_progress=lambda p: scored.append(p) if p["stage"] == "scoring" else None)
    assert len(calls) == 1
    assert scored[0]["total"] <= MAX_CANDIDATE_POOL

import threading
from app.errors import Cancelled
from tests.conftest import TEST_DSN

def test_run_refresh_raises_cancelled_when_event_set_before_enrich_loop(tmp_path):
    conn = connect(TEST_DSN)
    init_schema(conn)
    cfg = Config(username="alice", tmdb_api_key="k", database_url="postgresql:///unused")

    scraped = [{"slug": "parasite", "title": "Parasite", "rating": 5.0, "tmdb_id": 1}]
    cancel_event = threading.Event()
    cancel_event.set()  # already cancelled before run starts
    deps = Deps(
        load_films_fn=lambda user: scraped,
        enrich_fn=lambda tid, key: (_ for _ in ()).throw(AssertionError("enrich_fn should not run")),
        related_fn=lambda tid, key: [],
    )
    with pytest.raises(Cancelled):
        run_refresh(conn, cfg, deps, cancel_event=cancel_event)

def test_run_refresh_raises_cancelled_mid_scoring_loop(tmp_path):
    conn = connect(TEST_DSN)
    init_schema(conn)
    cfg = Config(username="alice", tmdb_api_key="k", database_url="postgresql:///unused")

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
        load_films_fn=lambda user: scraped,
        enrich_fn=enrich_fn,
        related_fn=lambda tid, key: [99, 100],  # pool of 2, so a 2nd scoring iteration exists to catch the flag
    )
    with pytest.raises(Cancelled):
        run_refresh(conn, cfg, deps, cancel_event=cancel_event)
    recs = conn.execute("SELECT * FROM recommendations").fetchall()
    assert recs == []  # cancelled before the commit at the end
