import pytest
from pathlib import Path
from app.scraper import parse_films_page

FIX = Path(__file__).parent / "fixtures"

def test_parse_films_page_extracts_slug_title_rating():
    html = (FIX / "films_page.html").read_text()
    entries = parse_films_page(html)
    by_slug = {e["slug"]: e for e in entries}
    assert by_slug["parasite"]["title"] == "Parasite"
    assert by_slug["parasite"]["rating"] == 5.0
    assert by_slug["cats"]["rating"] == 1.0
    # unrated film present but rating is None
    assert by_slug["unrated-film"]["rating"] is None

def test_parse_films_page_extracts_year_from_item_name():
    html = (FIX / "films_page.html").read_text()
    by_slug = {e["slug"]: e for e in parse_films_page(html)}
    assert by_slug["parasite"]["year"] == 2019
    assert by_slug["parasite"]["title"] == "Parasite"
    assert by_slug["cats"]["year"] == 2019

def test_parse_films_page_handles_item_name_without_year():
    html = '''<html><body><ul class="grid">
      <li class="griditem">
        <div data-item-name="Some Film" data-item-slug="some-film" data-item-link="/film/some-film/">
          <img class="image" alt="Some Film"/>
        </div>
      </li></ul></body></html>'''
    entries = parse_films_page(html)
    assert entries[0]["title"] == "Some Film"
    assert entries[0]["year"] is None

def test_parse_films_page_falls_back_to_alt_when_no_item_name():
    html = '''<html><body><ul class="grid">
      <li class="griditem">
        <div data-item-slug="alt-only-film">
          <img class="image" alt="Alt Only Film"/>
        </div>
      </li></ul></body></html>'''
    entries = parse_films_page(html)
    assert entries[0]["title"] == "Alt Only Film"
    assert entries[0]["year"] is None

def test_parse_films_page_finds_next_page():
    html = (FIX / "films_page.html").read_text()
    assert parse_next_page_url(html) == "/alice/films/page/2/"

from app.scraper import parse_next_page_url  # noqa: E402

from app.scraper import parse_tmdb_id

def test_parse_tmdb_id_from_film_page():
    html = (FIX / "film_detail.html").read_text()
    assert parse_tmdb_id(html) == 496243

def test_parse_tmdb_id_missing_returns_none():
    assert parse_tmdb_id("<html><body>no link</body></html>") is None

from app.scraper import scrape_profile
from app.scraper import crawl_films_list

def test_scrape_profile_paginates_and_resolves_tmdb_ids():
    page1 = (FIX / "films_page.html").read_text()  # 3 films: parasite, cats, unrated-film
    page2 = '<html><body><ul class="poster-list"></ul></body></html>'
    detail = (FIX / "film_detail.html").read_text()
    stats = '<html><body><h4 class="profile-statistic statistic"><a href="/alice/films/"><span class="value">3</span></a></h4></body></html>'

    def fake_get(url):
        if url.endswith("/films/") or url.endswith("/films/page/1/"):
            return page1
        if url.endswith("/films/page/2/"):
            return page2
        if url.endswith("/alice/"):
            return stats
        return detail  # any film page

    films = scrape_profile("alice", fake_get, delay=0)
    rated = {f["slug"]: f for f in films}
    assert rated["parasite"]["tmdb_id"] == 496243
    assert rated["parasite"]["rating"] == 5.0
    assert all(f["tmdb_id"] == 496243 for f in films)

def test_scrape_profile_raises_when_scraped_count_is_below_declared_total():
    page1 = (FIX / "films_page.html").read_text()  # 3 films
    page2 = '<html><body><ul class="poster-list"></ul></body></html>'
    detail = (FIX / "film_detail.html").read_text()
    stats = '<html><body><h4 class="profile-statistic statistic"><a href="/alice/films/"><span class="value">87</span></a></h4></body></html>'

    def fake_get(url):
        if url.endswith("/films/") or url.endswith("/films/page/1/"):
            return page1
        if url.endswith("/films/page/2/"):
            return page2
        if url.endswith("/alice/"):
            return stats
        return detail

    with pytest.raises(RuntimeError, match="Incomplete scrape"):
        scrape_profile("alice", fake_get, delay=0)

from app import scraper

class _FakeResp:
    def __init__(self, status):
        self.status = status

