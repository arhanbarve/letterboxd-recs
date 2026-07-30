import requests
import pytest
import responses
from app.tmdb import (
    enrich, related_ids, watch_providers, search_person, discover_by_person,
    search_movie, _get, TIMEOUT, MAX_RETRIES,
)

class _FakeResp:
    def __init__(self, json_data):
        self._json = json_data
    def raise_for_status(self):
        pass
    def json(self):
        return self._json

class _FailNTimesSession:
    """Fails with exc_cls on the first n_failures calls, then returns result."""
    def __init__(self, n_failures, exc_cls=requests.exceptions.ConnectionError, result=None):
        self.n_failures = n_failures
        self.exc_cls = exc_cls
        self.result = result if result is not None else {"ok": True}
        self.calls = []
    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": params, "timeout": timeout})
        if len(self.calls) <= self.n_failures:
            raise self.exc_cls("boom")
        return _FakeResp(self.result)

def test_get_passes_a_timeout(monkeypatch):
    monkeypatch.setattr("app.tmdb.time.sleep", lambda s: None)
    s = _FailNTimesSession(0)
    _get(s, "https://api.themoviedb.org/3/movie/1", {"api_key": "k"})
    assert s.calls[0]["timeout"] == TIMEOUT

def test_get_retries_on_connection_error_then_succeeds(monkeypatch):
    monkeypatch.setattr("app.tmdb.time.sleep", lambda s: None)
    s = _FailNTimesSession(1, exc_cls=requests.exceptions.ConnectionError)
    data = _get(s, "https://api.themoviedb.org/3/movie/1", {"api_key": "k"})
    assert data == {"ok": True}
    assert len(s.calls) == 2

def test_get_retries_on_read_timeout_then_succeeds(monkeypatch):
    monkeypatch.setattr("app.tmdb.time.sleep", lambda s: None)
    s = _FailNTimesSession(1, exc_cls=requests.exceptions.Timeout)
    data = _get(s, "https://api.themoviedb.org/3/movie/1", {"api_key": "k"})
    assert data == {"ok": True}
    assert len(s.calls) == 2

def test_get_raises_after_exhausting_retries(monkeypatch):
    monkeypatch.setattr("app.tmdb.time.sleep", lambda s: None)
    s = _FailNTimesSession(99, exc_cls=requests.exceptions.ConnectionError)
    with pytest.raises(requests.exceptions.ConnectionError):
        _get(s, "https://api.themoviedb.org/3/movie/1", {"api_key": "k"})
    assert len(s.calls) == MAX_RETRIES

@responses.activate
def test_enrich_normalizes_movie():
    responses.add(
        responses.GET,
        "https://api.themoviedb.org/3/movie/496243",
        json={
            "title": "Parasite", "release_date": "2019-05-30",
            "poster_path": "/p.jpg", "backdrop_path": "/b.jpg",
            "overview": "Greed and class discrimination threaten a family.",
            "runtime": 132, "vote_average": 8.5,
            "genres": [{"name": "Thriller"}, {"name": "Comedy"}],
            "credits": {
                "crew": [{"job": "Director", "name": "Bong Joon-ho", "id": 21684, "profile_path": "/d.jpg"}],
                "cast": [
                    {"name": "Song Kang-ho", "id": 1523, "profile_path": "/a1.jpg"},
                    {"name": "Lee Sun-kyun", "id": 21686, "profile_path": None},
                ],
            },
            "keywords": {"keywords": [{"name": "class conflict"}]},
        },
        status=200,
    )
    m = enrich(496243, "key", session=None)
    assert m["tmdb_id"] == 496243
    assert m["title"] == "Parasite"
    assert m["year"] == 2019
    assert m["decade"] == 2010
    assert m["director"] == "Bong Joon-ho"
    assert m["director_id"] == 21684
    assert m["genres"] == ["Thriller", "Comedy"]
    assert m["cast"] == ["Song Kang-ho", "Lee Sun-kyun"]
    assert m["cast_people"] == [
        {"person_id": 1523, "name": "Song Kang-ho", "profile_path": "/a1.jpg"},
        {"person_id": 21686, "name": "Lee Sun-kyun", "profile_path": None},
    ]
    assert m["director_person"] == {"person_id": 21684, "name": "Bong Joon-ho", "profile_path": "/d.jpg"}
    assert m["keywords"] == ["class conflict"]
    assert m["poster_path"] == "/p.jpg"
    assert m["backdrop_path"] == "/b.jpg"
    assert m["overview"] == "Greed and class discrimination threaten a family."
    assert m["runtime"] == 132
    assert m["vote_avg"] == 8.5

