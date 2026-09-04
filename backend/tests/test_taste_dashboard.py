from app.db import connect, init_schema
from app.taste_dashboard import build_dashboard
from tests.conftest import TEST_DSN

def _seed_alice(conn):
    films = [
        (1, "Parasite", 2019, 2010, "Bong Joon-ho", 21684),
        (2, "Snowpiercer", 2013, 2010, "Bong Joon-ho", 21684),
        (3, "Rom Com", 2015, 2010, "Someone Else", 2),
    ]
    for tmdb_id, title, year, decade, director, director_id in films:
        conn.execute(
            "INSERT INTO films (tmdb_id,title,year,decade,director,director_id) VALUES (%s,%s,%s,%s,%s,%s)",
            (tmdb_id, title, year, decade, director, director_id))
    conn.execute("INSERT INTO people VALUES (21684,'Bong Joon-ho','/d.jpg')")
    conn.execute("INSERT INTO people VALUES (1523,'Song Kang-ho','/a.jpg')")
    conn.execute("INSERT INTO film_genres VALUES (1,'Thriller')")
    conn.execute("INSERT INTO film_genres VALUES (2,'Thriller')")
    conn.execute("INSERT INTO film_genres VALUES (3,'Romance')")
    conn.execute("INSERT INTO film_cast VALUES (1,'Song Kang-ho',1523)")
    conn.execute("INSERT INTO film_cast VALUES (2,'Song Kang-ho',1523)")
    conn.execute("INSERT INTO ratings (username,film_id,your_rating) VALUES ('alice',1,5.0)")
    conn.execute("INSERT INTO ratings (username,film_id,your_rating) VALUES ('alice',2,4.5)")
    conn.execute("INSERT INTO ratings (username,film_id,your_rating) VALUES ('alice',3,2.0)")
    conn.commit()

def test_build_dashboard_totals_and_average(tmp_path):
    conn = connect(TEST_DSN); init_schema(conn); _seed_alice(conn)
    dash = build_dashboard(conn, "alice")
    assert dash["total_rated"] == 3
    assert round(dash["average_rating"], 2) == round((5.0 + 4.5 + 2.0) / 3, 2)

def test_build_dashboard_favorite_decade(tmp_path):
    conn = connect(TEST_DSN); init_schema(conn); _seed_alice(conn)
    dash = build_dashboard(conn, "alice")
    assert dash["favorite_decade"] == 2010

def test_rating_distribution_uses_half_star_buckets():
    from app.taste_dashboard import _rating_distribution
    rows = [{"your_rating": 4.5}, {"your_rating": 4.5}, {"your_rating": 3.0}, {"your_rating": 0.5}]
    dist = _rating_distribution(rows)
    assert [b["star"] for b in dist] == [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]
    by = {b["star"]: b["count"] for b in dist}
    assert by[4.5] == 2 and by[3.0] == 1 and by[0.5] == 1

def test_build_dashboard_rating_distribution_buckets_by_half_star(tmp_path):
    conn = connect(TEST_DSN); init_schema(conn); _seed_alice(conn)
    dash = build_dashboard(conn, "alice")
    dist = {b["star"]: b["count"] for b in dash["rating_distribution"]}
    assert dist[5.0] == 1 and dist[4.5] == 1  # 5.0 and 4.5 now land in separate half-star buckets
    assert dist[2.0] == 1

def test_top_directors_include_top_films(tmp_path):
    conn = connect(TEST_DSN); init_schema(conn); _seed_alice(conn)
    dash = build_dashboard(conn, "alice")
    d0 = dash["top_directors"][0]
    assert "top_films" in d0 and len(d0["top_films"]) <= 3
    assert d0["top_films"] == sorted(d0["top_films"], key=lambda f: f["rating"], reverse=True)
    assert {"title", "year", "rating", "poster_path"} <= set(d0["top_films"][0])

def test_build_dashboard_top_director_has_headshot(tmp_path):
    conn = connect(TEST_DSN); init_schema(conn); _seed_alice(conn)
    dash = build_dashboard(conn, "alice")
    top = dash["top_directors"][0]
    assert top["name"] == "Bong Joon-ho"
    assert top["profile_path"] == "/d.jpg"

def test_build_dashboard_top_actor_has_headshot(tmp_path):
    conn = connect(TEST_DSN); init_schema(conn); _seed_alice(conn)
    dash = build_dashboard(conn, "alice")
    top = dash["top_actors"][0]
    assert top["name"] == "Song Kang-ho"
    assert top["profile_path"] == "/a.jpg"

def test_build_dashboard_genre_affinities_for_radar(tmp_path):
    conn = connect(TEST_DSN); init_schema(conn); _seed_alice(conn)
    dash = build_dashboard(conn, "alice")
    genres = {g["name"] for g in dash["genre_affinities"]}
    assert genres == {"Thriller", "Romance"}

def test_build_dashboard_signature_is_a_nonempty_sentence(tmp_path):
    conn = connect(TEST_DSN); init_schema(conn); _seed_alice(conn)
    dash = build_dashboard(conn, "alice")
    assert isinstance(dash["signature"], str) and dash["signature"].endswith(".")

def test_build_dashboard_empty_for_user_with_no_ratings(tmp_path):
    conn = connect(TEST_DSN); init_schema(conn)
    dash = build_dashboard(conn, "nobody")
    assert dash["total_rated"] == 0
    assert dash["top_directors"] == []
    assert dash["top_actors"] == []

def test_dashboard_does_not_query_per_rated_film():
    """Four queries per film meant ~380 round trips for a 95-film profile and a
    twenty-second response every time the tab was opened."""
    conn = connect(TEST_DSN); init_schema(conn)
    for i in range(1, 41):
        conn.execute("INSERT INTO films (tmdb_id,title,year,decade,director)"
                     " VALUES (%s,%s,2000,2000,%s)", (i, f"F{i}", f"Dir{i}"))
        conn.execute("INSERT INTO film_genres VALUES (%s,'Drama')", (i,))
        conn.execute("INSERT INTO film_keywords VALUES (%s,'kw')", (i,))
        conn.execute("INSERT INTO film_cast VALUES (%s,%s,%s)", (i, f"Actor{i}", i))
        conn.execute("INSERT INTO ratings (username,film_id,your_rating)"
                     " VALUES ('alice',%s,4.0)", (i,))
    conn.commit()

    queries = {"n": 0}
    real_execute = conn.execute
    class CountingConn:
        def __getattr__(self, k): return getattr(conn, k)
        def execute(self, *a, **kw): queries["n"] += 1; return real_execute(*a, **kw)

    dash = build_dashboard(CountingConn(), "alice")
    assert dash["total_rated"] == 40
    assert dash["genre_affinities"][0]["name"] == "Drama"
    # rated rows + genres + keywords + cast + directors + people lookups — a
    # fixed handful, not four per film
    assert queries["n"] <= 10, f"40 rated films issued {queries['n']} queries"
