import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Config:
    username: str
    tmdb_api_key: str
    db_path: str
    omdb_api_key: str = ""
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:5173"])
    # Preview deployments get a fresh hostname every push, so an exact-origin
    # list can never cover them — a pattern can (e.g. https://.*\.vercel\.app).
    cors_origin_regex: str | None = None

def load_config() -> Config:
    origins = os.environ.get("CORS_ORIGINS", "http://localhost:5173")
    return Config(
        username=os.environ.get("LETTERBOXD_USERNAME", ""),
        tmdb_api_key=os.environ["TMDB_API_KEY"],
        db_path=os.environ.get("DB_PATH", "letterboxd.db"),
        omdb_api_key=os.environ.get("OMDB_API_KEY", ""),
        cors_origins=[o.strip() for o in origins.split(",")],
        cors_origin_regex=os.environ.get("CORS_ORIGIN_REGEX") or None,
    )
