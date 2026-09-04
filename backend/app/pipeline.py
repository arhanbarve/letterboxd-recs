import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from app.candidates import build_candidate_pool, build_person_candidate_pool
from app.errors import Cancelled
from app.profile import build_taste_profile
from app.scorer import score_candidates

LIKED_THRESHOLD = 4.0
FALLBACK_THRESHOLD = 3.5
TOP_PEOPLE_COUNT = 5

# Scoring is pure CPU over the whole candidate pool, and it is the part that a
# small instance cannot finish: at 5000 candidates it starved a 0.1-CPU box hard
# enough to stop answering health checks, so the platform killed the run. Both
# ceilings are env-tunable — raise them on a machine with cores to spare.
OMDB_TOP_N = int(os.environ.get("OMDB_TOP_N", "30"))

# Candidate generation fans out ~3 pages of TMDB "related" per seed film, and
# every candidate then costs one enrich call. Left uncapped, a full imported
# watch history turns a ~3-minute refresh into an hours-long one, so both ends
# are bounded: the seeds we expand from, and the pool they may grow to.
MAX_SEED_FILMS = 50
MAX_CANDIDATE_POOL = int(os.environ.get("MAX_CANDIDATE_POOL", "800"))

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

def _check_deadline(started_at):
    if started_at is not None and time.monotonic() - started_at > MAX_REFRESH_SECONDS:
        raise RuntimeError(
            f"Refresh gave up after {MAX_REFRESH_SECONDS // 60} minutes. This is "
            "usually an upstream API being slow rather than your data — the work "
            "done so far is saved, so running it again picks up most of it from "
            "cache.")

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

# Writes go out in batches of this size, each committed. Chosen so a crash or a
# platform restart loses seconds of work rather than the entire run — the old
# code held every write in one transaction until the very end.
PERSIST_BATCH = 100

# A refresh that has run this long is not going to finish; something upstream is
# hanging. Fail with a message the user can act on instead of occupying the
# process until the platform kills it.
MAX_REFRESH_SECONDS = 25 * 60

def _flush(conn, films, ratings) -> None:
    """Persists a batch of enriched films plus their ratings, then commits."""
    if not films and not ratings:
        return
    _persist_films(conn, films)
    if ratings:
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO ratings (username,film_id,your_rating) VALUES (%s,%s,%s)"
                " ON CONFLICT (username, film_id) DO UPDATE SET"
                " your_rating = EXCLUDED.your_rating", ratings)
    conn.commit()

def _persist_person(conn, person):
    if person is None:
        return
    conn.execute(
        "INSERT INTO people (person_id, name, profile_path) VALUES (%s,%s,%s)"
        " ON CONFLICT (person_id) DO UPDATE SET"
        " name = EXCLUDED.name, profile_path = EXCLUDED.profile_path",
        (person["person_id"], person["name"], person["profile_path"]))

def _persist_film(conn, m):
    """Single-film convenience wrapper. Prefer _persist_films for bulk work."""
    _persist_films(conn, [m])