@responses.activate
def test_enrich_handles_missing_director():
    responses.add(
        responses.GET,
        "https://api.themoviedb.org/3/movie/1",
        json={
            "title": "No Director Movie", "release_date": "2020-01-01",
            "genres": [], "credits": {"crew": [], "cast": []},
            "keywords": {"keywords": []},
        },
        status=200,
    )
    m = enrich(1, "key", session=None)
    assert m["director"] is None
    assert m["director_id"] is None
    assert m["director_person"] is None

def test_enrich_captures_imdb_id_and_vote_count():
    class FakeResp:
        def raise_for_status(self): pass
        def json(self):
            return {
                "title": "X", "release_date": "2010-01-01",
                "vote_average": 7.5, "vote_count": 1234,
                "genres": [], "credits": {"crew": [], "cast": []},
                "keywords": {"keywords": []},
                "external_ids": {"imdb_id": "tt0111161"},
            }
    class FakeSession:
        def get(self, url, params=None, timeout=None): return FakeResp()
    m = enrich(1, "key", session=FakeSession())
    assert m["imdb_id"] == "tt0111161"
    assert m["vote_count"] == 1234

@responses.activate
def test_related_ids_paginates_across_multiple_pages():
    for endpoint in ("recommendations", "similar"):
        responses.add(
            responses.GET, f"https://api.themoviedb.org/3/movie/1/{endpoint}",
            json={"page": 1, "total_pages": 2, "results": [{"id": 10}, {"id": 11}]},
            status=200,
        )
        responses.add(
            responses.GET, f"https://api.themoviedb.org/3/movie/1/{endpoint}",
            json={"page": 2, "total_pages": 2, "results": [{"id": 12}]},
            status=200,
        )
    ids = related_ids(1, "key", session=None, pages=2)
    assert sorted(ids) == [10, 10, 11, 11, 12, 12]

@responses.activate
def test_related_ids_stops_at_total_pages():
    for endpoint in ("recommendations", "similar"):
        responses.add(
            responses.GET, f"https://api.themoviedb.org/3/movie/1/{endpoint}",
            json={"page": 1, "total_pages": 1, "results": [{"id": 10}]},
            status=200,
        )
    ids = related_ids(1, "key", session=None, pages=3)
    assert sorted(ids) == [10, 10]

@responses.activate
def test_watch_providers_normalizes_region():
    responses.add(
        responses.GET, "https://api.themoviedb.org/3/movie/496243/watch/providers",
        json={"results": {
            "US": {
                "link": "https://www.themoviedb.org/movie/496243/watch?locale=US",
                "flatrate": [{"provider_name": "Hulu", "provider_id": 15, "logo_path": "/h.jpg"}],
                "rent": [{"provider_name": "Apple TV", "provider_id": 2, "logo_path": "/a.jpg"}],
            },
            "FR": {"flatrate": [{"provider_name": "Netflix", "provider_id": 8, "logo_path": "/n.jpg"}]},
        }},
        status=200,
    )
    result = watch_providers(496243, "key", region="US", session=None)
    assert result["link"] == "https://www.themoviedb.org/movie/496243/watch?locale=US"
    assert result["flatrate"] == [{"name": "Hulu", "logo_path": "/h.jpg"}]
    assert result["rent"] == [{"name": "Apple TV", "logo_path": "/a.jpg"}]
    assert result["buy"] == []

@responses.activate
def test_watch_providers_missing_region_returns_empty():
    responses.add(
        responses.GET, "https://api.themoviedb.org/3/movie/1/watch/providers",
        json={"results": {}}, status=200,
    )
    result = watch_providers(1, "key", region="US", session=None)
    assert result == {"link": None, "flatrate": [], "rent": [], "buy": []}

@responses.activate
def test_search_person_returns_top_result_id():
    responses.add(
        responses.GET, "https://api.themoviedb.org/3/search/person",
        json={"results": [{"id": 1032, "name": "Martin Scorsese"}, {"id": 999, "name": "Someone Else"}]},
        status=200,
    )
    assert search_person("Martin Scorsese", "key", session=None) == 1032

@responses.activate
def test_search_person_no_results_returns_none():
    responses.add(
        responses.GET, "https://api.themoviedb.org/3/search/person",
        json={"results": []}, status=200,
    )
    assert search_person("Nobody", "key", session=None) is None

@responses.activate
def test_discover_by_person_returns_movie_ids():
    responses.add(
        responses.GET, "https://api.themoviedb.org/3/discover/movie",
        json={"results": [{"id": 769, "title": "GoodFellas"}, {"id": 103, "title": "Taxi Driver"}]},
        status=200,
    )
    assert discover_by_person(1032, "key", session=None) == [769, 103]

