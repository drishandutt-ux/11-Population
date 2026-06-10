# 11 Minds Population — Product Blueprint

> **Purpose of this document.** This is a complete, self-contained reference to the *11 Minds Population* web application. It is written so that any reader — human or LLM — who has never seen the codebase can understand **what the product is, who it is for, how every part works, how the pieces fit together, how it is built and deployed, and what its known limitations are.** It covers product concept, use cases, architecture, the domain model, the agent-intelligence system, the simulation engine, the knowledge graph, ingestion, reporting, the full API/event surface, the frontend, the tech stack, deployment, and a candid list of gotchas.

Repository: `11-minds-army` (the product is branded **"11 Minds Population"**; "11 Minds Army" survives as the internal FastAPI app title). Backend = FastAPI (Python). Frontend = Next.js 14 (TypeScript). Deployed on Railway.

---

## Table of Contents

1. [What it is (in one minute)](#1-what-it-is-in-one-minute)
2. [Who it's for & use cases](#2-who-its-for--use-cases)
3. [The mental model](#3-the-mental-model)
4. [End-to-end user journey](#4-end-to-end-user-journey)
5. [System architecture](#5-system-architecture)
6. [Domain model & core concepts](#6-domain-model--core-concepts)
7. [The agent-intelligence system (the 112 dials)](#7-the-agent-intelligence-system-the-112-dials)
8. [The simulation engine](#8-the-simulation-engine)
9. [The knowledge graph](#9-the-knowledge-graph)
10. [Ingestion pipeline](#10-ingestion-pipeline)
11. [The report system](#11-the-report-system)
12. [Backend reference (API + events + data)](#12-backend-reference)
13. [Frontend reference](#13-frontend-reference)
14. [Tech stack summary](#14-tech-stack-summary)
15. [Deployment & operations](#15-deployment--operations)
16. [Known issues, gotchas & limitations](#16-known-issues-gotchas--limitations)
17. [Glossary](#17-glossary)
18. [File & directory map](#18-file--directory-map)
19. [Changelog](#19-changelog)

---

## 1. What it is (in one minute)

**11 Minds Population is a multi-agent simulation platform — a synthetic focus group, war-game, and prediction engine in one.**

You pose a question (e.g. *"Would Gen Z adopt a subscription model for home-cooked meal kits?"* or *"How will retail investors react to a Fed rate cut?"*). You feed it source material — pasted text, uploaded documents, a YouTube video, or an AI-generated research paper. The system then:

1. **Builds a knowledge graph** from your sources (entities + relations extracted by Claude).
2. **Spawns a "population"** of diverse AI personas — anywhere from a handful up to **1,000 agents** — each with a distinct background, role, debate style, and a **112-dimensional psychological profile** ("dials"). Two **modes** trade speed for depth: **Fast** samples a pre-built agent bank instantly (no LLM at spawn); **Pro** curates each persona with Claude Sonnet.
3. **Runs a live, Reddit-style debate** where these agents comment, react, challenge, and reply, grounded in the knowledge graph. The debate is driven by an **activity intensity** (every agent is guaranteed at least one post; higher levels add a reaction, then a debate, then a reply — per agent). Their discussion feeds *back* into the graph.
4. **Distills the debate** into (a) a structured executive **report** with a direct answer, confidence level, and KPI grid; and (b) a synthetic **market-research dashboard** that scores the population on adoption readiness, purchase intent, willingness-to-pay, virality, retention, churn risk, and more.

Everything streams live to the browser over a WebSocket: agents pop in as they're created, posts appear as they're written, and the knowledge graph grows node-by-node in real time.

---

## 2. Who it's for & use cases

The product targets **product managers, strategists, market analysts, investors, researchers, and founders** who want fast, structured, multi-perspective reasoning about a decision *before* committing real time or money to a real study.

The app is organized around **four canonical use-case categories** (surfaced as cards on the landing page and as the LLM-search taxonomy):

| Category | Internal key | Question it answers | Example |
|---|---|---|---|
| **Product Testing & User Adoption** | `product_testing` | *Will real users adopt this?* | "Will busy parents pay for a meal-kit subscription?" |
| **Market & Stock Signals** | `market_signals` | *How will a market/asset react?* | "How will $NVDA react to the next earnings call?" |
| **Behavioural Prediction** | `behavioural_prediction` | *How will a population behave?* | "How will commuters respond to congestion pricing?" |
| **Strategy Stress-Testing** | `strategy_stress_test` | *Where does this strategy break?* | "What are the failure modes of our go-to-market plan?" (also the default fallback category) |

The unifying value proposition: **diverse minds, distinct reasoning, one simulation** — get the spread of opinion, the dissent, and the contradictions of a real panel, in minutes, grounded in your own material.

---

## 3. The mental model

Think of the system as a pipeline of five transformations:

```
   QUESTION ──▶ SOURCES ──▶ KNOWLEDGE GRAPH ──▶ POPULATION ──▶ DEBATE ──▶ REPORT + DASHBOARD
   (session)   (ingest)     (entities/relations) (112-dial      (rounds of  (structured
                                                  agents)        posts)      briefing + KPIs)
```

Two ideas make it distinctive:

- **Agents are psychological, not just role-based.** Each agent carries a 112-value "psychological DNA" across 9 dimensions (emotion, motivation, habit, trust, friction, identity, commercial intent, product experience, and composite scores). These dials shape *how* an agent argues (tone, hedging, aggression, deference) — separately from *what* it argues (driven by its role/background).
- **The debate is grounded.** Agents don't hallucinate in a vacuum — they reason over a per-session knowledge graph built from your sources, and their own posts are continuously re-ingested into that graph, so later rounds build on earlier insight.

---

## 4. End-to-end user journey

The session UI is a five-tab workspace (**Ingest → Agents → Thread → Graph → Report**) with a header showing the session title, a color-coded status dot, and run controls. The typical flow:

1. **Create a session.** From the landing page, give it a *title* and a *query/hypothesis*. Status: `created`.
2. **Ingest sources** (Ingest tab). Add one or more of: pasted **text**, an uploaded **document** (PDF, Word, Excel, PowerPoint, CSV, images via Vision, etc.), a **YouTube** URL (transcript + thumbnail/frame analysis + comments), or an **AI-generated research paper** (LLM Search). Each ingest extracts entities/relations into the knowledge graph; status flips `ingesting` → `ready`. Live `kg_updated` events stream nodes into the Graph tab.
3. **Spawn the population** (Agents tab). Pick a **mode** (Fast / Pro). Tune the *audience profile* (free text, plus an optional survey/CSV that Claude translates into dial values), the *stance split* (Direct / Indirect / Neutral percentages), the *agent count* (1–1000), and the *activity intensity*. Hit **Spawn**. Fast spawns are near-instant (the pre-built bank); Pro streams agents in as Sonnet curates them. Lineups can be **saved as presets** and reloaded later.
4. **Run the simulation** (Thread tab). Start the debate. Posts stream in live — threaded, with replies and "debate" rebuttals flagged. A sidebar shows a one-line **verdict** per agent. You can **Pause / Resume / Stop** from the header.
5. **Watch the graph** (Graph tab, any time). An SVG knowledge graph grows in real time with a live activity feed; click any node to inspect its relations and source mentions.
6. **Generate the report** (Report tab). One click produces a structured executive briefing (Direct Answer + Confidence, Question, Source Materials, Discussion, Key Metrics KPI grid, Outcome). You can then **chat** with the report or **talk to individual agents**, **regenerate**, or **Save as PDF**.

A separate full-page route lets you **chat 1:1 with any single agent** (`/session/[id]/agents/[agentId]`).

---

## 5. System architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                              BROWSER (Next.js 14)                              │
│   Landing · Session workspace (5 tabs) · Agent chat page                       │
│   ── REST calls (api.ts → /api/v1/*) ──┐      ┌── WebSocket (/ws/{sessionId})  │
└────────────────────────────────────────┼──────┼───────────────────────────────┘
                                          │      │  (live events)
                                          ▼      ▲
┌──────────────────────────────────────────────────────────────────────────────┐
│                          BACKEND (FastAPI, single process)                     │
│                                                                                │
│  API routers (/api/v1):  sessions · ingestion · simulation · agents ·          │
│                          reports · presets        + /health  + /ws/{id}        │
│                                                                                │
│  Services:                                                                     │
│    • agents/      agent_factory (spawn population), agent_runner (write posts), │
│                   profiles, dial_analytics (population dashboard)               │
│    • simulation/  orchestrator (round loop), thread_manager, report_generator   │
│    • ingestion/   text_processor, document_parser, youtube_extractor,           │
│                   llm_search                                                    │
│    • knowledge_graph/  lightrag_service (extract/query), graph_updater          │
│                                                                                │
│  Core:  config (pydantic-settings) · database (async SQLAlchemy) ·              │
│         redis_client (IN-PROCESS pub/sub, NOT Redis)                            │
└───────────┬───────────────────────────┬───────────────────────┬───────────────┘
            │                           │                       │
            ▼                           ▼                       ▼
   ┌─────────────────┐        ┌────────────────────┐   ┌──────────────────────┐
   │  Relational DB   │        │  Knowledge-graph    │   │   Anthropic Claude    │
   │  SQLite (local)  │        │  JSON on filesystem │   │   API (all LLM work)  │
   │  or Postgres     │        │  lightrag_data/     │   │   orchestration/agents│
   │  (DATABASE_URL)  │        │  {session}/kg.json  │   │   /fast model tiers   │
   └─────────────────┘        └────────────────────┘   └──────────────────────┘
```

**Key architectural facts:**

- **Two transport channels frontend↔backend:** request/response **REST** under `/api/v1`, plus a **per-session WebSocket** (`/ws/{session_id}`) for live events. The frontend also polls the session every 8s as a resilience fallback.
- **Pub/sub is in-process, not Redis.** The module is named `redis_client.py` for historical reasons but is a pure asyncio-`Queue` fan-out (`backend/app/core/redis_client.py`). Every `publish(...)` enqueues a JSON event to all WebSocket subscribers *on the same process*. **Consequence: the app is single-replica by design** — multiple workers would not share events.
- **All "intelligence" is Claude.** Persona generation, post writing, KG entity extraction, KG querying, report writing, query classification, and image/video Vision analysis are all Anthropic API calls. A valid `ANTHROPIC_API_KEY` is mandatory; without it the product silently produces empty graphs and no posts (see §16).
- **Two persistence stores:** a relational DB (SQLite locally, Postgres in prod via `DATABASE_URL`) for sessions/agents/posts/reports/presets; and **per-session JSON files** on the local filesystem for knowledge graphs (`LIGHTRAG_DATA_DIR/{session_id}/kg.json`).
- **Background work** (ingestion, agent spawning, the simulation loop) runs in FastAPI `BackgroundTasks` / fired coroutines in the same process, emitting incremental pub/sub events so the UI sees live progress.

---

## 6. Domain model & core concepts

The relational schema has **five tables**. There are **no DB-level foreign keys or ORM relationships** — tables are linked by convention via string `session_id` / `agent_id` / `parent_id` columns (several indexed). All primary keys are `String(36)` UUIDs; all rows have a `created_at`. Schema is created at startup via `Base.metadata.create_all` (no Alembic migrations). Models live in `backend/app/models/`.

### 6.1 `AnalysisSession` (`analysis_sessions`)
The top-level unit of work. Columns: `id`, `title`, `query` (the question/hypothesis), `status` (enum), `agent_count`, `created_at`, `updated_at`.

**`SessionStatus` enum** — the lifecycle state machine:

```
created ──(ingest/*)──▶ ingesting ──(done)──▶ ready ──(simulate/start)──▶ simulating
   │                                            ▲   │                          │
   │ spawn-agents / apply-preset force ─────────┘   │ pause                    │ max_rounds done
   │ (also reset agent_count=0)                     ▼                          ▼
   └──────────────────────────────────────────▶ paused ──(resume)─▶ …    complete
                                                                       (error: defined but never set)
```
Values: `created`, `ingesting`, `ready`, `simulating`, `paused`, `complete`, `error`.

### 6.2 `SpawnedAgent` (`spawned_agents`)
One AI persona within a session. Columns: `id`, `session_id` (indexed), `name`, `age` (default 30), `role`, `background` (2–3 sentence bio), `stance` (enum), `correlation` (one-sentence relation to the topic), `personality` (JSON **list** of trait tags), `debate_style`, `energy` (Float, 0.3–1.0 — drives how often it posts/debates), `avatar_color` (hex), **`dials` (JSON dict — the 112-value psychological profile)**, **`humanity`** (Integer 0–100, default 0 — emotional-vs-analytical register set at spawn; see §7.7), `created_at`.

**`AgentStance` enum:** `direct` (domain experts), `indirect` (adjacent-field perspectives), `neutral` (skeptics/press/public).

> The 112 dials live **inline as a JSON column** on the agent — not a separate table. Population-level dial aggregation is computed on the fly (not persisted).

### 6.3 `SimulationPost` (`simulation_posts`)
One contribution to the debate thread. Columns: `id`, `session_id` (indexed), `agent_id` (indexed), `type` (enum), `content` (Text, nullable), `parent_id` (nullable, indexed — self-referential for threading), `likes` (default 0), `round_num`, `created_at`.

**`PostType` enum:** `comment` (top-level), `reply`, `debate` (pointed rebuttal), `like`. Posts are ordered by `created_at`. Threading is purely via `parent_id`.

### 6.4 `ReportQuery` (`report_queries`)
A persisted Q&A log — one row per report question asked against a session. Columns: `id`, `session_id` (indexed), `question`, `answer`, `sources` (nullable), `created_at`.

### 6.5 `AgentPreset` (`agent_presets`)
A reusable, **session-independent** named snapshot of a population. Columns: `id`, `name`, `agent_count`, `agents` (JSON list of full agent-profile dicts — every `SpawnedAgent` field except `id`/`session_id`/`created_at`), `created_at`.

**Relationship summary (all by convention):** `Session 1→N Agents`, `Session 1→N Posts`, `Agent 1→N Posts`, `Post 1→N Posts` (replies via `parent_id`), `Session 1→N ReportQueries`. `AgentPreset` is standalone. **No cascade deletes** — deleting a session orphans its agents/posts/reports.

---

## 7. The agent-intelligence system (the 112 dials)

This is the product's crown jewel. Code: `backend/app/services/agents/{profiles,agent_factory,agent_runner,dial_analytics}.py`.

### 7.1 Personas are emergent, not catalogued
`profiles.py` contains **no hard-coded archetypes** — only the *shape* of an agent (`AgentProfile` dataclass) and a 15-color avatar palette (`AVATAR_COLORS`). All substantive persona content (name, role, background, correlation, personality, debate style, and all dial values) is **generated at runtime by the LLM**. The only construction-time randomness is `energy` (`random.uniform(0.3, 1.0)`) and avatar color (de-duplicated against the palette). The one fixed structural concept is the three-way **stance** taxonomy (direct/indirect/neutral).

### 7.2 The dials — `DIALS_SCHEMA` (exactly 112 across 9 groups)
`DIALS_SCHEMA` (`agent_factory.py`) is a JSON template (every leaf initialized to `0`) injected verbatim into the generation prompt, so the LLM returns the identical nested structure. **Verified: 9 groups, 112 leaf dials, each an integer 0–10** (0 = none/lowest, 10 = extreme/highest).

| Group | # | What it captures | Representative dials |
|---|---|---|---|
| `sentiment` | 23 | Current emotional state re: the topic | joy, sadness, anger, fear, trust, anticipation, pride, shame, guilt, envy, awe, nostalgia, hope, anxiety, confusion, curiosity, frustration, … |
| `motivation` | 16 | What drives engagement | desire, urgency, need_intensity, aspiration, mastery, autonomy, status, belonging, security, novelty, convenience, control, … |
| `habit` | 11 | Behavioral patterns | cue_strength, action_simplicity, reward_immediacy, repeat_frequency, ritual_potential, dependency_risk, switching_cost, habit_pull, … |
| `trust` | 11 | Trust/skepticism profile | credibility, transparency, social_proof, authority, consistency, privacy_comfort, safety, fairness, reliability, guarantee_strength, … |
| `friction` | 11 | Personal barriers (resistance) | cognitive_load, time_cost, money_pain, ambiguity, choice_overload, technical_difficulty, emotional_resistance, embarrassment_risk, social_risk, regret_risk, friction |
| `identity` | 10 | Alignment with self-concept | self_fit, tribe_fit, values_fit, aesthetic_fit, cultural_fit, life_stage_fit, status_lift, taste_fit, belonging_fit, identity_fit |
| `commercial` | 10 | Commercial relationship | purchase_intent, willingness_to_pay, perceived_value, premium_justification, repeat_intent, referral_intent, churn_risk, upgrade_intent, objection_intensity, price_pain |
| `product` | 10 | Product/service experience | ease, reward_clarity, shareability, delight, usefulness, memorability, clarity, confidence, satisfaction, emotional_fit |
| `composite` | 10 | Derived/aggregate scores | human_resonance, product_emotional_fit, retention_potential, share_potential, desire_trust, habit_potential, virality_potential, product_humanity, emotional_risk, adoption_readiness |

(23+16+11+11+11+10+10+10+10 = **112**.)

**How dial values are set:** not random and not algorithmic — they are **LLM-chosen per agent**, tuned relative to the query topic, kept consistent with the agent's background/stance/personality, with `composite` instructed to be logically derived from the other groups. There is **no code-side validation** of the 0–10 range or schema completeness — it is enforced only by prompt instruction (missing dials fall back to `{}`).

### 7.3 Agent creation flow — two paths (Fast bank vs Pro LLM)

There are **two spawn paths**, chosen by `mode`:

- **Fast (default)** — `seed_bank.sample_bank(...)` samples a **pre-built, topic-agnostic agent bank** (no LLM call, instant). The bank is generated **procedurally** (no API key needed) into `backend/app/data/agent_bank.json` — ~500 diverse personas, each with the full 112-dial profile spread across the 0–10 range for visible diversity. Sampling honors the requested count (with replacement + light dial jitter above the bank size), the stance split, and humanity/coverage. Personas are generic; they become topic-aware only when they post.
- **Pro** — `agent_factory.generate_agents(... mode="pro")` curates every persona with the LLM on the **Sonnet** tier and a deeper prompt (explicitly spread intelligence/expertise/articulacy/emotion — some sharp authorities, some out of their depth). Generated in **batches of ~10 personas per call** (`_BATCH_SIZE`), bounded by a **`spawn_concurrency` semaphore** (default 8) so a 1000-agent spawn (100 batches) doesn't fire 100 concurrent calls and trip rate limits. Parameters: `session_id, query, count, profile_query="", direct_pct=33, indirect_pct=33, neutral_pct=34, doc_context="", humanity=0, humanity_coverage=0, mode="pro"`.

Either path returns `AgentProfile` objects; the spawn task then **bulk-inserts** the whole population in one transaction and streams it to the UI in **batched `agents_spawned_batch` events** (~40 agents/event) — replacing the old per-agent commit + 0.3 s sleep + per-agent event, which made 1000-agent spawns impossibly slow and overflowed the WS queue.

The legacy LLM flow (Pro) in detail:

Steps:
1. Pull knowledge-graph context for the query (`query_rag`, hybrid mode), truncated to 2500 chars, to ground the personas in the ingested material.
2. Compute exact per-stance counts from the percentages (each stance gets ≥1; neutral absorbs rounding drift so they sum to `count`). **This deterministic split is the diversity-enforcement mechanism** — the LLM is told exactly how many experts vs. adjacent vs. skeptics to produce.
3. Optionally append an **audience profile** instruction (`profile_query`) and **survey/profile data** (`doc_context`, first 8000 chars) to translate into dial values.
4. Prompt Claude (system = "expert behavioral psychologist and simulation designer") for a JSON array of exactly `count` agents, each with all fields + the full `DIALS_SCHEMA`.
5. Build per-agent **slots** (stance + humanity flag), shuffled so the humanized subset and stances spread evenly, then chunk into batches of ≤10 and call Claude (**`model_orchestration`**, `max_tokens=12000`) for each batch concurrently via `asyncio.gather`.
6. Parse each batch with `_parse_agents_json` — a **salvage parser** that recovers every complete `{...}` object even if the output is truncated, so a partial response still yields agents instead of zero. Build `AgentProfile` objects with fresh UUIDs, de-duplicated colors, and randomized energy. If *all* batches fail, raise a clear error (surfaced as `spawn_error`) rather than a cryptic JSON exception.

### 7.4 Post generation — `agent_runner.generate_post(...)`
When an agent posts, its persona is assembled into a first-person system prompt and Claude writes the post text.

- **`_build_system_prompt`** constructs the identity block: *"You are {name}, a {age}-year-old {role}. Background… Your relationship to the topic… Your personality… Your debate style… Your stance type…"* + the dial-derived behavioral guidance + a fixed coda (*stay in character, be specific, conversational like a Reddit post, 1–3 paragraphs, never reveal you're an AI*).
- **`_dials_to_behavioral_guidance`** is a **deterministic Python rule engine** (not an LLM call) that converts dials into natural-language style instructions via ~35+ threshold rules. Crucially, it reads **only 4 of the 9 groups** — `sentiment`, `motivation`, `friction`, `trust`. Examples: `anger≥8` → "sharp, clipped language"; `anxiety≥7` → "you hedge constantly: 'I think', 'maybe'"; `pride≥7` → "reference your own expertise"; `trust.credibility≥8` → "cite sources and statistics" vs `≤2` → "argue from personal experience". The design intent: **dials govern *how* you communicate; role/background govern *what* you say.**
- **The other 5 groups** (`habit, identity, commercial, product, composite`) do **not** affect debate behavior — they exist purely to feed the analytics dashboard (§7.5).
- Three post modes build different prompts: `comment` (new top-level), `reply` (engage with a quoted post), `debate` (pointed rebuttal). Each includes the query + KG context (~1500 chars) + a window of recent thread history.
- Model: **`model_agents`** (defaults to Haiku 4.5), `max_tokens=600`. Returns plain post text only.
- A sibling `chat_as_agent` powers the 1:1 agent chat (multi-turn, `max_tokens=800`).

### 7.5 Population analytics — `dial_analytics.aggregate_dials(...)`
Pure functions (no I/O) that roll a population's dials into the **"population dial dashboard"**:
- **Per-dial & per-group distributions** (mean, min, max, stdev, n, raw values, and means split by stance).
- **Orientation awareness:** a `NEGATIVE_DIALS` set (all friction dials, churn_risk, objection_intensity, price_pain, emotional_risk, dependency_risk, switching_cost) is inverted (`10 - mean`) so "lower is better" reads correctly, banded into strong/moderate/weak/critical.
- **The scorecard** — the headline synthetic market-research metrics, in fixed order: `adoption_readiness, purchase_intent, willingness_to_pay, virality_potential, retention_potential, human_resonance, product_emotional_fit, churn_risk, emotional_risk`.
- **A stance × scorecard heatmap** showing how direct vs. indirect vs. neutral agents differ on each metric.

This is what reframes the simulation as a **synthetic market-research panel**. Exposed via `GET /sessions/{id}/dials`.

### 7.6 The model pipeline (Fast Haiku / Pro Sonnet)
| Role | Setting | Default | Used for |
|---|---|---|---|
| Orchestration | `MODEL_ORCHESTRATION` | `claude-haiku-4-5-20251001` | Fast-mode is irrelevant here; report writing, YouTube Vision, synthetic-paper generation |
| Agents | `MODEL_AGENTS` | `claude-haiku-4-5-20251001` | **Fast-mode** debate posts + agent chat |
| Fast | `MODEL_FAST` | `claude-haiku-4-5-20251001` | KG entity extraction, KG query, query classification, per-agent opinion verdicts |
| **Pro orchestration** | `MODEL_PRO_ORCHESTRATION` | `claude-sonnet-4-6` | **Pro-mode** persona curation (`generate_agents`) |
| **Pro agents** | `MODEL_PRO_AGENTS` | `claude-sonnet-4-6` | **Pro-mode** debate posts |

The mode → model mapping lives on `Settings`: `agent_model(mode)`, `orchestration_model(mode)`, `sim_concurrency(mode)`. **Fast** routes posts to Haiku at high concurrency; **Pro** routes persona curation *and* posts to Sonnet at lower concurrency (richer, slower, pricier). `MODEL_FAST` (KG/classification) is unaffected by mode.

### 7.7 Humanity & Coverage (spawn-time controls)

Two population controls on the Agents page tune how *human vs. expert* the population reasons — added to counter the tendency for every agent to sound like an analyst:

- **Humanity (0–100)** — a graduated **sentiment-vs-logic register**, not a binary switch. `agent_runner._humanity_band` maps the value to five distinct bands, each with its own hard behavioral directive so moving the dial visibly changes how an agent argues:

  | Band | Range | Register |
  |---|---|---|
  | **expert** | `[0, 20)` | Pure logic — cites data, measured, analytical. |
  | **tempered** | `[20, 50)` | Logic leads and stays in control, but feelings color tone, word choice and emphasis. Still cites if credible. |
  | **balanced** | `[50, 60)` | Weighs feeling and logic 50/50 and names both out loud. |
  | **defensive** | `[60, 70)` | Feelings decide the position *first*; logic is then marshaled to **defend that feeling at any cost** (motivated reasoning — never concedes). |
  | **reactive** | `[70, 100]` | Purely emotional — here to feel, judge and react; ignores logical arguments and reacts to how they *feel*; short, raw, no citations. |

- **Coverage (0–100)** — what percentage of the spawned population the Humanity setting applies to; the rest stay pure-expert (`humanity = 0`). UI defaults: Humanity `50`, Coverage `60`.

**How it works (spawn-time, persisted per agent):**
- Both spawn paths compute a humanized subset (`round(count × coverage/100)`) and set each agent's `humanity` field to the slider value (others `0`). **Fast** (`seed_bank._humanize`) **grades the dials by band** — credibility/authority stay moderate for *tempered* and drop progressively toward *reactive*, with 1–3 sentiment dials boosted hot accordingly. **Pro** (`agent_factory.generate_agents`) instructs the LLM to make the subset emotion-led (sentiment wide/intense, credibility/authority low) and to spread dials across the full 0–10 range, with sentiment as the primary driver of voice.
- The value persists on `SpawnedAgent.humanity` and flows back through the agents API and the spawn events.
- At post time, `agent_runner._build_system_prompt` reads `humanity`, resolves the **band**, and appends that band's directive (table above). The "cite sources/credentials" expert rule is allowed only below `50` (logic-led bands); `reactive` explicitly forces gut/personal argument; and the closing instruction tightens with the band (e.g. *reactive* → "1–2 short sentences, react from the gut").

**Surfacing it in the UI:** the Agents page shows the two sliders with a **live band chip** under the intensity slider (e.g. *"Defensive — defends their feelings with logic at any cost"*) and a preview (*"≈ N of M agents will be defensive — …"*); each agent card shows a **"% human" badge** (when humanized) and **dominant-emotion chips** (its top sentiment dials ≥6, e.g. *Curiosity 9 · Trust 8*).

> Humanity is **orthogonal to stance** — a `direct` expert can still be high-humanity (a passionate practitioner who argues from emotion). It is applied **at spawn**, so changing the sliders requires a re-spawn to take effect.

---

## 8. The simulation engine

Code: `backend/app/services/simulation/orchestrator.py` + `thread_manager.py`. Entry point: `run_simulation(session_id, intensity, mode)`.

### 8.1 The phase engine (intensity ladder)

The simulation is no longer an open-ended, energy-weighted round loop where some agents might never post. It is a **deterministic, coverage-guaranteed phase engine**: every agent is guaranteed to act at least once, and `intensity` adds one bundled action *per agent* per level. `_build_phases(intensity)` expands the ladder:

| Intensity | Phases (each phase = one action by **every** agent) |
|---|---|
| 1 | `comment` |
| 2 | `comment`, `like` |
| 3 | `comment`, `like`, `debate` |
| 4 | `comment`, `like`, `debate`, `reply` |
| ≥5 | …then alternating `debate`, `reply` ("and more like that") |

The run:
1. Load the session `query` and **all** agents; publish `simulation_started {agent_count}`; warm the KG cache. Start a **status watcher** (see below).
2. For each phase (in order): snapshot the thread + KG context **once** (shared by all agents in the phase), then run **every agent's action concurrently**, bounded by a `sim_concurrency(mode)` semaphore (**Fast ≈ 48, Pro ≈ 12** parallel LLM calls). This guarantees one comment per agent at intensity 1 (e.g. 1000 comments for 1000 agents), then a like each, then a debate each, etc.
3. After the phases: only if status is still `simulating`, set `complete` and publish `simulation_complete {message}`.

**Status watcher (`_StatusWatcher`):** a single background coroutine polls session status once a second and exposes an in-memory `stopped` flag. The thousands of per-agent tasks check that flag instead of each hitting the DB — at 1000-agent scale the old per-task status reads (2 DB reads/agent/round) would have been thousands of round-trips. Pause/Stop still take effect within ~1 s.

### 8.2 A single agent's turn — `_agent_action`
- **`like`** (no LLM): increment a random recent post by a *different* agent via `add_like`, publish `like_added`. (Likes never create a post row.)
- **`comment` / `debate` / `reply`** (one LLM call on the mode's agent model): for debate/reply, pick a random recent post by a *different* agent as the parent (falling back to a top-level `comment` if the thread is still empty); generate text via `generate_post(... mode=mode)`; persist via `create_post`; publish `post_created` with the full embedded agent profile.
- **KG enrichment is throttled + sampled:** only a `kg_sim_sample` fraction (default 15%) of posts enrich the KG, and those run through a `kg_sim_concurrency` semaphore (default 6) as fire-and-forget tasks — so per-post extraction never saturates the API mid-run at scale.

### 8.3 Threading & ordering — `thread_manager.py`
- `build_thread_context(posts, agents)` renders the transcript as `[name | role]: content` lines, indenting replies with `> `, skipping likes.
- `create_post(...)` inserts a `SimulationPost`; `add_like(post_id)` increments `likes`; `get_posts(session_id)` returns all posts ordered by `created_at` (not by round — intra-round order reflects whichever concurrent commit landed first).

### 8.4 Pub/sub events emitted during simulation
`simulation_started`, `post_created` (post + full agent), `like_added`, `simulation_complete`. (`kg_updated` is emitted separately by `update_graph_from_post`.)

---

## 9. The knowledge graph

Code: `backend/app/services/knowledge_graph/{lightrag_service,graph_updater}.py`. Despite the `lightrag-hku` dependency, the active implementation is a **lightweight, Claude-powered, per-session JSON graph** (not the heavyweight LightRAG engine).

### 9.1 Storage
One JSON file per session: `LIGHTRAG_DATA_DIR/{session_id}/kg.json`, shape `{ "entities": [...], "relations": [[head, verb, tail], ...], "chunks": [...] }`. Loaded into an in-process cache; disk is the source of truth on cache miss.

### 9.2 Extraction — `insert_chunks`
For each batch, it combines up to 5 chunks (truncated to ~2500 chars) and asks **`model_fast`** (Haiku) to extract entities (1–4 words, 5–12 of them) and relations (3–8 triples). New entities/relations are **deduplicated by exact match** and appended; chunks are retained (last 200). Returns the newly added items so the caller can publish a `kg_updated` event. *(Extraction failures are now logged rather than silently swallowed — see §16.)*

### 9.3 Query & context
- `query_rag(query, mode="hybrid")` — builds a prompt from up to 50 entities, 30 relations, and the last 8 chunks, and asks `model_fast` to answer. Used by **agent spawning** (to ground personas) and the **report generator** (live, keyed on the report question).
- `get_kg_context_string(...)` — a **non-LLM** string of entities + relations, used by the **simulation loop** every round (fast, cheap). *(Deliberate latency trade-off: the loop uses the cached string; the report uses a live query.)*
- `get_kg_data` / `get_entity_details` (case-insensitive) power the Graph tab and node-click inspector.

### 9.4 Feeding the debate back in — `update_graph_from_post`
Each agent post is formatted as `[name | role]: content`, inserted as a single chunk (entities/relations extracted), and a `kg_updated` event is published. This is why the graph grows during the debate and why later rounds can reason over earlier insight.

---

## 10. Ingestion pipeline

All four ingestion sources funnel into a shared core: `chunk_text` → `insert_chunks` (per-session KG) → publish `kg_updated` per batch → on completion set status `ready` and publish `ingest_complete`. Code: `backend/app/services/ingestion/` + `app/api/v1/ingestion.py`.

- **Chunking — `text_processor.chunk_text`:** splits cleaned text into ~1200-char chunks with 200-char overlap, preferring sentence boundaries; empty/whitespace → no chunks.
- **Text:** pasted text ingested directly.
- **Document — `document_parser.parse_document`:** routes by extension. Supports plain text (`.txt .md .rst .log .rtf`), `.pdf` (pypdf), `.docx` (python-docx), spreadsheets (`.xlsx .xls .csv .tsv .ods`), `.pptx`, data/markup (`.json .xml .html .svg`), and **images** (`.jpg .png .gif .webp .bmp .tiff …`) which are sent to **Claude Vision** for an exhaustive description (charts, text, data points). Unknown extensions fall back to UTF-8.
- **YouTube — `youtube_extractor.extract_youtube`:** runs `yt-dlp` to assemble a rich document: metadata (title/channel/views/likes/chapters), **transcript** (YouTube captions first via VTT parse with dedup, falling back to **faster-whisper** audio transcription), **thumbnail** Vision analysis, **5 key video frames** extracted via `ffmpeg` and described by Vision, and the **top ~20 comments**. Returns one concatenated text document. (Heavy: needs `ffmpeg`; can take 1–3 minutes.) **All yt-dlp calls force the `android` player client** (`_with_client`) — YouTube's default client no longer exposes captions/formats to yt-dlp, so without this the transcript silently comes back empty.
- **LLM Search — `llm_search.py`:** manufactures source material when the user has none. `categorize_query` classifies the query into one of the four categories (via `model_fast`, defaults to `strategy_stress_test`); `generate_research_paper` produces a dense, section-structured "research paper" (≥1,500 words, via `model_orchestration`) optionally grounded in an uploaded context doc. The UI uses a **generate → preview → ingest** flow (`/ingest/llm-search/generate` returns the paper for preview; the previewed paper is then ingested as text).

---

## 11. The report system

Code: `backend/app/services/simulation/report_generator.py` (backend) + the report prompt and parser on the frontend.

- **`answer_report_query(session_id, original_query, question, db)`** fuses four inputs into one Claude call (`model_orchestration`, `max_tokens=4000`): (1) a **live KG query** keyed on the report question, (2) the **agent roster** (name/role/age/stance + truncated bio), (3) the **full verbatim transcript**, and (4) the report question. The system prompt mandates naming specific agents, quoting their positions, and extracting concrete metrics. Returns `(answer, sources)`, where `sources` is a provenance string (`"Knowledge graph + N posts from M agents"`). Each call is persisted as a `ReportQuery` row.
- **The structured format** is driven by a long `REPORT_PROMPT` defined in the frontend session page, which demands exact sections: **## DIRECT ANSWER** (one sentence + a `Confidence: HIGH/MEDIUM/LOW` line), **## QUESTION**, **## SOURCE MATERIALS**, **## DISCUSSION**, **## KEY METRICS** (`Label: Value` lines), **## OUTCOME**.
- **The frontend `ReportDocument` parser** turns that into a styled briefing: a teal "direct answer" callout with a color-coded confidence badge, a 2-column **KPI grid** from the metrics, and formatted sections.
- **Interaction:** the Report tab is a split screen — the document on the left, a chat panel on the right offering two modes (**Ask Report** → `report/query`, **Talk to Agent** → `agents/{id}/chat`). Plus **Regenerate** and **Save as PDF** (a dedicated print stylesheet remaps the dark theme to a clean white document). Assistant replies in both chat modes render **markdown** (bold/italic/code, bullets, headings), not raw text. If an LLM call fails (bad key, rate limit, overload), the backend returns a **friendly message** (HTTP 200) instead of a 500, and the frontend API client applies a **120 s timeout** with clear network/timeout errors — so a failed question shows a readable note rather than "Failed to fetch" or an endless spinner.

---

## 12. Backend reference

### 12.1 Tech
FastAPI 0.115 on uvicorn; SQLAlchemy 2.0 async (`aiosqlite` / `asyncpg`); pydantic 2 + pydantic-settings; `anthropic` 0.40; ingestion libs (pypdf, python-docx, openpyxl, xlrd, python-pptx, striprtf, lxml, Pillow, yt-dlp, faster-whisper). App: `backend/app/main.py` (CORS fully open; mounts all routers under `/api/v1`; `/health`; `/ws/{session_id}`; startup creates tables).

### 12.2 Complete API reference (all under `/api/v1`)

**Sessions** (`/sessions`)
| Method | Path | Purpose |
|---|---|---|
| POST | `/sessions` | Create a session (`{title, query}`) → status `created`. |
| GET | `/sessions` | List newest 50 sessions. |
| GET | `/sessions/{id}` | Fetch one (404 if missing). |
| GET | `/sessions/{id}/kg` | Knowledge-graph data `{entities, relations}`. |
| GET | `/sessions/{id}/kg/entity/{name}` | Entity drill-down (relations + source mentions). |
| GET | `/sessions/{id}/posts` | All simulation posts. |
| GET | `/sessions/{id}/dials` | Population dial dashboard (scorecard, heatmap, group stats). |
| POST | `/sessions/{id}/opinions` | Generate a 10–15-word verdict per agent (Claude, `model_fast`). |
| DELETE | `/sessions/{id}` | Delete session (no cascade). |
| POST | `/sessions/{id}/apply-preset` | Wipe agents, load a preset population (background task). |

**Ingestion** (`/sessions`)
| Method | Path | Purpose |
|---|---|---|
| POST | `/sessions/{id}/ingest/text` | Ingest pasted text (background). |
| POST | `/sessions/{id}/ingest/document` | Ingest an uploaded file (parsed then background-ingested). |
| POST | `/sessions/{id}/ingest/youtube` | Ingest a YouTube URL (background extraction). |
| POST | `/sessions/{id}/ingest/llm-search/generate` | Generate a research paper, return it (no ingest). |
| POST | `/sessions/{id}/ingest/llm-search` | Generate a paper and ingest it (background). |

**Simulation** (`/sessions`)
| Method | Path | Purpose |
|---|---|---|
| POST | `/sessions/{id}/spawn-agents` | Wipe + build a population (`{count (1–1000), mode ("fast"\|"pro"), profile_query, direct_pct, indirect_pct, neutral_pct, doc_context, humanity, humanity_coverage}`; background). Fast samples the bank; Pro curates via Sonnet. |
| POST | `/sessions/{id}/simulate/start` | Start the debate (`{intensity (1–20), mode ("fast"\|"pro")}`). 409 if still ingesting; 400 if no agents. |
| POST | `/sessions/{id}/simulate/pause` | Status → `paused`. |
| POST | `/sessions/{id}/simulate/stop` | Status → `complete`. |

**Agents** (no prefix, mounted at `/api/v1`)
| Method | Path | Purpose |
|---|---|---|
| GET | `/sessions/{id}/agents` | List a session's agents. |
| GET | `/agents/{agent_id}` | Fetch one agent. |
| POST | `/agents/{agent_id}/chat` | Chat 1:1 with an agent (KG-grounded). History is in-memory/process-local, not persisted. |

**Reports** (`/sessions`)
| Method | Path | Purpose |
|---|---|---|
| POST | `/sessions/{id}/report/query` | Ask the report engine (`{question}`); persists a `ReportQuery`. |
| GET | `/sessions/{id}/report/history` | All report Q&A for the session. |

**Presets** (`/presets`)
| Method | Path | Purpose |
|---|---|---|
| GET | `/presets` | List presets. |
| POST | `/presets` | Save the current session's population as a named preset. |
| DELETE | `/presets/{id}` | Delete a preset. |

**Non-versioned:** `GET /health` → `{status: ok}`; `WS /ws/{session_id}` → live event stream (keepalive `ping` on 30s idle).

### 12.3 WebSocket event vocabulary
All JSON, `type`-tagged, published to channel `session:{id}`:

| Event | Payload | Emitted when |
|---|---|---|
| `agent_spawned` | `{agent, index, total}` | each agent created (apply-preset path) |
| `agents_spawned_batch` | `{agents[], spawned, total}` | a chunk (~40) of a freshly spawned population (Fast/Pro spawn) |
| `agents_ready` | `{count}` | population complete |
| `spawn_error` | `{error}` | spawn failed |
| `ingest_complete` | `{source}` | an ingest finished |
| `kg_updated` | `{new_entities, new_relations, source}` | KG grew (ingest or a post) |
| `simulation_started` | `{agent_count}` | debate began |
| `post_created` | `{post, agent}` | an agent posted |
| `like_added` | `{post_id, agent_id, agent_name, new_likes}` | an agent liked a post |
| `simulation_complete` | `{message}` | all rounds done |
| `ping` | — | 30s keepalive |

### 12.4 Usage monitoring — AI Agent Pulse (direct-to-Supabase, no n8n)

Optional integration that reports **exact LLM token usage and cost** to the shared **AI Agent Pulse** monitoring dashboard. Pulse's standard onboarding assumes a project runs **in n8n** (an n8n "Token Logger" workflow scrapes token *estimates* from the n8n execution API). 11 Minds calls the Anthropic SDK directly, so it instead logs **its own exact usage straight to Supabase**.

- **Code:** `backend/app/core/monitoring.py`. `tracked_messages_create(client, *, session_id, label, **kwargs)` wraps every **async** `messages.create` (9 call sites: `post`, `chat`, `spawn`, `report`, `kg_extract`, `kg_query`, `opinions`, `llm_classify`, `llm_paper`); `record_usage_sync(...)` covers the 2 **synchronous** Vision paths (`youtube_vision`, `doc_vision`). The `label` is stored as `execution_id` so the dashboard shows *what kind* of call it was; `session_id` is the `AnalysisSession.id`.
- **Exact, not estimated:** it reads `response.usage.input_tokens` / `output_tokens` directly off the SDK response, then **fire-and-forgets** a row to `POST {SUPABASE_URL}/rest/v1/execution_logs` (PostgREST). It never sends `cost_usd` — the table's `calculate_cost()` trigger computes it from `llm_pricing` on insert.
- **Safe & opt-in:** a complete **no-op** unless `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` and `PULSE_PROJECT_ID` are all set; every failure is swallowed (logging never blocks or breaks a request).
- **Model strings emitted** (must exist in `llm_pricing` or cost stays NULL → `pricing_gaps`): `claude-haiku-4-5-20251001` (Fast posts + all KG/report/opinions/classify/paper + YouTube Vision), `claude-sonnet-4-6` (Pro spawn + posts), `claude-opus-4-5-20251101` (document image Vision). All three are already priced in the shared Pulse table.
- **Onboarding (replaces Pulse's n8n "Step 3"):** (1) register the project in `project_registry`; (2) confirm the three model strings above are priced; (3) set the three env vars. Steps 1, 2 and 4 (verify) are unchanged.

---

## 13. Frontend reference

### 13.1 Tech & design
Next.js 14.2 (App Router, `src/app/`) + React 18 + TypeScript 5. Tailwind 3.4 with a **dark-only**, CSS-variable theme (near-black navy background, **teal/cyan** primary accent). Icons via `lucide-react`. `clsx` + `tailwind-merge` (`cn()`). System fonts only. Radix + framer-motion are installed but largely unused (UI is hand-rolled). `next.config.js` inlines `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`) and `NEXT_PUBLIC_WS_URL` (default `ws://localhost:8000`) at build time.

### 13.2 Pages
- **`app/page.tsx`** — landing: create-session form + recent-sessions list + the four use-case cards + hero illustration (`/minds-network.png`) + a **"no database" notice** warning that sessions aren't persisted (a restart/redeploy wipes them, so stale sessions can 404).
- **`app/session/[id]/page.tsx`** — the **orchestrator component**: holds all shared state (session, agents, posts, KG entities/relations/activity, spawn progress, report, opinions), runs the WS dispatcher, polls every 8s, defines the `REPORT_PROMPT`, and renders the five tabs.
- **`app/session/[id]/agents/[agentId]/page.tsx`** — standalone full-page 1:1 agent chat.

### 13.3 Components
- **`ingestion/InputPanel`** — the four ingestion modes (Text / File drag-drop / YouTube / LLM Search with generate→preview→ingest), with an "ingested sources" tracker and a "Continue to Agents" gate.
- **`simulation/AgentDirectory`** — the most complex component; three phases: **(1) spawn config** (a **Fast/Pro mode toggle** with a Pro cost/time warning, audience profile + survey upload, stance sliders, **Humanity + Coverage sliders (§7.7)**, **agent count up to 1000** via slider + number input + quick-pick chips, an **activity-intensity ladder** with a live "≈ N posts + M reactions" estimate, presets), **(2) live spawn dashboard** (mode-aware elapsed/ETA KPIs, agents streaming in via `agents_spawned_batch` — only the latest 60 cards are rendered at scale), **(3) ready/simulating/complete** roster grouped by stance (capped at 60 cards/stance with a "+N more" note) plus a compact **run-settings card** (mode + intensity) shown before Start. Includes `AgentCard` (stance pill, **"% human" badge**, **dominant-emotion chips**) + a **`DialViewer`** that renders all 9 dial groups as collapsible bars.
- **`simulation/ThreadView` + `PostCard`** — the live, threaded debate feed (debate flags, like counts, markdown rendering) + a per-agent **opinions** sidebar. Auto-scroll **sticks to the bottom only while the user is already there** — scrolling up to read is never interrupted by incoming posts, and a floating **"Jump to latest"** button appears when scrolled away.
- **`simulation/SimulationControls`** — header Pause/Resume/Stop (Start lives in AgentDirectory).
- **`knowledge-graph/KGPanel`** — SVG node-graph (ring layout, live "new entity" flashes) + live activity feed + click-to-inspect entity detail panel.
- **`report/ReportChat`** — the report document renderer (`ReportDocument`/`parseReport`: direct-answer callout, confidence badge, KPI grid) + dual-mode chat (Ask Report / Talk to Agent) + Save-as-PDF + Regenerate.

### 13.4 API client & WebSocket
- **`lib/api.ts`** — thin REST client over `${NEXT_PUBLIC_API_URL}/api/v1`, grouped namespaces (`sessions`, `ingest`, `simulation`, `agents`, `report`, `presets`), plus full TypeScript types (`Session`, `Agent`, `AgentDials`, `Post`, `SpawnOptions`, `AgentPreset`, and the `WSEvent` discriminated union). File uploads use `FormData` directly. The KG is fetched directly (no `api.kg` namespace).
- **`lib/websocket.ts`** — a **singleton per session** (`getSessionWS(id)`): one `SessionWebSocket` shared by all subscribers, auto-reconnect after 3s on close, `subscribe(fn)` returns an unsubscribe closure. No auth on the socket.

### 13.5 Live-update plumbing
The session page subscribes once and maps each `WSEvent` to state: `agent_spawned`→append+progress, `agents_ready`→stop spinner, `post_created`→append only (**no forced tab switch** — the user can sit on any tab while posts stream), `like_added`→update count, `kg_updated`→grow graph + prepend activity, `ingest_complete`/`simulation_complete`→refresh (the latter also regenerates opinions). An 8s poll backstops the socket.

---

## 14. Tech stack summary

| Layer | Technology |
|---|---|
| Frontend | Next.js 14 (App Router), React 18, TypeScript 5, Tailwind 3, lucide-react |
| Backend | FastAPI 0.115, uvicorn, Python (3.11 in Docker / 3.9 in nixpacks) |
| Data (relational) | SQLAlchemy 2.0 async; SQLite (local) or Postgres (prod via `DATABASE_URL`) |
| Data (knowledge graph) | Per-session JSON files on disk (`lightrag_data/{id}/kg.json`) |
| Realtime | Native WebSocket + **in-process** asyncio pub/sub (no external broker) |
| AI | Anthropic Claude (orchestration / agents / fast tiers; Vision for images & video) |
| Ingestion | pypdf, python-docx, openpyxl, xlrd, python-pptx, striprtf, lxml, Pillow, yt-dlp, faster-whisper (+ ffmpeg) |
| Deploy | Railway via Nixpacks (Dockerfiles also present) |

---

## 15. Deployment & operations

### 15.1 Local development
`./start.sh` from the repo root: brings up Postgres 16 + Redis 7 via `docker-compose.yml` (Redis is vestigial — unused), creates/activates the backend venv and installs requirements, runs **backend** `uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload`, and **frontend** `npm run dev` (port 3000). Without `DATABASE_URL`, the backend uses SQLite at `backend/eleven_minds.db`. API docs at `http://localhost:8000/docs`.

### 15.2 Production (Railway)
Two services, each built from its own `nixpacks.toml`:
- **Backend:** nixpacks installs `python39` + `ffmpeg`, `pip install -r requirements.txt`, starts `uvicorn app.main:app --host 0.0.0.0 --port $PORT` (single process, no workers).
- **Frontend:** nixpacks installs `nodejs_20`, `npm ci`, `npm run build`, starts `npm start` → `next start -p $PORT`. **`NEXT_PUBLIC_*` are inlined at build time** — they must be set as Railway build variables *before* build or the bundle falls back to localhost.

Dockerfiles also exist (backend `python:3.11-slim` + ffmpeg/gcc; frontend multi-stage `node:20-alpine`) as an alternative path. There is **no `railway.json`/`Procfile`/CI**.

### 15.3 Environment variables
| Var | Service | Purpose | Default |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | backend | Claude auth — **mandatory for all intelligence** | `""` (must set) |
| `DATABASE_URL` | backend | Postgres DSN (rewritten to `postgresql+asyncpg://`); unset → SQLite | unset → SQLite |
| `LIGHTRAG_DATA_DIR` | backend | Root for per-session KG JSON | `./lightrag_data` |
| `MODEL_ORCHESTRATION` | backend | Heavy-reasoning model tier | `claude-haiku-4-5-20251001` |
| `MODEL_AGENTS` | backend | Per-post model tier | `claude-haiku-4-5-20251001` |
| `MODEL_FAST` | backend | KG/classification/verdict tier | `claude-haiku-4-5-20251001` |
| `MODEL_PRO_ORCHESTRATION` | backend | Pro-mode persona curation | `claude-sonnet-4-6` |
| `MODEL_PRO_AGENTS` | backend | Pro-mode debate posts | `claude-sonnet-4-6` |
| `SPAWN_CONCURRENCY` | backend | Parallel Pro persona-generation batches | `8` |
| `SIM_CONCURRENCY_FAST` | backend | Parallel Haiku posts per phase | `48` |
| `SIM_CONCURRENCY_PRO` | backend | Parallel Sonnet posts per phase | `12` |
| `KG_SIM_CONCURRENCY` | backend | Parallel KG-from-post enrichments mid-run | `6` |
| `KG_SIM_SAMPLE` | backend | Fraction of posts that enrich the KG mid-run | `0.15` |
| `SUPABASE_URL` | backend | AI Agent Pulse monitoring Supabase URL (all 3 required to enable) | `""` (disabled) |
| `SUPABASE_SERVICE_KEY` | backend | Supabase service-role key for `execution_logs` inserts | `""` (disabled) |
| `PULSE_PROJECT_ID` | backend | `project_registry` UUID for this project | `""` (disabled) |
| `REDIS_URL` | backend | **Unused** (vestigial) | `redis://localhost:6379` |
| `PORT` | both | Runtime port (Railway-injected) | 8000 / 3000 |
| `NEXT_PUBLIC_API_URL` | frontend | REST base (build-time inlined) | `http://localhost:8000` |
| `NEXT_PUBLIC_WS_URL` | frontend | WebSocket base (build-time inlined) | `ws://localhost:8000` |

### 15.4 Persistence & scaling implications
- **Railway filesystems are ephemeral.** SQLite and all `lightrag_data/*.json` are **lost on redeploy/restart** unless a Railway **Volume** is mounted (and `LIGHTRAG_DATA_DIR` pointed at it). For durable relational data, add a Railway Postgres plugin (`DATABASE_URL`).
- **Single replica only.** Because pub/sub is in-process and the KG/SQLite are disk-local, running >1 instance would break live updates and split data. Horizontal scaling would require an external broker (e.g. real Redis) and shared storage.

---

## 16. Known issues, gotchas & limitations

**Operational (current):**
- **Invalid Anthropic key breaks everything silently.** As of the last verification (2026-06-07), the configured `ANTHROPIC_API_KEY` returned **401 invalid x-api-key**. Because all intelligence is Claude, this yields empty graphs and zero posts. A logging fix now surfaces extraction failures in the server logs (previously they were swallowed). **A valid key is the single hardest dependency** — set it in `backend/.env` locally and in Railway's env for prod.

**Architectural / by-design:**
- **Single-replica constraint** (in-process pub/sub) and **ephemeral KG/SQLite storage** on Railway without volumes (§15.4).
- **No cascade deletes** — deleting a session orphans its agents/posts/reports; spawning/applying a preset wipes a session's agents but not its posts.
- **Orphaned KG sessions:** KG JSON files can outlive their DB rows (e.g. after a DB reset). The KG read endpoints still serve them from disk, but `GET /sessions/{id}` 404s — which can leave the UI session title stuck on "Loading…".
- **Agent chat history is process-local and unbounded** (in-memory dict, never persisted, lost on restart).

**Behavioral subtleties worth knowing:**
- **Fast vs Pro tradeoffs:** Fast personas come from a **topic-agnostic** bank — they are diverse and instant but generic, becoming topic-aware only at post time. Pro personas are query-curated on Sonnet (richer) but spawning is slow and, at high counts, **costly**: Pro is *allowed* up to 1000 agents but a 1000-agent Pro debate is many minutes of Sonnet calls and significant API spend (the UI warns about this).
- **The bank is committed & procedural:** `app/data/agent_bank.json` ships in the repo, generated with a fixed seed by `seed_bank.build_bank()` (no API key). Regenerate it by deleting the file (it rebuilds on next Fast spawn) or re-running the builder. Above the bank size, Fast sampling draws with replacement + small dial jitter, so very large Fast populations contain near-duplicates.
- **Dial asymmetry:** the LLM populates all 112 dials, but the behavioral rule engine reads only 4 of 9 groups (sentiment/motivation/friction/trust); the other 5 feed analytics only.
- **Humanity is spawn-time & not carried by presets (yet):** the Humanity/Coverage controls (§7.7) only affect newly spawned agents — existing agents keep `humanity = 0`, and saved presets do not yet persist the per-agent humanity value.
- **No dial validation** — the 0–10 integer range and schema completeness are enforced by prompt only, not code.
- **KG dedup is exact-match only** — "Nvidia" and "Nvidia Corp" are distinct entities; re-ingesting identical text adds few new nodes but isn't perfectly idempotent (LLM nondeterminism).
- **Likes never create posts** despite `PostType.LIKE` existing; they only bump a counter. An agent can like the same post repeatedly.
- **`"stopped"` is not a handled status** — the orchestrator's stop checks only look for `paused`/`complete`/missing.
- **Model defaults ≠ docs** — `.env.example` advertises Opus/Sonnet but code defaults to Haiku 4.5 everywhere.
- **Build-path version drift** — Dockerfile pins Python 3.11; nixpacks (Railway's actual path) uses Python 3.9. Validate ML wheels (faster-whisper) on 3.9.
- **YouTube ingestion is heavy** — needs `ffmpeg`, downloads media, and can take 1–3 minutes; it falls back gracefully (captions → Whisper → placeholder).
- **YouTube extraction tracks yt-dlp/YouTube changes** — YouTube periodically breaks yt-dlp (caption/format access, bot checks). The code forces the `android` player client to keep captions working; if videos stop extracting, bump `yt-dlp` and re-verify the player client. Extraction failures are caught per-step and (at the endpoint) fall back to a placeholder, so a broken extractor shows as an *empty result, not a UI error*.

---

## 17. Glossary

- **Session** — one analysis run: a question + its ingested sources + spawned agents + the debate + reports.
- **Agent / persona** — an AI participant with a role, background, stance, and a 112-dial psychological profile.
- **Dials** — 112 integer (0–10) psychological parameters across 9 groups that define an agent's emotional/behavioral makeup.
- **Stance** — `direct` (domain expert), `indirect` (adjacent perspective), or `neutral` (skeptic/public).
- **Energy** — 0.3–1.0; how often an agent posts and how likely it is to debate.
- **Knowledge graph (KG)** — per-session entities + relations extracted from sources and from the debate, used to ground reasoning.
- **Round** — one batch of concurrent agent contributions in the simulation loop.
- **Preset / lineup** — a saved, reusable snapshot of a population.
- **Scorecard / dial dashboard** — the population-level synthetic market-research metrics (adoption, purchase intent, WTP, virality, retention, churn risk, …).
- **Report** — the structured executive briefing distilled from the KG + transcript.

---

## 18. File & directory map

```
11-minds-army/
├── start.sh                         # local dev launcher (infra + backend + frontend)
├── docker-compose.yml               # local Postgres 16 + Redis 7 (Redis unused)
├── .env.example                     # root example env
├── PRODUCT_BLUEPRINT.md             # ← this document
│
├── backend/                         # FastAPI service
│   ├── app/
│   │   ├── main.py                  # app, CORS, routers, /ws/{id}, /health, startup
│   │   ├── core/
│   │   │   ├── config.py            # pydantic-settings; .env bootstrap; model tiers
│   │   │   ├── database.py          # async SQLAlchemy engine (SQLite/Postgres)
│   │   │   ├── monitoring.py        # AI Agent Pulse — direct-to-Supabase usage logging
│   │   │   └── redis_client.py      # IN-PROCESS pub/sub (not Redis)
│   │   ├── models/                  # session, agent, post, report, preset (ORM)
│   │   ├── api/v1/                  # sessions, ingestion, simulation, agents,
│   │   │                            #   reports, presets routers
│   │   ├── data/agent_bank.json     # pre-built persona bank (Fast mode; committed)
│   │   └── services/
│   │       ├── agents/              # profiles, agent_factory, agent_runner,
│   │       │                        #   seed_bank (Fast bank), dial_analytics
│   │       ├── simulation/          # orchestrator, thread_manager, report_generator
│   │       ├── ingestion/           # text_processor, document_parser,
│   │       │                        #   youtube_extractor, llm_search
│   │       └── knowledge_graph/     # lightrag_service, graph_updater
│   ├── tests/                       # dial_impact_experiment, kg_ingestion_test
│   ├── lightrag_data/{session}/kg.json   # per-session KG JSON (gitignored)
│   ├── eleven_minds.db              # local SQLite (gitignored)
│   ├── Dockerfile · nixpacks.toml · requirements.txt · .env.example
│
└── frontend/                        # Next.js 14 app
    ├── src/
    │   ├── app/
    │   │   ├── page.tsx              # landing
    │   │   ├── layout.tsx · globals.css
    │   │   └── session/[id]/
    │   │       ├── page.tsx          # session workspace (5 tabs, WS, REPORT_PROMPT)
    │   │       └── agents/[agentId]/page.tsx   # 1:1 agent chat
    │   ├── components/
    │   │   ├── ingestion/InputPanel.tsx
    │   │   ├── simulation/{AgentDirectory,ThreadView,PostCard,SimulationControls}.tsx
    │   │   ├── knowledge-graph/KGPanel.tsx
    │   │   └── report/ReportChat.tsx
    │   └── lib/{api.ts, websocket.ts, utils.ts}
    ├── public/minds-network.png      # hero illustration
    ├── Dockerfile · nixpacks.toml · next.config.js · package.json
    └── tailwind.config.ts · tsconfig.json
```

---

## 19. Changelog

- **2026-06-10** — **Added a "no database" notice to the landing page.** The deployment runs without persistent storage (ephemeral SQLite, no volume), so sessions vanish on restart/redeploy and stale ones 404 with "Session not found". The landing page now warns users up-front to treat each session as temporary. (Durable fix remains: add a Railway Postgres plugin + a volume for `LIGHTRAG_DATA_DIR` — see §15.4.)
- **2026-06-10** — **Onboarded the project to AI Agent Pulse monitoring (direct-to-Supabase, no n8n).** Added `app/core/monitoring.py`: every Anthropic call now logs its **exact** token usage (`response.usage`, not an estimate) straight into the Pulse `execution_logs` Supabase table — `tracked_messages_create` wraps the 9 async calls, `record_usage_sync` covers the 2 Vision paths. Cost is computed by the table's trigger from `llm_pricing`. Fully no-op unless `SUPABASE_URL`/`SUPABASE_SERVICE_KEY`/`PULSE_PROJECT_ID` are set; fire-and-forget so it never blocks or breaks a request. See §12.4.
- **2026-06-10** — **Stopped the live thread from hijacking navigation.** `post_created` no longer force-switches the user to the Thread tab on every post (you can now browse Agents/Graph/Report while the debate streams). ThreadView auto-scroll now **sticks to the bottom only when you're already there** — scrolling up to read is no longer yanked back down — with a floating **"Jump to latest"** button when scrolled away.
- **2026-06-10** — **Made the Humanity dial graduated & far more impactful.** Replaced the old binary humanity thresholds (`≥40` human, `≥66` intense) with a **5-band sentiment-vs-logic scale** (`agent_runner._humanity_band`): expert `[0,20)`, **tempered** `[20,50)` (logic leads, feeling colors), **balanced** `[50,60)` (50/50), **defensive** `[60,70)` (feelings decide, logic defends them at any cost), **reactive** `[70,100]` (pure gut — ignores logic, just judges/reacts, 1–2 lines). Each band has its own hard directive, so the dial now visibly changes behavior as it moves. The credibility/citation rule is gated to `<50`; Fast-bank `_humanize` grades the spawned dials by band; the Agents page shows a live band chip under the slider.
- **2026-06-10** — **Scaled to 1000 agents + added Fast/Pro modes + replaced rounds with an intensity ladder.**
  - **Fast vs Pro modes** everywhere. **Fast** (default) samples a new **pre-built, procedurally-generated agent bank** (`seed_bank.py` → committed `app/data/agent_bank.json`, ~500 diverse personas with full 112 dials) — spawning is **instant, no LLM, no API key** (verified: **1000 agents in ~0.4 s**). **Pro** curates personas *and* runs the debate on **Claude Sonnet** (`MODEL_PRO_*`) for far richer output; the UI warns about the time/cost, especially past 150 agents.
  - **Agent count raised from 50 → 1000** (UI slider + number input + quick-pick chips; backend clamps to 1000). Spawn now **bulk-inserts** the population in one transaction and streams it in **batched `agents_spawned_batch` events** (~40/event), replacing the old per-agent commit + 0.3 s sleep + per-agent event (which made big spawns take minutes and overflowed the WS queue). Pro batch generation is bounded by `SPAWN_CONCURRENCY`.
  - **Simulation rewritten as a coverage-guaranteed phase engine.** "Max rounds" → **activity intensity**: L1 = one post per agent (guaranteed), L2 +1 reaction, L3 +1 debate, L4 +1 reply, then more. Each phase runs every agent concurrently bounded by `SIM_CONCURRENCY_FAST` (48) / `SIM_CONCURRENCY_PRO` (12). An in-memory **status watcher** replaces thousands of per-agent DB status reads; KG-from-post enrichment is **sampled (15%) + concurrency-bounded (6)** so it never saturates the API mid-run.
  - WS subscriber queue raised to 4000; thread/roster/opinion rendering capped for 1000-scale (latest 400 posts, 60 cards/stance, top 150 opinions). New config: `MODEL_PRO_ORCHESTRATION`, `MODEL_PRO_AGENTS`, `SPAWN_CONCURRENCY`, `SIM_CONCURRENCY_FAST`, `SIM_CONCURRENCY_PRO`, `KG_SIM_CONCURRENCY`, `KG_SIM_SAMPLE`. *(Note: live debate posts still require a valid `ANTHROPIC_API_KEY`; the configured key currently returns 401, so the post-generation path could not be verified end-to-end — Fast spawn and the engine's control flow were.)*
- **2026-06-07** — Fixed **large-population spawning**: agent generation is now **batched** (~10 personas/call, run concurrently) so big counts no longer overflow `max_tokens` and truncate the JSON (which caused "Unterminated string" spawn errors). Added a salvage parser (`_parse_agents_json`) that recovers complete agents from partial output, and a clear error if generation fully fails.
- **2026-06-07** — Hardened **report & agent chat**: LLM failures now return a friendly message (HTTP 200) via `friendly_llm_error` instead of a 500; the frontend API client got a 120 s timeout with clear network/timeout errors (no more silent "Failed to fetch"/endless spinner); assistant chat replies now render markdown instead of raw text.
- **2026-06-07** — Fixed **YouTube transcript extraction**: forced the `android` yt-dlp player client (`_with_client`) on all calls because YouTube's default client returned zero captions/formats (transcripts were silently empty); bumped `yt-dlp` to `2025.10.14`.
- **2026-06-07** — Added **Humanity & Coverage** spawn-time controls (§7.7). A coverage% subset of the population now reasons emotionally (gut-driven, low-citation) instead of like experts; sentiment is the primary driver of agent voice; dial generation is pushed for greater diversity; agent cards surface a "% human" badge + dominant-emotion chips. Adds `SpawnedAgent.humanity` (with a non-destructive startup migration) and `humanity`/`humanity_coverage` params on `POST /spawn-agents`.
- **2026-06-07** — Removed the landing hero tagline; hardened KG ingestion (extraction failures now logged, not swallowed) and added `backend/tests/kg_ingestion_test.py`.
- **2026-06-07** — Initial blueprint authored.

---

*End of blueprint. For the precise behavior of any subsystem, the files above are authoritative; this document summarizes them as of 2026-06-10.*
