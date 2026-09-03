"""Parses an official Letterboxd data export zip (Settings -> Data -> Export
Your Data), which the user downloads themselves.

This replaces the old HTML crawl outright: nothing here reaches Letterboxd, so
Cloudflare bot management, residential proxies and headless-browser fingerprints
stop being this project's problem.

What the export actually contains (verified against a real export 2026-07-30):
  ratings.csv  Date,Name,Year,Letterboxd URI,Rating   (Rating: "0.5".."5")
  watched.csv  Date,Name,Year,Letterboxd URI          (superset of ratings.csv)
  profile.csv  ...,Username,...                       (authoritative username)
plus diary/reviews/watchlist/likes/deleted/orphaned members, all ignored.

"Letterboxd URI" is a boxd.it *shortlink* — there is no film slug in the export,
so TMDB ids are resolved later from title+year (see resolver/pipeline).
"""
import csv
import io
import re
import zipfile

MAX_UPLOAD_BYTES = 25 * 1024 * 1024

# A 25MB zip of repetitive CSV text decompresses to tens of gigabytes, and
# csv.DictReader is read into a list — so the compressed cap alone does not bound
# memory. Check the declared uncompressed size before opening any member, and cap
# the row count in case a crafted zip understates it.
MAX_UNCOMPRESSED_BYTES = 200 * 1024 * 1024
MAX_ROWS_PER_FILE = 200_000

RATINGS_FILE = "ratings.csv"
WATCHED_FILE = "watched.csv"
PROFILE_FILE = "profile.csv"

_REQUIRED_RATINGS_COLUMNS = {"Name", "Year", "Letterboxd URI", "Rating"}
_REQUIRED_WATCHED_COLUMNS = {"Name", "Year", "Letterboxd URI"}

_BOXD_RE = re.compile(r"boxd\.it/([A-Za-z0-9]+)")
_SLUG_RE = re.compile(r"letterboxd\.com/film/([^/]+)")

class ExportParseError(ValueError):
    """A bad upload. The message is written to be shown to the user verbatim."""

def parse_export(data: bytes) -> dict:
    """Returns {"username": str | None, "films": [{boxd_id,title,year,rating,rated_date}]}.
    Rating is None for a film that was watched but never rated."""
    if len(data) > MAX_UPLOAD_BYTES:
        raise ExportParseError(
            f"That file is bigger than {MAX_UPLOAD_BYTES // (1024 * 1024)}MB — "
            "a Letterboxd export is normally well under a megabyte.")
    if not data:
        raise ExportParseError("That file is empty.")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile:
        raise ExportParseError(
            "That isn't a zip file. Upload the .zip you downloaded from "
            "Letterboxd (Settings -> Data -> Export Your Data).") from None

    _reject_zip_bomb(archive)

    names = set(archive.namelist())
    if RATINGS_FILE not in names:
        raise ExportParseError(
            f"No {RATINGS_FILE} inside that zip — is it really a Letterboxd export?")

    rated = _read_rows(archive, RATINGS_FILE, _REQUIRED_RATINGS_COLUMNS)
    watched = (_read_rows(archive, WATCHED_FILE, _REQUIRED_WATCHED_COLUMNS)
               if WATCHED_FILE in names else [])
    username = _read_username(archive) if PROFILE_FILE in names else None
    return {"username": username, "films": _merge(rated, watched)}

def _reject_zip_bomb(archive) -> None:
    """The zip header declares each member's uncompressed size, so an absurd
    expansion ratio is knowable before a single byte is decompressed."""
    total = sum(info.file_size for info in archive.infolist())
    if total > MAX_UNCOMPRESSED_BYTES:
        raise ExportParseError(
            "The contents of that zip are far larger than a Letterboxd export — "
            "refusing to unpack it.")

def _read_rows(archive, filename, required_columns) -> list[dict]:
    with archive.open(filename) as raw:
        reader = csv.DictReader(io.TextIOWrapper(raw, "utf-8-sig"))
        columns = set(reader.fieldnames or [])
        missing = required_columns - columns
        if missing:
            raise ExportParseError(
                f"{filename} is missing the {', '.join(sorted(missing))} "
                f"column(s). Found: {', '.join(reader.fieldnames or ['nothing'])}.")
        rows = []
        for row in reader:
            if len(rows) >= MAX_ROWS_PER_FILE:
                raise ExportParseError(
                    f"{filename} has more than {MAX_ROWS_PER_FILE:,} rows — "
                    "that isn't a Letterboxd export.")
            rows.append(row)
        return rows

def _read_username(archive) -> str | None:
    rows = _read_rows(archive, PROFILE_FILE, {"Username"})
    return (rows[0].get("Username") or None) if rows else None

def _merge(rated_rows, watched_rows) -> list[dict]:
    """Rated films first (they carry the signal), then watched-only films."""
    films = {}
    for row in rated_rows:
        film = _film(row)
        if film:
            film["rating"] = _rating(row.get("Rating"))
            film["rated_date"] = row.get("Date") or None
            films[film["boxd_id"]] = film
    for row in watched_rows:
        film = _film(row)
        if film and film["boxd_id"] not in films:
            films[film["boxd_id"]] = film
    return list(films.values())

def _film(row) -> dict | None:
    title = (row.get("Name") or "").strip()
    if not title:
        return None
    return {"boxd_id": _boxd_id(row.get("Letterboxd URI") or ""),
            "title": title, "year": _year(row.get("Year")),
            "rating": None, "rated_date": None}

def _boxd_id(uri: str) -> str:
    """The export's stable per-film key. Falls back to a film slug, then to the
    raw URI, so an unrecognised URI form still gets a usable primary key rather
    than collapsing every such film onto one row."""
    for pattern in (_BOXD_RE, _SLUG_RE):
        match = pattern.search(uri)
        if match:
            return match.group(1)
    return uri.strip()

def _rating(raw) -> float | None:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None

def _year(raw) -> int | None:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None
