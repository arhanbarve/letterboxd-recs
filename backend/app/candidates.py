from app.tmdb import related_ids

def build_candidate_pool(liked_ids, watched_ids, api_key, related_fn=related_ids) -> set:
    pool = set()
    for fid in liked_ids:
        pool.update(related_fn(fid, api_key))
    return pool - set(watched_ids)