SEARCH_URL = "https://api.themoviedb.org/3/search/movie"

@responses.activate
def test_search_movie_exact_title_and_year_match():
    responses.add(responses.GET, SEARCH_URL, json={"results": [
        {"id": 11, "title": "The Thing", "release_date": "2011-10-14"},
        {"id": 42, "title": "The Thing", "release_date": "1982-06-25"},
    ]})
    assert search_movie("the thing", 1982, "KEY") == 42

@responses.activate
def test_search_movie_falls_back_to_year_only_match():
    responses.add(responses.GET, SEARCH_URL, json={"results": [
        {"id": 7, "title": "Parasite: Special Edition", "release_date": "2019-05-30"},
    ]})
    assert search_movie("Parasite", 2019, "KEY") == 7

@responses.activate
def test_search_movie_no_match_returns_none():
    responses.add(responses.GET, SEARCH_URL, json={"results": [
        {"id": 7, "title": "Wrong Film", "release_date": "1999-01-01"},
    ]})
    assert search_movie("Parasite", 2019, "KEY") is None

@responses.activate
def test_search_movie_without_year_requires_exact_title():
    responses.add(responses.GET, SEARCH_URL, json={"results": [
        {"id": 7, "title": "Parasite", "release_date": "2019-05-30"},
    ]})
    assert search_movie("parasite", None, "KEY") == 7

@responses.activate
def test_search_movie_empty_results_returns_none():
    responses.add(responses.GET, SEARCH_URL, json={"results": []})
    assert search_movie("Nothing", 2020, "KEY") is None

# Letterboxd records a film's *premiere* year, TMDB its primary *release* year,
# so a one-year offset is routine (Insidious: Letterboxd 2010, TMDB 2011-03-31).
# Confirmed live 2026-07-30: 2 of 92 films in a real export failed on this alone.

def _year_param(call):
    return call.request.params.get("primary_release_year")

@responses.activate
def test_search_movie_retries_one_year_later():
    responses.add(responses.GET, SEARCH_URL, json={"results": []})
    responses.add(responses.GET, SEARCH_URL, json={"results": [
        {"id": 49018, "title": "Insidious", "release_date": "2011-03-31"},
    ]})
    assert search_movie("Insidious", 2010, "KEY") == 49018
    assert [_year_param(c) for c in responses.calls] == ["2010", "2011"]

@responses.activate
def test_search_movie_retries_one_year_earlier():
    responses.add(responses.GET, SEARCH_URL, json={"results": []})
    responses.add(responses.GET, SEARCH_URL, json={"results": []})
    responses.add(responses.GET, SEARCH_URL, json={"results": [
        {"id": 5, "title": "Persona", "release_date": "2013-08-01"},
    ]})
    assert search_movie("Persona", 2014, "KEY") == 5
    assert [_year_param(c) for c in responses.calls] == ["2014", "2015", "2013"]

@responses.activate
def test_search_movie_falls_back_to_unfiltered_year():
    responses.add(responses.GET, SEARCH_URL, json={"results": []})
    responses.add(responses.GET, SEARCH_URL, json={"results": []})
    responses.add(responses.GET, SEARCH_URL, json={"results": []})
    responses.add(responses.GET, SEARCH_URL, json={"results": [
        {"id": 284303, "title": "Goodnight Mommy", "release_date": "2015-01-08"},
    ]})
    assert search_movie("Goodnight Mommy", 2014, "KEY") == 284303
    assert _year_param(responses.calls[3]) is None

@responses.activate
def test_search_movie_year_fallbacks_require_exact_title():
    # The loose "any result with a matching year" rule applies only to the
    # requested year — a neighbouring year must not match a different film.
    responses.add(responses.GET, SEARCH_URL, json={"results": []})
    responses.add(responses.GET, SEARCH_URL, json={"results": [
        {"id": 99, "title": "Some Other Film", "release_date": "2011-05-05"},
    ]})
    assert search_movie("Insidious", 2010, "KEY") is None

@responses.activate
def test_search_movie_stops_after_four_attempts():
    responses.add(responses.GET, SEARCH_URL, json={"results": []})
    assert search_movie("Nonexistent", 1999, "KEY") is None
    assert len(responses.calls) == 4

@responses.activate
def test_search_movie_without_year_makes_a_single_request():
    responses.add(responses.GET, SEARCH_URL, json={"results": []})
    assert search_movie("Nonexistent", None, "KEY") is None
    assert len(responses.calls) == 1
