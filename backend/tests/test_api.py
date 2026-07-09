import json
import threading
import time
from fastapi.testclient import TestClient
from app.api import create_app
from app.db import connect, init_schema

def _wait_until(cond, timeout=1.0, interval=0.01):
    start = time.time()
    while time.time() - start < timeout:
        if cond():
            return
        time.sleep(interval)
    raise AssertionError("condition not met in time")

def _mem_conn():
    conn = connect(":memory:")
    init_schema(conn)
    return conn

def _seed(conn):
    conn.execute(
        "INSERT INTO films (tmdb_id,title,year,poster_path,backdrop_path,overview,runtime,director)"
        " VALUES (99,'Rec',2018,'/r.jpg','/rb.jpg','A pitch.',108,'Bong')")
    conn.execute("INSERT INTO film_genres VALUES (99,'Thriller')")
    conn.execute("INSERT INTO film_cast VALUES (99,'Song Kang-ho',1523)")
    why = {"neighbors": [{"title": "Snowpiercer", "rating": 5.0}], "connection": "directed by Bong"}
    conn.execute("INSERT INTO recommendations VALUES ('alice', 99, 92.0, 4.3, ?, 'now')",
                 (json.dumps(why),))
    conn.execute("INSERT INTO ratings (username,film_id,your_rating) VALUES ('alice',99,0)")  # unused row
    conn.commit()

def test_get_recommendations_returns_cards(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn); _seed(conn)
    app = create_app(conn_factory=lambda: conn, refresh_fn=lambda conn, username=None, on_progress=None, cancel_event=None: None)
    client = TestClient(app)
    resp = client.get("/api/recommendations", params={"username": "alice"})
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["title"] == "Rec"
    assert body[0]["match_pct"] == 92.0
    assert body[0]["predicted_rating"] == 4.3
    assert body[0]["why"] == {"neighbors": [{"title": "Snowpiercer", "rating": 5.0}], "connection": "directed by Bong"}
    assert body[0]["poster_path"] == "/r.jpg"
    assert body[0]["backdrop_path"] == "/rb.jpg"

def test_get_recommendations_scoped_by_username(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn); _seed(conn)
    app = create_app(conn_factory=lambda: conn, refresh_fn=lambda conn, username=None, on_progress=None, cancel_event=None: None)
    client = TestClient(app)
    resp = client.get("/api/recommendations", params={"username": "bob"})
    assert resp.status_code == 200
    assert resp.json() == []  # bob has no recommendations, alice's don't leak

def test_get_film_detail_returns_full_metadata(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn)
    conn.execute(
        "INSERT INTO films (tmdb_id,title,year,poster_path,backdrop_path,overview,runtime,director)"
        " VALUES (99,'Rec',2018,'/r.jpg','/rb.jpg','A pitch.',108,'Bong')")
    conn.execute("INSERT INTO film_genres VALUES (99,'Thriller')")
    conn.execute("INSERT INTO film_genres VALUES (99,'Drama')")
    conn.execute("INSERT INTO film_cast VALUES (99,'Song Kang-ho',1523)")
    conn.commit()
    app = create_app(conn_factory=lambda: conn, refresh_fn=lambda conn, username=None, on_progress=None, cancel_event=None: None)
    client = TestClient(app)
    resp = client.get("/api/films/99")
    assert resp.status_code == 200
    body = resp.json()
    assert body["title"] == "Rec"
    assert body["year"] == 2018
    assert body["runtime"] == 108
    assert body["director"] == "Bong"
    assert body["overview"] == "A pitch."
    assert body["backdrop_path"] == "/rb.jpg"
    assert body["poster_path"] == "/r.jpg"
    assert sorted(body["genres"]) == ["Drama", "Thriller"]
    assert body["cast"] == ["Song Kang-ho"]

def test_get_film_detail_404_for_unknown_film(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn)
    app = create_app(conn_factory=lambda: conn, refresh_fn=lambda conn, username=None, on_progress=None, cancel_event=None: None)
    client = TestClient(app)
    resp = client.get("/api/films/999999")
    assert resp.status_code == 404

