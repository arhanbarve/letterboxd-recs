import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS films (
    tmdb_id INTEGER PRIMARY KEY,
    title TEXT, year INTEGER, decade INTEGER,
    director TEXT, director_id INTEGER,
    poster_path TEXT, backdrop_path TEXT, overview TEXT, runtime INTEGER,
    tmdb_vote_avg REAL, vote_count INTEGER, imdb_rating REAL, rt_score INTEGER
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
CREATE TABLE IF NOT EXISTS user_tokens (
    username TEXT PRIMARY KEY,
    token_hash TEXT NOT NULL,
    created_at TEXT
);
CREATE TABLE IF NOT EXISTS imported_films (
    username TEXT, boxd_id TEXT, title TEXT, year INTEGER,
    rating REAL,       -- NULL = watched but unrated
    rated_date TEXT,   -- ratings.csv Date, orders the scoring seeds
    tmdb_id INTEGER,   -- filled in during a refresh; NULL until then
    imported_at TEXT,
    PRIMARY KEY (username, boxd_id)
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
    "ALTER TABLE films ADD COLUMN vote_count INTEGER",
    "ALTER TABLE films ADD COLUMN imdb_rating REAL",
    "ALTER TABLE films ADD COLUMN rt_score INTEGER",
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

def get_token_hash(conn: sqlite3.Connection, username: str) -> str | None:
    """None means the username is unclaimed — nobody has imported under it yet."""
    row = conn.execute(
        "SELECT token_hash FROM user_tokens WHERE username=?", (username,)).fetchone()
    return row["token_hash"] if row else None

def store_token_hash(conn: sqlite3.Connection, username: str, token_hash: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO user_tokens (username, token_hash, created_at)"
        " VALUES (?,?,?)",
        (username, token_hash, datetime.now(timezone.utc).isoformat()))
    conn.commit()

def replace_imported_films(conn: sqlite3.Connection, username: str, films: list[dict],
                           imported_at: str | None = None) -> None:
    """Overwrites this username's imported films. A Letterboxd export is a full
    snapshot, so replacing is the correct semantic — merging would resurrect
    films you have since deleted from your Letterboxd account."""
    imported_at = imported_at or datetime.now(timezone.utc).isoformat()
    conn.execute("DELETE FROM imported_films WHERE username=?", (username,))
    conn.executemany(
        "INSERT OR REPLACE INTO imported_films"
        " (username, boxd_id, title, year, rating, rated_date, tmdb_id, imported_at)"
        " VALUES (?,?,?,?,?,?,NULL,?)",
        [(username, f["boxd_id"], f["title"], f["year"], f["rating"],
          f.get("rated_date"), imported_at) for f in films])
    conn.commit()

def load_imported_films(conn: sqlite3.Connection, username: str) -> list[dict]:
    return [dict(r) for r in conn.execute(
        "SELECT boxd_id, title, year, rating, rated_date, tmdb_id"
        " FROM imported_films WHERE username=? ORDER BY rowid", (username,)).fetchall()]

def set_imported_tmdb_id(conn: sqlite3.Connection, username: str, boxd_id: str,
                         tmdb_id: int | None) -> None:
    conn.execute("UPDATE imported_films SET tmdb_id=? WHERE username=? AND boxd_id=?",
                 (tmdb_id, username, boxd_id))

def import_status(conn: sqlite3.Connection, username: str) -> dict:
    row = conn.execute(
        "SELECT COUNT(*) AS imported,"
        " COUNT(rating) AS rated,"
        " MAX(imported_at) AS imported_at"
        " FROM imported_films WHERE username=?", (username,)).fetchone()
    return {"imported": row["imported"], "rated": row["rated"],
            "imported_at": row["imported_at"]}
