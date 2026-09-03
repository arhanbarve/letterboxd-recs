import psycopg
from datetime import datetime, timezone
from psycopg.rows import dict_row

SCHEMA = """
CREATE TABLE IF NOT EXISTS films (
    tmdb_id INTEGER PRIMARY KEY,
    title TEXT, year INTEGER, decade INTEGER,
    director TEXT, director_id INTEGER,
    poster_path TEXT, backdrop_path TEXT, overview TEXT, runtime INTEGER,
    tmdb_vote_avg DOUBLE PRECISION, vote_count INTEGER,
    imdb_rating DOUBLE PRECISION, rt_score INTEGER
);
CREATE TABLE IF NOT EXISTS film_genres (film_id INTEGER, genre TEXT);
CREATE TABLE IF NOT EXISTS film_keywords (film_id INTEGER, keyword TEXT);
CREATE TABLE IF NOT EXISTS film_cast (film_id INTEGER, actor TEXT, person_id INTEGER);
CREATE TABLE IF NOT EXISTS people (person_id INTEGER PRIMARY KEY, name TEXT, profile_path TEXT);
CREATE TABLE IF NOT EXISTS ratings (
    username TEXT, film_id INTEGER, your_rating DOUBLE PRECISION, watched_date TEXT,
    PRIMARY KEY (username, film_id)
);
CREATE TABLE IF NOT EXISTS watched (username TEXT, film_id INTEGER, PRIMARY KEY (username, film_id));
CREATE TABLE IF NOT EXISTS recommendations (
    username TEXT, film_id INTEGER, match_pct DOUBLE PRECISION,
    predicted_rating DOUBLE PRECISION, why TEXT, computed_at TEXT,
    PRIMARY KEY (username, film_id)
);
CREATE TABLE IF NOT EXISTS film_slug_tmdb (
    slug TEXT PRIMARY KEY,
    tmdb_id INTEGER,
    resolved_via TEXT
);
CREATE TABLE IF NOT EXISTS user_tokens (
    username TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS imported_films (
    -- Postgres has no rowid, and the export's order is meaningful (rated films
    -- first), so insertion order needs a column of its own to be recoverable.
    id BIGSERIAL,
    username TEXT, boxd_id TEXT, title TEXT, year INTEGER,
    rating DOUBLE PRECISION,  -- NULL = watched but unrated
    rated_date TEXT,          -- ratings.csv Date, orders the scoring seeds
    tmdb_id INTEGER,          -- filled in during a refresh; NULL until then
    imported_at TEXT,
    PRIMARY KEY (username, boxd_id)
);
"""

# Postgres has ADD COLUMN IF NOT EXISTS, so these are plain idempotent DDL —
# no exception-catching dance needed to make init_schema safe on every startup.
_MIGRATIONS = [
    "ALTER TABLE films ADD COLUMN IF NOT EXISTS director_id INTEGER",
    "ALTER TABLE films ADD COLUMN IF NOT EXISTS backdrop_path TEXT",
    "ALTER TABLE films ADD COLUMN IF NOT EXISTS overview TEXT",
    "ALTER TABLE films ADD COLUMN IF NOT EXISTS runtime INTEGER",
    "ALTER TABLE film_cast ADD COLUMN IF NOT EXISTS person_id INTEGER",
    "ALTER TABLE recommendations ADD COLUMN IF NOT EXISTS why TEXT",
    "ALTER TABLE films ADD COLUMN IF NOT EXISTS vote_count INTEGER",
    "ALTER TABLE films ADD COLUMN IF NOT EXISTS imdb_rating DOUBLE PRECISION",
    "ALTER TABLE films ADD COLUMN IF NOT EXISTS rt_score INTEGER",
]

def connect(dsn: str) -> psycopg.Connection:
    """One connection per caller. dict_row keeps every existing row["column"]
    access working unchanged, and dict(row) still produces a plain dict."""
    return psycopg.connect(dsn, row_factory=dict_row)

