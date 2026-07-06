import requests

API = "https://api.themoviedb.org/3"

def _get(session, url, params):
    s = session or requests
    resp = s.get(url, params=params)
    resp.raise_for_status()
    return resp.json()

def enrich(tmdb_id: int, api_key: str, session=None) -> dict:
    data = _get(session, f"{API}/movie/{tmdb_id}", {
        "api_key": api_key,
        "append_to_response": "credits,keywords",
    })
    year = int(data["release_date"][:4]) if data.get("release_date") else None
    crew = data.get("credits", {}).get("crew", [])
    director = next((c["name"] for c in crew if c.get("job") == "Director"), None)
    cast = [c["name"] for c in data.get("credits", {}).get("cast", [])[:5]]
    keywords = [k["name"] for k in data.get("keywords", {}).get("keywords", [])]
    return {
        "tmdb_id": tmdb_id,
        "title": data.get("title"),
        "year": year,
        "decade": (year // 10) * 10 if year else None,
        "director": director,
        "genres": [g["name"] for g in data.get("genres", [])],
        "cast": cast,
        "keywords": keywords,
        "poster_path": data.get("poster_path"),
        "vote_avg": data.get("vote_average"),
    }

def watch_providers(tmdb_id: int, api_key: str, region: str = "US", session=None) -> dict:
    data = _get(session, f"{API}/movie/{tmdb_id}/watch/providers", {"api_key": api_key})
    region_data = data.get("results", {}).get(region, {})

    def normalize(kind):
        return [
            {"name": p["provider_name"], "logo_path": p["logo_path"]}
            for p in region_data.get(kind, [])
        ]

    return {
        "link": region_data.get("link"),
        "flatrate": normalize("flatrate"),
        "rent": normalize("rent"),
        "buy": normalize("buy"),
    }

def related_ids(tmdb_id: int, api_key: str, session=None, pages: int = 1) -> list[int]:
    ids = []
    for endpoint in ("recommendations", "similar"):
        for page in range(1, pages + 1):
            data = _get(session, f"{API}/movie/{tmdb_id}/{endpoint}",
                        {"api_key": api_key, "page": page})
            ids.extend(r["id"] for r in data.get("results", []))
            if page >= data.get("total_pages", 1):
                break
    return ids
