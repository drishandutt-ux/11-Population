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

    # ── Fast tier (default) — Haiku everywhere ──────────────────────────────
    model_orchestration: str = "claude-haiku-4-5-20251001"
    model_agents: str = "claude-haiku-4-5-20251001"
    model_fast: str = "claude-haiku-4-5-20251001"

    # ── Pro tier — Sonnet for deeper persona curation + smarter posts ───────
    model_pro_orchestration: str = "claude-sonnet-4-6"
    model_pro_agents: str = "claude-sonnet-4-6"

    # ── Concurrency (sized so 1000 agents stay fast without rate-limiting) ──
    spawn_concurrency: int = 8        # parallel persona-generation batches (Pro spawn)
    sim_concurrency_fast: int = 48    # parallel Haiku posts per phase
    sim_concurrency_pro: int = 12     # parallel Sonnet posts per phase (slower/pricier)
    kg_sim_concurrency: int = 6       # parallel KG-from-post enrichments during a run
    kg_sim_sample: float = 0.15       # fraction of posts that enrich the KG mid-run

    def agent_model(self, mode: str) -> str:
        return self.model_pro_agents if mode == "pro" else self.model_agents

    def orchestration_model(self, mode: str) -> str:
        return self.model_pro_orchestration if mode == "pro" else self.model_orchestration

    def sim_concurrency(self, mode: str) -> int:
        return self.sim_concurrency_pro if mode == "pro" else self.sim_concurrency_fast


@lru_cache
def get_settings() -> Settings:
    return Settings()
