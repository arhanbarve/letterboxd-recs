import dataclasses
import json
import threading
from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

from app.auth import TOKEN_HEADER, hash_token, mint_token, token_matches
from app.config import load_config
from app.db import (connect, get_token_hash, init_schema, import_status,
                    load_imported_films, lookup_slug_tmdb,
                    replace_imported_films, set_imported_tmdb_id,
                    store_slug_tmdb, store_token_hash)
from app.errors import Cancelled, safe_message
from app.importer import MAX_UPLOAD_BYTES, ExportParseError, parse_export
from app.ratelimit import RateLimiter
from app.omdb import fetch_ratings
from app.pipeline import run_refresh, Deps
from app.resolver import make_resolver
from app.tmdb import (enrich, related_ids, search_movie, watch_providers,
                      search_person, discover_by_person)
from app.taste_dashboard import build_dashboard

class RefreshRequest(BaseModel):
    username: str | None = None

# Per client IP, per path. The refresh and import paths are the expensive ones —
# a refresh fans out thousands of TMDB/OMDB calls on a shared key, and an import
# accepts a file — so they get a much tighter ceiling than plain reads.
DEFAULT_RATE_LIMIT = (120, 60.0)
RATE_LIMITS = {
    "/api/import": (20, 3600.0),
    "/api/refresh": (10, 3600.0),
}

WRONG_CODE_DETAIL = (
    "Wrong or missing access code for that username. The code was shown when "
    "the export was first imported — paste it in, or re-import the export from "
    "the device that has it.")

def _real_watch_providers(tmdb_id):
    cfg = load_config()
    return watch_providers(tmdb_id, cfg.tmdb_api_key)

def _real_refresh(conn, username=None, on_progress=None, cancel_event=None):
    cfg = load_config()
    if username:
        cfg = dataclasses.replace(cfg, username=username)

    def load_films(user):
        # "slug" is the export's boxd.it shortcode — the resolver and the
        # film_slug_tmdb cache both just need a stable per-film key.
        return [{"slug": f["boxd_id"], "title": f["title"], "year": f["year"],
                 "rating": f["rating"], "rated_date": f["rated_date"],
                 "tmdb_id": f["tmdb_id"]}
                for f in load_imported_films(conn, user)]

    def resolve(films, on_progress=None, should_cancel=None):
        """cache -> TMDB title+year search, and nothing else. No request reaches
        Letterboxd: the export carries no film slug (only a boxd.it shortlink),
        and expanding those would mean crawling Letterboxd again — the exact
        Cloudflare-blocked path the import replaced."""
        resolve_ids = make_resolver(
            cache_get=lambda key: lookup_slug_tmdb(conn, key),
            cache_put=lambda key, tid, via: store_slug_tmdb(conn, key, tid, via),
            search_fn=lambda title, year: search_movie(title, year, cfg.tmdb_api_key),
            detail_fn=None,
        )
        resolve_ids(films, on_progress=on_progress, should_cancel=should_cancel)
        for film in films:
            set_imported_tmdb_id(conn, cfg.username, film["slug"], film["tmdb_id"])
        conn.commit()

    deps = Deps(
        load_films_fn=load_films,
        resolve_fn=resolve,
        enrich_fn=lambda tid, key: enrich(tid, key),
        related_fn=lambda tid, key: related_ids(tid, key, pages=3),
        person_search_fn=lambda name, key: search_person(name, key),
        person_discover_fn=lambda pid, key: discover_by_person(pid, key),
        omdb_fn=lambda imdb_id: fetch_ratings(imdb_id, cfg.omdb_api_key),
    )
    run_refresh(conn, cfg, deps, on_progress=on_progress, cancel_event=cancel_event)

