import os

# app.api builds its Config at import time, so on a fresh clone with no .env
# pytest cannot even *collect* the suite — it dies with a bare KeyError before
# running a line. Every test stubs the network layers, so a placeholder is the
# correct value here, and it keeps a real key out of the test environment.
os.environ.setdefault("TMDB_API_KEY", "test-key-never-sent-anywhere")