class _FakePage:
    def __init__(self, browser):
        self._browser = browser
    def goto(self, url, wait_until=None, timeout=None):
        item = self._browser._statuses.pop(0)
        if isinstance(item, Exception):
            raise item  # simulate a Playwright navigation failure (dead proxy, DNS, timeout)
        return _FakeResp(item)
    def wait_for_timeout(self, ms):
        pass
    def content(self):
        return self._browser._content

class _FakeContext:
    def __init__(self, browser):
        self._browser = browser
    def new_page(self):
        return _FakePage(self._browser)
    def close(self):
        self._browser.contexts_closed += 1

class _FakeBrowser:
    """One goto() pops one status; tracks context lifecycle."""
    def __init__(self, statuses, content="<html>ok</html>"):
        self._statuses = list(statuses)
        self._content = content
        self.context_kwargs = []
        self.contexts_closed = 0
    @property
    def contexts_opened(self):
        return len(self.context_kwargs)
    def new_context(self, **kwargs):
        self.context_kwargs.append(kwargs)
        return _FakeContext(self)

def _install_fake_browser(monkeypatch, statuses, content="<html>ok</html>"):
    fb = _FakeBrowser(statuses, content)
    monkeypatch.setattr(scraper, "_get_browser", lambda: fb)
    monkeypatch.setattr(scraper.time, "sleep", lambda s: None)
    return fb

def test_default_get_returns_content_on_first_success(monkeypatch):
    _install_fake_browser(monkeypatch, [200])
    assert scraper.default_get("https://letterboxd.com/alice/films/") == "<html>ok</html>"

def test_default_get_raises_after_exhausting_retries_on_403(monkeypatch):
    _install_fake_browser(monkeypatch, [403, 403, 403, 403], content="<html>challenge</html>")
    with pytest.raises(RuntimeError, match="Blocked"):
        scraper.default_get("https://letterboxd.com/alice/films/")

def test_default_get_recovers_after_one_retry(monkeypatch):
    _install_fake_browser(monkeypatch, [429, 200])
    assert scraper.default_get("https://letterboxd.com/alice/films/") == "<html>ok</html>"

def test_default_get_reports_each_attempt_via_on_request(monkeypatch):
    _install_fake_browser(monkeypatch, [429, 200])
    events = []
    scraper.default_get("https://letterboxd.com/alice/films/", on_request=events.append)
    assert [e["status"] for e in events] == [429, 200]
    assert [e["attempt"] for e in events] == [0, 1]
    assert all(e["challenged"] is False for e in events)

def test_default_get_opens_and_closes_fresh_context_per_attempt(monkeypatch):
    # THE fix: a Cloudflare-flagged session must never be reused, so every
    # attempt (not just every call) gets its own context — and closes it.
    fb = _install_fake_browser(monkeypatch, [429, 200])
    scraper.default_get("https://letterboxd.com/alice/films/")
    assert fb.contexts_opened == 2
    assert fb.contexts_closed == 2

def test_default_get_closes_every_context_even_when_blocked(monkeypatch):
    fb = _install_fake_browser(monkeypatch, [403, 403, 403, 403], content="x")
    with pytest.raises(RuntimeError):
        scraper.default_get("https://letterboxd.com/alice/films/")
    assert fb.contexts_opened == 4
    assert fb.contexts_closed == 4

def test_default_get_context_sends_ua_and_locale(monkeypatch):
    monkeypatch.delenv("SCRAPER_PROXY_SERVER", raising=False)
    fb = _install_fake_browser(monkeypatch, [200])
    scraper.default_get("https://letterboxd.com/alice/films/")
    assert fb.context_kwargs[0] == {"user_agent": scraper.USER_AGENT, "locale": "en-US"}

def test_default_get_uses_proxy_when_configured(monkeypatch):
    monkeypatch.setenv("SCRAPER_PROXY_SERVER", "http://proxy.example.com:8000")
    monkeypatch.setenv("SCRAPER_PROXY_USERNAME", "proxyuser")
    monkeypatch.setenv("SCRAPER_PROXY_PASSWORD", "proxypass")
    fb = _install_fake_browser(monkeypatch, [200])
    scraper.default_get("https://letterboxd.com/alice/films/")
    assert fb.context_kwargs[0] == {
        "user_agent": scraper.USER_AGENT, "locale": "en-US",
        "proxy": {"server": "http://proxy.example.com:8000",
                  "username": "proxyuser", "password": "proxypass"},
    }

