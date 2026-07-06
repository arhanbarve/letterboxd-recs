from app.config import load_config

def test_load_config_reads_env(monkeypatch):
    monkeypatch.setenv("LETTERBOXD_USERNAME", "alice")
    monkeypatch.setenv("TMDB_API_KEY", "key123")
    monkeypatch.setenv("DB_PATH", "test.db")
    cfg = load_config()
    assert cfg.username == "alice"
    assert cfg.tmdb_api_key == "key123"
    assert cfg.db_path == "test.db"
