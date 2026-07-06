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
