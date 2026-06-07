# Project rules — 11 Minds Population

`PRODUCT_BLUEPRINT.md` (repo root) is the **canonical, complete description of this app**.
Treat it as a living document and the source of truth for what the product does.

## RULE 1 — Keep the blueprint in sync (REQUIRED)

Whenever you add or materially change anything a reader should know about — a feature,
capability, API endpoint, data-model field, agent behavior, ingestion source, config/env
var, or a notable limitation — you MUST, in the same piece of work:

1. **Update `PRODUCT_BLUEPRINT.md`** — edit the relevant section(s) so they describe the
   new/changed behavior accurately, and add a dated entry to the **Changelog** (last
   section). Bump the "as of" date at the end of the document.
2. **Commit the blueprint update together with the code** (same commit, or an immediate
   follow-up commit).

Skip the blueprint only for trivial changes with no behavioral/structural impact (typos,
formatting, pure refactors, comments). When in doubt, update it.

Today's date is available in context — use it for Changelog entries and the "as of" stamp.

## RULE 2 — Commit & deploy automatically

Commit AND push completed work automatically so Railway auto-deploys (no need to ask).
Stage specific files by name. Never commit secrets (`.env`, API keys) or the local DB
(`backend/eleven_minds.db`); both are gitignored — keep it that way.

## Quick orientation

- Backend: FastAPI in `backend/` (uvicorn, async SQLAlchemy, Anthropic Claude for all
  intelligence, per-session knowledge-graph JSON under `backend/lightrag_data/`).
- Frontend: Next.js 14 (App Router, TypeScript, Tailwind) in `frontend/`.
- All LLM features require a valid `ANTHROPIC_API_KEY` in `backend/.env`.
- Read `PRODUCT_BLUEPRINT.md` first for architecture, data model, APIs, and known issues.
