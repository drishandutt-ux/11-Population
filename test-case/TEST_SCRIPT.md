# End-to-end test case: "Loop" e-bike subscription

One scenario that exercises every subsystem: auto-research, all four ingest
paths, Fast spawn, Pro spawn with a mirrored survey panel, the Population
Studio, the phase-engine simulation, verdicts, the knowledge graph, the
report + chats, the Behaviour Lab (probe, survey, A/B experiment), presets,
and the dial dashboard.

**Session query (paste at creation):**

> Would London commuters switch to a £65/month e-bike subscription (theft
> cover and 24-hour swap included) instead of paying for TfL or driving?

**Title:** `Loop £65/month — London commuter adoption`

The topic is deliberately real: auto-research will find genuine TfL fare,
e-bike, and bike-theft coverage, and Reddit has live chatter (r/london,
r/londoncycling, r/ukbike), so the research loop, the social judge, and the
evidence brief all get real material to chew on.

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
2. Watch the Research tab: frame appears (sub-questions should mention fares,
   theft, e-bikes, commuting), queries stream with engine names, Reddit items
   land with relevance scores, off-topic items show greyed not hidden.
3. **Regression check (Stop semantics, 2026-09-15 work):** press **Stop**
   mid-gather once. Status must go `stopping → finalising → stopped` within
   seconds, and a brief + recommendations must still be produced from what
   was gathered. If it lingers in `stopping`, press Stop again — that must
   hard-cancel, never no-op.
4. Verify the **Evidence brief** card shows stakeholder groups with stances
   and the **Recommended tools** card suggests purchase intent / price
   sensitivity (this topic should trigger both).

## Phase 2 — ingest all four source types

1. **Text:** paste `02-market-stats.md`. Watch `kg_updated` events grow the
   Graph tab live; entities like *TfL*, *Swapfiets*, *e-bike theft*,
   *travelcard* should appear.
2. **Document:** upload `01-product-brief.md` and `03-pilot-feedback.md`.
3. **YouTube:** any short e-bike commuting review, e.g. a "commuting by e-bike
   in London" video (keep it <10 min; expect 1–3 min processing — transcript,
   thumbnail Vision, 5 frames, comments).
4. **LLM Search:** generate a synthetic paper, check the preview step, ingest
   it, and later confirm the Graph/agents don't treat it as evidence (it is
   chunked with the `[SOURCE synthetic … a prior, NOT evidence]` header).
5. Status should end `ready`. Graph tab: click the *TfL* node — relations and
   source mentions must list the actual chunks.

## Phase 3 — populations (three ways)

**3a. Fast spawn (sanity + humanity dials).** 60 agents, stance 30/30/40,
Humanity 65 / Coverage 50, intensity 3. Spawn is near-instant. Check: band
chip reads *Defensive*, preview says "≈ 30 of 60", humanized cards show the
"% human" badge and emotion chips. Save as preset `loop-fast-60`.

**3b. Pro spawn with the mirrored panel.** Re-spawn: mode Pro, upload
`survey-panel.csv`, confirm **Mirror the panel** is on, paste
`audience-profile.txt` into the audience profile. Count 14.
Check: exactly one agent per respondent — a Priya-like enthusiast, a Dan-like
ownership sceptic, a Helen-like safety-anxious retiree; stances derived from
the panel, not the sliders. Dan's dials should show high friction/objection;
Priya's high purchase intent. (Fast mode must *warn* that the upload is
ignored — check that too.)

**3c. Population Studio (the deep path).** From the Agents tab open the
Studio. Target 80, mode Fast.
- **Detect** must read the brief + docs and propose dials *from research*
  (chips visible); geography should come back London.
- **Gather:** leave ON, tick ONS + YouGov + gov.uk. Facts with real numbers
  should land as `quant` evidence and stream to the Ingest feed.
- **Clarify:** answer at least one question, skip the rest.
- **Plan:** expect 4–7 segments resembling: TfL-cost-refugees, theft-anxious
  lapsed cyclists, ownership sceptics, safety-fearful older riders, car
  loyalists, couriers/heavy users. **Registers must vary** — consumer
  segments should NOT all be `expert`; expect tempered/defensive/reactive on
  the emotional ones (2026-09-15 register work).
