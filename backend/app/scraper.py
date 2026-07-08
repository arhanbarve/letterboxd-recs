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

def parse_declared_film_count(html: str) -> int | None:
    soup = BeautifulSoup(html, "html.parser")
    for h4 in soup.select("h4.profile-statistic"):
        link = h4.select_one("a")
        if link and link.get("href", "").rstrip("/").endswith("/films"):
            value = h4.select_one("span.value")
            if value:
                return int(value.get_text(strip=True).replace(",", ""))
    return None

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

def default_get(url: str, on_request=None) -> str:
    # Known limitation: profiles with >~72 rated films 403 on films-page 2.
    # Confirmed live (see docs/superpowers/plans/2026-07-08-refresh-and-progress-overhaul-plan.md,
    # Task 0) that pacing/jitter, wider backoff, click-driven pagination, stealth
    # patching, and browser-context rotation all fail identically at the same
    # request count — this is Cloudflare rate-limiting by source IP, not fixable
    # client-side. `on_request` lets a future investigation re-instrument cheaply.
    page = _get_page()
    backoffs = [2, 5, 10]
    last_status = None
    for attempt, wait in enumerate([0] + backoffs):
        if wait:
            time.sleep(wait)
        t0 = time.monotonic()
        resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(2500)
        dt = time.monotonic() - t0
        last_status = resp.status
        if on_request:
            challenged = "Just a moment" in page.content() or "cf-browser-verification" in page.content()
            on_request({"url": url, "status": last_status, "attempt": attempt, "elapsed_s": round(dt, 2), "challenged": challenged})
        if last_status not in (403, 429):
            return page.content()
    raise RuntimeError(
        f"Blocked fetching {url}: status {last_status} after {len(backoffs)} retries"
    )

def scrape_profile(
    username: str, get_html=default_get, delay: float = 1.0, on_progress=None
) -> list[dict]:
    films = []
    total_seen = 0
    url = f"{BASE}/{username}/films/"
    while url:
        html = get_html(url)
        page_entries = parse_films_page(html)
        total_seen += len(page_entries)
        for entry in page_entries:
            detail = get_html(f"{BASE}/film/{entry['slug']}/")
            entry["tmdb_id"] = parse_tmdb_id(detail)
            # Films Letterboxd can't link to TMDB can never be produced as a
            # recommendation candidate (candidates always come from TMDB), so
            # they're safe to drop here — nothing to exclude them from.
            if entry["tmdb_id"] is not None:
                films.append(entry)
            if on_progress:
                on_progress(len(films))
            if delay:
                time.sleep(delay)
        nxt = parse_next_page_url(html)
        url = f"{BASE}{nxt}" if nxt else None

    profile_html = get_html(f"{BASE}/{username}/")
    declared = parse_declared_film_count(profile_html)
    if declared is not None and total_seen < declared:
        raise RuntimeError(
            f"Incomplete scrape: found {total_seen} films but {username}'s "
            f"Letterboxd profile reports {declared}. The crawl was likely "
            f"blocked partway through — try refreshing again."
        )
    return films
