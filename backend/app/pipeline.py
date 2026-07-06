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
