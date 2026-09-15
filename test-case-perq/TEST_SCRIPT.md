# End-to-end test case: "Perq" AI employee incentive platform

One scenario that exercises every subsystem: auto-research, all four ingest
paths, Fast spawn, Pro spawn with a mirrored survey panel, the Population
Studio, the phase-engine simulation, verdicts, the knowledge graph, the
report + chats, the Behaviour Lab (probe, survey, A/B experiment), presets,
and the dial dashboard.

Unlike the Loop case (one product, one price), Perq is a **two-sided,
five-feature bundle** — employer pays, employee uses — so this case is the
better stress test of whether the population can hold a *composite* product
in its head and argue about its parts.

**Session query (paste at creation):**

> Would London employees actually use "Perq" — an employer-paid perks app
> (£10 per employee/month) with a live map of nearby deals, end-of-day
> surplus food and unsold event seats at up to 80% off (£3.99/month add-on),
> AI + human concierge, and tradeable surprise rewards — often enough to
> justify the spend to HR?

**Title:** `Perq £10 pepm — employee perks adoption & feature demand`

The topic is deliberately real: auto-research will find genuine material on
Perkbox/Ben pricing and activation, Too Good To Go, TodayTix Rush and unsold
West End inventory, and concierge services; Reddit has live chatter
(r/UKJobs, r/AskUK, r/london, r/humanresources) about perks-vs-pay, so the
research loop, the social judge, and the evidence brief all get real
material to chew on.

Files in this folder:

| File | Used in |
|---|---|
| `01-product-brief.md` | Ingest → Document upload (or paste as Text) |
| `02-market-stats.md` | Ingest → paste as Text |
| `03-pilot-feedback.md` | Ingest → Document upload |
| `survey-panel.csv` | Agents tab → survey upload (Pro, Mirror the panel) |
| `audience-profile.txt` | Agents tab → audience profile box |

---

## Phase 0 — preflight

- `GET /health` returns ok; `ANTHROPIC_API_KEY` set (without it: empty graph,
  no posts, no errors — the classic silent failure).
- If testing prod: **do not push to main mid-test** — a Railway deploy kills
  in-flight research runs, spawns, and simulations.

## Phase 1 — session + auto-research

1. Create the session with **auto-research ON**.
2. Watch the Research tab: frame appears (sub-questions should mention perks
   platform usage/activation, per-employee pricing, surplus food apps,
   unsold ticket inventory, and location privacy), queries stream with
   engine names, Reddit items land with relevance scores (expect perks-vs-
   salary threads), off-topic items show greyed not hidden.
3. **Regression check (Stop semantics):** press **Stop** mid-gather once.
   Status must go `stopping → finalising → stopped` within seconds, and a
   brief + recommendations must still be produced. A second press must
   hard-cancel, never no-op.
4. Verify the **Evidence brief** card shows stakeholder groups with stances —
   expect at least *employees*, *employers/HR*, and ideally *venues/merchants*
   (the supply side; a good composite-topic check) — and the **Recommended
   tools** card suggests purchase intent / price sensitivity.

## Phase 2 — ingest all four source types

1. **Text:** paste `02-market-stats.md`. Watch `kg_updated` events grow the
   Graph tab live; entities like *Perkbox*, *Too Good To Go*, *West End*,
   *per-employee pricing*, *activation* should appear.
2. **Document:** upload `01-product-brief.md` and `03-pilot-feedback.md`.
3. **YouTube:** any short review of a perks/benefits app or a "Too Good To Go
   haul" video (keep it <10 min; expect 1–3 min processing — transcript,
   thumbnail Vision, 5 frames, comments).
4. **LLM Search:** generate a synthetic paper (e.g. on gamified rewards and
   workplace fairness), check the preview step, ingest it, and later confirm
   the Graph/agents don't treat it as evidence (chunked with the
   `[SOURCE synthetic … a prior, NOT evidence]` header).
