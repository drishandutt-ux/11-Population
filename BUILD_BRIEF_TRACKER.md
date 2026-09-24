# Build Brief Tracker — 11 Populations

Working document for walking through Matthew Hunt's **11 Populations Build Brief** (10 Sep 2026) one layer at a time.
Requirement IDs are the brief's own and are stable. Status is what the codebase does **today**; Decision is what Drishan has said about it.

Status key: **Have** = in place · **Partial** = exists in a different shape · **Missing** = nothing yet.
Decision key: **Built** · **Deferred** · **Pinned** (future) · **Open** (not discussed yet) · **Answered** (a question was asked and answered, no build decision).

Last updated: 2026-09-24 (L3: L3-01 and the Agent Builder; L3-02 archetypes; L3-03 the cited report; L3-04 dynamic dials — the question's own dials, chosen by the model).

---

## L1 · Data & knowledge layer

| ID | The brief asks for | What we have today | Status | Decision |
|---|---|---|---|---|
| L1-01 | Ingestion for ONS census / mid-year estimates, IMD by LSOA, NHS workforce, ePACT / OpenPrescribing, Statista, More in Common, peer-reviewed literature, client documents | Statistics publishers are scraped page-by-page for facts in the Population Studio (`population/sources.py`, 31 publishers). Uploads and literature enter as text only. No tabular ingestion; IMD and LSOA appear nowhere. | Missing | **Answered** — where the sources live (ONS/Nomis, gov.uk IoD 2019 File 7, NHS England Digital workforce CSVs, OpenPrescribing API, Statista paid, More in Common reports). No build decision. |
| L1-02 | Scheduled / real-time collectors for Google Scholar, paper sites, social feeds, landing in the same store | Research runs once per session on demand (web + Reddit). No Scholar, no scheduling. | Missing | **Deferred** — "not a priority right now, make a note". |
| L1-03 | Knowledge graph over the entities we reason about: geography (nation → region → ICB → LA → LSOA), HCP role/specialty, condition, journey stage, intervention, channel, attitude segment | Typed ontology layer over the session graph, built on demand, shown via a dropdown on the Graph tab (blueprint §9.5). Debate and report do not read it yet. | Partial (built 2026-09-16) | **Built** — commit `e5ba865`. Revert on request. |
| L1-04 | RAG retrieval scoped by project and population so a twin retrieves what its cohort plausibly knows | **Built (step 1, 2026-09-16):** facet-tagged knowledge units, a dimension registry, exposure profiles per twin, versioned policies, a retrieval engine with routes — wired into the debate, Lab and chat; Graph tab → Scoping view (blueprint §9.6). Step 2 (claims instead of chunks) not built. | Partial (built) | **Built** — architecture agreed then implemented as step 1 the same day; the report still reads the shared graph. Earlier: why shared context is a problem (unbelievable personas, agreement as artefact, provenance breaks). **Design note (Drishan's point):** scoping must not wall places off — a Blackpool twin knowing Oxford gets the drug is realistic and the envy/resentment is the analysis. So: a *public layer* per place (what is in that place's public conversation, e.g. local press / Reddit comparisons, seen by every twin there) plus a *scoped layer* by role and place (audit figures, guidelines, commissioning terms for clinicians; counter, transport, cost material for patients). Cross-place comparisons that are not in public discourse are introduced deliberately as a Lab stimulus (decision 4, backfire), not ambiently. No build decision. |
| L1-05 | Provenance class on every claim: official_statistic, peer_reviewed, grey_literature, commissioned_research, client_data, social_signal, model_inference — carried to output | Evidence rows carry `source_class` (web / social / personal / synthetic / quant) + `trust_tier` + `relevance`; every graph chunk has a `[SOURCE …]` header. Nothing at claim level; nothing rendered per figure in the report. | Partial | **Open** — left blank in the L1 pass. |
| L1-06 | Immutable versioned corpus snapshots; a run records the snapshot ID it used | `kg_graphs` is one mutable row per session, overwritten in place. Only Lab probes store seed + model + schema + prompt hash. | Missing | **Wanted.** First step delivered: the data-linkage page (every store, who reads/writes it, the 9 links a run record cannot make). Run-record build is the follow-on. Page: https://claude.ai/code/artifact/452527c1-96f1-43db-b794-b64d7bdaf855 |
| L1-07 | Licence and permitted-use metadata per source; per-client data isolation | No licence field anywhere. Isolation is per user account; "client" and "project" are not concepts. | Missing | **Answered** — what it means (per-source permitted use; a client/project wall above sessions). No build decision. |
| — | Cumulative knowledge: an evidence base per market that compounds across sessions and clients | Graph is per session and dies with it. | Missing | **Pinned** — "we will think about it in future". |

---

## L2 · Population construction

| ID | The brief asks for | What we have today | Status | Decision |
|---|---|---|---|---|
| L2-01 | A sampling frame per geography from L1: real marginals for age, sex, ethnicity, IMD decile, employment, tenure, household, long-term condition prevalence, HCP counts per capita | No frame from real marginals. **Built 2026-09-16:** the *Sampling frame* graph in the Studio — the plan's cells (segments × place / age / gender / income / education / occupation / stance / mood) as a graph whose nodes inflate only with personas, live during a build. | Built (step 1) | **Built 2026-09-16** — the frame: ranked dimensions per question, distributions found from the statistics on file, the ladder (estimate / upload / proxy / skip) for gaps, rings in the graph from the targets (blueprint §7.9). Marginals only; joint reconciled by raking. |
| L2-02 | Quota sampling against those marginals with post-stratification weights; weights appear in aggregation | One agent one vote everywhere. `stats.rake_weights` (IPF) exists but nothing calls it. | Built (step 1) | **Built 2026-09-16** — raking weights per agent to the frame's targets, stored on the agent; the Lab reports the primary metric weighted beside unweighted with the effective n. Survey per-question numbers still unweighted. |
| L2-03 | Population editor: set size, sample to the true frame or deliberately over-sample a cohort, distortion made explicit and corrected in weighting | Studio: accept / edit / reject segments, re-plan, dials. No frame, no over-sampling tracking, no weight correction. | Partial (built) | **Built 2026-09-16** — target vs planned per cell on the frame card (the distortion shown), corrected by weighting at build. An explicit per-segment over-sample toggle is still just editing the share. |
| L2-04 | Populations named, saved, versioned, reusable across questions and projects | Presets: named rosters, reusable. Not versioned, not linked to the session/build/evidence that made them. | Partial | **Keep as is** for now. |
| L2-05 | Representativeness report at construction: achieved vs target marginals, under-filled cells, effective sample size; warn or refuse on unsupportable cuts | Nothing. Lab flags thin buckets (n < 3) at analysis time only. | Built (step 1) | **Built 2026-09-16** — the representativeness report: target vs planned vs achieved per dimension, level, thin cells "not safe to cut by", effective sample size, matched-exactly vs weighted vs unmatched, model-estimated dimensions flagged; stated in the final report. Refuse-on-cut not enforced in the Lab yet (flagged, not blocked). |
| L2-06 | Dyad / network structure linking patient twins to the HCP twins who would treat them | No relations between agents. | Missing | **Liked** — asked how to make it happen; answered with the design (agent-to-agent edges from the plan, treat/knows/lives-near, used in the debate and the Lab). No build decision. |

---

## L3 · Twin instantiation & persona fidelity

| ID | The brief asks for | What we have today | Status | Decision |
|---|---|---|---|---|
| L3-01 | Archetype template library authored to Minds standard, one per HCP role class and patient cohort class (behavioural spec, decision heuristics, vocabulary, information diet, failure modes) | **Agent Builder** (blueprint §7.10, 2026-09-24): an analyst authors one twin by hand — identity, description, place, stance, Expert ↔ Reactive, the five character fields (how they decide / behave / talk, information diet, failure modes) and any subset of the 112 dials, the rest tuned by *Build sentiment profile* — and saves it into a lineup. Archetypes (L3-02) make authored twins reusable moulds the Studio casts from, but there is still no typed *library* per HCP role / patient cohort class authored to a house standard. | Partial | Built (step 1) |
| L3-02 | Twin = archetype template + sampled attribute vector (L2) + retrieved local context (L1); LLM fills texture, does not invent the behavioural model | **Built (step 1, blueprint §7.11, 2026-09-24):** an authored agent ticked *use as an archetype* becomes a mould; the plan matches segments to archetypes by job (chip + picker per segment); at build the facts are drawn from the segment and the sampling frame before the model runs, graph context is retrieved per place, the model writes texture only, and the mould's character and dials (±2) / Expert↔Reactive (±10) are enforced. Segments with no archetype are still model-invented. Context is graph entities, not scoped knowledge units yet. | Partial | Built (step 1) |
| L3-03 | Persistent identity: stable ID, fixed name, immutable attribute record, reloaded verbatim every turn; name collisions blocked | Agents are stored once with a stable ID and fixed name, reloaded every turn; duplicate names/roles repaired at spawn; nothing rewrites a row after build (weights aside), so the attribute record is immutable in practice but not enforced. **Built 2026-09-24:** the report no longer types names — it cites twins by handle, the answer is stored as `[[twin:<id>]]` / `[[twin:<id>\|post:<id>]]` ids, a typed or drifted name is repaired into a citation, and the frontend renders the name from the agent row with a click-through trace card (who they are, where they came from, the line they said). The surname drift is fixed. | Have (mostly) + built | **Built (the narrow fix)** — Drishan chose option 3 (cite by ID, names injected verbatim) over marking it Have or hardening the record. Hardening (a frozen attribute snapshot + hash + override log) still waits on the run record (L1-06 / L5-05). |
| L3-04 | Explicit occupation and character per twin: HCP prescribing fields (formulary constraints, guideline adherence, rep/channel exposure, list deprivation); patient adherence fields (regimen tolerance, health literacy, transport/cost friction, routine stability) | **Dynamic dials, built 2026-09-24** (blueprint §7.2a): the model chooses 6–12 question-specific dials per session — formulary pressure, transport friction, waiting-list fatigue, regimen tolerance … — and every twin carries a 0–10 value on each, tuned like the sentiment dials, shown as a *Dynamic* group under Sentiment in the Builder, the roster and the dial dashboard, and injected into the persona prompt. Plus the free-text `character` record on authored twins. | Built (step 1) | **Built** — Drishan's direction: *not* a typed HCP/patient schema. "We will call them dynamic dials, show below sentiment dials, and they are generic, not just patients and HCPs. LLM will choose the dials and it would be tuned just how sentiment dials are tuned." Still open: making them a Lab cut, and the Fast bank path (no LLM) carries none. |
| L3-05 | Behavioural validation harness from Minds: scored battery per archetype (role knowledge, register, refusal outside knowledge, stability across restatements) | Nothing. | Missing | Open |
| L3-06 | Twins can say "I don't know" and hold minority positions; suppress consensus drift | Humanity bands and stances vary voice; no refusal-outside-knowledge, no unanimity check. | Missing | Open |

---

## L4 · Behavioural dials & calibration

| ID | The brief asks for | What we have today | Status | Decision |
|---|---|---|---|---|
| L4-01 | Dials as per-twin parameters with defaults derived from cohort data; manual override logged as an assumption in the run record | 112 dials per agent, model-chosen. Studio derives *population-level* dials from research and records their basis. No per-twin cohort defaults, no run-record assumption log. | Partial | Open |
| L4-02 | Documented, reviewable calibration mappings from evidence to dial values | None. The survey upload translates responses to dials through a prompt, undocumented. | Missing | Open |
| L4-03 | Auto-adjustment as new data lands (L1-02), drift bounded, every change recorded | Nothing. | Missing | Open |
| L4-04 | Behavioural lab (A/B, purchase and prescribing intent, price/access sensitivity) **gated** behind elasticity calibration | The Lab exists and is live: purchase intent, survey, A/B/n with three designs, choose-between. **Ungated.** | Partial (built, not gated) | Open |
| L4-05 | Sensitivity analysis: re-run with dials at bounds, report dial-driven vs evidence-driven share of the headline | Nothing. | Missing | Open |

---

## L5 · Query & elicitation engine

| ID | The brief asks for | What we have today | Status | Decision |
|---|---|---|---|---|
| L5-01 | Question types: open, closed/scaled, forced choice, allocation, journey-stage transition probability | Survey covers single / multi / scale / yes-no / number / text / grid; choose-between covers forced choice. No allocation, no transition probability. | Partial | Open |
| L5-02 | Independent elicitation by default; deliberation an optional labelled second round | Probes are private and independent. The **report** is synthesised from the debate, which is deliberative. | Partial | Open |
| L5-03 | Weighted aggregation to distributions with dispersion; automatic cuts by region, IMD, cohort, HCP role, any frame attribute | Wilson / bootstrap intervals; segment splits by stance, age band, humanity band, segment, gender, region, income, education. Unweighted. No IMD. | Partial | Open |
| L5-04 | Confidence derived from stated inputs (evidence density, provenance mix, ESS, dispersion, dial sensitivity), not asserted | Report confidence is a HIGH / MEDIUM / LOW line the model writes. Probes carry real intervals. | Missing (report) / Partial (Lab) | Open |
| L5-05 | Seeded and reproducible: population version + corpus snapshot + question + seed in the run record | Only probes/experiments are seeded (seed, model, schema id, prompt hash). Spawn and debate are unseeded; no snapshot, no population version. | Partial | Open |
| L5-06 | Model tiering by task, tier logged: strong model for design / synthesis / adjudication, cheaper for twin responses | Fast / Pro tiers exist; Pulse logs the model per call, outside the product. No task-based policy, no tier in a run record. | Partial | Open |

---

## L6 · Output layer — TPO-native

| ID | The brief asks for | What we have today | Status | Decision |
|---|---|---|---|---|
| L6-01 | TPO as the core record type; narrative rendered from structured data | Report is free-text markdown parsed by section heading in the frontend. | Missing | Open |
| L6-02 | Keep the current report structure (direct answer, question, source materials by role, discussion with dissent, metrics, outcome, caveats), wired to TPO objects | The structure exists. Not wired to anything structured. | Have (structure) | Open |
| L6-03 | Every figure rendered with provenance class and citation; model-inferred numbers visually distinct from official statistics and peer-reviewed findings | Key metrics are plain `Label: Value` lines. | Missing | Open |
| L6-04 | Equity stratification by default: every TPO by IMD decile / quintile as well as headline | No IMD anywhere. | Missing | Open |
| L6-05 | Ranked barrier attribution per TPO gap, traceable to the twins and evidence that produced it | Nothing. | Missing | Open |
| L6-06 | Export: structured TPO data (JSON/CSV), client report, and a delta view comparing two runs | CSV for probes and experiments; report as print-to-PDF. No TPO export, no run delta. | Partial | Open |
| L6-07 | Non-removable synthetic-population statement on every export | Nothing. | Missing | Open |

---

## L7 · Ex-ante decision support (the commercial core)

| ID | The brief asks for | What we have today | Status | Decision |
|---|---|---|---|---|
| L7-01 | Candidate TPO generation: one per journey-stage barrier the panel surfaces | Nothing. | Missing | Open |
| L7-02 | Gap quantification in individuals: TPO estimate × the L2 frame → headcount per stage | Nothing (no frame). | Missing | Open |
| L7-03 | Movability score per gap: reachable by a plausible lever vs structural | Nothing. | Missing | Open |
| L7-04 | Lever simulation (counterfactual runs) with dispersion; refuses to produce a number where no L4-02 mapping exists | Nothing. Scenario branching of the debate is explicitly not built. | Missing | Open |
| L7-05 | Behaviour targeting: rank HCP and patient behaviours by modelled TPO movement per unit of change | Nothing. | Missing | Open |
| L7-06 | Message testing against the panel; shift by cohort; backfire reported as prominently as success; gated on calibration | A/B experiments present framings, measure per-agent shift, and the segment heat-map shows where the effect does not hold. Ungated, unweighted, backfire not first-class. | Partial | Open |
| L7-07 | Portfolio comparison: rank candidate TPOs across populations and therapy areas on gap size, movability, modelled shift, confidence | Nothing. | Missing | Open |
| L7-08 | Commitment record: freeze the modelled baseline (population version, corpus snapshot, estimate, assumptions) when a client selects a TPO | Nothing. | Missing | Open |

---

## §05 · TPO output schema

| Item | The brief asks for | What we have today | Status | Decision |
|---|---|---|---|---|
| Journey-stage template | At risk → aware & seeking → assessed (TPO 1) → initiated (TPO 2) → retained (TPO 3) → outcome achieved; per condition and health system | No journey model. The ontology has a `journey_stage` class, nothing more. | Missing | Open |
| TPO record | id, label, condition (SNOMED/ICD-10), journey_stage, numerator, denominator, health_system, time_horizon, estimate {central, interval, dispersion, basis}, stratification[], barriers[] {attributed_share, evidence_refs, twin_refs, lever}, provenance {corpus_snapshot, population_version, model_tiers, seed, provenance_mix, human_review}, confidence {score, drivers}, caveats[] | No structured record of any kind. | Missing | Open |
| `basis` | simulated \| evidence_anchored \| client_reported — hold a client-supplied stage fixed, simulate the rest | Nothing. | Missing | Open |
| Candidate set | The record must support a portfolio of candidate TPOs, not one at a time | Nothing. | Missing | Open |

---

## §06 · Validation

| Item | The brief asks for | What we have today | Status | Decision |
|---|---|---|---|---|
| Panel back-test | Hold out real responses from the 2,000-person UK panel, build a matched synthetic population, report agreement per item | Nothing. | Missing | Open |
| Known-answer tests | Published statistics absent from the corpus snapshot, to measure calibration | Nothing. | Missing | Open |
| Calibration report | Per population version, shipped with the population | Nothing. | Missing | Open |
| Composition sensitivity | Re-sample under the same quotas; large movement → sampling artefact, and the run says so | Nothing. `stats.test_retest` exists as a utility. | Missing | Open |
| Adversarial checks | Leading-question sensitivity, order effects, a deliberate unanimity check | Nothing. | Missing | Open |
| Human review gate | No client-facing output without a named health-domain reviewer in `provenance.human_review` | Nothing. | Missing | Open |

---

## §07 · Non-functionals

| Item | The brief asks for | What we have today | Status | Decision |
|---|---|---|---|---|
| Project workspace | Project owns corpus subset, populations, questions, runs, reviewers | Unit of work is a session owned by a user. No project, no client. | Missing | Open |
| Reproducibility | Reproduce a number exactly six months later, then show what changes with current evidence | Only Lab probes are reproducible. | Partial | Open |
| Cost & latency envelope | Published per run at n = 100 / 500 / 1,000 under L5-06 tiering | Per-probe cost estimate only. | Partial | Open |
| Client data isolation & licence compliance | Especially for scraped social content | Per-user isolation only; no licence data. (See L1-07.) | Missing | Open |
| Real-person resemblance guardrails | Generated names and biographies must not converge on identifiable individuals, especially named HCPs and KOLs | Nothing. | Missing | Open |
| Audit log | Population edits, dial overrides, corpus changes, human review actions | Studio keeps a build log; nothing else. | Partial | Open |

---

## §08 · Phasing (the brief's order)

| Phase | Items | Unlocks |
|---|---|---|
| P1 Credibility | L3-03, L1-05 / L6-03, L5-02 / L5-03, L5-04, L5-05 | Output stops being challengeable on inspection |
| P2 Composition | L2-01 / 02, L2-03 / 04, L2-05, L3-01 / 02 / 05 | Audience crafting before the query |
| P3 Measurement & screening | L6-01, L6-04, L6-05, L6-06, client-anchored stages, L7-01, L7-02, L7-03, L7-07, L7-08 | Decisions 1 and 2 |
| P4 Calibration | §06, L4-01 / 02, L1-02, L2-06 | Defensible accuracy claim; hard gate on P5 |
| P5 Intervention | L7-04, L7-05, L7-06, L4-04, L4-05 | Decisions 3 and 4 |

---

## §09 · Decisions the brief needs from us

| # | Question | What the codebase says | Our position |
|---|---|---|---|
| 1 | Is the knowledge graph real or aspirational? | Per-session, document-level, free-text entities. The typed ontology now exists as a view; no cross-session graph. | L1-03 is a build; phasing shifts as the brief anticipates. |
| 2 | Where does the sampling frame come from? IPF over ONS marginals, or licensed microdata? | Nothing exists. `rake_weights` (IPF) is present and unused. | Open |
| 3 | How many archetype templates before a client project? | None exist. | Open |
| 4 | Does the consumer-research upload survive as-is? | Exists, Pro-only, "mirror the panel" gives one agent per respondent; translates responses to dials by prompt with no documented mapping. | Open — becomes L4-02 path or gets rebuilt against the frame. |
| 5 | Which stages can we estimate? Twin responses alone, or anchored to observed base rates? | Nothing computes a transition percentage; probes yield stated intent and attitude. | Brief assumes anchored. Open. |
| 6 | Panel size and cost at quality? | Up to 1,000 agents; no ESS or stability analysis. | Open |
| 7 | Social scraping under what licence? | Reddit read through a headless browser without auth; no licence position recorded. | Open |
| 8 | How to score movability without inventing it? | Nothing. | Brief leans to an authored lever-to-barrier mapping library. Open. |
| 9 | Counterfactual runs: re-simulate or re-weight? | Nothing. | Must be decided before P3 fixes the schema. Open. |

---

## Log

- **2026-09-16** — L1 walked through. L1-01 / L1-04 / L1-07 answered; L1-02 deferred; L1-03 built (ontology view, commit `e5ba865`); L1-06 linkage page published; cumulative knowledge pinned; L1-05 left open. Tracker created.
- **2026-09-16** — L1-04 scoping architecture agreed (generic: facets on knowledge, exposure profiles on twins, stacked policies, routes) and built as step 1 with a Scoping view for manual testing.
- **2026-09-16** — L2 walked through. First: the Population Studio became the Agents screen and the old quick-spawn form was deleted. L2-01 sampling-frame graph built; L2-02 / L2-03 / L2-06 answered; L2-04 kept as is; L2-05 explained.
- **2026-09-16** — L2 direction agreed (frame from researched distributions; flag gaps → upload / model estimate, all labelled) and built as step 1: L2-01, L2-02, L2-03, L2-05. L2-06 remains the design only.
- **2026-09-16** — Closed the loop on Drishan's idea: the frame's ranked dimensions now drive the statistics search (find first, flag only what the web doesn't have), with a TAM / SAM / SOM sizing trio read from the material and shown on the frame card.
- **2026-09-16** — Drishan: cell sizes must be persona counts and cells must be dynamic per question. Done: the frame's dimensions are the cells, segments and personas carry a value per dimension, the graph legend counts cells and personas.
- **2026-09-16** — Drishan reset the graph's purpose: a population map — final cells with persona counts, cell types chosen per question and ranked, 5–15 shown. Built (`facets.py`, `plan.facets`, persona-level facet labels, graph rewritten). The half-built 'real-data coverage' additions were reverted at his request.
- **2026-09-24** — L3 opened. L3-01 explained (authored archetype library, five parts, the L3-02 dependency, the content cost). Drishan's direction instead of a library first: a **Build your own agent** page in the Agents section — form + dial interface, dials by hand or left to the system, *Build sentiment profile* from the text, and the agent must join a lineup (new or existing). Built (blueprint §7.10): `agents/builder` route, `agent_builder.py`, `POST /presets/custom`, `POST /presets/{id}/agents`, `spawned_agents.character` (Alembic `0010_character`) injected into the persona prompt. L3-01 → Partial / Built (step 1); L3-04 → Partial.
- **2026-09-24** — L3-02 explained twice (the second time as the bridge between the two persona factories: Build your own authors the moulds, the Studio decides how many and where and casts them). Drishan: build it, keep lineups and multi-agent authoring intact. Built (blueprint §7.11): `Archetype` table + `/archetypes`, `as_archetype` on lineup saves (tick in the Builder, on by default), job-based matching at plan time with a chip + picker per segment, attributes sampled from the segment and frame before the model runs, per-place graph context, texture-only cast prompt, enforced drift bounds, roster chip. Found in the stub run: a batch whose slot numbers restart at 1 was dropped — fixed with order fallback. L3-02 → Partial / Built (step 1).
- **2026-09-24** — L3-03 reviewed: identity is already stable and collisions are repaired; the only real gap was the report paraphrasing names. Drishan picked the narrow fix and added the wider requirement — *set ourselves up for backtracking: who said what, and who he was*. Built (blueprint §11): `services/simulation/citations.py` (handles → stable-id citations, dangling handles dropped, typed/drifted names repaired, possessives kept), the report call rebuilt around handled roster + transcript lines, the roster line carrying each twin's origin, and a frontend trace card on every citation (identity, origin, frame weight, the verbatim line, *Talk to this twin*). Verified end to end against a stub: 9 citations rendered, no raw tokens, a deliberately drifted surname repaired. Tests: `citations_test.py` (15). Next in L3: **L3-04** (typed HCP / patient fields).
- **2026-09-24** — L3-04 put to Drishan as typed HCP / patient fields; he replaced the idea with a better one: **dynamic dials** — generic, not clinical, chosen by the model for the question, shown under the sentiment dials and tuned the same way. Built (blueprint §7.2a): `agents/dynamic_dials.py`, `analysis_sessions.dynamic_dials` (Alembic `0012`), picked and logged at Studio plan time, stated in every persona prompt (plan / quick-spawn / cast), stored in `dials["dynamic"]`, clamped to an archetype's priors, injected into the debate, chat and probe prompts, and rendered as a *Dynamic* group in the Builder, the roster and the dial dashboard. Verified end to end against a stub: 6 dials chosen, per-persona values written, a hand-set value surviving the lineup save. Tests: `dynamic_dials_test.py` (11). Next in L3: **L3-05** (behavioural validation harness) and **L3-06** ("I don't know" and minority positions).
