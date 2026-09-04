import inspect
import json
import threading
import time
from fastapi.testclient import TestClient
from app.api import create_app
from app.auth import hash_token, mint_token
from app.db import connect, init_schema, load_imported_films, store_token_hash
from tests.conftest import TEST_DSN

CODE_HEADER = "X-Access-Code"

def _claim(conn, username):
    """Claims a username the way a first import does, and returns its access
    code — so a test can exercise an authorized request without uploading."""
    code = mint_token()
    store_token_hash(conn, username, hash_token(code))
    return code

def _auth(code):
    return {CODE_HEADER: code}

def _wait_until(cond, timeout=1.0, interval=0.01):
    start = time.time()
    while time.time() - start < timeout:
        if cond():
            return
        time.sleep(interval)
    raise AssertionError("condition not met in time")

def _mem_conn():
    conn = connect(TEST_DSN)
    init_schema(conn)
    return conn

def _seed(conn):
    conn.execute(
        "INSERT INTO films (tmdb_id,title,year,poster_path,backdrop_path,overview,runtime,director)"
        " VALUES (99,'Rec',2018,'/r.jpg','/rb.jpg','A pitch.',108,'Bong')")
    conn.execute("INSERT INTO film_genres VALUES (99,'Thriller')")
    conn.execute("INSERT INTO film_cast VALUES (99,'Song Kang-ho',1523)")
    why = {"neighbors": [{"title": "Snowpiercer", "rating": 5.0}], "connection": "directed by Bong"}
    conn.execute("INSERT INTO recommendations VALUES ('alice', 99, 92.0, 4.3, %s, 'now')",
                 (json.dumps(why),))
    conn.execute("INSERT INTO ratings (username,film_id,your_rating) VALUES ('alice',99,0)")  # unused row
    conn.commit()

def test_get_recommendations_returns_cards(tmp_path):
    conn = connect(TEST_DSN); init_schema(conn); _seed(conn)
    app = create_app(conn_factory=lambda: conn, refresh_fn=lambda conn, username=None, on_progress=None, cancel_event=None: None)
    client = TestClient(app)
    code = _claim(conn, "alice")
    resp = client.get("/api/recommendations", params={"username": "alice"}, headers=_auth(code))
    assert resp.status_code == 200
    body = resp.json()
    assert body[0]["title"] == "Rec"
    assert body[0]["match_pct"] == 92.0
    assert body[0]["predicted_rating"] == 4.3
    assert body[0]["why"] == {"neighbors": [{"title": "Snowpiercer", "rating": 5.0}], "connection": "directed by Bong"}
    assert body[0]["poster_path"] == "/r.jpg"
    assert body[0]["backdrop_path"] == "/rb.jpg"

def test_recommendations_include_starring_and_ratings(tmp_path):
    conn = connect(TEST_DSN); init_schema(conn)
    conn.execute(
        "INSERT INTO films (tmdb_id,title,year,poster_path,backdrop_path,overview,runtime,director,"
        "tmdb_vote_avg,imdb_rating,rt_score)"
        " VALUES (1,'A',2010,'/a.jpg','/ab.jpg','A pitch.',100,'Dir',7.9,8.1,90)")
    conn.execute("INSERT INTO film_cast VALUES (1,'Actor One',101)")
    conn.execute("INSERT INTO film_cast VALUES (1,'Actor Two',102)")
    conn.execute("INSERT INTO film_cast VALUES (1,'Actor Three',103)")
    conn.execute("INSERT INTO film_cast VALUES (1,'Actor Four',104)")
    conn.execute("INSERT INTO recommendations VALUES ('u', 1, 92.0, 4.1, NULL, 'now')")
    conn.commit()
    app = create_app(conn_factory=lambda: conn, refresh_fn=lambda conn, username=None, on_progress=None, cancel_event=None: None)
    client = TestClient(app)
    code = _claim(conn, "u")
    row = client.get("/api/recommendations", params={"username": "u"},
                     headers=_auth(code)).json()[0]
    assert row["starring"] == ["Actor One", "Actor Two", "Actor Three"]
    assert row["imdb_rating"] == 8.1
    assert row["rt_score"] == 90
    assert row["vote_avg"] == 7.9

