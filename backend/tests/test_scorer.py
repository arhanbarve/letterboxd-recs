import math
from app.scorer import match_raw_score, predict_rating, why_tags, score_candidates

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

def test_why_tags_returns_top_features():
    tags = why_tags(CAND, PROFILE, n=2)
    assert len(tags) == 2
    assert "Bong Joon-ho" in tags or "Thriller" in tags

def test_score_candidates_normalizes_and_ranks():
    cands = [CAND, {"tmdb_id": 2, "genres": ["Comedy"], "keywords": [],
                    "director": "X", "cast": [], "decade": 1990}]
    rated = [{"rating": 5.0, "genres": ["Thriller"], "keywords": ["class conflict"]}]
    results = score_candidates(cands, PROFILE, rated, k=1)
    assert results[0]["tmdb_id"] == 999          # ranked first
    assert results[0]["match_pct"] == 100.0       # top of pool
    assert results[-1]["match_pct"] == 0.0        # bottom of pool
