"""Letterboxd RSS feed: exact tmdb ids for a user's ~50 most recent films.
A pure fallback layer for the id-resolution cascade — every failure path
returns None/{} rather than raising."""
import re

import requests

from app.scraper import USER_AGENT

RSS_URL_TEMPLATE = "https://letterboxd.com/{username}/rss/"

_ITEM_RE = re.compile(r"<item>(.*?)</item>", re.S)
_SLUG_RE = re.compile(r"letterboxd\.com/[^/]+/film/([^/]+)/")
_TMDB_RE = re.compile(r"<tmdb:movieId>(\d+)</tmdb:movieId>")

def fetch_rss(username: str, get_html=None) -> str | None:
    url = RSS_URL_TEMPLATE.format(username=username)
    try:
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
        if resp.status_code == 200:
            return resp.text
    except requests.RequestException:
        pass
    if get_html is None:
        return None
    try:
        return get_html(url)
    except Exception:
        return None

def parse_rss_tmdb_map(xml: str) -> dict[str, int]:
    out = {}
    for item in _ITEM_RE.findall(xml or ""):
        slug_m = _SLUG_RE.search(item)
        tmdb_m = _TMDB_RE.search(item)
        if slug_m and tmdb_m:
            out[slug_m.group(1)] = int(tmdb_m.group(1))
    return out
