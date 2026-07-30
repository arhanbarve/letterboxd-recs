"""Regenerates the synthetic Letterboxd-export fixture used by the E2E import test.

Run:  cd backend && .venv/bin/python scripts/make_sample_export.py

Mirrors the real export's structure (verified against a real export 2026-07-30)
with invented films and no personal data, so it is safe to commit. The films are
real enough for TMDB to resolve if a run gets that far, but the E2E test only
asserts on the import step.
"""
import zipfile
from pathlib import Path

FIXTURE = (Path(__file__).resolve().parents[2]
           / "frontend/tests/e2e/fixtures/letterboxd-export-sample.zip")

PROFILE = ("Date Joined,Username,Given Name,Family Name,Email Address,Location,"
           "Website,Bio,Pronoun,Favorite Films\n"
           "2026-01-01,e2e-sample,E2E,Sample,,,,,they/them,\n")

RATINGS = [
    ("2026-01-02", "The Prestige", 2006, "https://boxd.it/2b9k", "5"),
    ("2026-01-03", "Parasite", 2019, "https://boxd.it/hTha", "4.5"),
    ("2026-01-04", "Whiplash", 2014, "https://boxd.it/8slO", "4"),
    ("2026-01-05", "Arrival", 2016, "https://boxd.it/dEfG", "3.5"),
    ("2026-01-06", "Cats", 2019, "https://boxd.it/hIjK", "1"),
]
# One extra film that was watched but never rated, so the fixture exercises the
# watched-only path too.
WATCHED_ONLY = [("2026-01-07", "Aftersun", 2022, "https://boxd.it/lMnO")]

def main():
    ratings = "Date,Name,Year,Letterboxd URI,Rating\n" + "".join(
        f"{d},{n},{y},{u},{r}\n" for d, n, y, u, r in RATINGS)
    watched = "Date,Name,Year,Letterboxd URI\n" + "".join(
        f"{d},{n},{y},{u}\n" for d, n, y, u, _ in RATINGS) + "".join(
        f"{d},{n},{y},{u}\n" for d, n, y, u in WATCHED_ONLY)

    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(FIXTURE, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("profile.csv", PROFILE)
        z.writestr("ratings.csv", ratings)
        z.writestr("watched.csv", watched)
        z.writestr("watchlist.csv", "Date,Name,Year,Letterboxd URI\n")
        z.writestr("diary.csv", "Date,Name,Year,Letterboxd URI,Rating,Rewatch,Tags,Watched Date\n")
        z.writestr("reviews.csv", "Date,Name,Year,Letterboxd URI,Rating,Rewatch,Review,Tags,Watched Date\n")
        z.writestr("comments.csv", "Date,Type,Item,Comment\n")
        z.writestr("likes/films.csv", "Date,Name,Year,Letterboxd URI\n")
        z.writestr("deleted/diary.csv", "Date,Name\n")
        z.writestr("orphaned/reviews.csv", "Date,Name\n")
    print(f"wrote {FIXTURE} ({FIXTURE.stat().st_size} bytes)")

if __name__ == "__main__":
    main()