5. Status should end `ready`. Graph tab: click the *Too Good To Go* node —
   relations and source mentions must list the actual chunks.

## Phase 3 — populations (three ways)

**3a. Fast spawn (sanity + humanity dials).** 60 agents, stance 30/30/40,
Humanity 65 / Coverage 50, intensity 3. Spawn is near-instant. Check: band
chip reads *Defensive*, preview says "≈ 30 of 60", humanized cards show the
"% human" badge and emotion chips. Save as preset `perq-fast-60`.

**3b. Pro spawn with the mirrored panel.** Re-spawn: mode Pro, upload
`survey-panel.csv`, confirm **Mirror the panel** is on, paste
`audience-profile.txt` into the audience profile. Count 14.
Check: exactly one agent per respondent — an Ayesha-like map deal-maximiser,
a Rob-like pay-not-perks cynic, a Tunde-like privacy-blocked engineer, a
Grace-like HR buyer whose stance is *conditional on activation numbers*
(the interesting one — she is neither for nor against the product, she is
for a metric); stances derived from the panel, not the sliders. Rob's dials
should show high friction/objection; Ayesha's high purchase intent. (Fast
mode must *warn* that the upload is ignored — check that too.)

**3c. Population Studio (the deep path).** From the Agents tab open the
Studio. Target 80, mode Fast.
- **Detect** must read the brief + docs and propose dials *from research*
  (chips visible); geography should come back London, and the detected
  population should be *employees*, not employers (the docs mention both —
  a good detector disambiguation check).
- **Gather:** leave ON, tick ONS + YouGov + gov.uk. Facts with real numbers
  (commuting, food waste, subscription holding) should land as `quant`
  evidence and stream to the Ingest feed.
- **Clarify:** answer at least one question (e.g. "employees at companies
  that already bought Perq, or the general workforce?" — answer: employer
  has bought it), skip the rest.
- **Plan:** expect 4–7 segments resembling: map-driven deal-maximisers,
  surplus-driven shift workers, privacy-wary tech workers, pay-not-perks
  cynics, status/lounge traditionalists, left-out remote workers.
  **Registers must vary** — the cynics and shift workers should NOT come
  back `expert`; expect tempered/defensive/reactive on the emotional ones.
- **Review:** edit one segment's share (others rescale), reject one with a
  reason (e.g. "too generic — split by shift pattern"; it regenerates
  addressing the reason), change one register.
- **Approve & build:** agents stream in batches per segment, cards carry
  segment + demographics badges.
- **Regression check:** press **Stop** during the build once — personas
  already written must be kept and the log must say "stopped early: N of M".

## Phase 4 — simulation

Run at **intensity 3** on the Studio population (mode Fast).
- Every agent must post at least one comment (phase engine guarantee) —
  80 agents → ≥80 top-level comments, plus likes and debates.
- Voices must differ by register: reactive agents post 1–2 raw sentences, no
  citations ("just pay me the tenner"); experts cite the activation stats.
  **Nobody may say "the knowledge graph" or "the evidence provided" in a
  post.**
- Feature-level debate check (specific to this case): the thread should
  argue about *parts* of the bundle, not just the whole — expect surplus
  food praised by shift workers, the map's privacy attacked, Drops-fairness
  arguments between winners and non-winners. If every post reviews "the app"
  monolithically, the composite framing didn't survive spawning.
- Post lengths should visibly vary (per-post length draw).
- Pause → posts stop within ~1s → Resume → they continue. Then let it finish.
- Verdict sidebar: one-line verdicts fill in batches once everyone has
  posted; none stuck on "summarising…"; Refresh works.
- Graph tab during the run: nodes keep appearing (≤120 agents = every post
  feeds the graph).

## Phase 5 — report

1. Generate the report. Check the structure lands: teal Direct Answer +
   confidence badge, KPI grid, Outcome. The answer should engage with the
   £10 pepm price *and* discriminate between features (which drive
   activation, which are dead weight), and name specific agents.
