import json
from dataclasses import dataclass
from datetime import datetime, timezone

from app.candidates import build_candidate_pool, build_person_candidate_pool
from app.errors import Cancelled
from app.profile import build_taste_profile
from app.scorer import score_candidates

LIKED_THRESHOLD = 4.0
FALLBACK_THRESHOLD = 3.5
TOP_PEOPLE_COUNT = 5
OMDB_TOP_N = 80

# Candidate generation fans out ~3 pages of TMDB "related" per seed film, and
# every candidate then costs one enrich call. Left uncapped, a full imported
# watch history turns a ~3-minute refresh into an hours-long one, so both ends
# are bounded: the seeds we expand from, and the pool they may grow to.
MAX_SEED_FILMS = 50
MAX_CANDIDATE_POOL = 5000

@dataclass
class Deps:
    load_films_fn: callable  # (username) -> list[{slug,title,year,rating,rated_date,tmdb_id}]
    enrich_fn: callable   # (tmdb_id, api_key) -> metadata dict
    related_fn: callable  # (tmdb_id, api_key) -> list[int]
    resolve_fn: callable = None  # (films, on_progress=, should_cancel=) -> fills tmdb_id in place
    person_search_fn: callable = None   # (name, api_key) -> person_id | None
    person_discover_fn: callable = None  # (person_id, api_key) -> list[int]
    omdb_fn: callable = None  # (imdb_id) -> {"imdb_rating","rt_score"}

def _noop(*args, **kwargs):
    pass

def _check_cancel(cancel_event):
    if cancel_event is not None and cancel_event.is_set():
        raise Cancelled()

def _liked_ids(rated_meta, max_seeds=MAX_SEED_FILMS):
    """The films the candidate pool is grown from: your highest-rated first, and
    among equal ratings the most recently rated. Capped so pool size (and so
    refresh runtime) stays bounded no matter how large the import is."""
    liked = [m for m in rated_meta if m["rating"] >= LIKED_THRESHOLD]
    if len(liked) < 3:
        liked = [m for m in rated_meta if m["rating"] >= FALLBACK_THRESHOLD]
    # two stable sorts == order by (rating desc, rated_date desc)
    liked.sort(key=lambda m: m.get("rated_date") or "", reverse=True)
    liked.sort(key=lambda m: m["rating"], reverse=True)
    return [m["tmdb_id"] for m in liked[:max_seeds]]

def _top_people(profile, n=TOP_PEOPLE_COUNT):
    directors = sorted(profile["director"].items(), key=lambda kv: kv[1], reverse=True)
    actors = sorted(profile["actor"].items(), key=lambda kv: kv[1], reverse=True)
    names = [name for name, score in (directors[:n] + actors[:n]) if score > 0]
    return names

def _persist_person(conn, person):
    if person is None:
        return
    conn.execute(
        "INSERT INTO people (person_id, name, profile_path) VALUES (%s,%s,%s)"
        " ON CONFLICT (person_id) DO UPDATE SET"
        " name = EXCLUDED.name, profile_path = EXCLUDED.profile_path",
        (person["person_id"], person["name"], person["profile_path"]))

def _persist_film(conn, m):
    _persist_person(conn, m.get("director_person"))
    for p in m.get("cast_people", []):
        _persist_person(conn, p)

    conn.execute(
        "INSERT INTO films"
        " (tmdb_id,title,year,decade,director,director_id,poster_path,backdrop_path,overview,runtime,tmdb_vote_avg,vote_count)"
        " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
        " ON CONFLICT (tmdb_id) DO UPDATE SET"
        " title = EXCLUDED.title, year = EXCLUDED.year, decade = EXCLUDED.decade,"
        " director = EXCLUDED.director, director_id = EXCLUDED.director_id,"
        " poster_path = EXCLUDED.poster_path, backdrop_path = EXCLUDED.backdrop_path,"
        " overview = EXCLUDED.overview, runtime = EXCLUDED.runtime,"
        " tmdb_vote_avg = EXCLUDED.tmdb_vote_avg, vote_count = EXCLUDED.vote_count",
        (m["tmdb_id"], m["title"], m["year"], m["decade"], m["director"], m.get("director_id"),
         m["poster_path"], m.get("backdrop_path"), m.get("overview"), m.get("runtime"), m["vote_avg"],
         m.get("vote_count")))
    conn.execute("DELETE FROM film_genres WHERE film_id=%s", (m["tmdb_id"],))
    conn.execute("DELETE FROM film_keywords WHERE film_id=%s", (m["tmdb_id"],))
    conn.execute("DELETE FROM film_cast WHERE film_id=%s", (m["tmdb_id"],))
    cast_people_by_name = {p["name"]: p["person_id"] for p in m.get("cast_people", [])}
    with conn.cursor() as cur:
        cur.executemany("INSERT INTO film_genres VALUES (%s,%s)",
                        [(m["tmdb_id"], g) for g in m["genres"]])
        cur.executemany("INSERT INTO film_keywords VALUES (%s,%s)",
                        [(m["tmdb_id"], k) for k in m["keywords"]])
        cur.executemany("INSERT INTO film_cast VALUES (%s,%s,%s)",
                        [(m["tmdb_id"], a, cast_people_by_name.get(a)) for a in m["cast"]])

