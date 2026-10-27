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
    #: The Visual Lab's image provider (2026-10-26): "openai" (gpt-image-1), "google" (Imagen) or
    #: "none" (a placeholder hero drawn in code, the text layer still composited); "auto" picks the
    #: first with a key. The words on an image are never drawn by the provider — see visual_gen.
    image_provider: str = "auto"
    openai_api_key: str = ""
    google_api_key: str = ""
    #: 2026-10-26: Drishan's key lists gpt-image-1 … gpt-image-2.5 under /v1/models, yet the image
    #: endpoints answered "The model 'gpt-image-1' does not exist" — the old name is no longer
    #: served there. gpt-image-2 first, then the rest in order of preference; the chain also steps
    #: past a model that rejects a parameter. DALL·E 3 is the last resort: a generation only (no
    #: edit from the reference), 1024x1792, hd.
    image_model_openai: str = "gpt-image-2"
    image_model_openai_fallbacks: str = "gpt-image-2.5-sunburst,gpt-image-2.5-flare,gpt-image-1.5,gpt-image-1,gpt-image-1-mini,dall-e-3"
    image_model_google: str = "imagen-4.0-generate-001"
    #: How a generated or remade image is drawn (2026-10-26, after the first prod remake came back
    #: as a typed infographic): "full" — the provider draws the whole poster, photograph and words
    #: together, from the authored layout, with the parent image as the reference on a remake and
    #: one retry when the vision check finds an exact-text line wrong; "layered" — a hero picture
    #: with the words set in type by the system (the only mode with no provider key). "auto" = full
    #: with OpenAI, layered otherwise (Imagen's lettering is not reliable enough).
    #: After a remake is ready, re-show it to the same twins who judged its parent and count the
    #: paired shift (2026-10-27). Off = remakes end with a picture; the Re-test button still works.
    visual_auto_retest: bool = True
    image_render: str = "auto"
    #: gpt-image-1 quality for a full poster; text legibility needs "high".
    image_quality_openai: str = "high"
    #: List price per generated image, for the cost ledger (USD): a medium hero / a high full poster.
    image_cost_openai_usd: float = 0.07
    image_cost_openai_full_usd: float = 0.25
    image_cost_google_usd: float = 0.04

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
