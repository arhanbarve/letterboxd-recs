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
