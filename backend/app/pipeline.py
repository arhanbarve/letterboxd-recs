import json
from dataclasses import dataclass
from datetime import datetime, timezone

from app.candidates import build_candidate_pool, build_person_candidate_pool
from app.profile import build_taste_profile
from app.scorer import score_candidates

LIKED_THRESHOLD = 4.0
FALLBACK_THRESHOLD = 3.5
TOP_PEOPLE_COUNT = 5

@dataclass
class Deps:
    scrape_fn: callable   # (username, on_progress=None) -> list[{slug,title,rating,tmdb_id}]
    enrich_fn: callable   # (tmdb_id, api_key) -> metadata dict
    related_fn: callable  # (tmdb_id, api_key) -> list[int]
    person_search_fn: callable = None   # (name, api_key) -> person_id | None
    person_discover_fn: callable = None  # (person_id, api_key) -> list[int]

def _noop(*args, **kwargs):
    pass

def _liked_ids(rated_meta):
    liked = [m["tmdb_id"] for m in rated_meta if m["rating"] >= LIKED_THRESHOLD]
    if len(liked) < 3:
        liked = [m["tmdb_id"] for m in rated_meta if m["rating"] >= FALLBACK_THRESHOLD]
    return liked

def _top_people(profile, n=TOP_PEOPLE_COUNT):
    directors = sorted(profile["director"].items(), key=lambda kv: kv[1], reverse=True)
    actors = sorted(profile["actor"].items(), key=lambda kv: kv[1], reverse=True)
    names = [name for name, score in (directors[:n] + actors[:n]) if score > 0]
    return names

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

def run_refresh(conn, cfg, deps: Deps, on_progress=None) -> None:
    on_progress = on_progress or _noop

    on_progress({"stage": "scraping", "current": 0, "total": None,
                 "message": "Scraping your Letterboxd ratings..."})
    scraped = deps.scrape_fn(
        cfg.username,
        on_progress=lambda n: on_progress({
            "stage": "scraping", "current": n, "total": None,
            "message": f"Scraping your Letterboxd ratings... {n} found",
        }),
    )

    rated_meta = []
    conn.execute("DELETE FROM ratings WHERE username=?", (cfg.username,))
    conn.execute("DELETE FROM watched WHERE username=?", (cfg.username,))
    total = len(scraped)
    for i, f in enumerate(scraped):
        on_progress({"stage": "enriching", "current": i, "total": total,
                     "message": f"Fetching film details... {i}/{total}"})
        m = deps.enrich_fn(f["tmdb_id"], cfg.tmdb_api_key)
        _persist_film(conn, m)
        conn.execute("INSERT OR REPLACE INTO watched (username,film_id) VALUES (?,?)",
                     (cfg.username, f["tmdb_id"]))
        if f["rating"] is not None:
            conn.execute(
                "INSERT OR REPLACE INTO ratings (username,film_id,your_rating) VALUES (?,?,?)",
                (cfg.username, f["tmdb_id"], f["rating"]))
            rm = dict(m); rm["rating"] = f["rating"]
            rated_meta.append(rm)

    on_progress({"stage": "profiling", "current": 0, "total": None,
                 "message": "Building your taste profile..."})
    profile = build_taste_profile(rated_meta)
    watched_ids = {f["tmdb_id"] for f in scraped}
    pool = build_candidate_pool(_liked_ids(rated_meta), watched_ids,
                                cfg.tmdb_api_key, related_fn=deps.related_fn)

    if deps.person_search_fn and deps.person_discover_fn:
        on_progress({"stage": "profiling", "current": 0, "total": None,
                     "message": "Finding films by your favorite directors and actors..."})
        pool |= build_person_candidate_pool(
            _top_people(profile), watched_ids, cfg.tmdb_api_key,
            search_person_fn=deps.person_search_fn, discover_fn=deps.person_discover_fn,
        )

    cand_total = len(pool)
    cand_meta = []
    for i, cid in enumerate(pool):
        on_progress({"stage": "scoring", "current": i, "total": cand_total,
                     "message": f"Scoring candidates... {i}/{cand_total}"})
        cand_meta.append(deps.enrich_fn(cid, cfg.tmdb_api_key))
    for m in cand_meta:
        _persist_film(conn, m)

    results = score_candidates(cand_meta, profile, rated_meta)

    now = datetime.now(timezone.utc).isoformat()
    conn.execute("DELETE FROM recommendations WHERE username=?", (cfg.username,))
    for r in results:
        conn.execute(
            "INSERT INTO recommendations (username,film_id,match_pct,predicted_rating,why_tags,computed_at)"
            " VALUES (?,?,?,?,?,?)",
            (cfg.username, r["tmdb_id"], r["match_pct"], r["predicted_rating"],
             json.dumps(r["why_tags"]), now))
    conn.commit()
    on_progress({"stage": "done", "current": total, "total": total,
                 "message": "Done"})
