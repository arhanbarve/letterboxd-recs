"""One-off live reproduction of the 403 on films-page pagination.
Run manually: `cd backend && .venv/bin/python scripts/probe_403.py moviefan`
Not part of the test suite — hits real Letterboxd/Cloudflare.
"""
import functools
import sys

from app.scraper import default_get, scrape_profile

def log(event):
    print(f"[{event['attempt']}] {event['status']} challenged={event['challenged']} "
          f"{event['elapsed_s']}s {event['url']}")

def main(username):
    get_html = functools.partial(default_get, on_request=log)
    try:
        films = scrape_profile(username, get_html=get_html, delay=1.0)
        print(f"OK: scraped {len(films)} films")
    except RuntimeError as e:
        print(f"FAILED: {e}")

if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "moviefan")
