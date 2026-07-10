from app.omdb import fetch_ratings

class _Resp:
    def __init__(self, payload): self._p = payload
    def raise_for_status(self): pass
    def json(self): return self._p

class _Session:
    def __init__(self, payload): self._p = payload
    def get(self, url, params=None, timeout=None): return _Resp(self._p)

def test_fetch_ratings_parses_imdb_and_rt():
    payload = {"Response": "True", "imdbRating": "8.1",
               "Ratings": [{"Source": "Rotten Tomatoes", "Value": "94%"}]}
    out = fetch_ratings("tt1", "key", session=_Session(payload))
    assert out == {"imdb_rating": 8.1, "rt_score": 94}

def test_fetch_ratings_handles_missing_fields():
    payload = {"Response": "True", "imdbRating": "N/A", "Ratings": []}
    assert fetch_ratings("tt1", "key", session=_Session(payload)) == {"imdb_rating": None, "rt_score": None}

def test_fetch_ratings_response_false():
    assert fetch_ratings("tt1", "key", session=_Session({"Response": "False"})) == {"imdb_rating": None, "rt_score": None}

def test_fetch_ratings_no_key_or_id_short_circuits():
    assert fetch_ratings("", "key") == {"imdb_rating": None, "rt_score": None}
    assert fetch_ratings("tt1", "") == {"imdb_rating": None, "rt_score": None}
