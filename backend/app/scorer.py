import numpy as np

WEIGHTS = {"genre": 0.25, "keyword": 0.25, "director": 0.20,
           "actor": 0.20, "decade": 0.10}
THEORETICAL_MAX = sum(WEIGHTS.values())  # 1.0 — fixed ceiling for absolute match %

def _avg(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0

def _contributions(cand: dict, profile: dict) -> list[tuple[str, float]]:
    out = []
    genres = cand.get("genres", [])
    if genres:
        out.append(("genre", WEIGHTS["genre"] * _avg([profile["genre"].get(g, 0.0) for g in genres])))
    keywords = cand.get("keywords", [])
    if keywords:
        out.append(("keyword", WEIGHTS["keyword"] * _avg([profile["keyword"].get(k, 0.0) for k in keywords])))
    if cand.get("director"):
        out.append(("director", WEIGHTS["director"] * profile["director"].get(cand["director"], 0.0)))
    cast = cand.get("cast", [])
    if cast:
        out.append(("actor", WEIGHTS["actor"] * _avg([profile["actor"].get(a, 0.0) for a in cast])))
    if cand.get("decade") is not None:
        out.append(("decade", WEIGHTS["decade"] * profile["decade"].get(cand["decade"], 0.0)))
    return out

def match_raw_score(cand: dict, profile: dict) -> float:
    return sum(v for _, v in _contributions(cand, profile))

def _feature_vector(film: dict, vocab: list[str]) -> np.ndarray:
    tokens = set(film.get("genres", [])) | set(film.get("keywords", []))
    return np.array([1.0 if t in tokens else 0.0 for t in vocab])

def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))

def _nearest_rated(cand: dict, rated: list[dict], vocab: list[str], limit: int) -> list[dict]:
    sims = [(_cosine(_feature_vector(cand, vocab), _feature_vector(f, vocab)), f) for f in rated]
    sims = [s for s in sims if s[0] > 0]
    sims.sort(key=lambda s: s[0], reverse=True)
    return [f for _, f in sims[:limit]]

def top_neighbors(cand: dict, rated: list[dict], k: int = 2) -> list[dict]:
    """The rated films most like `cand`, preferring the ones the user rated highest."""
    vocab = sorted({t for f in rated + [cand]
                    for t in set(f.get("genres", [])) | set(f.get("keywords", []))})
    nearest = _nearest_rated(cand, rated, vocab, limit=5)
    nearest.sort(key=lambda f: f["rating"], reverse=True)
    return nearest[:k]

def connection_phrase(cand: dict, neighbors: list[dict]) -> str | None:
    if cand.get("director") and any(n.get("director") == cand["director"] for n in neighbors):
        return f"directed by {cand['director']}"
    cand_cast = set(cand.get("cast", []))
    for n in neighbors:
        shared = cand_cast & set(n.get("cast", []))
        if shared:
            return f"starring {sorted(shared)[0]}"
    cand_kw = set(cand.get("keywords", []))
    for n in neighbors:
        shared = cand_kw & set(n.get("keywords", []))
        if shared:
            return f"a shared thread of {sorted(shared)[0]}"
    cand_genre = set(cand.get("genres", []))
    for n in neighbors:
        shared = cand_genre & set(n.get("genres", []))
        if shared:
            return f"the same {sorted(shared)[0].lower()} sensibility"
    return None

def why_for(cand: dict, rated: list[dict]) -> dict:
    neighbors = top_neighbors(cand, rated, k=2)
    if not neighbors:
        return {"neighbors": [], "connection": None}
    return {
        "neighbors": [{"title": n["title"], "rating": n["rating"]} for n in neighbors],
        "connection": connection_phrase(cand, neighbors),
    }

def predict_rating(cand: dict, rated: list[dict], k: int = 10) -> float:
    vocab = sorted({t for f in rated + [cand]
                    for t in set(f.get("genres", [])) | set(f.get("keywords", []))})
    cv = _feature_vector(cand, vocab)
    sims = [(_cosine(cv, _feature_vector(f, vocab)), f["rating"]) for f in rated]
    sims = [s for s in sims if s[0] > 0]
    sims.sort(reverse=True)
    top = sims[:k]
    if not top:
        return float(np.mean([f["rating"] for f in rated])) if rated else 0.0
    wsum = sum(w for w, _ in top)
    return sum(w * r for w, r in top) / wsum

def score_candidates(cands, profile, rated, k: int = 10) -> list[dict]:
    if not cands:
        return []
    results = []
    for c in cands:
        raw = match_raw_score(c, profile)
        match_pct = round(max(0.0, min(raw, THEORETICAL_MAX)) / THEORETICAL_MAX * 100.0, 1)
        results.append({
            "tmdb_id": c["tmdb_id"],
            "match_pct": match_pct,
            "predicted_rating": round(predict_rating(c, rated, k), 2),
            "why": why_for(c, rated),
        })
    results.sort(key=lambda r: r["match_pct"], reverse=True)
    return results
