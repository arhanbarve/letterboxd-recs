import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Config:
    username: str
    tmdb_api_key: str
    db_path: str

def load_config() -> Config:
    return Config(
        username=os.environ["LETTERBOXD_USERNAME"],
        tmdb_api_key=os.environ["TMDB_API_KEY"],
        db_path=os.environ.get("DB_PATH", "letterboxd.db"),
    )
