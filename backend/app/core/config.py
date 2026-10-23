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
    lightrag_data_dir: str = "./lightrag_data"   # legacy: KG JSON files are read from here once and imported into the DB

    # ── App Supabase project ("11 Minds Population") — user auth + Postgres ────
    # Setting APP_SUPABASE_URL turns authentication ON: every API call must carry a Supabase
    # user access token. Leave unset for local dev (all requests run as a fixed dev user).
    app_supabase_url: str = ""            # https://<ref>.supabase.co
    app_supabase_anon_key: str = ""       # publishable/anon key (used only for the HS256 fallback)

    # ── Fast tier (default) — Haiku everywhere ──────────────────────────────
    model_orchestration: str = "claude-haiku-4-5-20251001"
    model_agents: str = "claude-haiku-4-5-20251001"
    model_fast: str = "claude-haiku-4-5-20251001"

    # ── Pro tier — Sonnet for deeper persona curation + smarter posts ───────
    model_pro_orchestration: str = "claude-sonnet-4-6"
    model_pro_agents: str = "claude-sonnet-4-6"

    # ── AI Agent Pulse monitoring — direct-to-Supabase usage logging (no n8n) ──
    # All three must be set to enable logging; otherwise it's a silent no-op.
    supabase_url: str = ""            # Monitoring Supabase project URL
    supabase_service_key: str = ""    # service-role key (bypasses RLS for server-side inserts)
    pulse_project_id: str = ""        # project_registry UUID for this project

    # ── Concurrency (sized so 1000 agents stay fast without rate-limiting) ──
    spawn_concurrency: int = 8        # parallel persona-generation batches (Pro spawn)
    sim_concurrency_fast: int = 48    # parallel Haiku posts per phase
    sim_concurrency_pro: int = 12     # parallel Sonnet posts per phase (slower/pricier)
    kg_sim_concurrency: int = 6       # parallel KG-from-post enrichments during a run
    kg_sim_max_updates: int = 120     # target KG-enriching posts per phase; runs <= this capture EVERY post, only larger runs throttle
    #: Share of twins who never read the thread (brief L3-06). They post from their own head every
    #: phase, so the room always contains voices that cannot have drifted toward the majority.
    independent_voice_share: float = 0.3
    #: Run the scope check on every debate post (2026-10-20): one fast structured call per post that
    #: flags where the author stepped outside its standing. Off → posts carry a footprint, no flags.
    scope_check_posts: bool = True
    #: Write the lay layer when tagging (2026-10-20): street-level versions of the professional and
    #: technical units, so a lay twin's scope is never empty. Off → tagging stores the chunks only.
    lay_layer: bool = True
    #: Sign-in is limited to these email domains when set (comma-separated, e.g. "11-london.com";
    #: 2026-10-20). Empty = any account Supabase lets in. Peers and sharing are always within a domain.
    allowed_email_domains: str = ""

    # Both follow the tier models in app/core/model_policy.py (2026-10-23), not the MODEL_* env vars:
    # an env override is how Opus reached production. The session's tier still has the last word
    # on every call (tracked_messages_create).
    def agent_model(self, mode: str) -> str:
        from app.core.model_policy import TIER_MODEL
        return TIER_MODEL["pro" if mode == "pro" else "fast"]

    def orchestration_model(self, mode: str) -> str:
        return self.agent_model(mode)

    def sim_concurrency(self, mode: str) -> int:
        return self.sim_concurrency_pro if mode == "pro" else self.sim_concurrency_fast


@lru_cache
def get_settings() -> Settings:
    return Settings()
