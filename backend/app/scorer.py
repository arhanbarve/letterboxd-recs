import numpy as np

WEIGHTS = {"genre": 0.25, "keyword": 0.25, "director": 0.20,
           "actor": 0.20, "decade": 0.10}

def _contributions(cand: dict, profile: dict) -> list[tuple[str, float]]:
    out = []
    for g in cand.get("genres", []):
        out.append((g, WEIGHTS["genre"] * profile["genre"].get(g, 0.0)))
    for k in cand.get("keywords", []):
        out.append((k, WEIGHTS["keyword"] * profile["keyword"].get(k, 0.0)))
    if cand.get("director"):
        out.append((cand["director"],
                    WEIGHTS["director"] * profile["director"].get(cand["director"], 0.0)))
    for a in cand.get("cast", []):
        out.append((a, WEIGHTS["actor"] * profile["actor"].get(a, 0.0)))
    if cand.get("decade") is not None:
        out.append((str(cand["decade"]),
                    WEIGHTS["decade"] * profile["decade"].get(cand["decade"], 0.0)))
    return out

def match_raw_score(cand: dict, profile: dict) -> float:
    return sum(v for _, v in _contributions(cand, profile))

def why_tags(cand: dict, profile: dict, n: int = 3) -> list[str]:
    contrib = sorted(_contributions(cand, profile), key=lambda x: x[1], reverse=True)
    return [name for name, val in contrib if val > 0][:n]

def _feature_vector(film: dict, vocab: list[str]) -> np.ndarray:
    tokens = set(film.get("genres", [])) | set(film.get("keywords", []))
    return np.array([1.0 if t in tokens else 0.0 for t in vocab])

def _cosine(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))

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
    raws = [(c, match_raw_score(c, profile)) for c in cands]
    vals = [r for _, r in raws]
    lo, hi = min(vals), max(vals)
    span = (hi - lo) or 1.0
    results = []
    for c, raw in raws:
        results.append({
            "tmdb_id": c["tmdb_id"],
            "match_pct": round((raw - lo) / span * 100.0, 1),
            "predicted_rating": round(predict_rating(c, rated, k), 2),
            "why_tags": why_tags(c, profile),
        })
    results.sort(key=lambda r: r["match_pct"], reverse=True)
    return results
