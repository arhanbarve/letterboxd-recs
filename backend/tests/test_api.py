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

def _seed(conn):
    conn.execute("INSERT INTO films (tmdb_id,title,year,poster_path) VALUES (99,'Rec',2018,'/r.jpg')")
    conn.execute("INSERT INTO film_genres VALUES (99,'Thriller')")
    conn.execute("INSERT INTO recommendations VALUES ('alice', 99, 92.0, 4.3, ?, 'now')",
                 (json.dumps(["Thriller", "Bong"]),))
    conn.execute("INSERT INTO ratings (username,film_id,your_rating) VALUES ('alice',99,0)")  # unused row
    conn.commit()

def test_get_recommendations_returns_cards(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn); _seed(conn)
    app = create_app(conn_factory=lambda: conn, refresh_fn=lambda conn, username=None, on_progress=None: None)
    client = TestClient(app)
    resp = client.get("/api/recommendations", params={"username": "alice"})
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["title"] == "Rec"
    assert body[0]["match_pct"] == 92.0
    assert body[0]["predicted_rating"] == 4.3
    assert body[0]["why_tags"] == ["Thriller", "Bong"]
    assert body[0]["poster_path"] == "/r.jpg"

def test_get_recommendations_scoped_by_username(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn); _seed(conn)
    app = create_app(conn_factory=lambda: conn, refresh_fn=lambda conn, username=None, on_progress=None: None)
    client = TestClient(app)
    resp = client.get("/api/recommendations", params={"username": "bob"})
    assert resp.status_code == 200
    assert resp.json() == []  # bob has no recommendations, alice's don't leak

def test_get_taste_profile_scoped_by_username(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn)
    conn.execute("INSERT INTO films (tmdb_id,title,year) VALUES (1,'X',2000)")
    conn.execute("INSERT INTO film_genres VALUES (1,'Thriller')")
    conn.execute("INSERT INTO ratings (username,film_id,your_rating) VALUES ('alice',1,5.0)")
    conn.commit()
    app = create_app(conn_factory=lambda: conn, refresh_fn=lambda conn, username=None, on_progress=None: None)
    client = TestClient(app)
    resp = client.get("/api/taste-profile", params={"username": "alice"})
    assert resp.json()["genres"] == [{"name": "Thriller", "count": 1}]
    resp_bob = client.get("/api/taste-profile", params={"username": "bob"})
    assert resp_bob.json()["genres"] == []

def test_post_refresh_invokes_refresh_fn(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn)
    called = {"n": 0}
    def fake_refresh(c, username=None, on_progress=None):
        called["n"] += 1
    app = create_app(conn_factory=lambda: conn, refresh_fn=fake_refresh)
    client = TestClient(app)
    resp = client.post("/api/refresh")
    assert resp.status_code == 200
    _wait_until(lambda: called["n"] == 1)

def test_post_refresh_passes_username_override(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn)
    seen = {}
    def fake_refresh(c, username=None, on_progress=None):
        seen["username"] = username
    app = create_app(conn_factory=lambda: conn, refresh_fn=fake_refresh)
    client = TestClient(app)
    resp = client.post("/api/refresh", json={"username": "alice"})
    assert resp.status_code == 200
    _wait_until(lambda: seen.get("username") == "alice")

def test_post_refresh_without_body_passes_none_username(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn)
    seen = {}
    def fake_refresh(c, username=None, on_progress=None):
        seen["username"] = username
    app = create_app(conn_factory=lambda: conn, refresh_fn=fake_refresh)
    client = TestClient(app)
    resp = client.post("/api/refresh")
    assert resp.status_code == 200
    _wait_until(lambda: "username" in seen)
    assert seen["username"] is None

def test_refresh_status_reflects_progress_reported_during_refresh(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn)
    def fake_refresh(c, username=None, on_progress=None):
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
    def fake_refresh(c, username=None, on_progress=None):
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
    app = create_app(conn_factory=lambda: conn, refresh_fn=lambda c, username=None, on_progress=None: None)
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
