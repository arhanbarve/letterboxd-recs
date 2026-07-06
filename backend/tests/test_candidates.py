from app.candidates import build_candidate_pool

def test_pool_unions_dedupes_and_excludes_watched():
    # fake fetcher: film 1 -> {10, 11}, film 2 -> {11, 12}
    def fake_related(tmdb_id, api_key):
        return {1: [10, 11], 2: [11, 12]}[tmdb_id]

    watched = {12}
    pool = build_candidate_pool(
        liked_ids=[1, 2], watched_ids=watched,
        api_key="k", related_fn=fake_related,
    )
    assert pool == {10, 11}  # 12 excluded (watched), 11 deduped
