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
    page1 = (FIX / "films_page.html").read_text()
    # page 2 has no films and no next link -> terminates
    page2 = '<html><body><ul class="poster-list"></ul></body></html>'
    detail = (FIX / "film_detail.html").read_text()

    def fake_get(url):
        if url.endswith("/films/") or url.endswith("/films/page/1/"):
            return page1
        if url.endswith("/films/page/2/"):
            return page2
        return detail  # any film page

    films = scrape_profile("alice", fake_get, delay=0)
    rated = {f["slug"]: f for f in films}
    assert rated["parasite"]["tmdb_id"] == 496243
    assert rated["parasite"]["rating"] == 5.0
    # every returned film has a tmdb_id resolved
    assert all(f["tmdb_id"] == 496243 for f in films)
