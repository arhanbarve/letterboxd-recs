from app.db import connect, init_schema

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
