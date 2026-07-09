import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS films (
    tmdb_id INTEGER PRIMARY KEY,
    title TEXT, year INTEGER, decade INTEGER,
    director TEXT, director_id INTEGER,
    poster_path TEXT, backdrop_path TEXT, overview TEXT, runtime INTEGER,
    tmdb_vote_avg REAL
);
CREATE TABLE IF NOT EXISTS film_genres (film_id INTEGER, genre TEXT);
CREATE TABLE IF NOT EXISTS film_keywords (film_id INTEGER, keyword TEXT);
CREATE TABLE IF NOT EXISTS film_cast (film_id INTEGER, actor TEXT, person_id INTEGER);
CREATE TABLE IF NOT EXISTS people (person_id INTEGER PRIMARY KEY, name TEXT, profile_path TEXT);
CREATE TABLE IF NOT EXISTS ratings (
    username TEXT, film_id INTEGER, your_rating REAL, watched_date TEXT,
    PRIMARY KEY (username, film_id)
);
CREATE TABLE IF NOT EXISTS watched (username TEXT, film_id INTEGER, PRIMARY KEY (username, film_id));
CREATE TABLE IF NOT EXISTS recommendations (
    username TEXT, film_id INTEGER, match_pct REAL,
    predicted_rating REAL, why TEXT, computed_at TEXT,
    PRIMARY KEY (username, film_id)
);
CREATE TABLE IF NOT EXISTS film_slug_tmdb (
    slug TEXT PRIMARY KEY,
    tmdb_id INTEGER,
    resolved_via TEXT
);
"""

# sqlite has no "ADD COLUMN IF NOT EXISTS" - applied idempotently by catching
# the duplicate-column error so init_schema is safe to call on every startup.
_MIGRATIONS = [
    "ALTER TABLE films ADD COLUMN director_id INTEGER",
    "ALTER TABLE films ADD COLUMN backdrop_path TEXT",
    "ALTER TABLE films ADD COLUMN overview TEXT",
    "ALTER TABLE films ADD COLUMN runtime INTEGER",
    "ALTER TABLE film_cast ADD COLUMN person_id INTEGER",
    "ALTER TABLE recommendations ADD COLUMN why TEXT",
]

def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    for stmt in _MIGRATIONS:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.commit()

def lookup_slug_tmdb(conn: sqlite3.Connection, slug: str) -> tuple | None:
    """Returns None when the slug was never resolved, or a 1-tuple (tmdb_id,)
    when it was — tmdb_id may itself be None, meaning 'confirmed no TMDB link,
    do not re-fetch'."""
    row = conn.execute(
        "SELECT tmdb_id FROM film_slug_tmdb WHERE slug = ?", (slug,)).fetchone()
    return None if row is None else (row["tmdb_id"],)

def store_slug_tmdb(conn: sqlite3.Connection, slug: str, tmdb_id: int | None, via: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO film_slug_tmdb (slug, tmdb_id, resolved_via) VALUES (?,?,?)",
        (slug, tmdb_id, via))
    conn.commit()  # cache must survive a later run failure
