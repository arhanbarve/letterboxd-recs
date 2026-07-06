import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS films (
    tmdb_id INTEGER PRIMARY KEY,
    title TEXT, year INTEGER, decade INTEGER,
    director TEXT, poster_path TEXT, tmdb_vote_avg REAL
);
CREATE TABLE IF NOT EXISTS film_genres (film_id INTEGER, genre TEXT);
CREATE TABLE IF NOT EXISTS film_keywords (film_id INTEGER, keyword TEXT);
CREATE TABLE IF NOT EXISTS film_cast (film_id INTEGER, actor TEXT);
CREATE TABLE IF NOT EXISTS ratings (
    username TEXT, film_id INTEGER, your_rating REAL, watched_date TEXT,
    PRIMARY KEY (username, film_id)
);
CREATE TABLE IF NOT EXISTS watched (username TEXT, film_id INTEGER, PRIMARY KEY (username, film_id));
CREATE TABLE IF NOT EXISTS recommendations (
    username TEXT, film_id INTEGER, match_pct REAL,
    predicted_rating REAL, why_tags TEXT, computed_at TEXT,
    PRIMARY KEY (username, film_id)
);
"""

def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()
