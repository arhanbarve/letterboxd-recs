import json
from fastapi.testclient import TestClient
from app.api import create_app
from app.db import connect, init_schema

def _seed(conn):
    conn.execute("INSERT INTO films (tmdb_id,title,year,poster_path) VALUES (99,'Rec',2018,'/r.jpg')")
    conn.execute("INSERT INTO film_genres VALUES (99,'Thriller')")
    conn.execute("INSERT INTO recommendations VALUES (99, 92.0, 4.3, ?, 'now')",
                 (json.dumps(["Thriller", "Bong"]),))
    conn.execute("INSERT INTO ratings (film_id,your_rating) VALUES (99,0)")  # unused row
    conn.commit()

def test_get_recommendations_returns_cards(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn); _seed(conn)
    app = create_app(conn_factory=lambda: conn, refresh_fn=lambda conn: None)
    client = TestClient(app)
    resp = client.get("/api/recommendations")
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["title"] == "Rec"
    assert body[0]["match_pct"] == 92.0
    assert body[0]["predicted_rating"] == 4.3
    assert body[0]["why_tags"] == ["Thriller", "Bong"]
    assert body[0]["poster_path"] == "/r.jpg"

def test_post_refresh_invokes_refresh_fn(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn)
    called = {"n": 0}
    def fake_refresh(c):
        called["n"] += 1
    app = create_app(conn_factory=lambda: conn, refresh_fn=fake_refresh)
    client = TestClient(app)
    resp = client.post("/api/refresh")
    assert resp.status_code == 200
    assert called["n"] == 1
