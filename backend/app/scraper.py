import re
import threading
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
    for li in soup.select("li.griditem"):
        poster = li.select_one("div[data-item-slug]")
        if poster is None:
            continue
        img = poster.select_one("img")
        entries.append({
            "slug": poster.get("data-item-slug"),
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
    link = soup.select_one('a[data-track-action="TMDB"]')
    if link is None:
        return None
    m = re.search(r"/movie/(\d+)", link.get("href", ""))
    return int(m.group(1)) if m else None

BASE = "https://letterboxd.com"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

_thread_local = threading.local()

def _get_page():
    """Lazily creates one Playwright browser page per thread. Letterboxd sits
    behind Cloudflare bot-management (JS challenge); plain HTTP clients
    (requests, cloudscraper) get walled off, but a real browser engine passes
    it like any other visitor."""
    if not hasattr(_thread_local, "page"):
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT)
        _thread_local.pw = pw
        _thread_local.browser = browser
        _thread_local.page = page
    return _thread_local.page

def default_get(url: str) -> str:
    page = _get_page()
    backoffs = [2, 5, 10]
    for wait in [0] + backoffs:
        if wait:
            time.sleep(wait)
        resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2500)
        if resp.status not in (403, 429):
            return page.content()
    return page.content()

def scrape_profile(
    username: str, get_html=default_get, delay: float = 1.0, on_progress=None
) -> list[dict]:
    films = []
    url = f"{BASE}/{username}/films/"
    while url:
        html = get_html(url)
        for entry in parse_films_page(html):
            detail = get_html(f"{BASE}/film/{entry['slug']}/")
            entry["tmdb_id"] = parse_tmdb_id(detail)
            if entry["tmdb_id"] is not None:
                films.append(entry)
            if on_progress:
                on_progress(len(films))
            if delay:
                time.sleep(delay)
        nxt = parse_next_page_url(html)
        url = f"{BASE}{nxt}" if nxt else None
    return films
