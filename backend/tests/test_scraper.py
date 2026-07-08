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
    def __init__(self, statuses, content="<html>ok</html>"):
        self._statuses = list(statuses)
        self._content = content
    def goto(self, url, wait_until=None, timeout=None):
        return _FakeResp(self._statuses.pop(0))
    def wait_for_timeout(self, ms):
        pass
    def content(self):
        return self._content

def test_default_get_returns_content_on_first_success(monkeypatch):
    monkeypatch.setattr(scraper, "_get_page", lambda: _FakePage([200]))
    monkeypatch.setattr(scraper.time, "sleep", lambda s: None)
    assert scraper.default_get("https://letterboxd.com/alice/films/") == "<html>ok</html>"

def test_default_get_raises_after_exhausting_retries_on_403(monkeypatch):
    monkeypatch.setattr(scraper, "_get_page", lambda: _FakePage([403, 403, 403, 403], content="<html>challenge</html>"))
    monkeypatch.setattr(scraper.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError, match="Blocked"):
        scraper.default_get("https://letterboxd.com/alice/films/")

def test_default_get_recovers_after_one_retry(monkeypatch):
    monkeypatch.setattr(scraper, "_get_page", lambda: _FakePage([429, 200]))
    monkeypatch.setattr(scraper.time, "sleep", lambda s: None)
    assert scraper.default_get("https://letterboxd.com/alice/films/") == "<html>ok</html>"

def test_default_get_reports_each_attempt_via_on_request(monkeypatch):
    monkeypatch.setattr(scraper, "_get_page", lambda: _FakePage([429, 200]))
    monkeypatch.setattr(scraper.time, "sleep", lambda s: None)
    events = []
    scraper.default_get("https://letterboxd.com/alice/films/", on_request=events.append)
    assert [e["status"] for e in events] == [429, 200]
    assert [e["attempt"] for e in events] == [0, 1]
    assert all(e["challenged"] is False for e in events)

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
    # Set directly (not via monkeypatch): _close_page deletes these attrs as
    # part of normal teardown, which would conflict with monkeypatch's own
    # delattr-on-undo when it recorded no prior value.
    scraper._thread_local.page = object()
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
    scraper._thread_local.page = object()
    scraper._thread_local.browser = _FakeBrowser()
    scraper._thread_local.pw = _FakePw()

    def fake_get(url):
        raise AssertionError("unreachable")
    with pytest.raises(Cancelled):
        scrape_profile("alice", fake_get, delay=0, should_cancel=lambda: True)
    assert not hasattr(scraper._thread_local, "browser")
