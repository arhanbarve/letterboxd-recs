from app.profile import build_taste_profile

TOUGH_GRADER_THRESHOLD = 3.3

def _rated_films(conn, username):
    rows = conn.execute(
        "SELECT f.tmdb_id, f.decade, r.your_rating"
        " FROM ratings r JOIN films f ON f.tmdb_id = r.film_id"
        " WHERE r.username = %s", (username,)).fetchall()
    return rows

def _rating_distribution(rows):
    buckets = {round(0.5 * i, 1): 0 for i in range(1, 11)}  # 0.5 .. 5.0
    for r in rows:
        star = round(r["your_rating"] * 2) / 2
        star = max(0.5, min(5.0, star))
        buckets[star] += 1
    return [{"star": s, "count": c} for s, c in sorted(buckets.items())]

def _favorite_decade(rows):
    counts = {}
    for r in rows:
        if r["decade"] is not None:
            counts[r["decade"]] = counts.get(r["decade"], 0) + 1
    return max(counts, key=counts.get) if counts else None

def _person_top_films(conn, username, id_col, id_value, cast_join=False):
    if cast_join:
        sql = ("SELECT f.title, f.year, f.poster_path, r.your_rating AS rating"
               " FROM film_cast t JOIN films f ON f.tmdb_id = t.film_id"
               " JOIN ratings r ON r.film_id = t.film_id"
               " WHERE r.username = %s AND t.person_id = %s"
               " ORDER BY r.your_rating DESC LIMIT 3")
    else:
        sql = ("SELECT f.title, f.year, f.poster_path, r.your_rating AS rating"
               " FROM films f JOIN ratings r ON r.film_id = f.tmdb_id"
               " WHERE r.username = %s AND f.director_id = %s"
               " ORDER BY r.your_rating DESC LIMIT 3")
    return [{"title": x["title"], "year": x["year"], "poster_path": x["poster_path"],
             "rating": x["rating"]} for x in conn.execute(sql, (username, id_value)).fetchall()]

def _top_people(conn, username, role_table, role_col, person_col):
    rows = conn.execute(
        f"SELECT p.name, p.profile_path, t.{person_col} AS pid, COUNT(*) c"
        f" FROM {role_table} t"
        f" JOIN ratings r ON r.film_id = t.film_id"
        f" JOIN people p ON p.person_id = t.{person_col}"
        f" WHERE r.username = %s AND t.{person_col} IS NOT NULL"
        f" GROUP BY t.{person_col}, p.name, p.profile_path"
        f" ORDER BY c DESC LIMIT 6", (username,)).fetchall()
    return [{"name": r["name"], "profile_path": r["profile_path"], "count": r["c"],
             "top_films": _person_top_films(conn, username, person_col, r["pid"], cast_join=True)}
            for r in rows]

def _top_directors(conn, username):
    rows = conn.execute(
        "SELECT p.name, p.profile_path, f.director_id AS pid, COUNT(*) c"
        " FROM films f"
        " JOIN ratings r ON r.film_id = f.tmdb_id"
        " JOIN people p ON p.person_id = f.director_id"
        " WHERE r.username = %s AND f.director_id IS NOT NULL"
        " GROUP BY f.director_id, p.name, p.profile_path"
        " ORDER BY c DESC LIMIT 6", (username,)).fetchall()
    return [{"name": r["name"], "profile_path": r["profile_path"], "count": r["c"],
             "top_films": _person_top_films(conn, username, "director_id", r["pid"], cast_join=False)}
            for r in rows]

def _genre_affinities(profile):
    return [{"name": g, "affinity": round(v, 3)} for g, v in
            sorted(profile["genre"].items(), key=lambda kv: kv[1], reverse=True)]

def _top_keywords(profile, n=8):
    return [k for k, _ in sorted(profile["keyword"].items(), key=lambda kv: kv[1], reverse=True)[:n]]

def _build_signature(avg_rating, top_genre, top_decade):
    tone = "a tough grader" if avg_rating and avg_rating < TOUGH_GRADER_THRESHOLD else "a generous grader"
    parts = [tone[0].upper() + tone[1:]]
    if top_genre:
        parts.append(f"drawn to {top_genre.lower()}")
    if top_decade:
        parts.append(f"with a soft spot for the {top_decade}s")
    return " ".join(parts) + "."

def build_dashboard(conn, username: str) -> dict:
    rated_rows = _rated_films(conn, username)
    total_rated = len(rated_rows)
    average_rating = (sum(r["your_rating"] for r in rated_rows) / total_rated) if total_rated else 0.0

    rated_meta = []
    for r in rated_rows:
        genres = [g["genre"] for g in conn.execute(
            "SELECT genre FROM film_genres WHERE film_id = %s", (r["tmdb_id"],)).fetchall()]
        keywords = [k["keyword"] for k in conn.execute(
            "SELECT keyword FROM film_keywords WHERE film_id = %s", (r["tmdb_id"],)).fetchall()]
        cast = [c["actor"] for c in conn.execute(
            "SELECT actor FROM film_cast WHERE film_id = %s", (r["tmdb_id"],)).fetchall()]
        director_row = conn.execute(
            "SELECT director FROM films WHERE tmdb_id = %s", (r["tmdb_id"],)).fetchone()
        rated_meta.append({
            "rating": r["your_rating"], "genres": genres, "keywords": keywords,
            "cast": cast, "director": director_row["director"] if director_row else None,
            "decade": r["decade"],
        })
    profile = build_taste_profile(rated_meta)
    genre_affinities = _genre_affinities(profile)
    top_genre = genre_affinities[0]["name"] if genre_affinities else None
    favorite_decade = _favorite_decade(rated_rows)

    return {
        "total_rated": total_rated,
        "average_rating": round(average_rating, 2),
        "favorite_decade": favorite_decade,
        "rating_distribution": _rating_distribution(rated_rows),
        "genre_affinities": genre_affinities,
        "top_directors": _top_directors(conn, username),
        "top_actors": _top_people(conn, username, "film_cast", "actor", "person_id"),
        "top_keywords": _top_keywords(profile),
        "signature": _build_signature(average_rating, top_genre, favorite_decade),
    }
