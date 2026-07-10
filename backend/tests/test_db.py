from app.db import connect, init_schema, lookup_slug_tmdb, store_slug_tmdb

def test_init_schema_creates_tables(tmp_path):
    db = str(tmp_path / "t.db")
    conn = connect(db)
    init_schema(conn)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    assert {"films", "film_genres", "film_keywords",
            "film_cast", "ratings", "watched", "recommendations"} <= tables

def test_insert_and_read_rating(tmp_path):
    conn = connect(str(tmp_path / "t.db"))
    init_schema(conn)
    conn.execute("INSERT INTO films (tmdb_id, title, year) VALUES (1, 'X', 2000)")
    conn.execute("INSERT INTO ratings (username, film_id, your_rating) VALUES ('alice', 1, 4.5)")
    conn.commit()
    row = conn.execute("SELECT your_rating FROM ratings WHERE film_id=1 AND username='alice'").fetchone()
    assert row[0] == 4.5

def test_ratings_scoped_per_username(tmp_path):
    conn = connect(str(tmp_path / "t.db"))
    init_schema(conn)
    conn.execute("INSERT INTO films (tmdb_id, title, year) VALUES (1, 'X', 2000)")
    conn.execute("INSERT INTO ratings (username, film_id, your_rating) VALUES ('alice', 1, 5.0)")
    conn.execute("INSERT INTO ratings (username, film_id, your_rating) VALUES ('bob', 1, 2.0)")
    conn.commit()
    alice = conn.execute("SELECT your_rating FROM ratings WHERE film_id=1 AND username='alice'").fetchone()
    bob = conn.execute("SELECT your_rating FROM ratings WHERE film_id=1 AND username='bob'").fetchone()
    assert alice[0] == 5.0
    assert bob[0] == 2.0

def test_init_schema_creates_people_table_and_new_columns(tmp_path):
    conn = connect(str(tmp_path / "t.db"))
    init_schema(conn)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "people" in tables

    film_cols = {r[1] for r in conn.execute("PRAGMA table_info(films)")}
    assert {"backdrop_path", "overview", "runtime", "director_id"} <= film_cols

    cast_cols = {r[1] for r in conn.execute("PRAGMA table_info(film_cast)")}
    assert "person_id" in cast_cols

    rec_cols = {r[1] for r in conn.execute("PRAGMA table_info(recommendations)")}
    assert "why" in rec_cols

def test_init_schema_is_idempotent_on_existing_db(tmp_path):
    db = str(tmp_path / "t.db")
    conn = connect(db)
    init_schema(conn)
    init_schema(conn)  # must not raise on second call
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "people" in tables

def test_schema_has_quality_columns(tmp_path):
    from app.db import connect, init_schema
    conn = connect(str(tmp_path / "t.db"))
    init_schema(conn)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(films)").fetchall()}
    assert {"vote_count", "imdb_rating", "rt_score"} <= cols

def test_slug_tmdb_cache_roundtrip():
    conn = connect(":memory:")
    init_schema(conn)
    assert lookup_slug_tmdb(conn, "parasite") is None  # no row yet
    store_slug_tmdb(conn, "parasite", 496243, "search")
    assert lookup_slug_tmdb(conn, "parasite") == (496243,)

def test_slug_tmdb_cache_stores_negative_result():
    conn = connect(":memory:")
    init_schema(conn)
    store_slug_tmdb(conn, "obscure-film", None, "none")
    # row exists (don't re-fetch) but the id is None
    assert lookup_slug_tmdb(conn, "obscure-film") == (None,)

def test_slug_tmdb_cache_upsert_overwrites():
    conn = connect(":memory:")
    init_schema(conn)
    store_slug_tmdb(conn, "parasite", None, "none")
    store_slug_tmdb(conn, "parasite", 496243, "detail")
    assert lookup_slug_tmdb(conn, "parasite") == (496243,)
