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
