"""Layered TMDB-id resolution for a user's Letterboxd films.

Order, first hit wins:  cache -> rss -> tmdb search -> letterboxd detail page.
Every layer is optional. The import path (see app.importer) supplies only the
cache and search layers, so resolution never touches Letterboxd at all; the rss
and detail layers remain for any caller that has a film slug to work with.
"""
from dataclasses import dataclass

from app.errors import Cancelled

MAX_DETAIL_FALLBACKS = 40

@dataclass
class ResolverStats:
    cache: int = 0
    rss: int = 0
    search: int = 0
    detail: int = 0
    unresolved: int = 0

def make_resolver(cache_get=None, cache_put=None, rss_map=None, search_fn=None,
                  detail_fn=None, max_detail=MAX_DETAIL_FALLBACKS):
    """Returns resolve_all(entries, on_progress=None, should_cancel=None) -> ResolverStats.
    Mutates each entry's "tmdb_id" in place. Every layer is optional; layer
    exceptions fall through to the next layer. Negative results are cached only
    when the detail page authoritatively confirmed there is no TMDB link."""
    rss_map = rss_map or {}

    def resolve_all(entries, on_progress=None, should_cancel=None) -> ResolverStats:
        stats = ResolverStats()
        detail_used = 0
        resolved = 0
        for entry in entries:
            if should_cancel and should_cancel():
                raise Cancelled()
            entry.setdefault("tmdb_id", None)
            slug = entry.get("slug")
            via = None

            if slug and cache_get:
                try:
                    hit = cache_get(slug)
                except Exception:
                    hit = None
                if hit is not None:
                    entry["tmdb_id"] = hit[0]
                    stats.cache += 1
                    via = "cache"

            if via is None and slug and slug in rss_map:
                entry["tmdb_id"] = rss_map[slug]
                stats.rss += 1
                via = "rss"

            if via is None and search_fn and entry.get("title"):
                try:
                    tid = search_fn(entry["title"], entry.get("year"))
                except Exception:
                    tid = None
                if tid is not None:
                    entry["tmdb_id"] = tid
                    stats.search += 1
                    via = "search"

            if via is None and detail_fn and slug and detail_used < max_detail:
                detail_used += 1
                try:
                    tid = detail_fn(slug)
                except Exception:
                    pass  # not authoritative — leave uncached, retry next run
                else:
                    entry["tmdb_id"] = tid
                    stats.detail += 1
                    via = "detail" if tid is not None else "none"

            if via is None:
                stats.unresolved += 1
            elif via != "cache" and slug and cache_put:
                cache_put(slug, entry["tmdb_id"], via)

            if entry["tmdb_id"] is not None:
                resolved += 1
            if on_progress:
                on_progress(resolved)
        return stats

    return resolve_all
