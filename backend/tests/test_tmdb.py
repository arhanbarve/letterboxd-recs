import responses
from app.tmdb import enrich, related_ids, watch_providers

@responses.activate
def test_enrich_normalizes_movie():
    responses.add(
        responses.GET,
        "https://api.themoviedb.org/3/movie/496243",
        json={
            "title": "Parasite", "release_date": "2019-05-30",
            "poster_path": "/p.jpg", "vote_average": 8.5,
            "genres": [{"name": "Thriller"}, {"name": "Comedy"}],
            "credits": {
                "crew": [{"job": "Director", "name": "Bong Joon-ho"}],
                "cast": [{"name": "Song Kang-ho"}, {"name": "Lee Sun-kyun"}],
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
    assert m["genres"] == ["Thriller", "Comedy"]
    assert m["cast"] == ["Song Kang-ho", "Lee Sun-kyun"]
    assert m["keywords"] == ["class conflict"]
    assert m["vote_avg"] == 8.5

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
