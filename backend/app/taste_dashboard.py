from app.profile import build_taste_profile

TOUGH_GRADER_THRESHOLD = 3.3

def _rated_films(conn, username):
    rows = conn.execute(
        "SELECT f.tmdb_id, f.decade, r.your_rating"
        " FROM ratings r JOIN films f ON f.tmdb_id = r.film_id"
        " WHERE r.username = ?", (username,)).fetchall()
    return rows

def _rating_distribution(rows):
    buckets = {star: 0 for star in range(1, 6)}
    for r in rows:
        star = max(1, min(5, int(r["your_rating"] + 0.5)))  # round half up, not banker's rounding
        buckets[star] += 1
    return [{"star": s, "count": c} for s, c in sorted(buckets.items())]

def _favorite_decade(rows):
    counts = {}
    for r in rows:
        if r["decade"] is not None:
            counts[r["decade"]] = counts.get(r["decade"], 0) + 1
    return max(counts, key=counts.get) if counts else None

def _top_people(conn, username, role_table, role_col, person_col):
    rows = conn.execute(
        f"SELECT p.name, p.profile_path, COUNT(*) c"
        f" FROM {role_table} t"
        f" JOIN ratings r ON r.film_id = t.film_id"
        f" JOIN people p ON p.person_id = t.{person_col}"
        f" WHERE r.username = ? AND t.{person_col} IS NOT NULL"
        f" GROUP BY t.{person_col} ORDER BY c DESC LIMIT 6", (username,)).fetchall()
    return [{"name": r["name"], "profile_path": r["profile_path"], "count": r["c"]} for r in rows]

def _top_directors(conn, username):
    rows = conn.execute(
        "SELECT p.name, p.profile_path, COUNT(*) c"
        " FROM films f"
        " JOIN ratings r ON r.film_id = f.tmdb_id"
        " JOIN people p ON p.person_id = f.director_id"
        " WHERE r.username = ? AND f.director_id IS NOT NULL"
        " GROUP BY f.director_id ORDER BY c DESC LIMIT 6", (username,)).fetchall()
    return [{"name": r["name"], "profile_path": r["profile_path"], "count": r["c"]} for r in rows]

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
            "SELECT genre FROM film_genres WHERE film_id = ?", (r["tmdb_id"],)).fetchall()]
        keywords = [k["keyword"] for k in conn.execute(
            "SELECT keyword FROM film_keywords WHERE film_id = ?", (r["tmdb_id"],)).fetchall()]
        cast = [c["actor"] for c in conn.execute(
            "SELECT actor FROM film_cast WHERE film_id = ?", (r["tmdb_id"],)).fetchall()]
        director_row = conn.execute(
            "SELECT director FROM films WHERE tmdb_id = ?", (r["tmdb_id"],)).fetchone()
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
