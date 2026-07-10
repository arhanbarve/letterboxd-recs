import dataclasses
import json
import threading
import time
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

from app.config import load_config
from app.db import connect, init_schema, lookup_slug_tmdb, store_slug_tmdb
from app.errors import Cancelled
from app.omdb import fetch_ratings
from app.pipeline import run_refresh, Deps
from app.resolver import make_resolver
from app.rss import fetch_rss, parse_rss_tmdb_map
from app.scraper import BASE, default_get, parse_tmdb_id, scrape_profile
from app.tmdb import (enrich, related_ids, search_movie, watch_providers,
                      search_person, discover_by_person)
from app.taste_dashboard import build_dashboard

class RefreshRequest(BaseModel):
    username: str | None = None

def _real_watch_providers(tmdb_id):
    cfg = load_config()
    return watch_providers(tmdb_id, cfg.tmdb_api_key)

def _real_refresh(conn, username=None, on_progress=None, cancel_event=None):
    cfg = load_config()
    if username:
        cfg = dataclasses.replace(cfg, username=username)

    def detail_fn(slug):
        tid = parse_tmdb_id(default_get(f"{BASE}/film/{slug}/"))
        time.sleep(1.0)  # pace the capped Letterboxd fallback — see resolver.MAX_DETAIL_FALLBACKS
        return tid

    def scrape(user, on_progress=None, should_cancel=None):
        rss_xml = fetch_rss(user, get_html=default_get)
        resolve_ids = make_resolver(
            cache_get=lambda slug: lookup_slug_tmdb(conn, slug),
            cache_put=lambda slug, tid, via: store_slug_tmdb(conn, slug, tid, via),
            rss_map=parse_rss_tmdb_map(rss_xml) if rss_xml else {},
            search_fn=lambda title, year: search_movie(title, year, cfg.tmdb_api_key),
            detail_fn=detail_fn,
        )
        return scrape_profile(user, on_progress=on_progress,
                              should_cancel=should_cancel, resolve_ids=resolve_ids)

    deps = Deps(
        scrape_fn=scrape,
        enrich_fn=lambda tid, key: enrich(tid, key),
        related_fn=lambda tid, key: related_ids(tid, key, pages=3),
        person_search_fn=lambda name, key: search_person(name, key),
        person_discover_fn=lambda pid, key: discover_by_person(pid, key),
        omdb_fn=lambda imdb_id: fetch_ratings(imdb_id, cfg.omdb_api_key),
    )
    run_refresh(conn, cfg, deps, on_progress=on_progress, cancel_event=cancel_event)

def create_app(
    conn_factory=None, refresh_fn=_real_refresh, watch_providers_fn=_real_watch_providers,
    cors_origins=("http://localhost:5173",),
) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware, allow_origins=list(cors_origins),
        allow_methods=["*"], allow_headers=["*"])

    progress_lock = threading.Lock()
    progress_by_user = {}
    cancel_events = {}

    def make_set_progress(username):
        def set_progress(p):
            with progress_lock:
                progress_by_user.setdefault(username, {}).update(p)
        return set_progress

    def get_conn():
        if conn_factory:
            return conn_factory()
        cfg = load_config()
        conn = connect(cfg.db_path)
        init_schema(conn)
        return conn

    @app.get("/api/recommendations")
    def recommendations(username: str):
        conn = get_conn()
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

    @app.get("/api/taste-profile")
    def taste_profile(username: str):
        conn = get_conn()
        return build_dashboard(conn, username)

    @app.get("/api/last-updated")
    def last_updated(username: str):
        conn = get_conn()
        row = conn.execute(
            "SELECT MAX(computed_at) AS ts FROM recommendations WHERE username = ?",
            (username,)).fetchone()
        return {"last_updated": row["ts"]}

    ACTIVE_STAGES = {"starting", "scraping", "enriching", "profiling", "scoring"}

    def _launch_refresh(username, starting_message):
        set_progress = make_set_progress(username)
        with progress_lock:
            if progress_by_user.get(username, {}).get("stage") in ACTIVE_STAGES:
                return {"status": "already_running"}
            cancel_event = threading.Event()
            cancel_events[username] = cancel_event
            progress_by_user.setdefault(username, {}).update(
                {"stage": "starting", "current": 0, "total": None, "message": starting_message})

        def run():
            conn = get_conn()
            try:
                refresh_fn(conn, username, on_progress=set_progress, cancel_event=cancel_event)
            except Cancelled:
                conn.rollback()
                set_progress({"stage": "cancelled", "current": 0, "total": None, "message": "Refresh cancelled."})
            except Exception as e:
                conn.rollback()
                set_progress({"stage": "error", "current": 0, "total": None, "message": str(e)})

        threading.Thread(target=run, daemon=True).start()
        return {"status": "started"}

    @app.post("/api/refresh")
    def refresh(body: RefreshRequest | None = None):
        username = body.username if body else None
        return _launch_refresh(username, "Starting refresh...")

    @app.post("/api/refresh/cancel")
    def refresh_cancel(body: RefreshRequest | None = None):
        username = body.username if body else None
        with progress_lock:
            ev = cancel_events.get(username)
            if ev is None:
                ev = threading.Event()
                cancel_events[username] = ev
            ev.set()
        return {"status": "cancelling"}

    @app.get("/api/refresh/status")
    def refresh_status(username: str | None = None):
        with progress_lock:
            return progress_by_user.get(
                username, {"stage": "idle", "current": 0, "total": None, "message": ""})

    @app.get("/api/films/{tmdb_id}/watch-providers")
    def film_watch_providers(tmdb_id: int):
        return watch_providers_fn(tmdb_id)

    @app.get("/api/films/{tmdb_id}")
    def film_detail(tmdb_id: int):
        conn = get_conn()
        row = conn.execute(
            "SELECT tmdb_id, title, year, runtime, director, overview,"
            " poster_path, backdrop_path, tmdb_vote_avg, imdb_rating, rt_score"
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
            "vote_avg": row["tmdb_vote_avg"], "imdb_rating": row["imdb_rating"],
            "rt_score": row["rt_score"], "genres": genres, "cast": cast,
        }

    return app

app = create_app(cors_origins=load_config().cors_origins)
