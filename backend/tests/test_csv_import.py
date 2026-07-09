import io
import zipfile

import pytest

from app.csv_import import parse_export

RATINGS_CSV = """Date,Name,Year,Letterboxd URI,Rating
2024-01-01,Parasite,2019,https://boxd.it/abc,5
2024-01-02,Cats,2019,https://boxd.it/def,0.5
"""

WATCHED_CSV = """Date,Name,Year,Letterboxd URI
2024-01-01,Parasite,2019,https://boxd.it/abc
2024-01-03,Unrated Film,2020,https://boxd.it/ghi
"""

def _zip_bytes(files: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, text in files.items():
            zf.writestr(name, text)
    return buf.getvalue()

def test_parse_raw_ratings_csv():
    entries = parse_export(RATINGS_CSV.encode())
    by_title = {e["title"]: e for e in entries}
    assert by_title["Parasite"] == {
        "slug": None, "title": "Parasite", "year": 2019, "rating": 5.0}
    assert by_title["Cats"]["rating"] == 0.5

def test_parse_zip_merges_watched_and_ratings():
    data = _zip_bytes({"watched.csv": WATCHED_CSV, "ratings.csv": RATINGS_CSV})
    entries = parse_export(data)
    by_title = {e["title"]: e for e in entries}
    assert len(entries) == 3
    assert by_title["Parasite"]["rating"] == 5.0      # rated row wins
    assert by_title["Unrated Film"]["rating"] is None  # watched-only

def test_parse_zip_without_expected_csvs_raises():
    with pytest.raises(ValueError, match="watched.csv or ratings.csv"):
        parse_export(_zip_bytes({"diary.csv": "Date,Name\n"}))

def test_parse_garbage_raises():
    with pytest.raises(ValueError):
        parse_export(b"\x00\x01\x02 not a csv or zip")

def test_parse_empty_csv_raises():
    with pytest.raises(ValueError, match="No films"):
        parse_export(b"Date,Name,Year,Letterboxd URI\n")