def create_app(
    conn_factory=None, refresh_fn=_real_refresh, watch_providers_fn=_real_watch_providers,
    cors_origins=("http://localhost:5173",), cors_origin_regex=None,
    rate_limits=None, default_rate_limit=None,
) -> FastAPI:
    app = FastAPI()
    limiter = RateLimiter()
    limits = RATE_LIMITS if rate_limits is None else rate_limits
    fallback_limit = default_rate_limit or DEFAULT_RATE_LIMIT

    # Registered before CORS so that CORS ends up the *outer* middleware and a
    # 429 still carries its Access-Control headers — otherwise the browser
    # reports a CORS failure instead of the real "slow down".
    @app.middleware("http")
    async def rate_limit(request, call_next):
        if request.method == "OPTIONS":  # never throttle a CORS preflight
            return await call_next(request)
        limit, window = limits.get(request.url.path, fallback_limit)
        client = request.client.host if request.client else "unknown"
        if not limiter.check(f"{client}:{request.url.path}", limit, window):
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests — wait a bit and try again."})
        return await call_next(request)

    app.add_middleware(
        CORSMiddleware, allow_origins=list(cors_origins),
        allow_origin_regex=cors_origin_regex,
        allow_methods=["*"], allow_headers=["*"])

    def authorize(conn, username, access_code):
        """Every user-scoped endpoint goes through here. An unclaimed username has
        no data to protect, but it also has nothing to return, so both cases are
        the same 403 — that way the response does not tell a stranger which
        usernames exist."""
        if not username or not token_matches(access_code, get_token_hash(conn, username)):
            raise HTTPException(status_code=403, detail=WRONG_CODE_DETAIL)

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
        conn = connect(cfg.database_url)
        init_schema(conn)
        return conn

    @app.get("/healthz")
    def healthz():
        """Liveness only — deliberately touches no database and takes no lock.
        A health check that opens a Postgres connection is one the platform will
        fail under CPU contention, and Render restarts the instance when it does,
        killing any refresh running in a background thread."""
        return {"ok": True}

    @app.get("/api/recommendations")
    def recommendations(username: str, access_code: str | None = Header(None, alias=TOKEN_HEADER)):
        conn = get_conn()
        authorize(conn, username, access_code)
        rows = conn.execute(
            "SELECT f.tmdb_id, f.title, f.year, f.poster_path, f.backdrop_path,"
            " f.imdb_rating, f.rt_score, f.tmdb_vote_avg,"
            " r.match_pct, r.predicted_rating, r.why"
            " FROM recommendations r JOIN films f ON f.tmdb_id = r.film_id"
            " WHERE r.username = %s"
            " ORDER BY r.match_pct DESC", (username,)).fetchall()
        # One query for every film's cast, not one per row. At 800
        # recommendations the per-row version meant 800 extra round trips and a
        # 65-second response; the whole page is useless before it arrives.
        film_ids = [r["tmdb_id"] for r in rows]
        cast_by_film = {}
        if film_ids:
            for c in conn.execute(
                "SELECT film_id, actor FROM film_cast WHERE film_id = ANY(%s)",
                    (film_ids,)).fetchall():
                cast_by_film.setdefault(c["film_id"], []).append(c["actor"])

        def starring(fid):
            return cast_by_film.get(fid, [])[:3]
        return [{
            "tmdb_id": r["tmdb_id"], "title": r["title"], "year": r["year"],
            "poster_path": r["poster_path"], "backdrop_path": r["backdrop_path"],
            "match_pct": r["match_pct"], "predicted_rating": r["predicted_rating"],
            "imdb_rating": r["imdb_rating"], "rt_score": r["rt_score"],
            "vote_avg": r["tmdb_vote_avg"],
            "starring": starring(r["tmdb_id"]),
            "why": json.loads(r["why"]) if r["why"] else {"neighbors": [], "connection": None},
        } for r in rows]

    @app.post("/api/import")
    def import_export(file: UploadFile = File(...), username: str | None = Form(None),
                      access_code: str | None = Header(None, alias=TOKEN_HEADER)):
        # Read one byte past the cap rather than the whole body: an oversized
        # upload is then rejected without ever being held in full.
        raw = file.file.read(MAX_UPLOAD_BYTES + 1)
        try:
            parsed = parse_export(raw)
        except ExportParseError as e:
            raise HTTPException(status_code=400, detail=str(e)) from None
        owner = parsed["username"] or username
        if not owner:
            raise HTTPException(
                status_code=400,
                detail="That export has no profile.csv, so we can't tell whose it "
                       "is — type your Letterboxd username and upload again.")
        conn = get_conn()

        # First import for a username claims it and mints the access code; every
        # later import has to prove it holds that code, so a stranger cannot
        # overwrite someone else's data by guessing their Letterboxd username.
        stored = get_token_hash(conn, owner)
        issued = None
        if stored is None:
            issued = mint_token()
            store_token_hash(conn, owner, hash_token(issued))
        elif not token_matches(access_code, stored):
            raise HTTPException(status_code=403, detail=WRONG_CODE_DETAIL)

        replace_imported_films(conn, owner, parsed["films"])
        body = {"username": owner, **import_status(conn, owner)}
        if issued:
            body["access_code"] = issued
        return body

    @app.get("/api/import/status")
    def get_import_status(username: str,
                          access_code: str | None = Header(None, alias=TOKEN_HEADER)):
        # The one endpoint that answers without a code, because the app needs it
        # to decide whether to show the first-import panel. It reveals only
        # whether the username is claimed — never any film data.
        conn = get_conn()
        stored = get_token_hash(conn, username)
        if stored is None:
            return {"imported": 0, "rated": 0, "imported_at": None, "claimed": False}
        if not token_matches(access_code, stored):
            return {"imported": 0, "rated": 0, "imported_at": None, "claimed": True}
        return {**import_status(conn, username), "claimed": True}

    @app.get("/api/taste-profile")
    def taste_profile(username: str, access_code: str | None = Header(None, alias=TOKEN_HEADER)):
        conn = get_conn()
        authorize(conn, username, access_code)
        return build_dashboard(conn, username)

    @app.get("/api/last-updated")
    def last_updated(username: str, access_code: str | None = Header(None, alias=TOKEN_HEADER)):
        conn = get_conn()
        authorize(conn, username, access_code)
        row = conn.execute(
            "SELECT MAX(computed_at) AS ts FROM recommendations WHERE username = %s",
            (username,)).fetchone()
        return {"last_updated": row["ts"]}

    ACTIVE_STAGES = {"starting", "resolving", "enriching", "profiling", "scoring"}

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
                # safe_message, never str(e): a requests HTTPError carries the
                # full upstream URL, and TMDB/OMDB take the API key as a query
                # parameter — so the raw text would publish a live key here.
                set_progress({"stage": "error", "current": 0, "total": None,
                              "message": safe_message(e)})

        threading.Thread(target=run, daemon=True).start()
        return {"status": "started"}

    @app.post("/api/refresh")
    def refresh(body: RefreshRequest | None = None,
                access_code: str | None = Header(None, alias=TOKEN_HEADER)):
        username = body.username if body else None
        authorize(get_conn(), username, access_code)
        return _launch_refresh(username, "Starting refresh...")

    @app.post("/api/refresh/cancel")
    def refresh_cancel(body: RefreshRequest | None = None,
                       access_code: str | None = Header(None, alias=TOKEN_HEADER)):
        username = body.username if body else None
        authorize(get_conn(), username, access_code)
        with progress_lock:
            ev = cancel_events.get(username)
            if ev is None:
                ev = threading.Event()
                cancel_events[username] = ev
            ev.set()
        return {"status": "cancelling"}

    @app.get("/api/refresh/status")
    def refresh_status(username: str | None = None,
                       access_code: str | None = Header(None, alias=TOKEN_HEADER)):
        # Gated as tightly as the data endpoints: progress messages carry
        # upstream error text, which is the one place an API key could surface.
        authorize(get_conn(), username, access_code)
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
            " FROM films WHERE tmdb_id = %s", (tmdb_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Film not found")
        genres = [r["genre"] for r in conn.execute(
            "SELECT genre FROM film_genres WHERE film_id = %s", (tmdb_id,)).fetchall()]
        cast = [r["actor"] for r in conn.execute(
            "SELECT actor FROM film_cast WHERE film_id = %s", (tmdb_id,)).fetchall()]
        return {
            "tmdb_id": row["tmdb_id"], "title": row["title"], "year": row["year"],
            "runtime": row["runtime"], "director": row["director"], "overview": row["overview"],
            "poster_path": row["poster_path"], "backdrop_path": row["backdrop_path"],
            "vote_avg": row["tmdb_vote_avg"], "imdb_rating": row["imdb_rating"],
            "rt_score": row["rt_score"], "genres": genres, "cast": cast,
        }

    return app

_cfg = load_config()
app = create_app(
    cors_origins=_cfg.cors_origins, cors_origin_regex=_cfg.cors_origin_regex,
    rate_limits={"/api/import": (_cfg.imports_per_hour, 3600.0),
                 "/api/refresh": (_cfg.refreshes_per_hour, 3600.0)})