def init_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA)
    for stmt in _MIGRATIONS:
        conn.execute(stmt)
    conn.commit()

def lookup_slug_tmdb(conn: psycopg.Connection, slug: str) -> tuple | None:
    """Returns None when the slug was never resolved, or a 1-tuple (tmdb_id,)
    when it was — tmdb_id may itself be None, meaning 'confirmed no TMDB link,
    do not re-fetch'."""
    row = conn.execute(
        "SELECT tmdb_id FROM film_slug_tmdb WHERE slug = %s", (slug,)).fetchone()
    return None if row is None else (row["tmdb_id"],)

def store_slug_tmdb(conn: psycopg.Connection, slug: str, tmdb_id: int | None, via: str) -> None:
    conn.execute(
        "INSERT INTO film_slug_tmdb (slug, tmdb_id, resolved_via) VALUES (%s,%s,%s)"
        " ON CONFLICT (slug) DO UPDATE SET"
        " tmdb_id = EXCLUDED.tmdb_id, resolved_via = EXCLUDED.resolved_via",
        (slug, tmdb_id, via))
    conn.commit()  # cache must survive a later run failure

def get_token_hash(conn: psycopg.Connection, username: str) -> str | None:
    """None means the username is unclaimed — nobody has imported under it yet."""
    row = conn.execute(
        "SELECT token_hash FROM user_tokens WHERE username=%s", (username,)).fetchone()
    return row["token_hash"] if row else None

def store_token_hash(conn: psycopg.Connection, username: str, token_hash: str) -> None:
    conn.execute(
        "INSERT INTO user_tokens (username, token_hash, created_at) VALUES (%s,%s,%s)"
        " ON CONFLICT (username) DO UPDATE SET"
        " token_hash = EXCLUDED.token_hash, created_at = EXCLUDED.created_at",
        (username, token_hash, datetime.now(timezone.utc).isoformat()))
    conn.commit()

def replace_imported_films(conn: psycopg.Connection, username: str, films: list[dict],
                           imported_at: str | None = None) -> None:
    """Overwrites this username's imported films. A Letterboxd export is a full
    snapshot, so replacing is the correct semantic — merging would resurrect
    films you have since deleted from your Letterboxd account."""
    imported_at = imported_at or datetime.now(timezone.utc).isoformat()
    conn.execute("DELETE FROM imported_films WHERE username=%s", (username,))
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO imported_films"
            " (username, boxd_id, title, year, rating, rated_date, tmdb_id, imported_at)"
            " VALUES (%s,%s,%s,%s,%s,%s,NULL,%s)"
            " ON CONFLICT (username, boxd_id) DO UPDATE SET"
            " title = EXCLUDED.title, year = EXCLUDED.year, rating = EXCLUDED.rating,"
            " rated_date = EXCLUDED.rated_date, tmdb_id = NULL,"
            " imported_at = EXCLUDED.imported_at",
            [(username, f["boxd_id"], f["title"], f["year"], f["rating"],
              f.get("rated_date"), imported_at) for f in films])
    conn.commit()

def load_imported_films(conn: psycopg.Connection, username: str) -> list[dict]:
    return [{k: v for k, v in r.items() if k != "id"} for r in conn.execute(
        "SELECT id, boxd_id, title, year, rating, rated_date, tmdb_id"
        " FROM imported_films WHERE username=%s ORDER BY id", (username,)).fetchall()]

def set_imported_tmdb_id(conn: psycopg.Connection, username: str, boxd_id: str,
                         tmdb_id: int | None) -> None:
    conn.execute("UPDATE imported_films SET tmdb_id=%s WHERE username=%s AND boxd_id=%s",
                 (tmdb_id, username, boxd_id))

def import_status(conn: psycopg.Connection, username: str) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) AS imported,"
        " COUNT(rating) AS rated,"
        " MAX(imported_at) AS imported_at"
        " FROM imported_films WHERE username=%s", (username,)).fetchone()
    return {"imported": row["imported"], "rated": row["rated"],
            "imported_at": row["imported_at"]}
