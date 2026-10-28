# SimBench diagnostics — what the first benchmark runs tell us (2026-10-28)

Written after a day of runs on SimBench grouped (arXiv 2510.17516): how our twins score against
real survey answers, what in the pipeline works, what does not, and what to build to make the
tool measurably the most accurate synthetic population in the business. Plain words first;
code names in brackets for whoever builds the fix.

Related: `PRODUCT_BLUEPRINT.md` §7.8 (the persona writer), §11a.9 (the benchmark runner and its
Studio arm), `docs/FUTURE_UPGRADES.md` §9 (the benchmark build order).

---

## 1. How to read the numbers

**The score.** Each case is a real survey subgroup (e.g. *Great Britain, 2017–2020, no
religion*), one question and the share of real people who chose each answer. We produce our own
shares; the score says how close we came: **100 = exactly the real answer, 0 = no better than
an even split, below 0 = worse than guessing.** A run's score is the average over its cases.

**Two columns on every case.**
- **Twins** — our product: the population the tool builds, each twin answering the question
  through Forms; their answers are pooled into one set of shares.
- **Model alone** — the same AI model with none of our product around it, asked in one prompt
  to guess the group's shares (the benchmark authors' own prompt).

The difference between the two is the only thing that measures our product. Comparing our
number with the published leaderboard is not fair unless the cases are the same mix (§4).

---

## 2. The runs

| Run | Where | Model | What built the twins | Groups | Cases | Twins | Model alone | Spend |
|---|---|---|---|---|---|---|---|---|
| Plain-twins pilot (`ac5d7995`, stopped) | local | Haiku | persona writer only, one block of 60 per group | 9 | 26 | **36.0** ±7.4 | **33.2** ±8.0 | $13.87 |
| Full-Studio arm | local | gpt-4.1-mini (through a scratch shim; the Claude key was at its monthly cap) | research → knowledge graph → Studio plan → spawn, 60 per group | 10 | 32 | **33.7** ±6.8 | **32.9** ±7.7 | $7.08 |
| Full-Studio arm, UK (`e47192cf`, stopped) | **prod** | Haiku | the same, on Railway with Claude web search; 40 per group | 3 (1 more failed) | 8 | **49.2** | **48.3** | $18.25 |

