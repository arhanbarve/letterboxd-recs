from pathlib import Path

import responses

from app.rss import RSS_URL_TEMPLATE, fetch_rss, parse_rss_tmdb_map

FIX = Path(__file__).parent / "fixtures"

def test_parse_rss_maps_slug_to_tmdb_id():
    xml = (FIX / "rss_feed.xml").read_text()
    assert parse_rss_tmdb_map(xml) == {"parasite": 496243, "cats": 440249}

def test_parse_rss_garbage_returns_empty():
    assert parse_rss_tmdb_map("<not>even</rss>") == {}
    assert parse_rss_tmdb_map("") == {}

@responses.activate
def test_fetch_rss_uses_plain_requests_first():
    responses.add(responses.GET, RSS_URL_TEMPLATE.format(username="alice"),
                  body="<rss>feed</rss>", status=200)
    def get_html(url):
        raise AssertionError("Playwright fallback should not be used on 200")
    assert fetch_rss("alice", get_html=get_html) == "<rss>feed</rss>"

@responses.activate
def test_fetch_rss_falls_back_to_get_html_on_403():
    responses.add(responses.GET, RSS_URL_TEMPLATE.format(username="alice"), status=403)
    assert fetch_rss("alice", get_html=lambda url: "<rss>via-playwright</rss>") == "<rss>via-playwright</rss>"

@responses.activate
def test_fetch_rss_returns_none_when_everything_fails():
    responses.add(responses.GET, RSS_URL_TEMPLATE.format(username="alice"), status=403)
    def get_html(url):
        raise RuntimeError("blocked")
    assert fetch_rss("alice", get_html=get_html) is None
    assert fetch_rss("alice", get_html=None) is None
