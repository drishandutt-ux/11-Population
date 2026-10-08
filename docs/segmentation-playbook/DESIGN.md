# Segmentation playbooks — design proposal (2026-10-08)

Status: **step 1 built 2026-10-08** (upload / paste / library → build; research flags, never overrides;
shared library). Steps 2–4 below are still to do. As built: `PRODUCT_BLUEPRINT.md` §7.15.
Template and example: [`backend/app/data/playbooks/`](../../backend/app/data/playbooks/).

## The idea in one line

Before: the Studio decides how to cut a population and which forces matter, from the question
and the research. Now: the analyst can bring **their own segmentation method** as a `.md`
playbook (written by hand, uploaded, or brainstormed with a chat), and the Studio builds the
population their way — still checking their hunches against the evidence and saying which
parts are the analyst's assumptions.

A playbook is a **hand-written kit**. Kits (§7.14) already replace detect → plan with published
research; a playbook does the same job with the analyst's own thinking, and can be partial
(the Studio fills in what it leaves out).

## 1. How the analyst gets a playbook

Three doors, the same pattern as Lab Forms (import / write / chat):

| Door | What happens |
|---|---|
| **Write** | Download the template (sections: Approach, Segments, Variables, Rules of character, Not sure about), fill it in, upload it. |
| **Upload** | Any `.md` / `.docx` / pasted text, in any shape. The parser maps it to the sections. |
| **Brainstorm** | A conversational chat in the Studio. It has read the session (question, evidence brief, uploads), asks one thing at a time — *who exactly? how would you split them? what do generic personas get wrong about them? what wears them down? what blocks them?* — proposes variables the analyst has not thought of, and ends by writing the playbook. The analyst downloads the `.md`, edits it, keeps it for next time. |

Playbooks are saved per owner (like archetypes), so a *Migraine HCPs in London* playbook can be
reused in a later session.

## 2. What the Studio reads out of it

One structured parse call turns the `.md` into:

```
approach      primary axis, secondary axis, why, match-exactly list
segments[]    name, share (number | "find" | blank), description, source
variables[]   name, what it is, low/high anchors, kind (dial | category | rule | auto),
              per-segment range or values, "shows up as", evidence (source | "find" | none)
rules[]       character rules, population-wide or per segment
unsure[]      open questions
```

The analyst then sees a **"What I understood"** screen before anything is built: each segment,
each variable with *where it will live* and *which standard dials it pushes*, every one
editable. Nothing is built from a misreading.

## 3. Where each part of the playbook goes

| Playbook part | Goes into (existing machinery) | Effect on the twins |
|---|---|---|
| **Approach** | The planner's instructions + which frame dimensions are matched exactly | Decides what a segment *is* (see §5) |
| **Segments** with shares | Plan segments, created already accepted (as a kit does) | The population's mix |
| Segments with `find` | A gather target for the share; falls back to the planner's figure, labelled | Shares come from evidence where possible |
| No segments | The ordinary planner, told the approach | The Studio proposes segments the analyst's way |
| **Variable → dial** (a degree: burnout, commute) | A **pinned dynamic dial** (§7.2a) — the model's own picks fill the remaining slots | Every twin carries 0–10, it reaches every prompt, it becomes a Lab split |
| **Variable → category** (care setting, commute mode) | A **persona facet** (§7.8 map) and, if shares are given or found, a **frame dimension** (§7.9) | Each twin sits in one cell; matched / weighted; a Lab split |
| **Variable → rule** (a behaviour, not a degree) | The twin's **character** block (§7.10) | Obeyed word for word in posts, chat, Lab |
| **Dial links** (see §4) | A new nudge step after the persona writer | The standard 112 move consistently with the variable |
| **Rules of character** | Character `decision_rules` / `behaviour`, per segment | As above |
| **Not sure about** | Clarify questions + gather targets | Evidence is hunted for exactly what the analyst doubts |

## 4. Which dials move — dial links

A variable on its own is one number. To make it change behaviour it has to push the standard
dials that drive the voice. Today only four groups shape how a twin talks (`sentiment`,
`motivation`, `friction`, `trust` — `_dials_to_behavioral_guidance`); the other five feed
analytics. So every dial variable gets a list of **links**: a fixed dial, a direction, a
strength 1–3.

The Studio proposes the links (one call, constrained to real dial keys from `DIALS_SCHEMA`),
the analyst can edit them on the "What I understood" screen.

**Example links:**

