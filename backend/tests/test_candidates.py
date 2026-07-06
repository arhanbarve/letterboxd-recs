from app.candidates import build_candidate_pool, build_person_candidate_pool

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

def test_person_pool_resolves_names_and_unions_dedupes_excludes_watched():
    def fake_search(name, api_key):
        return {"Scorsese": 1032, "Nolan": 525}[name]

    def fake_discover(person_id, api_key):
        return {1032: [769, 103], 525: [103, 27205]}[person_id]

    pool = build_person_candidate_pool(
        names=["Scorsese", "Nolan"], watched_ids={27205}, api_key="k",
        search_person_fn=fake_search, discover_fn=fake_discover,
    )
    assert pool == {769, 103}  # 27205 excluded (watched), 103 deduped

def test_person_pool_skips_unresolvable_names():
    pool = build_person_candidate_pool(
        names=["Nobody"], watched_ids=set(), api_key="k",
        search_person_fn=lambda name, api_key: None,
        discover_fn=lambda pid, api_key: [999],
    )
    assert pool == set()