def test_get_recommendations_scoped_by_username(tmp_path):
    conn = connect(TEST_DSN); init_schema(conn); _seed(conn)
    app = create_app(conn_factory=lambda: conn, refresh_fn=lambda conn, username=None, on_progress=None, cancel_event=None: None)
    client = TestClient(app)
    bob_code = _claim(conn, "bob")
    resp = client.get("/api/recommendations", params={"username": "bob"}, headers=_auth(bob_code))
    assert resp.status_code == 200
    assert resp.json() == []  # bob has no recommendations, alice's don't leak

def test_get_film_detail_returns_full_metadata(tmp_path):
    conn = connect(TEST_DSN); init_schema(conn)
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
    conn = connect(TEST_DSN); init_schema(conn)
    app = create_app(conn_factory=lambda: conn, refresh_fn=lambda conn, username=None, on_progress=None, cancel_event=None: None)
    client = TestClient(app)
    resp = client.get("/api/films/999999")
    assert resp.status_code == 404

def test_get_taste_profile_scoped_by_username(tmp_path):
    conn = connect(TEST_DSN); init_schema(conn)
    conn.execute("INSERT INTO films (tmdb_id,title,year,decade) VALUES (1,'X',2000,2000)")
    conn.execute("INSERT INTO film_genres VALUES (1,'Thriller')")
    conn.execute("INSERT INTO ratings (username,film_id,your_rating) VALUES ('alice',1,5.0)")
    conn.commit()
    app = create_app(conn_factory=lambda: conn, refresh_fn=lambda conn, username=None, on_progress=None, cancel_event=None: None)
    client = TestClient(app)
    alice_code, bob_code = _claim(conn, "alice"), _claim(conn, "bob")
    resp = client.get("/api/taste-profile", params={"username": "alice"}, headers=_auth(alice_code))
    body = resp.json()
    assert body["total_rated"] == 1
    assert body["genre_affinities"][0]["name"] == "Thriller"
    resp_bob = client.get("/api/taste-profile", params={"username": "bob"}, headers=_auth(bob_code))
    assert resp_bob.json()["total_rated"] == 0

def test_post_refresh_invokes_refresh_fn(tmp_path):
    conn = connect(TEST_DSN); init_schema(conn)
    called = {"n": 0}
    def fake_refresh(c, username=None, on_progress=None, cancel_event=None):
        called["n"] += 1
    app = create_app(conn_factory=lambda: conn, refresh_fn=fake_refresh)
    client = TestClient(app)
    code = _claim(conn, "alice")
    resp = client.post("/api/refresh", json={"username": "alice"}, headers=_auth(code))
    assert resp.status_code == 200
    _wait_until(lambda: called["n"] == 1)

def test_post_refresh_passes_username_override(tmp_path):
    conn = connect(TEST_DSN); init_schema(conn)
    seen = {}
    def fake_refresh(c, username=None, on_progress=None, cancel_event=None):
        seen["username"] = username
    app = create_app(conn_factory=lambda: conn, refresh_fn=fake_refresh)
    client = TestClient(app)
    code = _claim(conn, "alice")
    resp = client.post("/api/refresh", json={"username": "alice"}, headers=_auth(code))
    assert resp.status_code == 200
    _wait_until(lambda: seen.get("username") == "alice")

def test_post_refresh_without_a_username_is_rejected(tmp_path):
    conn = connect(TEST_DSN); init_schema(conn)
    seen = {}
    def fake_refresh(c, username=None, on_progress=None, cancel_event=None):
        seen["username"] = username
    app = create_app(conn_factory=lambda: conn, refresh_fn=fake_refresh)
    client = TestClient(app)
    resp = client.post("/api/refresh")
    assert resp.status_code == 403
    assert seen == {}  # and no TMDB-spending work was started

def test_refresh_status_reflects_progress_reported_during_refresh(tmp_path):
    conn = connect(TEST_DSN); init_schema(conn)
    def fake_refresh(c, username=None, on_progress=None, cancel_event=None):
        on_progress({"stage": "enriching", "current": 3, "total": 10, "message": "..."})
    app = create_app(conn_factory=lambda: conn, refresh_fn=fake_refresh)
    client = TestClient(app)
    code = _claim(conn, "alice")
    client.post("/api/refresh", json={"username": "alice"}, headers=_auth(code))

    body = {}
    def check():
        nonlocal body
        body = client.get("/api/refresh/status", params={"username": "alice"},
                          headers=_auth(code)).json()
        return body.get("stage") == "enriching"
    _wait_until(check)

    assert body["current"] == 3
    assert body["total"] == 10

