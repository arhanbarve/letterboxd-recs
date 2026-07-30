import io
import zipfile

import pytest

from app.importer import MAX_UPLOAD_BYTES, ExportParseError, parse_export

RATINGS_HEADER = "Date,Name,Year,Letterboxd URI,Rating\n"
WATCHED_HEADER = "Date,Name,Year,Letterboxd URI\n"
PROFILE = ("Date Joined,Username,Given Name,Family Name,Email Address,Location,"
           "Website,Bio,Pronoun,Favorite Films\n"
           "2026-02-05,moviefan,Arhan,B,a@example.com,,,,they/them,\n")

def make_zip(**members) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, content in members.items():
            z.writestr(name.replace("__", "/"), content)
    return buf.getvalue()

def sample_zip(ratings_rows="2026-02-05,Parasite,2019,https://boxd.it/293w,5\n",
               watched_rows="2026-02-05,Parasite,2019,https://boxd.it/293w\n",
               **extra):
    return make_zip(**{
        "ratings.csv": RATINGS_HEADER + ratings_rows,
        "watched.csv": WATCHED_HEADER + watched_rows,
        "profile.csv": PROFILE,
        **extra,
    })

def test_parses_username_and_films():
    result = parse_export(sample_zip())
    assert result["username"] == "moviefan"
    assert result["films"] == [{
        "boxd_id": "293w", "title": "Parasite", "year": 2019,
        "rating": 5.0, "rated_date": "2026-02-05",
    }]

def test_extracts_boxd_shortlink_code():
    # The export's "Letterboxd URI" is a boxd.it shortlink, not a film slug —
    # confirmed against a real export 2026-07-30.
    films = parse_export(sample_zip(
        ratings_rows="2026-02-05,Aftersun,2022,https://boxd.it/wUow,4.5\n",
        watched_rows=""))["films"]
    assert films[0]["boxd_id"] == "wUow"

def test_falls_back_to_film_slug_when_uri_is_a_full_url():
    films = parse_export(sample_zip(
        ratings_rows="2026-02-05,Parasite,2019,https://letterboxd.com/film/parasite/,5\n",
        watched_rows=""))["films"]
    assert films[0]["boxd_id"] == "parasite"

def test_unrecognised_uri_still_yields_a_stable_key():
    films = parse_export(sample_zip(
        ratings_rows="2026-02-05,Weird,2019,not-a-url,5\n", watched_rows=""))["films"]
    assert films[0]["boxd_id"] == "not-a-url"

@pytest.mark.parametrize("raw,expected", [
    ("0.5", 0.5), ("3", 3.0), ("3.5", 3.5), ("5", 5.0), ("", None),
])
def test_parses_half_star_ratings(raw, expected):
    films = parse_export(sample_zip(
        ratings_rows=f"2026-02-05,Film,2019,https://boxd.it/a,{raw}\n",
        watched_rows=""))["films"]
    assert films[0]["rating"] == expected

def test_watched_only_film_has_no_rating():
    films = parse_export(sample_zip(
        ratings_rows="",
        watched_rows="2026-02-05,Unrated Film,2021,https://boxd.it/zzz\n"))["films"]
    assert films == [{"boxd_id": "zzz", "title": "Unrated Film", "year": 2021,
                      "rating": None, "rated_date": None}]

def test_film_in_both_files_merges_to_one_row():
    films = parse_export(sample_zip())["films"]
    assert len(films) == 1
    assert films[0]["rating"] == 5.0

def test_rated_films_come_before_watched_only_films():
    films = parse_export(sample_zip(
        ratings_rows="2026-02-05,Rated,2019,https://boxd.it/aaa,4\n",
        watched_rows=("2026-02-05,Rated,2019,https://boxd.it/aaa\n"
                      "2026-02-06,Unrated,2020,https://boxd.it/bbb\n")))["films"]
    assert [f["boxd_id"] for f in films] == ["aaa", "bbb"]

def test_missing_year_is_none():
    films = parse_export(sample_zip(
        ratings_rows="2026-02-05,No Year,,https://boxd.it/a,4\n", watched_rows=""))["films"]
    assert films[0]["year"] is None

def test_rows_without_a_title_are_skipped():
    films = parse_export(sample_zip(
        ratings_rows="2026-02-05,,2019,https://boxd.it/a,4\n", watched_rows=""))["films"]
    assert films == []

def test_watched_csv_is_optional():
    data = make_zip(**{"ratings.csv": RATINGS_HEADER + "2026-02-05,P,2019,https://boxd.it/a,5\n",
                       "profile.csv": PROFILE})
    assert len(parse_export(data)["films"]) == 1

def test_username_is_none_when_profile_csv_is_absent():
    data = make_zip(**{"ratings.csv": RATINGS_HEADER + "2026-02-05,P,2019,https://boxd.it/a,5\n"})
    assert parse_export(data)["username"] is None

def test_ignores_the_other_export_members():
    # A real export also ships diary/reviews/likes/deleted/orphaned members.
    data = sample_zip(**{
        "diary.csv": "Date,Name,Year,Letterboxd URI,Rating,Rewatch,Tags,Watched Date\n",
        "likes__films.csv": WATCHED_HEADER + "2026-02-05,Liked,2019,https://boxd.it/qqq\n",
        "deleted__diary.csv": "Date,Name\n",
        "orphaned__reviews.csv": "Date,Name\n",
    })
    assert [f["boxd_id"] for f in parse_export(data)["films"]] == ["293w"]

def test_rejects_non_zip_bytes():
    with pytest.raises(ExportParseError, match="zip"):
        parse_export(b"Date,Name,Year\n2026,Parasite,2019\n")

def test_rejects_zip_without_ratings_csv():
    with pytest.raises(ExportParseError, match="ratings.csv"):
        parse_export(make_zip(**{"profile.csv": PROFILE}))

def test_rejects_ratings_csv_with_unexpected_columns():
    data = make_zip(**{"ratings.csv": "Film,Stars\nParasite,5\n"})
    with pytest.raises(ExportParseError) as exc:
        parse_export(data)
    assert "Film" in str(exc.value)  # tells you what it actually found

def test_rejects_oversized_upload():
    with pytest.raises(ExportParseError, match="25"):
        parse_export(b"x" * (MAX_UPLOAD_BYTES + 1))

def test_rejects_empty_upload():
    with pytest.raises(ExportParseError):
        parse_export(b"")
