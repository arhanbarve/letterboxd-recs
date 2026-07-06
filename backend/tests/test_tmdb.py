import responses
from app.tmdb import enrich

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
