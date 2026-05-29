import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


def _bootstrap_env():
    """Load .env into os.environ before pydantic-settings reads them."""
    # Search for .env from this file upward
    here = os.path.abspath(__file__)
    for _ in range(6):
        here = os.path.dirname(here)
        candidate = os.path.join(here, ".env")
        if os.path.exists(candidate):
            with open(candidate) as f:
                for raw in f:
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, _, val = line.partition("=")
                    key, val = key.strip(), val.strip()
                    # Override if not set OR set to empty string
                    if key and not os.environ.get(key):
                        os.environ[key] = val
            return


_bootstrap_env()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    anthropic_api_key: str = ""
    lightrag_data_dir: str = "./lightrag_data"

    model_orchestration: str = "claude-haiku-4-5-20251001"
    model_agents: str = "claude-haiku-4-5-20251001"
    model_fast: str = "claude-haiku-4-5-20251001"


@lru_cache
def get_settings() -> Settings:
    return Settings()
