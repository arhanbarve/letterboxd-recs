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
