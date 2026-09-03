"""Test database wiring.

The app talks to Postgres, so the tests do too — there is no in-memory stand-in
that would prove the real SQL works. A throwaway database is created once per
session and emptied between tests, which is fast enough that the suite still
runs in seconds.

Needs a local Postgres reachable as the current user (`brew services start
postgresql@16`). Point somewhere else with TEST_ADMIN_DSN / TEST_DATABASE_URL.
"""
import os

import psycopg
import pytest

# app.api builds its Config at import time, so these must exist before pytest
# imports any test module — a fresh clone has no .env to supply them. Every
# test stubs the network, so the key is a placeholder on purpose.
os.environ.setdefault("TMDB_API_KEY", "test-key-never-sent-anywhere")

ADMIN_DSN = os.environ.get("TEST_ADMIN_DSN", "postgresql:///postgres")
TEST_DB = os.environ.get("TEST_DB_NAME", "letterboxd_test")
TEST_DSN = os.environ.get("TEST_DATABASE_URL", f"postgresql:///{TEST_DB}")
os.environ.setdefault("DATABASE_URL", TEST_DSN)

_TABLES = ("films", "film_genres", "film_keywords", "film_cast", "people",
           "ratings", "watched", "recommendations", "film_slug_tmdb",
           "user_tokens", "imported_films")

def _disconnect_everyone(admin):
    """DROP DATABASE refuses while sessions are open, and tests deliberately do
    not close their connections."""
    admin.execute(
        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity"
        " WHERE datname = %s AND pid <> pg_backend_pid()", (TEST_DB,))

@pytest.fixture(scope="session", autouse=True)
def _database():
    from app.db import connect, init_schema
    with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
        _disconnect_everyone(admin)
        admin.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}"')
        admin.execute(f'CREATE DATABASE "{TEST_DB}"')
    conn = connect(TEST_DSN)
    init_schema(conn)
    conn.close()
    yield
    with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
        _disconnect_everyone(admin)
        admin.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}"')

@pytest.fixture(autouse=True)
def _clean_tables(_database):
    """Empty before, disconnect after. The disconnect matters: tests open
    connections freely and never close them, and without this the suite
    exhausts Postgres' connection limit partway through."""
    with psycopg.connect(TEST_DSN, autocommit=True) as conn:
        conn.execute(f"TRUNCATE {', '.join(_TABLES)} RESTART IDENTITY CASCADE")
    yield
    with psycopg.connect(ADMIN_DSN, autocommit=True) as admin:
        _disconnect_everyone(admin)