def test_post_refresh_rejects_concurrent_start_for_same_user(tmp_path):
    conn = connect(TEST_DSN); init_schema(conn)
    started = threading.Event()
    finish = threading.Event()
    def fake_refresh(c, username=None, on_progress=None, cancel_event=None):
        started.set()
        finish.wait(timeout=2)
    app = create_app(conn_factory=lambda: conn, refresh_fn=fake_refresh)
    client = TestClient(app)
    code = _claim(conn, "alice")
    client.post("/api/refresh", json={"username": "alice"}, headers=_auth(code))
    assert started.wait(timeout=1)
    resp = client.post("/api/refresh", json={"username": "alice"}, headers=_auth(code))
    assert resp.json()["status"] == "already_running"
    finish.set()

def test_refresh_status_defaults_to_idle(tmp_path):
    conn = connect(TEST_DSN); init_schema(conn)
    app = create_app(conn_factory=lambda: conn, refresh_fn=lambda c, username=None, on_progress=None, cancel_event=None: None)
    client = TestClient(app)
    code = _claim(conn, "alice")
    resp = client.get("/api/refresh/status", params={"username": "alice"}, headers=_auth(code))
    assert resp.status_code == 200
    assert resp.json()["stage"] in ("idle", "done")

def test_get_watch_providers_returns_normalized_data(tmp_path):
    conn = connect(TEST_DSN); init_schema(conn)
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
    conn = connect(TEST_DSN); init_schema(conn)
    started = threading.Event()
    from app.errors import Cancelled
    def fake_refresh(c, username=None, on_progress=None, cancel_event=None):
        started.set()
        while not cancel_event.is_set():
            time.sleep(0.01)
        raise Cancelled()
    app = create_app(conn_factory=lambda: conn, refresh_fn=fake_refresh)
    client = TestClient(app)
    code = _claim(conn, "alice")
    client.post("/api/refresh", json={"username": "alice"}, headers=_auth(code))
    assert started.wait(timeout=1)

    resp = client.post("/api/refresh/cancel", json={"username": "alice"}, headers=_auth(code))
    assert resp.status_code == 200

    body = {}
    def check():
        nonlocal body
        body = client.get("/api/refresh/status", params={"username": "alice"},
                          headers=_auth(code)).json()
        return body.get("stage") == "cancelled"
    _wait_until(check)
    assert body["stage"] == "cancelled"

def test_cancel_event_cleared_when_new_run_starts(tmp_path):
    conn = connect(TEST_DSN); init_schema(conn)
    seen_cancel_states = []
    def fake_refresh(c, username=None, on_progress=None, cancel_event=None):
        seen_cancel_states.append(cancel_event.is_set())
        # Reach a terminal stage, like a well-behaved refresh_fn, so the next
        # POST isn't rejected by the already-running gate.
        on_progress({"stage": "done", "current": 0, "total": None, "message": "Done"})
    app = create_app(conn_factory=lambda: conn, refresh_fn=fake_refresh)
    client = TestClient(app)

    code = _claim(conn, "alice")
    client.post("/api/refresh", json={"username": "alice"}, headers=_auth(code))
    _wait_until(lambda: len(seen_cancel_states) == 1)
    client.post("/api/refresh/cancel", json={"username": "alice"}, headers=_auth(code))

    client.post("/api/refresh", json={"username": "alice"}, headers=_auth(code))
    _wait_until(lambda: len(seen_cancel_states) == 2)
    assert seen_cancel_states[1] is False  # fresh event for the new run, not the old cancelled one

def _noop_refresh(conn, username=None, on_progress=None, cancel_event=None):
    return None

def _client(conn):
    return TestClient(create_app(conn_factory=lambda: conn, refresh_fn=_noop_refresh))

def _upload(client, data, filename="letterboxd-sample-2026-07-30-19-33-utc.zip",
            code=None, **form):
    return client.post("/api/import", files={"file": (filename, data, "application/zip")},
                       data=form, headers=_auth(code) if code else None)