def test_default_get_proxy_without_credentials_omits_them(monkeypatch):
    monkeypatch.setenv("SCRAPER_PROXY_SERVER", "http://proxy.example.com:8000")
    monkeypatch.delenv("SCRAPER_PROXY_USERNAME", raising=False)
    monkeypatch.delenv("SCRAPER_PROXY_PASSWORD", raising=False)
    fb = _install_fake_browser(monkeypatch, [200])
    scraper.default_get("https://letterboxd.com/alice/films/")
    assert fb.context_kwargs[0]["proxy"] == {"server": "http://proxy.example.com:8000"}

def test_default_get_new_context_per_attempt_uses_fresh_proxy_config(monkeypatch):
    # each retry re-reads env so a proxy rotation/health-check between
    # attempts (e.g. a supervisor swapping SCRAPER_PROXY_SERVER) takes effect
    monkeypatch.setenv("SCRAPER_PROXY_SERVER", "http://proxy.example.com:8000")
    fb = _install_fake_browser(monkeypatch, [429, 200])
    scraper.default_get("https://letterboxd.com/alice/films/")
    assert len(fb.context_kwargs) == 2
    assert all("proxy" in kw for kw in fb.context_kwargs)

def test_default_get_blocked_error_suggests_retrying(monkeypatch):
    _install_fake_browser(monkeypatch, [403, 403, 403, 403], content="x")
    with pytest.raises(RuntimeError, match="try again in a minute"):
        scraper.default_get("https://letterboxd.com/alice/films/")

def test_default_get_retries_when_goto_raises_then_succeeds(monkeypatch):
    # A dead/rotated proxy makes page.goto raise net::ERR_PROXY_CONNECTION_FAILED
    # instead of returning a status. That must be retried like a transient
    # block, not crash the whole refresh with a raw Playwright error.
    err = RuntimeError("Page.goto: net::ERR_PROXY_CONNECTION_FAILED")
    fb = _install_fake_browser(monkeypatch, [err, 200])
    assert scraper.default_get("https://letterboxd.com/alice/films/") == "<html>ok</html>"
    assert fb.contexts_opened == 2
    assert fb.contexts_closed == 2

def test_default_get_raises_friendly_error_when_goto_always_raises(monkeypatch):
    err = RuntimeError("Page.goto: net::ERR_PROXY_CONNECTION_FAILED")
    fb = _install_fake_browser(monkeypatch, [err, err, err, err])
    with pytest.raises(RuntimeError, match="try again in a minute"):
        scraper.default_get("https://letterboxd.com/alice/films/")
    assert fb.contexts_closed == 4  # no context leaked on the exception path

def test_default_get_closes_context_if_new_page_raises(monkeypatch):
    # page creation can fail (browser process disconnected, etc.) — the
    # context must still be closed, not leaked.
    class _ExplodingContext:
        def __init__(self, browser):
            self._browser = browser
        def new_page(self):
            raise RuntimeError("page creation failed")
        def close(self):
            self._browser.contexts_closed += 1

    fb = _FakeBrowser([200])
    def new_context(**kwargs):
        fb.context_kwargs.append(kwargs)
        return _ExplodingContext(fb)
    monkeypatch.setattr(fb, "new_context", new_context)
    monkeypatch.setattr(scraper, "_get_browser", lambda: fb)
    monkeypatch.setattr(scraper.time, "sleep", lambda s: None)

    with pytest.raises(RuntimeError, match="page creation failed"):
        scraper.default_get("https://letterboxd.com/alice/films/")
    assert fb.contexts_closed == 1

from app.scraper import parse_declared_film_count

def test_parse_declared_film_count_strips_thousands_comma():
    html = (FIX / "profile_stats.html").read_text()
    assert parse_declared_film_count(html) == 1234

def test_parse_declared_film_count_missing_returns_none():
    assert parse_declared_film_count("<html><body>no stats</body></html>") is None

from app.errors import Cancelled

def test_scrape_profile_raises_cancelled_before_films_page_fetch():
    def fake_get(url):
        raise AssertionError("get_html should not be called once cancelled")
    with pytest.raises(Cancelled):
        scrape_profile("alice", fake_get, delay=0, should_cancel=lambda: True)

def test_scrape_profile_raises_cancelled_mid_film_detail_loop():
    page1 = (FIX / "films_page.html").read_text()  # 3 films
    detail = (FIX / "film_detail.html").read_text()
    calls = {"n": 0}
    def fake_get(url):
        if url.endswith("/films/"):
            return page1
        calls["n"] += 1
        return detail
    def should_cancel():
        return calls["n"] >= 1  # cancel after the first film-detail fetch
    with pytest.raises(Cancelled):
        scrape_profile("alice", fake_get, delay=0, should_cancel=should_cancel)

