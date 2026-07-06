from collections import defaultdict

MIDPOINT = 2.5

def _normalize(d: dict) -> dict:
    if not d:
        return {}
    m = max(abs(v) for v in d.values()) or 1.0
    return {k: v / m for k, v in d.items()}

def build_taste_profile(films: list[dict]) -> dict:
    raw = {ft: defaultdict(float) for ft in
           ("genre", "director", "actor", "keyword", "decade")}
    for f in films:
        w = f["rating"] - MIDPOINT
        for g in f.get("genres", []):
            raw["genre"][g] += w
        for k in f.get("keywords", []):
            raw["keyword"][k] += w
        for a in f.get("cast", []):
            raw["actor"][a] += w
        if f.get("director"):
            raw["director"][f["director"]] += w
        if f.get("decade") is not None:
            raw["decade"][f["decade"]] += w
    return {ft: _normalize(dict(d)) for ft, d in raw.items()}