def run_refresh(conn, cfg, deps: Deps, on_progress=None, cancel_event=None) -> None:
    on_progress = on_progress or _noop

    films = deps.load_films_fn(cfg.username)
    if not films:
        raise RuntimeError(
            "No films imported yet. Download your Letterboxd export "
            "(Settings -> Data -> Export Your Data) and upload the zip first.")

    # Unlike the old scrape, the film count is known before any network work, so
    # this stage reports a real fraction instead of an estimated creep.
    total = len(films)
    on_progress({"stage": "resolving", "current": 0, "total": total,
                 "message": f"Matching your films to TMDB... 0/{total}"})
    if deps.resolve_fn:
        deps.resolve_fn(
            films,
            on_progress=lambda n: on_progress({
                "stage": "resolving", "current": n, "total": total,
                "message": f"Matching your films to TMDB... {n}/{total}",
            }),
            should_cancel=lambda: cancel_event is not None and cancel_event.is_set(),
        )
    _check_cancel(cancel_event)

    # A film with no TMDB id can never be scored or recommended against, so it is
    # dropped — counted, not silently swallowed (reported in the done message).
    matched = [f for f in films if f.get("tmdb_id") is not None]
    skipped = total - len(matched)
    rated = [f for f in matched if f.get("rating") is not None]

    conn.execute("DELETE FROM ratings WHERE username=%s", (cfg.username,))
    conn.execute("DELETE FROM watched WHERE username=%s", (cfg.username,))
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO watched (username,film_id) VALUES (%s,%s)"
            " ON CONFLICT (username, film_id) DO NOTHING",
            [(cfg.username, f["tmdb_id"]) for f in matched])

    # Only rated films are enriched: an unrated-but-watched film contributes
    # nothing except its id to the exclusion set, and nothing joins watched to
    # films, so paying an enrich call for it would buy nothing.
    rated_meta = []
    rated_total = len(rated)
    for i, f in enumerate(rated):
        _check_cancel(cancel_event)
        on_progress({"stage": "enriching", "current": i, "total": rated_total,
                     "message": f"Fetching film details... {i}/{rated_total}"})
        m = deps.enrich_fn(f["tmdb_id"], cfg.tmdb_api_key)
        _persist_film(conn, m)
        conn.execute(
            "INSERT INTO ratings (username,film_id,your_rating) VALUES (%s,%s,%s)"
            " ON CONFLICT (username, film_id) DO UPDATE SET"
            " your_rating = EXCLUDED.your_rating",
            (cfg.username, f["tmdb_id"], f["rating"]))
        rm = dict(m); rm["rating"] = f["rating"]; rm["rated_date"] = f.get("rated_date")
        rated_meta.append(rm)

    on_progress({"stage": "profiling", "current": 0, "total": None,
                 "message": "Building your taste profile..."})
    profile = build_taste_profile(rated_meta)
    watched_ids = {f["tmdb_id"] for f in matched}
    pool = build_candidate_pool(_liked_ids(rated_meta), watched_ids,
                                cfg.tmdb_api_key, related_fn=deps.related_fn,
                                max_pool=MAX_CANDIDATE_POOL)

    if deps.person_search_fn and deps.person_discover_fn:
        on_progress({"stage": "profiling", "current": 0, "total": None,
                     "message": "Finding films by your favorite directors and actors..."})
        pool |= build_person_candidate_pool(
            _top_people(profile), watched_ids, cfg.tmdb_api_key,
            search_person_fn=deps.person_search_fn, discover_fn=deps.person_discover_fn,
            max_pool=max(0, MAX_CANDIDATE_POOL - len(pool)),
        )

    cand_total = len(pool)
    cand_meta = []
    for i, cid in enumerate(pool):
        _check_cancel(cancel_event)
        on_progress({"stage": "scoring", "current": i, "total": cand_total,
                     "message": f"Scoring candidates... {i}/{cand_total}"})
        cand_meta.append(deps.enrich_fn(cid, cfg.tmdb_api_key))
    for m in cand_meta:
        _persist_film(conn, m)

    results = score_candidates(cand_meta, profile, rated_meta)

    if deps.omdb_fn:
        imdb_by_id = {m["tmdb_id"]: m.get("imdb_id") for m in cand_meta}
        for r in results[:OMDB_TOP_N]:
            _check_cancel(cancel_event)
            imdb_id = imdb_by_id.get(r["tmdb_id"])
            if not imdb_id:
                continue
            ratings = deps.omdb_fn(imdb_id)
            conn.execute(
                "UPDATE films SET imdb_rating=%s, rt_score=%s WHERE tmdb_id=%s",
                (ratings.get("imdb_rating"), ratings.get("rt_score"), r["tmdb_id"]))

    now = datetime.now(timezone.utc).isoformat()
    conn.execute("DELETE FROM recommendations WHERE username=%s", (cfg.username,))
    for r in results:
        conn.execute(
            "INSERT INTO recommendations (username,film_id,match_pct,predicted_rating,why,computed_at)"
            " VALUES (%s,%s,%s,%s,%s,%s)",
            (cfg.username, r["tmdb_id"], r["match_pct"], r["predicted_rating"],
             json.dumps(r["why"]), now))
    conn.commit()
    message = f"Done — {len(matched)} films matched"
    if skipped:
        message += f", {skipped} skipped"
    on_progress({"stage": "done", "current": len(matched), "total": total,
                 "message": message})