def test_scrape_profile_closes_browser_on_cancel():
    closed = {"browser": False, "pw": False}
    class _FakeBrowser:
        def close(self):
            closed["browser"] = True
    class _FakePw:
        def stop(self):
            closed["pw"] = True
    # Set directly (not via monkeypatch): _close_browser deletes these attrs as
    # part of normal teardown, which would conflict with monkeypatch's own
    # delattr-on-undo when it recorded no prior value.
    scraper._thread_local.browser = _FakeBrowser()
    scraper._thread_local.pw = _FakePw()

    def fake_get(url):
        raise AssertionError("unreachable")
    with pytest.raises(Cancelled):
        scrape_profile("alice", fake_get, delay=0, should_cancel=lambda: True)
    assert closed == {"browser": True, "pw": True}

def test_scrape_profile_raises_cancelled_even_if_browser_close_fails():
    class _FakeBrowser:
        def close(self):
            raise RuntimeError("browser already dead")
    class _FakePw:
        def stop(self):
            raise RuntimeError("pw already stopped")
    scraper._thread_local.browser = _FakeBrowser()
    scraper._thread_local.pw = _FakePw()

    def fake_get(url):
        raise AssertionError("unreachable")
    with pytest.raises(Cancelled):
        scrape_profile("alice", fake_get, delay=0, should_cancel=lambda: True)
    assert not hasattr(scraper._thread_local, "browser")

def test_crawl_films_list_paginates_without_detail_pages():
    page1 = (FIX / "films_page.html").read_text()  # 3 films + next link
    page2 = '<html><body><ul class="poster-list"></ul></body></html>'
    urls = []
    def fake_get(url):
        urls.append(url)
        return page2 if "/page/2/" in url else page1
    entries = crawl_films_list("alice", fake_get, delay=0)
    assert len(entries) == 3
    assert entries[0]["year"] == 2019
    assert all("/film/" not in u for u in urls)  # list pages only

def test_scrape_profile_with_injected_resolver_never_touches_detail_pages():
    page1 = (FIX / "films_page.html").read_text()
    page2 = '<html><body><ul class="poster-list"></ul></body></html>'
    stats = '<html><body><h4 class="profile-statistic"><a href="/alice/films/"><span class="value">3</span></a></h4></body></html>'
    urls = []
    def fake_get(url):
        urls.append(url)
        if "/page/2/" in url:
            return page2
        if url.endswith("/alice/"):
            return stats
        return page1
    def resolve_ids(entries, on_progress=None, should_cancel=None):
        for e in entries:
            e["tmdb_id"] = 496243
    films = scrape_profile("alice", fake_get, delay=0, resolve_ids=resolve_ids)
    assert len(films) == 3
    assert all("/film/" not in u for u in urls)

def test_scrape_profile_drops_films_the_resolver_could_not_resolve():
    page1 = (FIX / "films_page.html").read_text()
    stats = '<html><body><h4 class="profile-statistic"><a href="/alice/films/"><span class="value">3</span></a></h4></body></html>'
    def fake_get(url):
        return stats if url.endswith("/alice/") else page1.replace(
            '<a class="next" href="/alice/films/page/2/">Older</a>', "")
    def resolve_ids(entries, on_progress=None, should_cancel=None):
        for e in entries:
            e["tmdb_id"] = 496243 if e["slug"] == "parasite" else None
    films = scrape_profile("alice", fake_get, delay=0, resolve_ids=resolve_ids)
    assert [f["slug"] for f in films] == ["parasite"]

def test_incomplete_scrape_error_suggests_retrying():
    page1 = (FIX / "films_page.html").read_text()
    page2 = '<html><body></body></html>'
    stats = '<html><body><h4 class="profile-statistic"><a href="/alice/films/"><span class="value">87</span></a></h4></body></html>'
    def fake_get(url):
        if "/page/2/" in url:
            return page2
        if url.endswith("/alice/"):
            return stats
        return page1
    def resolve_ids(entries, on_progress=None, should_cancel=None):
        for e in entries:
            e["tmdb_id"] = 1
    with pytest.raises(RuntimeError, match="try refreshing again"):
        scrape_profile("alice", fake_get, delay=0, resolve_ids=resolve_ids)