def test_get_taste_profile_scoped_by_username(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn)
    conn.execute("INSERT INTO films (tmdb_id,title,year,decade) VALUES (1,'X',2000,2000)")
    conn.execute("INSERT INTO film_genres VALUES (1,'Thriller')")
    conn.execute("INSERT INTO ratings (username,film_id,your_rating) VALUES ('alice',1,5.0)")
    conn.commit()
    app = create_app(conn_factory=lambda: conn, refresh_fn=lambda conn, username=None, on_progress=None, cancel_event=None: None)
    client = TestClient(app)
    resp = client.get("/api/taste-profile", params={"username": "alice"})
    body = resp.json()
    assert body["total_rated"] == 1
    assert body["genre_affinities"][0]["name"] == "Thriller"
    resp_bob = client.get("/api/taste-profile", params={"username": "bob"})
    assert resp_bob.json()["total_rated"] == 0

def test_post_refresh_invokes_refresh_fn(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn)
    called = {"n": 0}
    def fake_refresh(c, username=None, on_progress=None, cancel_event=None):
        called["n"] += 1
    app = create_app(conn_factory=lambda: conn, refresh_fn=fake_refresh)
    client = TestClient(app)
    resp = client.post("/api/refresh")
    assert resp.status_code == 200
    _wait_until(lambda: called["n"] == 1)

def test_post_refresh_passes_username_override(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn)
    seen = {}
    def fake_refresh(c, username=None, on_progress=None, cancel_event=None):
        seen["username"] = username
    app = create_app(conn_factory=lambda: conn, refresh_fn=fake_refresh)
    client = TestClient(app)
    resp = client.post("/api/refresh", json={"username": "alice"})
    assert resp.status_code == 200
    _wait_until(lambda: seen.get("username") == "alice")

def test_post_refresh_without_body_passes_none_username(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn)
    seen = {}
    def fake_refresh(c, username=None, on_progress=None, cancel_event=None):
        seen["username"] = username
    app = create_app(conn_factory=lambda: conn, refresh_fn=fake_refresh)
    client = TestClient(app)
    resp = client.post("/api/refresh")
    assert resp.status_code == 200
    _wait_until(lambda: "username" in seen)
    assert seen["username"] is None

def test_refresh_status_reflects_progress_reported_during_refresh(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn)
    def fake_refresh(c, username=None, on_progress=None, cancel_event=None):
        on_progress({"stage": "enriching", "current": 3, "total": 10, "message": "..."})
    app = create_app(conn_factory=lambda: conn, refresh_fn=fake_refresh)
    client = TestClient(app)
    client.post("/api/refresh")

    body = {}
    def check():
        nonlocal body
        body = client.get("/api/refresh/status").json()
        return body.get("stage") == "enriching"
    _wait_until(check)

    assert body["current"] == 3
    assert body["total"] == 10

def test_post_refresh_rejects_concurrent_start_for_same_user(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn)
    started = threading.Event()
    finish = threading.Event()
    def fake_refresh(c, username=None, on_progress=None, cancel_event=None):
        started.set()
        finish.wait(timeout=2)
    app = create_app(conn_factory=lambda: conn, refresh_fn=fake_refresh)
    client = TestClient(app)
    client.post("/api/refresh", json={"username": "alice"})
    assert started.wait(timeout=1)
    resp = client.post("/api/refresh", json={"username": "alice"})
    assert resp.json()["status"] == "already_running"
    finish.set()

def test_refresh_status_defaults_to_idle(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn)
    app = create_app(conn_factory=lambda: conn, refresh_fn=lambda c, username=None, on_progress=None, cancel_event=None: None)
    client = TestClient(app)
    resp = client.get("/api/refresh/status")
    assert resp.status_code == 200
    assert resp.json()["stage"] in ("idle", "done")

def test_get_watch_providers_returns_normalized_data(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn)
    app = create_app(
        conn_factory=lambda: conn,
        watch_providers_fn=lambda tid: {"link": "https://x", "flatrate": [{"name": "Netflix", "logo_path": "/n.jpg"}], "rent": [], "buy": []},
    )
    client = TestClient(app)
    resp = client.get("/api/films/496243/watch-providers")
    assert resp.status_code == 200
    body = resp.json()
    assert body["flatrate"][0]["name"] == "Netflix"
    assert body["link"] == "https://x"

