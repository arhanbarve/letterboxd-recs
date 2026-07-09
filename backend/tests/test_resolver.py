import pytest

from app.errors import Cancelled
from app.resolver import make_resolver

def entry(slug="parasite", title="Parasite", year=2019):
    return {"slug": slug, "title": title, "year": year, "rating": 5.0}

def test_cache_hit_wins_and_skips_all_other_layers():
    def boom(*a, **k):
        raise AssertionError("layer should not be called on cache hit")
    resolve = make_resolver(
        cache_get=lambda slug: (496243,),
        cache_put=boom, search_fn=boom, detail_fn=boom, rss_map={"parasite": 1})
    e = entry()
    resolve([e])
    assert e["tmdb_id"] == 496243

def test_cached_negative_result_skips_refetch():
    def boom(*a, **k):
        raise AssertionError("no layer should run for a cached negative")
    resolve = make_resolver(cache_get=lambda slug: (None,), search_fn=boom, detail_fn=boom)
    e = entry()
    resolve([e])
    assert e["tmdb_id"] is None

def test_rss_beats_search():
    resolve = make_resolver(
        rss_map={"parasite": 496243},
        search_fn=lambda t, y: 999)
    e = entry()
    resolve([e])
    assert e["tmdb_id"] == 496243

def test_search_used_when_rss_misses_and_result_is_cached():
    stored = []
    resolve = make_resolver(
        cache_get=lambda slug: None,
        cache_put=lambda slug, tid, via: stored.append((slug, tid, via)),
        rss_map={}, search_fn=lambda t, y: 496243)
    e = entry()
    resolve([e])
    assert e["tmdb_id"] == 496243
    assert stored == [("parasite", 496243, "search")]

def test_search_miss_falls_to_detail_and_caches_via_detail():
    stored = []
    resolve = make_resolver(
        cache_put=lambda slug, tid, via: stored.append((slug, tid, via)),
        search_fn=lambda t, y: None,
        detail_fn=lambda slug: 496243)
    e = entry()
    resolve([e])
    assert e["tmdb_id"] == 496243
    assert stored == [("parasite", 496243, "detail")]

def test_detail_none_is_cached_as_authoritative_negative():
    stored = []
    resolve = make_resolver(
        cache_put=lambda slug, tid, via: stored.append((slug, tid, via)),
        detail_fn=lambda slug: None)
    e = entry()
    resolve([e])
    assert e["tmdb_id"] is None
    assert stored == [("parasite", None, "none")]

def test_detail_cap_limits_letterboxd_hits_and_leaves_rest_uncached():
    stored, detail_calls = [], []
    def detail_fn(slug):
        detail_calls.append(slug)
        return None
    resolve = make_resolver(
        cache_put=lambda slug, tid, via: stored.append(slug),
        detail_fn=detail_fn, max_detail=1)
    entries = [entry(slug=f"film-{i}", title=f"Film {i}") for i in range(3)]
    stats = resolve(entries)
    assert len(detail_calls) == 1
    assert stored == ["film-0"]          # only the attempted one is cached
    assert stats.unresolved == 2          # the capped-out ones retry next run

def test_search_exception_falls_through_to_detail():
    def search_fn(t, y):
        raise RuntimeError("tmdb down")
    resolve = make_resolver(search_fn=search_fn, detail_fn=lambda slug: 496243)
    e = entry()
    resolve([e])
    assert e["tmdb_id"] == 496243

def test_detail_exception_leaves_film_unresolved_and_uncached():
    stored = []
    def detail_fn(slug):
        raise RuntimeError("403")
    resolve = make_resolver(
        cache_put=lambda slug, tid, via: stored.append(slug), detail_fn=detail_fn)
    e = entry()
    stats = resolve([e])
    assert e["tmdb_id"] is None
    assert stored == []
    assert stats.unresolved == 1

def test_resolver_raises_cancelled():
    resolve = make_resolver(rss_map={"parasite": 1})
    with pytest.raises(Cancelled):
        resolve([entry()], should_cancel=lambda: True)

def test_on_progress_reports_running_resolved_count():
    counts = []
    resolve = make_resolver(rss_map={"a": 1, "c": 3})
    resolve([entry(slug="a"), entry(slug="b"), entry(slug="c")],
            on_progress=counts.append)
    assert counts == [1, 1, 2]  # b unresolved, count doesn't advance