2. **Ask Report:** "If we could ship only two of the five features at
   launch, which two, and which segment do we lose with each cut?" — expect
   named agents, the activation stats, and the shift-worker/surplus link.
3. **Talk to Agent:** pick the most hostile pay-not-perks cynic and ask what,
   if anything, an employer perks app could offer that beats £120/year in
   salary. Markdown must render.
4. Save as PDF — white print stylesheet, no dark-theme bleed.

## Phase 6 — Behaviour Lab

1. **Purchase intent probe** on all agents. Stimulus: the **Perq Surplus
   add-on** — £3.99/month of the employee's own money for end-of-day
   surplus at 70–90% off plus last-minute event seats at up to 80% off,
   cancel anytime. Price £3.99, GBP. (Deliberately the employee-paid part:
   it's the only clean consumer purchase in the bundle.)
   Check: cost estimate shows the *resolved model id*; live dots fill;
   results show buy-share with Wilson CI, driver mix (expect price/value and
   "another subscription" fatigue to dominate, with food-waste feel-good as
   a secondary), **demand curve** with revenue-optimal price (interesting vs
   £3.99 — the panel's stated ceilings run £2–6), and the contradiction
   count.
2. **Survey** from the *Concept test* template, 4–5 questions, one primary
   scale question ("How likely are you to open Perq in a typical week?"),
   plus a feature-ranking question across the five features; run on 40
   agents. Check per-type charts and click-through to the personas behind a
   bar.
3. **A/B experiment (within-subjects / Rate each)**, purchase intent base:
   - A (control): monthly Drops you **keep** — a random big reward lands,
     it's yours.
   - B: monthly Drops that are **tradeable on the Perq marketplace** — swap
     what you won for what you want.
   The direction is genuinely uncertain (trading adds utility but invites
   gambling/fairness objections) — that's the point. Expect a flow diagram
   of flippers with both reasonings and a quotable verdict sentence. Live
   view: agent pills split per arm, movers ringed in amber.
4. **Choose between** with 3 message framings, e.g.
   A "Your city, on the house." / B "Never pay full price after 5pm again." /
   C "The perk that actually gets used." — preference race with intervals,
   winner settled or not, per-option themes. (C is the HR-facing line — if
   the *employee* population picks it, the go-to-market messaging is
   inverted; worth flagging in the report chat.)
5. Reproducibility: re-run the probe with the same seed — same agent sample.

## Phase 7 — analytics & persistence

- `GET /sessions/{id}/dials` (or the dashboard UI): scorecard order correct,
  friction/churn inverted ("lower is better" reads green), stance × scorecard
  heatmap populated, and Lab segment splits offer `segment`/`gender`/`region`
  (Studio demographics flowing through).
- Load preset `perq-fast-60` into a **new** session — agents restore with
  dials, humanity, and (if saved from Studio) segment/demographics.
- Reload the session page mid-simulation: state must rebuild from REST + the
  8s poll (no blank tabs).

## What "great insights" look like from this run

Beyond the mechanical checks, the run has succeeded as *research* if the
report can answer these with named agents and numbers:

1. A predicted sustained monthly-activation band, and whether it clears
   Grace/Raj's ~40% bar (the entire B2B case).
2. A feature kill-list: which of the five features no segment would miss.
3. The Surplus add-on's revenue-optimal price vs £3.99, and the attach-rate
   ceiling given "another subscription" fatigue.
4. Whether tradeable Drops net-help or net-harm — and the fairness design
   fix the non-winners ask for.
5. The privacy fix that flips the Tunde segment (on-device processing +
   plain-language promise) and how much adoption it buys.

## Known-issue traps (don't misfile these as new bugs)

- No cascade deletes: deleting a session orphans agents/posts locally
  (Postgres has FKs; SQLite doesn't).
- Local dev without `ANTHROPIC_API_KEY` fails silently — empty graph, no posts.
- Reddit 403s over plain HTTP are expected; the Chromium fallback handles it.
- Statista teaser facts without numbers are dropped by design.
