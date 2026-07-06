from app.tmdb import related_ids, search_person, discover_by_person

def build_candidate_pool(liked_ids, watched_ids, api_key, related_fn=related_ids) -> set:
    pool = set()
    for fid in liked_ids:
        pool.update(related_fn(fid, api_key))
    return pool - set(watched_ids)

def build_person_candidate_pool(
    names, watched_ids, api_key,
    search_person_fn=search_person, discover_fn=discover_by_person,
) -> set:
    pool = set()
    for name in names:
        person_id = search_person_fn(name, api_key)
        if person_id is not None:
            pool.update(discover_fn(person_id, api_key))
    return pool - set(watched_ids)
