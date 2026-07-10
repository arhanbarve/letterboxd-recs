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