def _persist_films(conn, films) -> None:
    """Writes a batch of enriched films in a fixed number of round trips.

    The per-film version issued roughly a dozen statements each — people upserts,
    the film upsert, three deletes and three inserts. Across a full candidate
    pool that is tens of thousands of round trips to a database on the other side
    of the network, which is what made a refresh take longer than the platform
    would leave the process alive. Batching makes the cost proportional to the
    number of statements, not the number of films.
    """
    films = [m for m in films if m]
    if not films:
        return

    people = {}
    for m in films:
        for person in [m.get("director_person"), *m.get("cast_people", [])]:
            if person:
                people[person["person_id"]] = person

    film_ids = [m["tmdb_id"] for m in films]
    genres = [(m["tmdb_id"], g) for m in films for g in m.get("genres", [])]
    keywords = [(m["tmdb_id"], k) for m in films for k in m.get("keywords", [])]
    cast = []
    for m in films:
        by_name = {p["name"]: p["person_id"] for p in m.get("cast_people", [])}
        cast += [(m["tmdb_id"], a, by_name.get(a)) for a in m.get("cast", [])]

    with conn.cursor() as cur:
        if people:
            cur.executemany(
                "INSERT INTO people (person_id, name, profile_path) VALUES (%s,%s,%s)"
                " ON CONFLICT (person_id) DO UPDATE SET"
                " name = EXCLUDED.name, profile_path = EXCLUDED.profile_path",
                [(p["person_id"], p["name"], p["profile_path"]) for p in people.values()])

        cur.executemany(
            "INSERT INTO films"
            " (tmdb_id,title,year,decade,director,director_id,poster_path,backdrop_path,overview,runtime,tmdb_vote_avg,vote_count)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"
            " ON CONFLICT (tmdb_id) DO UPDATE SET"
            " title = EXCLUDED.title, year = EXCLUDED.year, decade = EXCLUDED.decade,"
            " director = EXCLUDED.director, director_id = EXCLUDED.director_id,"
            " poster_path = EXCLUDED.poster_path, backdrop_path = EXCLUDED.backdrop_path,"
            " overview = EXCLUDED.overview, runtime = EXCLUDED.runtime,"
            " tmdb_vote_avg = EXCLUDED.tmdb_vote_avg, vote_count = EXCLUDED.vote_count",
            [(m["tmdb_id"], m["title"], m["year"], m["decade"], m["director"], m.get("director_id"),
              m["poster_path"], m.get("backdrop_path"), m.get("overview"), m.get("runtime"),
              m["vote_avg"], m.get("vote_count")) for m in films])

        # One delete per table for the whole batch, rather than three per film.
        for table in ("film_genres", "film_keywords", "film_cast"):
            cur.execute(f"DELETE FROM {table} WHERE film_id = ANY(%s)", (film_ids,))

        if genres:
            cur.executemany("INSERT INTO film_genres VALUES (%s,%s)", genres)
        if keywords:
            cur.executemany("INSERT INTO film_keywords VALUES (%s,%s)", keywords)
        if cast:
            cur.executemany("INSERT INTO film_cast VALUES (%s,%s,%s)", cast)

def run_refresh(conn, cfg, deps: Deps, on_progress=None, cancel_event=None) -> None:
    on_progress = on_progress or _noop
    started_at = time.monotonic()

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
    _check_deadline(started_at)

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
    pending, pending_ratings = [], []
    for i, f in enumerate(rated):
        _check_cancel(cancel_event)
        _check_deadline(started_at)
        on_progress({"stage": "enriching", "current": i, "total": rated_total,
                     "message": f"Fetching film details... {i}/{rated_total}"})
        m = deps.enrich_fn(f["tmdb_id"], cfg.tmdb_api_key)
        pending.append(m)
        pending_ratings.append((cfg.username, f["tmdb_id"], f["rating"]))
        rm = dict(m); rm["rating"] = f["rating"]; rm["rated_date"] = f.get("rated_date")
        rated_meta.append(rm)
        if len(pending) >= PERSIST_BATCH:
            _flush(conn, pending, pending_ratings)
            pending, pending_ratings = [], []
    _flush(conn, pending, pending_ratings)

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
        _check_deadline(started_at)
        on_progress({"stage": "scoring", "current": i, "total": cand_total,
                     "message": f"Scoring candidates... {i}/{cand_total}"})
        cand_meta.append(deps.enrich_fn(cid, cfg.tmdb_api_key))
    for start in range(0, len(cand_meta), PERSIST_BATCH):
        _check_cancel(cancel_event)
        _check_deadline(started_at)
        _persist_films(conn, cand_meta[start:start + PERSIST_BATCH])
        conn.commit()  # candidate metadata is a cache; committing early costs nothing

    results = score_candidates(cand_meta, profile, rated_meta)

    if deps.omdb_fn:
        imdb_by_id = {m["tmdb_id"]: m.get("imdb_id") for m in cand_meta}
        for r in results[:OMDB_TOP_N]:
            _check_cancel(cancel_event)
            _check_deadline(started_at)
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
