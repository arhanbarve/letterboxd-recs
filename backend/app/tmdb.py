import time

import requests

API = "https://api.themoviedb.org/3"
TIMEOUT = 15
MAX_RETRIES = 3

def _get(session, url, params):
    s = session or requests
    for attempt in range(MAX_RETRIES):
        if attempt:
            time.sleep(2 ** (attempt - 1))  # 1s, 2s
        try:
            resp = s.get(url, params=params, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if attempt == MAX_RETRIES - 1:
                raise

def enrich(tmdb_id: int, api_key: str, session=None) -> dict:
    data = _get(session, f"{API}/movie/{tmdb_id}", {
        "api_key": api_key,
        "append_to_response": "credits,keywords",
    })
    year = int(data["release_date"][:4]) if data.get("release_date") else None
    crew = data.get("credits", {}).get("crew", [])
    director_entry = next((c for c in crew if c.get("job") == "Director"), None)
    cast_entries = data.get("credits", {}).get("cast", [])[:5]
    keywords = [k["name"] for k in data.get("keywords", {}).get("keywords", [])]
    return {
        "tmdb_id": tmdb_id,
        "title": data.get("title"),
        "year": year,
        "decade": (year // 10) * 10 if year else None,
        "director": director_entry["name"] if director_entry else None,
        "director_id": director_entry["id"] if director_entry else None,
        "director_person": ({
            "person_id": director_entry["id"], "name": director_entry["name"],
            "profile_path": director_entry.get("profile_path"),
        } if director_entry else None),
        "genres": [g["name"] for g in data.get("genres", [])],
        "cast": [c["name"] for c in cast_entries],
        "cast_people": [
            {"person_id": c["id"], "name": c["name"], "profile_path": c.get("profile_path")}
            for c in cast_entries
        ],
        "keywords": keywords,
        "poster_path": data.get("poster_path"),
        "backdrop_path": data.get("backdrop_path"),
        "overview": data.get("overview"),
        "runtime": data.get("runtime"),
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

def search_person(name: str, api_key: str, session=None) -> int | None:
    data = _get(session, f"{API}/search/person", {"api_key": api_key, "query": name})
    results = data.get("results", [])
    return results[0]["id"] if results else None

def discover_by_person(person_id: int, api_key: str, session=None) -> list[int]:
    data = _get(session, f"{API}/discover/movie", {
        "api_key": api_key,
        "with_people": person_id,
        "sort_by": "vote_average.desc",
        "vote_count.gte": 50,
    })
    return [m["id"] for m in data.get("results", [])]

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

def search_movie(title: str, year: int | None, api_key: str, session=None) -> int | None:
    """Resolve a TMDB id from title+year. Exact title (+year) wins; else any
    result with a matching year; else None (caller falls through to the next
    resolution layer)."""
    params = {"api_key": api_key, "query": title}
    if year:
        params["primary_release_year"] = year
    data = _get(session, f"{API}/search/movie", params)
    results = data.get("results", [])

    def _year(r):
        rd = r.get("release_date") or ""
        return int(rd[:4]) if len(rd) >= 4 and rd[:4].isdigit() else None

    for r in results:
        if r.get("title", "").lower() == title.lower() and (year is None or _year(r) == year):
            return r["id"]
    if year is not None:
        for r in results:
            if _year(r) == year:
                return r["id"]
    return None