- **Review:** edit one segment's share (others rescale), reject one with a
  reason (it regenerates addressing the reason), change one register.
- **Approve & build:** agents stream in batches per segment, cards carry
  segment + demographics badges.
- **Regression check:** press **Stop** during the build once — personas
  already written must be kept and the log must say "stopped early: N of M".

## Phase 4 — simulation

Run at **intensity 3** on the Studio population (mode Fast).
- Every agent must post at least one comment (phase engine guarantee) —
  80 agents → ≥80 top-level comments, plus likes and debates.
- Voices must differ by register: reactive agents post 1–2 raw sentences, no
  citations; experts cite the stats. **Nobody may say "the knowledge graph"
  or "the evidence provided" in a post** (2026-09-15 fix).
- Post lengths should visibly vary (per-post length draw).
- Pause → posts stop within ~1s → Resume → they continue. Then let it finish.
- Verdict sidebar: one-line verdicts fill in batches once everyone has
  posted; none stuck on "summarising…" (the old truncation bug); Refresh
  works.
- Graph tab during the run: nodes keep appearing (≤120 agents = every post
  feeds the graph).

## Phase 5 — report

1. Generate the report. Check the structure lands: teal Direct Answer +
   confidence badge, KPI grid, Outcome. The answer should engage with the
   £65 price point and name specific agents.
2. **Ask Report:** "Which segment is most likely to churn in the first 90
   days and why?" — expect named agents and the Buzzbike churn stat.
3. **Talk to Agent:** pick the most hostile ownership sceptic and ask what
   price, if any, would convert them. Markdown must render.
4. Save as PDF — white print stylesheet, no dark-theme bleed.

## Phase 6 — Behaviour Lab

1. **Purchase intent probe** on all agents. Stimulus: the Loop offer
   (£65/month, theft cover, 24h swap, cancel 30 days). Price £65, GBP.
   Check: cost estimate shows the *resolved model id*; live dots fill; results
   show buy-share with Wilson CI, driver mix (expect theft/trust and price to
   dominate), **demand curve** with revenue-optimal price (interesting vs
   £65), and the contradiction count.
2. **Survey** from the *Concept test* template, 4–5 questions, one primary
   scale question; run on 40 agents. Check per-type charts and click-through
   to the personas behind a bar.
3. **A/B experiment (within-subjects / Rate each)**, purchase intent base:
   - A (control): £65/month standard.
   - B: **£39/month for the first 3 months, then £65** (same product).
   Expect a positive, likely significant lift on would-buy, a flow diagram of
   flippers with both reasonings, and a quotable verdict sentence. Live view:
   agent pills split per arm, movers ringed in amber.
4. **Choose between** with 3 message framings, e.g.
   A "Your bike, our problem." / B "Commute for £2.16 a day." /
   C "Never buy a bike again." — preference race with intervals, winner
   settled or not, per-option themes.
5. Reproducibility: re-run the probe with the same seed — same agent sample.

## Phase 7 — analytics & persistence

- `GET /sessions/{id}/dials` (or the dashboard UI): scorecard order correct,
  friction/churn inverted ("lower is better" reads green), stance × scorecard
  heatmap populated, and Lab segment splits offer `segment`/`gender`/`region`
  (Studio demographics flowing through).
- Load preset `loop-fast-60` into a **new** session — agents restore with
  dials, humanity, and (if saved from Studio) segment/demographics.
- Reload the session page mid-simulation: state must rebuild from REST + the
  8s poll (no blank tabs).

## Known-issue traps (don't misfile these as new bugs)

- No cascade deletes: deleting a session orphans agents/posts locally
  (Postgres has FKs; SQLite doesn't).
- Local dev without `ANTHROPIC_API_KEY` fails silently — empty graph, no posts.
- Reddit 403s over plain HTTP are expected; the Chromium fallback handles it.
- Statista teaser facts without numbers are dropped by design.
