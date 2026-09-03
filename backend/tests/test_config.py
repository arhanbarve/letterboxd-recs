from app.config import load_config

def test_load_config_reads_env(monkeypatch):
    monkeypatch.setenv("LETTERBOXD_USERNAME", "alice")
    monkeypatch.setenv("TMDB_API_KEY", "key123")
    monkeypatch.setenv("DB_PATH", "test.db")
    cfg = load_config()
    assert cfg.username == "alice"
    assert cfg.tmdb_api_key == "key123"
    assert cfg.db_path == "test.db"

def test_load_config_username_optional(monkeypatch):
    monkeypatch.delenv("LETTERBOXD_USERNAME", raising=False)
    monkeypatch.setenv("TMDB_API_KEY", "key123")
    cfg = load_config()
    assert cfg.username == ""

def test_load_config_reads_cors_origins(monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "key123")
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example.com,https://b.example.com")
    cfg = load_config()
    assert cfg.cors_origins == ["https://a.example.com", "https://b.example.com"]

def test_load_config_cors_origins_default(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    monkeypatch.setenv("TMDB_API_KEY", "key123")
    cfg = load_config()
    assert cfg.cors_origins == ["http://localhost:5173"]

def test_load_config_reads_omdb_key(monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "tmdb")
    monkeypatch.setenv("OMDB_API_KEY", "omdb")
    from app.config import load_config
    cfg = load_config()
    assert cfg.omdb_api_key == "omdb"

def test_load_config_omdb_key_optional(monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "tmdb")
    monkeypatch.delenv("OMDB_API_KEY", raising=False)
    from app.config import load_config
    assert load_config().omdb_api_key == ""

def test_load_config_reads_cors_origin_regex(monkeypatch):
    monkeypatch.setenv("TMDB_API_KEY", "key123")
    monkeypatch.setenv("CORS_ORIGIN_REGEX", r"https://.*\.vercel\.app")
    cfg = load_config()
    assert cfg.cors_origin_regex == r"https://.*\.vercel\.app"

def test_load_config_cors_origin_regex_defaults_to_none(monkeypatch):
    monkeypatch.delenv("CORS_ORIGIN_REGEX", raising=False)
    monkeypatch.setenv("TMDB_API_KEY", "key123")
    assert load_config().cors_origin_regex is None

def test_safe_message_redacts_api_keys_from_upstream_urls():
    from app.errors import safe_message
    msg = ("401 Client Error for url: "
           "https://api.themoviedb.org/3/movie/550?api_key=SECRET123&append=credits")
    out = safe_message(msg)
    assert "SECRET123" not in out
    assert "api_key=[redacted]" in out

def test_safe_message_redacts_omdb_style_keys_and_caps_length():
    from app.errors import MAX_MESSAGE_CHARS, safe_message
    assert "SECRET123" not in safe_message("https://www.omdbapi.com/?apikey=SECRET123&i=tt1")
    assert len(safe_message("x" * 10_000)) <= MAX_MESSAGE_CHARS + 1

def test_rate_limits_are_tunable_from_the_environment(monkeypatch):
    from app.config import load_config
    monkeypatch.setenv("TMDB_API_KEY", "k")
    monkeypatch.setenv("RATE_LIMIT_IMPORTS_PER_HOUR", "500")
    monkeypatch.setenv("RATE_LIMIT_REFRESHES_PER_HOUR", "7")
    cfg = load_config()
    assert cfg.imports_per_hour == 500
    assert cfg.refreshes_per_hour == 7

def test_rate_limits_default_to_safe_ceilings(monkeypatch):
    from app.config import load_config
    monkeypatch.setenv("TMDB_API_KEY", "k")
    monkeypatch.delenv("RATE_LIMIT_IMPORTS_PER_HOUR", raising=False)
    monkeypatch.delenv("RATE_LIMIT_REFRESHES_PER_HOUR", raising=False)
    cfg = load_config()
    assert cfg.imports_per_hour == 20
    assert cfg.refreshes_per_hour == 10
