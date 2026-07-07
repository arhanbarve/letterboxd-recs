import dataclasses
import json
import threading
from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

from app.config import load_config
from app.db import connect, init_schema
from app.pipeline import run_refresh, Deps
from app.scraper import scrape_profile
from app.tmdb import enrich, related_ids, watch_providers, search_person, discover_by_person

class RefreshRequest(BaseModel):
    username: str | None = None

def _real_watch_providers(tmdb_id):
    cfg = load_config()
    return watch_providers(tmdb_id, cfg.tmdb_api_key)

def _real_refresh(conn, username=None, on_progress=None):
    cfg = load_config()
    if username:
        cfg = dataclasses.replace(cfg, username=username)
    deps = Deps(
        scrape_fn=lambda user, on_progress=None: scrape_profile(user, on_progress=on_progress),
        enrich_fn=lambda tid, key: enrich(tid, key),
        related_fn=lambda tid, key: related_ids(tid, key, pages=3),
        person_search_fn=lambda name, key: search_person(name, key),
        person_discover_fn=lambda pid, key: discover_by_person(pid, key),
    )
    run_refresh(conn, cfg, deps, on_progress=on_progress)

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
            "SELECT f.tmdb_id, f.title, f.year, f.poster_path,"
            " r.match_pct, r.predicted_rating, r.why_tags"
            " FROM recommendations r JOIN films f ON f.tmdb_id = r.film_id"
            " WHERE r.username = ?"
            " ORDER BY r.match_pct DESC", (username,)).fetchall()
        return [{
            "tmdb_id": r["tmdb_id"], "title": r["title"], "year": r["year"],
            "poster_path": r["poster_path"], "match_pct": r["match_pct"],
            "predicted_rating": r["predicted_rating"],
            "why_tags": json.loads(r["why_tags"]),
        } for r in rows]

    @app.get("/api/taste-profile")
    def taste_profile(username: str):
        conn = get_conn()
        def top(table, col):
            rows = conn.execute(
                f"SELECT {col} v, COUNT(*) c FROM {table}"
                f" JOIN ratings ra ON ra.film_id = {table}.film_id"
                f" WHERE ra.username = ?"
                f" GROUP BY {col} ORDER BY c DESC LIMIT 10", (username,)).fetchall()
            return [{"name": str(r["v"]), "count": r["c"]} for r in rows]
        return {
            "genres": top("film_genres", "genre"),
            "actors": top("film_cast", "actor"),
        }

    ACTIVE_STAGES = {"starting", "scraping", "enriching", "profiling", "scoring"}

    @app.post("/api/refresh")
    def refresh(body: RefreshRequest | None = None):
        username = body.username if body else None
        set_progress = make_set_progress(username)

        with progress_lock:
            if progress_by_user.get(username, {}).get("stage") in ACTIVE_STAGES:
                return {"status": "already_running"}
            progress_by_user.setdefault(username, {}).update(
                {"stage": "starting", "current": 0, "total": None, "message": "Starting refresh..."})

        def run():
            conn = get_conn()
            try:
                refresh_fn(conn, username, on_progress=set_progress)
            except Exception as e:
                set_progress({"stage": "error", "current": 0, "total": None, "message": str(e)})

        threading.Thread(target=run, daemon=True).start()
        return {"status": "started"}

    @app.get("/api/refresh/status")
    def refresh_status(username: str | None = None):
        with progress_lock:
            return progress_by_user.get(
                username, {"stage": "idle", "current": 0, "total": None, "message": ""})

    @app.get("/api/films/{tmdb_id}/watch-providers")
    def film_watch_providers(tmdb_id: int):
        return watch_providers_fn(tmdb_id)

    return app

app = create_app(cors_origins=load_config().cors_origins)
