import time
import requests

API = "https://www.omdbapi.com/"
TIMEOUT = 15
MAX_RETRIES = 3

def _get(session, params):
    s = session or requests
    for attempt in range(MAX_RETRIES):
        if attempt:
            time.sleep(2 ** (attempt - 1))
        try:
            resp = s.get(API, params=params, timeout=TIMEOUT)
            resp.raise_for_status()
            return resp.json()
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if attempt == MAX_RETRIES - 1:
                raise

def fetch_ratings(imdb_id: str, api_key: str, session=None) -> dict:
    """IMDb rating + Rotten Tomatoes % for an imdb_id. Never raises; returns
    {"imdb_rating": float|None, "rt_score": int|None}."""
    empty = {"imdb_rating": None, "rt_score": None}
    if not imdb_id or not api_key:
        return empty
    try:
        data = _get(session, {"apikey": api_key, "i": imdb_id})
    except Exception:
        return empty
    if not data or data.get("Response") == "False":
        return empty
    imdb_rating = None
    try:
        imdb_rating = float(data["imdbRating"])
    except (KeyError, ValueError, TypeError):
        pass
    rt_score = None
    for r in data.get("Ratings", []):
        if r.get("Source") == "Rotten Tomatoes":
            v = str(r.get("Value", "")).rstrip("%")
            if v.isdigit():
                rt_score = int(v)
    return {"imdb_rating": imdb_rating, "rt_score": rt_score}
