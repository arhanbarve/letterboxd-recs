"""Live acceptance gate for the layered scraper.
Run manually: `cd backend && .venv/bin/python scripts/live_acceptance.py moviefan`
Hits real Letterboxd + TMDB. Requires TMDB_API_KEY in .env.
Not part of the test suite."""
import functools
import os
import sys
import tempfile

from dotenv import load_dotenv
load_dotenv()

from app.db import connect, init_schema, lookup_slug_tmdb, store_slug_tmdb
from app.resolver import make_resolver
from app.rss import fetch_rss, parse_rss_tmdb_map
from app.scraper import BASE, default_get, parse_tmdb_id, scrape_profile
from app.tmdb import search_movie

def main(username):
    api_key = os.environ["TMDB_API_KEY"]
    lb_events = []
    def log(event):
        lb_events.append(event)
        print(f"LB[{len(lb_events)}] {event['status']} {event['url']}")
    get_html = functools.partial(default_get, on_request=log)

    conn = connect(os.path.join(tempfile.mkdtemp(), "acceptance.db"))
    init_schema(conn)

    rss_xml = fetch_rss(username, get_html=get_html)
    rss_map = parse_rss_tmdb_map(rss_xml) if rss_xml else {}
    print(f"RSS: {len(rss_map)} exact ids")

    resolve_ids = make_resolver(
        cache_get=lambda slug: lookup_slug_tmdb(conn, slug),
        cache_put=lambda slug, tid, via: store_slug_tmdb(conn, slug, tid, via),
        rss_map=rss_map,
        search_fn=lambda title, year: search_movie(title, year, api_key),
        detail_fn=lambda slug: parse_tmdb_id(get_html(f"{BASE}/film/{slug}/")),
    )

    box = {}
    def resolve_and_capture(entries, **kw):
        box["total"] = len(entries)
        box["stats"] = resolve_ids(entries, **kw)

    films = scrape_profile(username, get_html=get_html, delay=1.0,
                           resolve_ids=resolve_and_capture)

    total, stats = box["total"], box["stats"]
    rate = len(films) / total if total else 0
    print("\n=== ACCEPTANCE ===")
    print(f"films on profile grid : {total}")
    print(f"tmdb ids resolved     : {len(films)} ({rate:.0%})")
    print(f"via                   : {stats}")
    print(f"letterboxd requests   : {len(lb_events)}")
    ok = len(lb_events) < 15 and rate >= 0.95
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1

if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "moviefan"))
