from app.db import connect, init_schema
from app.taste_dashboard import build_dashboard

def _seed_alice(conn):
    films = [
        (1, "Parasite", 2019, 2010, "Bong Joon-ho", 21684),
        (2, "Snowpiercer", 2013, 2010, "Bong Joon-ho", 21684),
        (3, "Rom Com", 2015, 2010, "Someone Else", 2),
    ]
    for tmdb_id, title, year, decade, director, director_id in films:
        conn.execute(
            "INSERT INTO films (tmdb_id,title,year,decade,director,director_id) VALUES (?,?,?,?,?,?)",
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
    conn = connect(str(tmp_path / "t.db")); init_schema(conn); _seed_alice(conn)
    dash = build_dashboard(conn, "alice")
    assert dash["total_rated"] == 3
    assert round(dash["average_rating"], 2) == round((5.0 + 4.5 + 2.0) / 3, 2)

def test_build_dashboard_favorite_decade(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn); _seed_alice(conn)
    dash = build_dashboard(conn, "alice")
    assert dash["favorite_decade"] == 2010

def test_build_dashboard_rating_distribution_buckets_by_whole_star(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn); _seed_alice(conn)
    dash = build_dashboard(conn, "alice")
    dist = {b["star"]: b["count"] for b in dash["rating_distribution"]}
    assert dist[5] == 2  # 5.0 and 4.5 both round up into the 5-star bucket
    assert dist[2] == 1

def test_build_dashboard_top_director_has_headshot(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn); _seed_alice(conn)
    dash = build_dashboard(conn, "alice")
    top = dash["top_directors"][0]
    assert top["name"] == "Bong Joon-ho"
    assert top["profile_path"] == "/d.jpg"

def test_build_dashboard_top_actor_has_headshot(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn); _seed_alice(conn)
    dash = build_dashboard(conn, "alice")
    top = dash["top_actors"][0]
    assert top["name"] == "Song Kang-ho"
    assert top["profile_path"] == "/a.jpg"

def test_build_dashboard_genre_affinities_for_radar(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn); _seed_alice(conn)
    dash = build_dashboard(conn, "alice")
    genres = {g["name"] for g in dash["genre_affinities"]}
    assert genres == {"Thriller", "Romance"}

def test_build_dashboard_signature_is_a_nonempty_sentence(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn); _seed_alice(conn)
    dash = build_dashboard(conn, "alice")
    assert isinstance(dash["signature"], str) and dash["signature"].endswith(".")

def test_build_dashboard_empty_for_user_with_no_ratings(tmp_path):
    conn = connect(str(tmp_path / "t.db")); init_schema(conn)
    dash = build_dashboard(conn, "nobody")
    assert dash["total_rated"] == 0
    assert dash["top_directors"] == []
    assert dash["top_actors"] == []
