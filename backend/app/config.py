import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Config:
    username: str
    tmdb_api_key: str
    database_url: str
    omdb_api_key: str = ""
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:5173"])
    # Preview deployments get a fresh hostname every push, so an exact-origin
    # list can never cover them — a pattern can (e.g. https://.*\.vercel\.app).
    cors_origin_regex: str | None = None
    # Per client IP, per hour. Households and campuses share one address, so the
    # ceiling has to sit above plausible honest use — and a repeated E2E run is
    # the case that trips it first, which is why it is tunable at all.
    imports_per_hour: int = 20
    refreshes_per_hour: int = 10

class MissingConfig(RuntimeError):
    """Startup failed for a reason the operator can fix. The message is written
    to be read in a deploy log with no other context."""

def load_config() -> Config:
    origins = os.environ.get("CORS_ORIGINS", "http://localhost:5173")
    if not os.environ.get("DATABASE_URL"):
        raise MissingConfig(
            "DATABASE_URL is not set. Locally: start Postgres and use e.g. "
            "postgresql://localhost/letterboxd. On a host: paste the connection "
            "string your Postgres provider gives you (Neon's pooled one).")
    if not os.environ.get("TMDB_API_KEY"):
        raise MissingConfig(
            "TMDB_API_KEY is not set. Locally: copy backend/.env.example to "
            "backend/.env and fill it in. On a host: set it as an environment "
            "variable. A free v3 key comes from "
            "https://www.themoviedb.org/settings/api")
    return Config(
        imports_per_hour=int(os.environ.get("RATE_LIMIT_IMPORTS_PER_HOUR", "20")),
        refreshes_per_hour=int(os.environ.get("RATE_LIMIT_REFRESHES_PER_HOUR", "10")),
        username=os.environ.get("LETTERBOXD_USERNAME", ""),
        tmdb_api_key=os.environ["TMDB_API_KEY"],
        database_url=os.environ["DATABASE_URL"],
        omdb_api_key=os.environ.get("OMDB_API_KEY", ""),
        cors_origins=[o.strip() for o in origins.split(",")],
        cors_origin_regex=os.environ.get("CORS_ORIGIN_REGEX") or None,
    )