| Variable | Pushes up | Pushes down |
|---|---|---|
| **Burnout** | sentiment.frustration (2), friction.cognitive_load (2), friction.time_cost (2), habit.switching_cost (1), sentiment.anxiety (1) | motivation.novelty (2), sentiment.hope (1), sentiment.curiosity (1) |
| **Commute burden** | friction.time_cost (2), motivation.convenience (2), sentiment.frustration (1) | — |
| **Formulary pressure** | friction.friction (2), friction.ambiguity (1), commercial.objection_intensity (1) | motivation.autonomy (1), motivation.control (1) |

**The rule, in code, after the persona writer returns:**

```
shift(dial) = Σ over linked variables of  direction × strength × (value − 5) / 5
shift capped at ±4, then dial = clamp(dial + round(shift), 0, 10)
```

A twin with burnout 9 gets frustration +1.6 → +2, novelty −1.6 → −2; a twin with burnout 2 gets
the opposite, smaller. Value 5 changes nothing. The writer is also told the values and links, so
the life story agrees with the numbers; the nudge only guarantees it.

**How it then shows up in a post:** high frustration → the existing rule "sharp, clipped
language"; high time_cost and cognitive_load → "complains about effort"; low novelty →
resists the new thing. Plus the dynamic dial's own prompt line: *Burnout: 9/10 — running on
empty*.

## 5. What the approach changes

| Approach | A segment is defined by | Matched exactly | Dials the segments differ most on |
|---|---|---|---|
| **Demographic** | who they are: role, setting, age, place | role, place, age | identity, plus place-driven geo shifts |
| **Behavioural** | what they do: prescribing pattern, referral habit, channel use | the behaviour, then role | habit, commercial, product |
| **Value / needs-based** | what they want: evidence-led, patient-experience-led, cost-led | role (as a check) | motivation, trust, character decision rules |
| **Attitudinal** | what they believe about the topic | — (attitudes are never estimated, §7.9) | sentiment, trust, beliefs |
| **Hybrid** | primary axis segments, secondary axis inside each segment | top of each | both |

Concretely: the planner is told *"segments must differ on <axis>; describe each by <axis>
first"*, and the frame picker is told the match-exactly list instead of choosing its own.

## 6. Values per twin — drawn, not invented

The model clusters if it chooses the numbers itself (everyone "7"). So, like archetype casting
(§7.11), each twin's variable value is **drawn before any model call**: seeded, spread evenly over
every value in the segment's range (a draw around the middle also clustered — five 7s in a 6–8
segment — so it was dropped). The
writer gets the value as a fixed fact and writes around it; `enforce` overwrites it if it drifts.
Category values are drawn from the shares as a stratified quota (as kit cards do).

## 7. Checking the analyst's hunches

A playbook is opinion until something backs it. Each variable marked `find` (or with no
source) becomes a **gather target** ("NHS Staff Survey burnout London trusts", "NHS staff
travel to work London"). Afterwards each variable carries a status:

- **supported** — evidence on file agrees (source shown);
- **contradicted** — evidence disagrees: flagged in the log, on the plan and in the report; the
  analyst's choice is kept (decided 2026-10-08: "not override, just flag");
- **no evidence** — kept, labelled **analyst hypothesis**.

The report's population block lists the playbook and each variable's status, so a client sees
which forces were measured and which were the analyst's call. (New provenance label beside
`official_statistic`, `client_data`, `research_web`, `model_inference`.)

## 8. What the analyst gets afterwards

- In the Lab, every dial variable is a split (low / mid / high) and every category a split —
  *"burnt-out GPs would prescribe 18%, others 34%"* — with no extra work (§7.2a already does this).
- The population map shows the category variables as panels.
- The playbook is stored on the build, so a rebuild or a new session uses the same method.

## 9. Build plan (smallest useful first)

1. **Playbook in → population out.** Template download, upload, parse, "What I understood"
   screen, apply to the build (segments, pinned dynamic dials with drawn values, facets, rules,
   dial links + nudge). Works in the Studio and the simple view.
2. **Brainstorm chat** that writes the `.md` (reuses the Forms chat plumbing and the session brief).
3. **Evidence check** of variables (gather targets, supported / contradicted / hypothesis, report block).
4. **Playbook library** — saved per owner, pick one for a new session.

Code touch-points: new `services/population/playbook.py` (parse, links, draw, nudge),
`dynamic_dials.ensure` gains pinned dials, `facets.pick_facets` gains pinned facets,
`agent_factory.generate_agents_from_plan` gets the draw + nudge step, `builder` reads
`constraints.playbook`, new `/population/playbook` routes, a `playbooks` table, Studio UI.

## 10. Decisions (2026-10-08)

1. Research still runs when a playbook names segments and shares — it flags, never overrides.
2. Variables are per-segment ranges for now; conditional variables later.
3. Playbooks are shared across the team (no multi-tenancy yet; the author is recorded).
