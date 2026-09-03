"""A small in-process rate limiter.

The expensive endpoints here fan out to TMDB and OMDB on someone else's API
quota, and the import endpoint accepts file uploads, so both need a ceiling that
does not depend on the caller being friendly. This deliberately keeps state in
memory: the deployment is a single instance, and a Redis dependency would cost
more than it buys at this scale. A restart forgives everyone, which is fine —
this is an abuse ceiling, not a billing meter.
"""
import threading
import time
from collections import defaultdict, deque

class RateLimiter:
    """Sliding-window counter, keyed by whatever the caller considers an identity
    (here: client IP + route bucket)."""

    def __init__(self, clock=time.monotonic):
        self._hits = defaultdict(deque)
        self._lock = threading.Lock()
        self._clock = clock

    def check(self, key: str, limit: int, window_seconds: float) -> bool:
        """True if this hit is allowed, False if the caller is over the limit."""
        now = self._clock()
        cutoff = now - window_seconds
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= limit:
                return False
            hits.append(now)
            return True

    def prune(self, max_age_seconds: float = 3600.0) -> None:
        """Drops keys nothing has touched recently, so a long-lived process does
        not accumulate an entry per IP forever."""
        cutoff = self._clock() - max_age_seconds
        with self._lock:
            for key in [k for k, hits in self._hits.items()
                        if not hits or hits[-1] <= cutoff]:
                del self._hits[key]