def test_post_refresh_cancel_sets_event_and_stage_becomes_cancelled(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn)
    started = threading.Event()
    from app.errors import Cancelled
    def fake_refresh(c, username=None, on_progress=None, cancel_event=None):
        started.set()
        while not cancel_event.is_set():
            time.sleep(0.01)
        raise Cancelled()
    app = create_app(conn_factory=lambda: conn, refresh_fn=fake_refresh)
    client = TestClient(app)
    client.post("/api/refresh", json={"username": "alice"})
    assert started.wait(timeout=1)

    resp = client.post("/api/refresh/cancel", json={"username": "alice"})
    assert resp.status_code == 200

    body = {}
    def check():
        nonlocal body
        body = client.get("/api/refresh/status", params={"username": "alice"}).json()
        return body.get("stage") == "cancelled"
    _wait_until(check)
    assert body["stage"] == "cancelled"

def test_cancel_event_cleared_when_new_run_starts(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn)
    seen_cancel_states = []
    def fake_refresh(c, username=None, on_progress=None, cancel_event=None):
        seen_cancel_states.append(cancel_event.is_set())
        # Reach a terminal stage, like a well-behaved refresh_fn, so the next
        # POST isn't rejected by the already-running gate.
        on_progress({"stage": "done", "current": 0, "total": None, "message": "Done"})
    app = create_app(conn_factory=lambda: conn, refresh_fn=fake_refresh)
    client = TestClient(app)

    client.post("/api/refresh", json={"username": "alice"})
    _wait_until(lambda: len(seen_cancel_states) == 1)
    client.post("/api/refresh/cancel", json={"username": "alice"})

    client.post("/api/refresh", json={"username": "alice"})
    _wait_until(lambda: len(seen_cancel_states) == 2)
    assert seen_cancel_states[1] is False  # fresh event for the new run, not the old cancelled one

def test_real_refresh_builds_cascade_and_scrapes_without_detail_pages(monkeypatch, tmp_path):
    """_real_refresh must inject a resolve_ids cascade into scrape_profile:
    cache + rss + search + detail. We stub every network layer and assert the
    scrape resolves via rss/search and persists to the slug cache."""
    import app.api as api_mod
    from app.config import Config
    from app.db import connect, init_schema, lookup_slug_tmdb

    conn = connect(":memory:")
    init_schema(conn)

    monkeypatch.setattr(api_mod, "load_config", lambda: Config(
        username="alice", tmdb_api_key="KEY", db_path=str(tmp_path / "x.db")))
    monkeypatch.setattr(api_mod, "fetch_rss", lambda user, get_html=None: "<rss/>")
    monkeypatch.setattr(api_mod, "parse_rss_tmdb_map", lambda xml: {"parasite": 496243})
    monkeypatch.setattr(api_mod, "search_movie", lambda title, year, key: 555)

    captured = {}
    def fake_scrape_profile(user, get_html=None, delay=1.0, on_progress=None,
                            should_cancel=None, resolve_ids=None):
        entries = [
            {"slug": "parasite", "title": "Parasite", "year": 2019, "rating": 5.0},
            {"slug": "cats", "title": "Cats", "year": 2019, "rating": 1.0},
        ]
        resolve_ids(entries, on_progress=on_progress, should_cancel=should_cancel)
        captured["entries"] = entries
        return [e for e in entries if e["tmdb_id"] is not None]
    monkeypatch.setattr(api_mod, "scrape_profile", fake_scrape_profile)

    def fake_run_refresh(conn_, cfg, deps, on_progress=None, cancel_event=None):
        deps.scrape_fn(cfg.username, on_progress=None, should_cancel=None)
    monkeypatch.setattr(api_mod, "run_refresh", fake_run_refresh)

    api_mod._real_refresh(conn, "alice")

    by_slug = {e["slug"]: e for e in captured["entries"]}
    assert by_slug["parasite"]["tmdb_id"] == 496243   # via rss
    assert by_slug["cats"]["tmdb_id"] == 555          # via search
    assert lookup_slug_tmdb(conn, "cats") == (555,)   # persisted to cache
