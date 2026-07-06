from app.profile import build_taste_profile

def test_affinity_sums_rating_minus_midpoint_then_normalizes():
    films = [
        {"rating": 4.5, "genres": ["Thriller"], "keywords": [], "cast": [],
         "director": "Bong", "decade": 2010},
        {"rating": 1.0, "genres": ["Thriller"], "keywords": [], "cast": [],
         "director": "Other", "decade": 2000},
    ]
    prof = build_taste_profile(films)
    # Thriller raw = (4.5-2.5) + (1.0-2.5) = 2.0 - 1.5 = 0.5; it's the only genre
    # normalized by max abs (0.5) -> 1.0
    assert prof["genre"]["Thriller"] == 1.0
    # Bong raw = 2.0 (max abs among directors), Other raw = -1.5
    assert prof["director"]["Bong"] == 1.0
    assert round(prof["director"]["Other"], 3) == -0.75
