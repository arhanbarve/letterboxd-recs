from app.tmdb import related_ids, search_person, discover_by_person

def _full(pool, max_pool) -> bool:
    """Checked before each fan-out rather than after, so max_pool=0 means "no
    budget left" and adds nothing. The last batch may overshoot max_pool — the
    cap bounds runtime, it isn't an exact quota."""
    return max_pool is not None and len(pool) >= max_pool

def build_candidate_pool(liked_ids, watched_ids, api_key, related_fn=related_ids,
                         max_pool=None) -> set:
    pool = set()
    for fid in liked_ids:
        if _full(pool, max_pool):
            break
        pool.update(related_fn(fid, api_key))
    return pool - set(watched_ids)

def build_person_candidate_pool(
    names, watched_ids, api_key,
    search_person_fn=search_person, discover_fn=discover_by_person,
    max_pool=None,
) -> set:
    pool = set()
    for name in names:
        if _full(pool, max_pool):
            break
        person_id = search_person_fn(name, api_key)
        if person_id is not None:
            pool.update(discover_fn(person_id, api_key))
    return pool - set(watched_ids)
