from app.db import (connect, init_schema, lookup_slug_tmdb, store_slug_tmdb,
                    replace_imported_films, load_imported_films,
                    set_imported_tmdb_id, import_status)

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

def _films(*rows):
    return [{"boxd_id": b, "title": t, "year": y, "rating": r, "rated_date": d}
            for b, t, y, r, d in rows]

def _fresh():
    conn = connect(":memory:")
    init_schema(conn)
    return conn

def test_init_schema_creates_imported_films_table():
    conn = _fresh()
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "imported_films" in tables
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(imported_films)").fetchall()}
    assert cols == {"username", "boxd_id", "title", "year", "rating",
                    "rated_date", "tmdb_id", "imported_at"}

def test_imported_films_roundtrip():
    conn = _fresh()
    replace_imported_films(conn, "alice", _films(
        ("293w", "Parasite", 2019, 5.0, "2026-02-05"),
        ("wUow", "Aftersun", 2022, None, "2026-02-06"),
    ), imported_at="2026-07-30T00:00:00Z")
    films = load_imported_films(conn, "alice")
    assert [(f["boxd_id"], f["title"], f["year"], f["rating"]) for f in films] == [
        ("293w", "Parasite", 2019, 5.0),
        ("wUow", "Aftersun", 2022, None),
    ]
    assert all(f["tmdb_id"] is None for f in films)  # unresolved until a refresh

def test_replace_imported_films_wipes_previous_import():
    conn = _fresh()
    replace_imported_films(conn, "alice", _films(("old1", "Gone", 1999, 3.0, None)))
    replace_imported_films(conn, "alice", _films(("new1", "Kept", 2020, 4.0, None)))
    assert [f["boxd_id"] for f in load_imported_films(conn, "alice")] == ["new1"]

def test_replace_imported_films_only_touches_that_username():
    conn = _fresh()
    replace_imported_films(conn, "bob", _films(("b1", "Bob's Film", 2001, 4.0, None)))
    replace_imported_films(conn, "alice", _films(("a1", "Alice's Film", 2002, 5.0, None)))
    assert [f["boxd_id"] for f in load_imported_films(conn, "bob")] == ["b1"]

def test_replace_imported_films_upserts_duplicate_boxd_ids():
    conn = _fresh()
    replace_imported_films(conn, "alice", _films(
        ("293w", "Parasite", 2019, 5.0, None),
        ("293w", "Parasite", 2019, 4.0, None),
    ))
    assert len(load_imported_films(conn, "alice")) == 1

def test_set_imported_tmdb_id_persists_resolution():
    conn = _fresh()
    replace_imported_films(conn, "alice", _films(("293w", "Parasite", 2019, 5.0, None)))
    set_imported_tmdb_id(conn, "alice", "293w", 496243)
    assert load_imported_films(conn, "alice")[0]["tmdb_id"] == 496243

def test_import_status_counts_films_and_ratings():
    conn = _fresh()
    replace_imported_films(conn, "alice", _films(
        ("a", "Rated", 2019, 5.0, None),
        ("b", "Also rated", 2020, 3.5, None),
        ("c", "Unrated", 2021, None, None),
    ), imported_at="2026-07-30T00:00:00Z")
    assert import_status(conn, "alice") == {
        "imported": 3, "rated": 2, "imported_at": "2026-07-30T00:00:00Z"}

def test_import_status_when_nothing_imported():
    assert import_status(_fresh(), "nobody") == {
        "imported": 0, "rated": 0, "imported_at": None}
