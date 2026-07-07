import math
from app.scorer import (
    match_raw_score, predict_rating, score_candidates,
    top_neighbors, connection_phrase, why_for,
)

PROFILE = {
    "genre": {"Thriller": 1.0, "Comedy": 0.5},
    "keyword": {"class conflict": 1.0},
    "director": {"Bong Joon-ho": 1.0},
    "actor": {"Song Kang-ho": 1.0},
    "decade": {2010: 1.0},
}

CAND = {
    "tmdb_id": 999, "genres": ["Thriller"], "keywords": ["class conflict"],
    "director": "Bong Joon-ho", "cast": ["Song Kang-ho"], "decade": 2010,
}

def test_match_raw_score_weighted_sum():
    # .25*1 + .25*1 + .20*1 + .20*1 + .10*1 = 1.0
    assert round(match_raw_score(CAND, PROFILE), 4) == 1.0

def test_match_raw_score_partial():
    weak = {"tmdb_id": 1, "genres": ["Comedy"], "keywords": [],
            "director": "X", "cast": [], "decade": 1990}
    # only genre contributes: .25 * 0.5 = 0.125
    assert round(match_raw_score(weak, PROFILE), 4) == 0.125

def test_predict_rating_knn_weighted_average():
    rated = [
        {"rating": 5.0, "genres": ["Thriller"], "keywords": ["class conflict"]},
        {"rating": 2.0, "genres": ["Romance"], "keywords": []},
    ]
    pred = predict_rating(CAND, rated, k=2)
    # candidate is identical to first film, orthogonal to second -> ~5.0
    assert pred > 4.5

RATED_SNOWPIERCER = {"rating": 5.0, "title": "Snowpiercer",
                     "genres": ["Thriller"], "keywords": ["class conflict"]}

def test_top_neighbors_prefers_higher_rated_among_similar():
    rated = [
        RATED_SNOWPIERCER,
        {"rating": 2.0, "title": "Random Comedy", "genres": ["Comedy"], "keywords": []},
    ]
    neighbors = top_neighbors(CAND, rated, k=1)
    assert neighbors[0]["title"] == "Snowpiercer"

def test_connection_phrase_prefers_director_over_cast_and_keywords():
    neighbor = {"title": "Snowpiercer", "rating": 5.0, "director": "Bong Joon-ho",
                "cast": ["Song Kang-ho"], "keywords": ["class conflict"], "genres": ["Thriller"]}
    assert connection_phrase(CAND, [neighbor]) == "directed by Bong Joon-ho"

def test_connection_phrase_falls_back_to_shared_keyword():
    neighbor = {"title": "Other Film", "rating": 4.0, "director": "Someone Else",
                "cast": [], "keywords": ["class conflict"], "genres": []}
    assert connection_phrase(CAND, [neighbor]) == "a shared thread of class conflict"

def test_connection_phrase_returns_none_when_nothing_shared():
    neighbor = {"title": "Unrelated", "rating": 4.0, "director": "Someone Else",
                "cast": [], "keywords": [], "genres": []}
    assert connection_phrase(CAND, [neighbor]) is None

def test_why_for_names_the_specific_neighbor_films():
    why = why_for(CAND, [RATED_SNOWPIERCER])
    assert why["neighbors"] == [{"title": "Snowpiercer", "rating": 5.0}]
    assert why["connection"] == "a shared thread of class conflict"

def test_why_for_empty_when_no_rated_films_are_similar():
    unrelated = {"rating": 3.0, "title": "Nothing Alike", "genres": ["Romance"], "keywords": []}
    assert why_for(CAND, [unrelated]) == {"neighbors": [], "connection": None}

def test_score_candidates_normalizes_and_ranks():
    cands = [CAND, {"tmdb_id": 2, "genres": ["Comedy"], "keywords": [],
                    "director": "X", "cast": [], "decade": 1990}]
    rated = [{"rating": 5.0, "title": "Snowpiercer", "genres": ["Thriller"], "keywords": ["class conflict"]}]
    results = score_candidates(cands, PROFILE, rated, k=1)
    assert results[0]["tmdb_id"] == 999          # ranked first
    assert results[0]["match_pct"] == 100.0       # perfect match on every weighted family == THEORETICAL_MAX
    assert results[-1]["match_pct"] == 12.5       # only genre family contributes: 0.25 * 0.5 affinity = 0.125 raw -> 12.5%

def test_score_candidates_empty_pool_returns_empty_list():
    assert score_candidates([], PROFILE, [{"rating": 5.0, "title": "X", "genres": ["Thriller"]}]) == []