Published reference points (the paper's averages over thousands of cases, all five surveys):
Claude 3.7 Sonnet 40.8, GPT-4.1 34.6, DeepSeek-R1 34.5.

**Reading.** In all three runs the twins come out 1–3 points ahead of the model alone, and in
all three that gap is smaller than the noise (±5–8 points). **Our product has not yet shown a
measurable accuracy advantage over the model it runs on.** The UK prod run's 49 is not a
leaderboard result: the model alone scored 48 on the same eight cases — UK cases are easy for
these models.

How many cases a real answer needs: at today's spread, telling apart a 3-point gap takes about
300–350 cases.

### The prod UK run, case by case

| UK group | Case | Twins | Model alone |
|---|---|---|---|
| Great Britain, never married | 4260 | 72.2 | 64.8 |
| | 4312 | 56.6 | 75.4 |
| | 4397 | 75.1 | 80.6 |
| Great Britain, no religion | 4251 | 70.6 | 71.4 |
| | 4306 | 44.6 | 29.8 |
| | 4387 | 50.4 | 28.4 |
| UK 2016, retired (35 twins of 40, see §5.4) | 1901 | 2.6 | 43.1 |
| | 2460 | 21.3 | −7.0 |
| UK 2016, never married | — | failed: no twins (§5.4) | — |

---

## 3. The central finding: the twins echo the model

The distance between two sets of answer shares (0 = identical; the benchmark's own measure):

| | Prod UK (8 cases) | Haiku pilot (26 cases) |
|---|---|---|
| Twins ↔ model alone | **0.10** | **0.18** |
| Twins ↔ real people | 0.17 | 0.22 |
| Model alone ↔ real people | 0.18 | 0.21 |
| Twins' top answer = real people's top answer | 5 of 8 | 14 of 26 |
| Model alone's top answer = real people's | 7 of 8 | 18 of 26 |

Case 4251 shows it plainly: twins 2 / 5 / 7 / 26 / 59 / 0 %, model alone 2 / 5 / 8 / 25 / 58 / 2 %.

**What it means.** The twins' pooled answer sits much closer to what the model thinks on its
own than to what real people said. Everything the pipeline adds — research, the Studio plan,
segments, standing, the 112 dials — changes *who* the twins are, but their *opinions* still come
from the model's general idea of what such a person thinks. That is why accuracy barely moves,
and why the twins lose a little on the most popular answer: they add variety, but not variety
that comes from data.

**Anti-slop is not accuracy.** The guardrails (scoping, standing, the honest *don't know*,
refusals counted — zero today) stop twins inventing what they could not know. They do not make a
twin's opinion match the real distribution. That is a separate problem, and it is the one that
decides who is most accurate.

---

## 4. What works — keep it

1. **We can prove accuracy.** The benchmark runner scores the whole product against real survey
   answers, beside the model alone, with a hard budget (`simbench.py`, arm `studio`,
   `budget_usd`). Few tools in this market can show error bars at all.
2. **Research on prod is strong.** 45–63 evidence items per group with Claude web search,
   against 1–6 useful pages on the keyless engines locally. The survey is never named in the
   research question; 3 of ~167 sources came from survey-publisher sites (logged per group as
   `publisher_sources`).
3. **Studio plans are realistic.** e.g. Brazil Catholics split into devout urban faithful,
   middle-class families and lower-income families; UK groups into believable segments.
4. **The persona writer is robust now** (all 2026-10-28): batches of six under a 16k cap,
   top-ups for anything missing, duplicate repairs in batches of six, a batch held to the count
   asked, bare quotes repaired (`repair_inner_quotes`), and a log line that says why a batch
   came back short (`parse_report`).
5. **Cost control.** Model tiers, the Studio's Stop (*plan with what is on file*), the hard
   budget stop.

---

## 5. What does not work yet

### 5.1 Opinions come from the model, not from data
§3. The single biggest gap.

### 5.2 Research brings facts, not attitudes
Sixty sources per group about life in the UK did not move the answers. Research is good at
statistics and reports; a twin's *view* on a question is still the model's guess.

### 5.3 The 112 dials are written by the model, not calibrated
They are set when the persona is written and nothing ties them to measured attitude
distributions; they did not visibly change what twins picked.

### 5.4 Variety collapses towards stereotypes; messy output loses people
- 4–17 look-alike twins per 60 (same job at a similar age) when six batches are written side by
  side — the model reaches for the same obvious people.
- Haiku writes nicknames in bare quotes (`"Margaret "Maggie" Aitken"`), which broke the JSON:
  one UK group lost every twin and failed, another kept 35 of 40, and it explains the morning's
  2-of-6 batches. Fixed in `550df5e` (not yet pushed at the time of writing).
- gpt-4.1-mini wrote more people than asked (70 for 60). Fixed (`c929193`).

### 5.5 The Studio's statistics step: UK-only, slow and expensive
- Every statistics publisher in the registry is British: for Brazil, Nigeria, Japan … it
  searched ONS, NISRA, YouGov and found nothing (~20 minutes wasted per group).
- On prod it ran about 150 Claude web searches in 4 minutes for two groups — about **$1 a
  minute** (a search costs ~$0.024 from the ledger). It was cut by hand after 3–5 minutes.
- It re-fetches the same national figures (UK population by age, by region) for every session.

### 5.6 Research reads PDFs at full price
19 PDF reads cost $1.30 of the first $2.37; PDFs over 100 pages fail outright (Claude's limit).

### 5.7 Stop leaves a tail
A stopped research run still writes its brief and tags its sources for scoping (ontology, lay
layer): ~$0.30 after the stop. The budget stop does not reach it.

### 5.8 No settled way to pool answers
Twins give a chance per option (*likelihood*) and a realised pick (*picks*). Picks scored better
locally (37.5 v 33.7), the chances better on prod (49.2 v 43.8). Needs a larger run to decide.

### 5.9 Cost per group
About $6 per UK group on prod (2–3 cases each): research ~$1.5–2, statistics ~$2–4 before the
cut, twins + answers ~$1. A 1,000-case reading would cost well over $1,000 at this rate.

---

## 6. What to build — ranked by expected effect on accuracy

1. **Twins whose answers come from their own data, not the model's opinion.** Start each twin
   from a real anonymised survey respondent's answers (ESS, British Social Attitudes,
   Understanding Society, or the client's own uploaded survey), then let the model write the life
   around those fixed answers; make the answer to a question follow the twin's recorded positions
   wherever they bear on it. Population kits and *Mirror the panel* already do part of this; it
   should become the core. For benchmarking, hold the tested survey and wave out so nothing leaks.
   Check the data licences first (ESS: free with registration; BSA and Understanding Society via
   the UK Data Service). See §7 for the first step.
2. **Calibration.** Learn from practice cases how the twins' pooled answer is systematically off
   (on the UK cases it was more concentrated on the top answer than real people in 7 of 8) and
   correct for it; report only on held-out cases.
3. **Variety by construction.** Draw each twin's facts *and* starting attitudes from the sampling
   frame before writing (as the archetype and kit paths already do) instead of asking the model
   for six different people at once.
4. **Measure what each feature earns.** On a fixed 100 cases, switch research, the Studio plan,
   scoping and the knowledge context off one at a time and keep only what pays for itself.
5. **Make a run cheap enough for every study.** A shared cache of national statistics across
   sessions; non-UK publishers (Eurostat, national statistics offices, World Bank); a cap on
   searches per target and on PDF pages; the budget stop reaching post-research tagging. Rough
   target: $1–2 a group instead of ~$6 (an estimate, not yet measured).
6. **Strict structured output for the persona writer** (tool use with a schema) so no text quirk
   can lose a person.
7. **Prove it publicly.** After 1–3, the 1,000-case subset, with the model-alone column published
   beside ours — an accuracy card no competitor can copy quickly.

---

## 7. Does a twin's setup drive its answer? (the setup-sensitivity test)

Run the same day on six cases of the local Studio lineups (gpt-4.1-mini, 70–73 twins each, about
$1): every twin answered each case twice — **FULL**, its whole setup exactly as the benchmark asked
it, and **THIN**, demographics only (name, age, gender, place, job, income, education; no
background, dials, character, standing). Distances are the benchmark's own (0 = identical).

| Case | Group | Twins differ (full / thin) | Pooled answer full↔thin | Full ↔ real people | Thin ↔ real people |
|---|---|---|---|---|---|
| 296 | US liberals | 0.13 / 0.12 | 0.02 | 0.16 | 0.18 |
| 346 | US liberals | 0.09 / 0.06 | 0.03 | 0.20 | 0.17 |
| 5148 | Brazil Catholics | 0.26 / 0.19 | 0.06 | 0.18 | **0.12** |
| 5285 | Brazil Catholics | 0.13 / 0.13 | 0.02 | 0.02 | 0.04 |
| 4181 | Japan, never married | 0.29 / 0.22 | 0.03 | 0.29 | 0.31 |
| 1334 | France | 0.13 / 0.12 | 0.03 | 0.13 | 0.16 |
| **Mean** | | **0.17 / 0.14** | **0.03** | **0.161** | **0.162** |

**Reading.** The detailed setup makes twins about a quarter more different from each other, but
it moves the pooled answer by only 0.03 and leaves accuracy exactly where demographics alone put
it (0.161 v 0.162). In the one case where it moved the answer most (5148) it moved it *away* from
reality. Everything the persona writer adds beyond demographics — background, 112 dials,
character, standing — currently contributes nothing measurable to accuracy.

**A second cause, seen in the twins themselves.** The "US liberals" lineup contains a
Massachusetts State Senator in a segment called *Democratic Politicians and Staff Nationwide*:
the Studio plans segments around people involved in the topic (it was built for stakeholder
debates), so a population meant to be a representative slice of the public is tilted towards
insiders.

**The numbers to beat.** Setup accuracy gain = thin↔real − full↔real = **+0.000** today; pooled
shift full↔thin = **0.03**. A fix works when the first clearly rises above zero.

## 8. Two answer engines, compared (same six cases, gpt-4.1-mini, local)

Built 2026-10-28 (`services/measurement/answer_engines.py`, blueprint §11a.2). **Strict**: one call per
twin, the group-naming topic dropped, the twin's own facts (demographics + ten core attitudes) beside
the question, answer from them and name them. **Map**: one call per question writes the chances of a
reference adult and how far each fact pulls each option; every twin's chances are calculated from its
own facts. Round 1 used moderate attitudes and capped pulls; round 2 set a group's defining trait where
real members sit and allowed realistic pull sizes.

| Case | Group | Persona (today) | Strict | Map (round 2) | Model alone |
|---|---|---|---|---|---|
| 296 | US liberals | 71.5 | **73.5** | −14.3 | 27.9 |
| 346 | US liberals (Biden approval) | 40.9 | 35.5 | **79.2** | 60.5 |
| 5148 | Brazil Catholics | **34.7** | 12.4 | −46.7 | 17.1 |
| 5285 | Brazil Catholics | 77.6 | **84.8** | 56.3 | 43.2 |
| 4181 | Japan, never married | **14.4** | 9.4 | −33.3 | −24.8 |
| 1334 | France | 60.7 | **83.6** | 57.1 | 31.3 |
| **Mean** | | **50.0** | **49.9** | **16.4** | 25.9 |

(Round 1: strict 48.2, map −2.1.) Six cases is a tiny sample, and on these six every engine beat the
model alone, which the full 32 did not.

**Reading.** Strict ties with today's engine, with bigger swings both ways. The map does what was
asked — every answer comes from the twin's own setup — and is the best method of all where a core
fact truly drives the answer (political leaning on a president's approval: 79), but badly wrong where
none does. Both of its halves are still the model's guesses: the twins' attitudes are inferred by the
model, the pulls are estimated by the model. **Making answers depend only on the setup does not help
until the setup comes from data.** The map is the right structure for that: give twins real
respondents' attitudes (ESS, British Social Attitudes, Understanding Society, a client's own survey)
and *fit* the pulls on real answers instead of asking for them — then both halves are data and the
model only writes the life around them.

## 9. Next steps

1. Data-backed twins: one real UK microdata source, respondents' attitudes on the twins, the map's
   pulls fitted from the same data, the tested survey and wave held out (licences checked first).
2. The Studio planner for survey populations: a representative slice of the public, not the people
   involved in the topic (the State Senator in the "US liberals" lineup).
3. Keep `persona` as the default; `strict` and `map` stay behind `spec.answer_engine`.