def test_post_import_stores_films_and_returns_counts():
    from tests.test_importer import sample_zip
    conn = _mem_conn()
    resp = _upload(_client(conn), sample_zip(
        ratings_rows=("2026-02-05,Parasite,2019,https://boxd.it/293w,5\n"
                      "2026-02-06,Cats,2019,https://boxd.it/xxx,1\n"),
        watched_rows="2026-02-07,Unrated,2020,https://boxd.it/yyy\n"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["username"] == "sampleuser"
    assert body["imported"] == 3
    assert body["rated"] == 2
    assert body["imported_at"]
    assert load_imported_films(conn, "sampleuser")[0]["title"] == "Parasite"

def test_post_import_replaces_a_previous_import():
    from tests.test_importer import sample_zip
    conn = _mem_conn()
    client = _client(conn)
    first = _upload(client, sample_zip(ratings_rows="2026-02-05,Old,2019,https://boxd.it/old,5\n",
                                       watched_rows=""))
    code = first.json()["access_code"]
    _upload(client, sample_zip(ratings_rows="2026-02-05,New,2020,https://boxd.it/new,4\n",
                               watched_rows=""), code=code)
    assert [f["title"] for f in load_imported_films(conn, "sampleuser")] == ["New"]

def test_post_import_falls_back_to_the_submitted_username():
    from tests.test_importer import RATINGS_HEADER, make_zip
    conn = _mem_conn()
    data = make_zip(**{"ratings.csv": RATINGS_HEADER + "2026-02-05,P,2019,https://boxd.it/a,5\n"})
    resp = _upload(_client(conn), data, username="typed_name")
    assert resp.status_code == 200
    assert resp.json()["username"] == "typed_name"

def test_post_import_400s_when_no_username_can_be_determined():
    from tests.test_importer import RATINGS_HEADER, make_zip
    data = make_zip(**{"ratings.csv": RATINGS_HEADER + "2026-02-05,P,2019,https://boxd.it/a,5\n"})
    resp = _upload(_client(_mem_conn()), data)
    assert resp.status_code == 400
    assert "username" in resp.json()["detail"].lower()

def test_post_import_400s_on_a_non_zip_upload():
    resp = _upload(_client(_mem_conn()), b"Name,Year\nParasite,2019\n", filename="ratings.csv")
    assert resp.status_code == 400
    assert "zip" in resp.json()["detail"]

def test_post_import_400s_when_ratings_csv_is_missing():
    from tests.test_importer import PROFILE, make_zip
    resp = _upload(_client(_mem_conn()), make_zip(**{"profile.csv": PROFILE}))
    assert resp.status_code == 400
    assert "ratings.csv" in resp.json()["detail"]

def test_get_import_status_reports_the_stored_import():
    from tests.test_importer import sample_zip
    conn = _mem_conn()
    client = _client(conn)
    code = _upload(client, sample_zip()).json()["access_code"]
    body = client.get("/api/import/status", params={"username": "sampleuser"},
                      headers=_auth(code)).json()
    assert body["imported"] == 1
    assert body["rated"] == 1
    assert body["imported_at"]

def test_get_import_status_is_empty_before_any_import():
    body = _client(_mem_conn()).get("/api/import/status", params={"username": "nobody"}).json()
    assert body == {"imported": 0, "rated": 0, "imported_at": None, "claimed": False}

def _real_refresh_env(monkeypatch, tmp_path, conn, search_results):
    """Wires _real_refresh up with every network layer stubbed, and captures the
    films its resolve_fn produced."""
    import app.api as api_mod
    from app.config import Config

    monkeypatch.setattr(api_mod, "load_config", lambda: Config(
        username="sampleuser", tmdb_api_key="KEY", database_url="postgresql:///unused"))
    monkeypatch.setattr(api_mod, "search_movie",
                        lambda title, year, key: search_results.get(title))

    captured = {}
    def fake_run_refresh(conn_, cfg, deps, on_progress=None, cancel_event=None):
        films = deps.load_films_fn(cfg.username)
        deps.resolve_fn(films, on_progress=lambda n: None, should_cancel=None)
        captured["films"] = films
    monkeypatch.setattr(api_mod, "run_refresh", fake_run_refresh)
    api_mod._real_refresh(conn, "sampleuser")
    return captured["films"]

def test_real_refresh_resolves_imported_films_via_tmdb_search(monkeypatch, tmp_path):
    from tests.test_importer import sample_zip
    from app.db import lookup_slug_tmdb

    conn = _mem_conn()
    _upload(_client(conn), sample_zip(
        ratings_rows=("2026-02-05,Parasite,2019,https://boxd.it/293w,5\n"
                      "2026-02-06,Obscure Short,1974,https://boxd.it/zzz,3\n"),
        watched_rows=""))

    films = _real_refresh_env(monkeypatch, tmp_path, conn, {"Parasite": 496243})
    by_key = {f["slug"]: f for f in films}
    assert by_key["293w"]["tmdb_id"] == 496243
    assert by_key["zzz"]["tmdb_id"] is None            # unmatched, dropped downstream
    assert lookup_slug_tmdb(conn, "293w") == (496243,)  # cached under the boxd.it code
    # written back so the row records its own resolution
    assert load_imported_films(conn, "sampleuser")[0]["tmdb_id"] == 496243

def test_real_refresh_reuses_the_cache_on_a_second_run(monkeypatch, tmp_path):
    from tests.test_importer import sample_zip

    conn = _mem_conn()
    _upload(_client(conn), sample_zip(
        ratings_rows="2026-02-05,Parasite,2019,https://boxd.it/293w,5\n", watched_rows=""))
    _real_refresh_env(monkeypatch, tmp_path, conn, {"Parasite": 496243})

    # search now returns nothing: a second run must still resolve, from cache
    films = _real_refresh_env(monkeypatch, tmp_path, conn, {})
    assert films[0]["tmdb_id"] == 496243

def test_real_refresh_never_imports_a_scraper():
    import app.api as api_mod
    source = inspect.getsource(api_mod)
    assert "scraper" not in source and "playwright" not in source.lower()

def test_cors_origin_regex_allows_matching_preview_origins():
    app = create_app(conn_factory=_mem_conn, refresh_fn=_noop_refresh,
                     cors_origins=("https://reel.example.com",),
                     cors_origin_regex=r"https://reel-.*\.vercel\.app")
    client = TestClient(app)
    resp = client.options("/api/import", headers={
        "Origin": "https://reel-git-abc123.vercel.app",
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })
    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == "https://reel-git-abc123.vercel.app"

def test_cors_still_rejects_unrelated_origins():
    app = create_app(conn_factory=_mem_conn, refresh_fn=_noop_refresh,
                     cors_origins=("https://reel.example.com",),
                     cors_origin_regex=r"https://reel-.*\.vercel\.app")
    resp = TestClient(app).options("/api/import", headers={
        "Origin": "https://evil.example.com",
        "Access-Control-Request-Method": "POST",
    })
    assert "access-control-allow-origin" not in resp.headers

# --- access codes -----------------------------------------------------------

def test_first_import_mints_an_access_code():
    from tests.test_importer import sample_zip
    resp = _upload(_client(_mem_conn()), sample_zip())
    assert resp.status_code == 200
    assert len(resp.json()["access_code"]) >= 32

def test_second_import_without_the_code_cannot_overwrite():
    from tests.test_importer import sample_zip
    conn = _mem_conn()
    client = _client(conn)
    _upload(client, sample_zip(ratings_rows="2026-02-05,Kept,2019,https://boxd.it/keep,5\n",
                               watched_rows=""))
    resp = _upload(client, sample_zip(ratings_rows="2026-02-05,Evil,2020,https://boxd.it/evil,1\n",
                                      watched_rows=""))
    assert resp.status_code == 403
    assert [f["title"] for f in load_imported_films(conn, "sampleuser")] == ["Kept"]

def test_second_import_with_a_wrong_code_cannot_overwrite():
    from tests.test_importer import sample_zip
    conn = _mem_conn()
    client = _client(conn)
    _upload(client, sample_zip(ratings_rows="2026-02-05,Kept,2019,https://boxd.it/keep,5\n",
                               watched_rows=""))
    resp = _upload(client, sample_zip(ratings_rows="2026-02-05,Evil,2020,https://boxd.it/evil,1\n",
                                      watched_rows=""), code=mint_token())
    assert resp.status_code == 403
    assert [f["title"] for f in load_imported_films(conn, "sampleuser")] == ["Kept"]

def test_only_the_first_import_returns_a_code():
    from tests.test_importer import sample_zip
    client = _client(_mem_conn())
    code = _upload(client, sample_zip()).json()["access_code"]
    assert "access_code" not in _upload(client, sample_zip(), code=code).json()

def test_recommendations_reject_a_missing_or_wrong_code(tmp_path):
    conn = connect(TEST_DSN); init_schema(conn); _seed(conn)
    _claim(conn, "alice")
    client = TestClient(create_app(conn_factory=lambda: conn, refresh_fn=_noop_refresh))
    assert client.get("/api/recommendations", params={"username": "alice"}).status_code == 403
    assert client.get("/api/recommendations", params={"username": "alice"},
                      headers=_auth(mint_token())).status_code == 403

def test_taste_profile_rejects_a_missing_code(tmp_path):
    conn = connect(TEST_DSN); init_schema(conn)
    conn.execute("INSERT INTO films (tmdb_id,title,year,decade) VALUES (1,'X',2000,2000)")
    conn.execute("INSERT INTO ratings (username,film_id,your_rating) VALUES ('alice',1,5.0)")
    conn.commit()
    _claim(conn, "alice")
    client = TestClient(create_app(conn_factory=lambda: conn, refresh_fn=_noop_refresh))
    assert client.get("/api/taste-profile", params={"username": "alice"}).status_code == 403

def test_last_updated_rejects_a_missing_code():
    conn = _mem_conn(); _claim(conn, "alice")
    client = TestClient(create_app(conn_factory=lambda: conn, refresh_fn=_noop_refresh))
    assert client.get("/api/last-updated", params={"username": "alice"}).status_code == 403

def test_refresh_rejects_a_missing_code():
    conn = _mem_conn(); _claim(conn, "alice")
    started = []
    def fake_refresh(c, username=None, on_progress=None, cancel_event=None):
        started.append(username)
    client = TestClient(create_app(conn_factory=lambda: conn, refresh_fn=fake_refresh))
    assert client.post("/api/refresh", json={"username": "alice"}).status_code == 403
    assert started == []  # no TMDB quota spent on an unauthorized caller

def test_refresh_status_rejects_a_missing_code():
    conn = _mem_conn(); _claim(conn, "alice")
    client = TestClient(create_app(conn_factory=lambda: conn, refresh_fn=_noop_refresh))
    assert client.get("/api/refresh/status", params={"username": "alice"}).status_code == 403

def test_refresh_cancel_rejects_a_missing_code():
    conn = _mem_conn(); _claim(conn, "alice")
    client = TestClient(create_app(conn_factory=lambda: conn, refresh_fn=_noop_refresh))
    assert client.post("/api/refresh/cancel", json={"username": "alice"}).status_code == 403

def test_import_status_without_a_code_reveals_only_whether_a_name_is_claimed():
    from tests.test_importer import sample_zip
    conn = _mem_conn()
    client = _client(conn)

    unclaimed = client.get("/api/import/status", params={"username": "nobody"}).json()
    assert unclaimed == {"imported": 0, "rated": 0, "imported_at": None, "claimed": False}

    code = _upload(client, sample_zip()).json()["access_code"]
    guessing = client.get("/api/import/status", params={"username": "sampleuser"}).json()
    assert guessing["claimed"] is True
    assert guessing["imported"] == 0  # counts stay hidden without the code

    owner = client.get("/api/import/status", params={"username": "sampleuser"},
                       headers=_auth(code)).json()
    assert owner["imported"] == 1

# --- secret leakage ---------------------------------------------------------

def test_refresh_error_message_never_leaks_the_tmdb_api_key():
    """A requests HTTPError embeds the full URL, and TMDB takes the key as a
    query parameter — so an upstream 401 used to publish a live key through the
    progress endpoint, which anyone could poll."""
    import requests
    conn = _mem_conn()
    code = _claim(conn, "alice")

    def exploding_refresh(c, username=None, on_progress=None, cancel_event=None):
        resp = requests.Response()
        resp.status_code = 401
        resp.reason = "Unauthorized"
        resp.url = "https://api.themoviedb.org/3/movie/550%sapi_key=SUPERSECRETKEY123&x=1"
        resp.raise_for_status()

    client = TestClient(create_app(conn_factory=lambda: conn, refresh_fn=exploding_refresh))
    client.post("/api/refresh", json={"username": "alice"}, headers=_auth(code))

    body = {}
    def check():
        nonlocal body
        body = client.get("/api/refresh/status", params={"username": "alice"},
                          headers=_auth(code)).json()
        return body.get("stage") == "error"
    _wait_until(check)

    assert "SUPERSECRETKEY123" not in json.dumps(body)
    assert "[redacted]" in body["message"]

# --- rate limiting ----------------------------------------------------------

def test_rate_limit_returns_429_once_the_ceiling_is_hit():
    conn = _mem_conn()
    app = create_app(conn_factory=lambda: conn, refresh_fn=_noop_refresh,
                     default_rate_limit=(2, 60.0))
    client = TestClient(app)
    assert client.get("/api/films/1").status_code in (200, 404)
    assert client.get("/api/films/1").status_code in (200, 404)
    assert client.get("/api/films/1").status_code == 429

def test_a_rate_limited_response_still_carries_cors_headers():
    """A bare 429 from outside the CORS middleware reaches the browser as an
    opaque CORS failure instead of a readable 'slow down'."""
    conn = _mem_conn()
    app = create_app(conn_factory=lambda: conn, refresh_fn=_noop_refresh,
                     cors_origins=("https://reel.example.com",), default_rate_limit=(1, 60.0))
    client = TestClient(app)
    client.get("/api/films/1", headers={"Origin": "https://reel.example.com"})
    resp = client.get("/api/films/1", headers={"Origin": "https://reel.example.com"})
    assert resp.status_code == 429
    assert resp.headers["access-control-allow-origin"] == "https://reel.example.com"

def test_import_and_refresh_have_tighter_ceilings_than_plain_reads():
    from app.api import DEFAULT_RATE_LIMIT, RATE_LIMITS
    reads_per_hour = DEFAULT_RATE_LIMIT[0] * (3600 / DEFAULT_RATE_LIMIT[1])
    for path in ("/api/import", "/api/refresh"):
        limit, window = RATE_LIMITS[path]
        assert limit * (3600 / window) < reads_per_hour

def test_healthz_needs_no_database_and_no_access_code():
    """Render restarts an instance whose health check times out, which kills any
    in-flight refresh. So this endpoint must not open a connection."""
    def exploding_conn():
        raise AssertionError("health check must not touch the database")
    client = TestClient(create_app(conn_factory=exploding_conn, refresh_fn=_noop_refresh))
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

def test_recommendations_does_not_query_cast_once_per_row():
    """At 800 recommendations the per-row cast lookup made the endpoint take
    over a minute, which is indistinguishable from broken."""
    conn = _mem_conn()
    for i in range(1, 41):
        conn.execute("INSERT INTO films (tmdb_id,title,year) VALUES (%s,%s,2000)", (i, f"F{i}"))
        conn.execute("INSERT INTO film_cast VALUES (%s,%s,%s)", (i, f"Actor{i}", i))
        conn.execute("INSERT INTO recommendations VALUES ('alice',%s,90.0,4.0,NULL,'now')", (i,))
    conn.commit()
    code = _claim(conn, "alice")

    queries = {"n": 0}
    real_execute = conn.execute
    class CountingConn:
        def __getattr__(self, k): return getattr(conn, k)
        def execute(self, *a, **kw): queries["n"] += 1; return real_execute(*a, **kw)

    client = TestClient(create_app(conn_factory=lambda: CountingConn(), refresh_fn=_noop_refresh))
    body = client.get("/api/recommendations", params={"username": "alice"},
                      headers=_auth(code)).json()
    assert len(body) == 40
    assert body[0]["starring"] == ["Actor1"]
    # auth + rows + cast — a handful, not one per recommendation
    assert queries["n"] <= 5, f"40 recommendations issued {queries['n']} queries"

def test_schema_is_initialised_once_not_per_request(monkeypatch, tmp_path):
    """Twenty DDL statements per request meant twenty round trips and DDL locks
    that concurrent callers blocked on; the API looked hung."""
    import app.api as api_mod
    from app.config import Config
    from tests.conftest import TEST_DSN
    calls = {"n": 0}
    real_init = api_mod.init_schema
    monkeypatch.setattr(api_mod, "init_schema",
                        lambda c: (calls.__setitem__("n", calls["n"] + 1), real_init(c))[1])
    monkeypatch.setattr(api_mod, "load_config", lambda: Config(
        username="", tmdb_api_key="k", database_url=TEST_DSN))
    client = TestClient(api_mod.create_app(refresh_fn=_noop_refresh))
    for _ in range(4):
        client.get("/api/import/status", params={"username": "nobody"})
    assert calls["n"] == 1, f"init_schema ran {calls['n']} times across 4 requests"
