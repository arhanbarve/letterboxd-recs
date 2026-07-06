import re
import time

from bs4 import BeautifulSoup

def _rating_from_class(rating_span) -> float | None:
    if rating_span is None:
        return None
    for cls in rating_span.get("class", []):
        if cls.startswith("rated-"):
            return int(cls.split("-")[1]) / 2.0
    return None

def parse_films_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    entries = []
    for li in soup.select("li.poster-container"):
        poster = li.select_one("div.film-poster")
        if poster is None:
            continue
        img = poster.select_one("img")
        entries.append({
            "slug": poster.get("data-film-slug"),
            "title": img.get("alt") if img else None,
            "rating": _rating_from_class(li.select_one("span.rating")),
        })
    return entries

def parse_next_page_url(html: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    nxt = soup.select_one("div.paginate-nextprev a.next")
    return nxt.get("href") if nxt else None

def parse_tmdb_id(html: str) -> int | None:
    soup = BeautifulSoup(html, "html.parser")
    link = soup.select_one('a[data-track-action="TMDb"]')
    if link is None:
        return None
    m = re.search(r"/movie/(\d+)", link.get("href", ""))
    return int(m.group(1)) if m else None

BASE = "https://letterboxd.com"

def default_get(url: str) -> str:
    import requests
    resp = requests.get(url, headers={"User-Agent": "personal-recommender"})
    resp.raise_for_status()
    return resp.text

def scrape_profile(username: str, get_html=default_get, delay: float = 1.0) -> list[dict]:
    films = []
    url = f"{BASE}/{username}/films/"
    while url:
        html = get_html(url)
        for entry in parse_films_page(html):
            detail = get_html(f"{BASE}/film/{entry['slug']}/")
            entry["tmdb_id"] = parse_tmdb_id(detail)
            if entry["tmdb_id"] is not None:
                films.append(entry)
            if delay:
                time.sleep(delay)
        nxt = parse_next_page_url(html)
        url = f"{BASE}{nxt}" if nxt else None
    return films
