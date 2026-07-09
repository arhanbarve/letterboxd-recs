import os
import re
import threading
import time

from bs4 import BeautifulSoup

from app.errors import Cancelled
from app.resolver import make_resolver

def _rating_from_class(rating_span) -> float | None:
    if rating_span is None:
        return None
    for cls in rating_span.get("class", []):
        if cls.startswith("rated-"):
            return int(cls.split("-")[1]) / 2.0
    return None

_NAME_YEAR_RE = re.compile(r"^(.*?)\s+\((\d{4})\)$")

def _split_item_name(name: str | None) -> tuple[str | None, int | None]:
    if not name:
        return None, None
    m = _NAME_YEAR_RE.match(name)
    if m:
        return m.group(1), int(m.group(2))
    return name, None

def parse_films_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    entries = []
    for li in soup.select("li.griditem"):
        poster = li.select_one("div[data-item-slug]")
        if poster is None:
            continue
        img = poster.select_one("img")
        title, year = _split_item_name(poster.get("data-item-name"))
        if title is None:
            title = img.get("alt") if img else None
        entries.append({
            "slug": poster.get("data-item-slug"),
            "title": title,
            "year": year,
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

def _proxy_config():
    """Cloudflare's bot score weighs source-IP reputation heavily — a
    datacenter/PaaS IP (e.g. Railway) gets treated with suspicion regardless
    of session freshness, unlike a residential IP (confirmed live 2026-07-09:
    identical code, same moment, home IP passed clean while the deployed
    backend's IP 403'd deterministically). Routing through a residential
    proxy is the fix; unset SCRAPER_PROXY_SERVER to disable."""
    server = os.environ.get("SCRAPER_PROXY_SERVER")
    if not server:
        return None
    proxy = {"server": server}
    username = os.environ.get("SCRAPER_PROXY_USERNAME")
    password = os.environ.get("SCRAPER_PROXY_PASSWORD")
    if username:
        proxy["username"] = username
    if password:
        proxy["password"] = password
    return proxy

def _get_browser():
    """Lazily creates one Playwright browser per thread. Letterboxd sits
    behind Cloudflare bot-management; plain HTTP clients (requests,
    cloudscraper) are refused outright on pagination URLs (TLS fingerprint —
    confirmed live 2026-07-09), but a real browser engine passes. Contexts are
    deliberately NOT cached here — see default_get."""
    if not hasattr(_thread_local, "browser"):
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        _thread_local.pw = pw
        _thread_local.browser = pw.chromium.launch(headless=True)
    return _thread_local.browser

def _close_browser():
    # Swallow close/stop errors so teardown never masks the exception that
    # triggered it (e.g. a Cancelled propagating through this finally block).
    if hasattr(_thread_local, "browser"):
        try:
            _thread_local.browser.close()
        except Exception:
            pass
        try:
            _thread_local.pw.stop()
        except Exception:
            pass
        del _thread_local.browser
        del _thread_local.pw

def default_get(url: str, on_request=None) -> str:
    # Cloudflare keys its bot verdict to the browser session's cookie jar —
    # not to the source IP and not to a request count. The first navigation in
    # a fresh context gets a grace pass while telemetry is collected; once the
    # (headless) session is flagged, every later navigation to a protected
    # path (profile pagination) 403s on that session, so retrying on the same
    # context is guaranteed futile. Confirmed live 2026-07-09 — see
    # docs/superpowers/specs/2026-07-09-scraper-cloudflare-resilience-design.md.
    # Therefore: one fresh context per attempt; a flagged session is never
    # reused. `on_request` lets investigations re-instrument cheaply.
    browser = _get_browser()
    backoffs = [2, 5, 10]
    last_status = None
    for attempt, wait in enumerate([0] + backoffs):
        if wait:
            time.sleep(wait)
        context_kwargs = {"user_agent": USER_AGENT, "locale": "en-US"}
        proxy = _proxy_config()
        if proxy:
            context_kwargs["proxy"] = proxy
        context = browser.new_context(**context_kwargs)
        try:
            page = context.new_page()
            t0 = time.monotonic()
            resp = page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2500)
            dt = time.monotonic() - t0
            last_status = resp.status
            body = page.content()
            if on_request:
                challenged = "Just a moment" in body or "cf-browser-verification" in body
                on_request({"url": url, "status": last_status, "attempt": attempt, "elapsed_s": round(dt, 2), "challenged": challenged})
            if last_status not in (403, 429):
                return body
        finally:
            context.close()
    raise RuntimeError(
        f"Blocked fetching {url}: status {last_status} after {len(backoffs)} "
        f"retries. Letterboxd's bot protection refused the crawl — try again "
        f"in a minute."
    )

def crawl_films_list(username, get_html=default_get, delay: float = 1.0, should_cancel=None) -> list[dict]:
    """Fetch only the paginated films-LIST pages (72 films each) — the entire
    Letterboxd HTML crawl on the happy path. TMDB ids come from the resolver
    cascade afterwards, not from per-film detail pages (which is what used to
    blow the ~72-request Cloudflare budget and 403 every >72-film profile)."""
    entries = []
    url = f"{BASE}/{username}/films/"
    while url:
        if should_cancel and should_cancel():
            raise Cancelled()
        html = get_html(url)
        entries.extend(parse_films_page(html))
        nxt = parse_next_page_url(html)
        url = f"{BASE}{nxt}" if nxt else None
        if url and delay:
            time.sleep(delay)
    return entries

def scrape_profile(
    username: str, get_html=default_get, delay: float = 1.0,
    on_progress=None, should_cancel=None, resolve_ids=None,
) -> list[dict]:
    try:
        entries = crawl_films_list(username, get_html, delay=delay, should_cancel=should_cancel)

        if resolve_ids is None:
            # Standalone/legacy mode: detail-page-only cascade, used until callers
            # inject the full cache->rss->search->detail cascade (see resolver.py).
            def detail_fn(slug):
                html = get_html(f"{BASE}/film/{slug}/")
                if delay:
                    time.sleep(delay)
                return parse_tmdb_id(html)
            resolve_ids = make_resolver(detail_fn=detail_fn, max_detail=len(entries))

        resolve_ids(entries, on_progress=on_progress, should_cancel=should_cancel)

        # Films without a TMDB id can never be produced as recommendation
        # candidates (candidates always come from TMDB), so they're safe to drop.
        films = [e for e in entries if e.get("tmdb_id") is not None]

        profile_html = get_html(f"{BASE}/{username}/")
        declared = parse_declared_film_count(profile_html)
        if declared is not None and len(entries) < declared:
            raise RuntimeError(
                f"Incomplete scrape: found {len(entries)} films but {username}'s "
                f"Letterboxd profile reports {declared}. The crawl was likely "
                f"blocked partway through — try refreshing again in a minute."
            )
        return films
    finally:
        _close_browser()
