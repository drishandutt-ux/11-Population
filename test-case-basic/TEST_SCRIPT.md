# Basic test script — "Manchester food-waste caddies"

A deliberately simple, everyday scenario that walks through the whole tool once, from an empty
session to an exported report, without needing to know anything about pharma or health systems.
Everything in this folder is invented test data and says so on the page.

## What we are trying to achieve

A council is rolling out a weekly food-waste caddy to every home. We want the tool to tell us:

1. **Who the population is** — a synthetic population of Manchester households, matched to the
   frame (deprivation is always one of the dimensions).
2. **Where people drop off** — the journey from "knows the scheme exists" to "still using the
   caddy after six months", with one candidate outcome per drop-off, the number of households
   behind each gap, and what stands in the way in the twins' own words.
3. **What a partner could move** — which barriers the council could fix alone, which need the
   wider system, and which nobody can move soon.
4. **What one lever would do** — a written, reviewed rule ("free liners") and the same twins
   answering again with it in place, so the shift is counted rather than asserted.
5. **A report a client could read**, an export, and a comparison between two runs.

If every step below produces what it says it should, the tool works end to end.

## The files and where they go

| File | Where to put it | What it is |
|---|---|---|
| `01-scheme-brief.md` | Ingest tab → **Documents** (upload) | What the scheme is, what the council can and cannot change |
| `02-facts.md` | Ingest tab → **Text** (paste the contents) | A table of illustrative statistics with test sources |
| `03-resident-feedback.md` | Ingest tab → **Documents** (upload) | Twelve short pilot quotes |
| `residents-panel.csv` | Agents tab → Studio → **Your inputs → Survey / panel data** (*Upload respondents to mirror*) | A 12-row resident panel the Studio reads as a survey |

## The queries to type (copy exactly)

**Session title:** `Food-waste caddies — Manchester`

**Session question:**
> Will Manchester households use the council's new weekly food-waste caddy collection, and what stops them from keeping it up?

**Journey steps** (the tool proposes its own; replace them with these five so every tester gets the same run):

1. `Knows the scheme exists` — has heard a weekly food-waste collection is starting
2. `Has a caddy at home` — the kitchen caddy and kerbside caddy have been delivered
3. `Has used it once` — put food waste out for collection at least once
4. `Uses it every week` — puts the caddy out most weeks
5. `Still using it at six months` — still putting it out six months after the start

**People in scope:** `230000` · what it counts: `households in Manchester` · source: `council housing stock return 2025 (test figure)`

**Lever for the rule:** `Free caddy liners`

---

## Step 1 — Create the session (2 minutes)

1. On the landing page type the title and the question above.
2. **Untick Research automatically.** Create. (Research off keeps the three test files as the only
   material, so every number and barrier in the run can be traced back to them.)
3. **Check:** the session opens on the Ingest tab with status *created* and no research panel running.
4. Optional second pass, later: repeat the whole script in a new session with research on, and check
   only that the research panel streams and greys off-topic finds, and that the Journey's barriers
   still match the twins' words rather than drifting to web material.

## Step 2 — Add the three files (5 minutes)

1. Ingest → **Documents**: upload `01-scheme-brief.md`. Wait for it to finish.
2. Ingest → **Text**: paste the whole of `02-facts.md`. Submit.
3. Ingest → **Documents**: upload `03-resident-feedback.md`.
4. **Check:** the status dot goes to *ready*. Open the **Graph** tab: you should see nodes such as
   *Manchester City Council*, *caddy*, *liners*, *Harpurhey*, *flats*. Click one; it lists the
   chunk it came from.

## Step 3 — Build the population (10 minutes)

1. Open the **Agents** tab. It is the Population Studio while there are no twins.
2. Set the twin count to **40** and the mode to **Fast**.
3. Under **Your inputs → Survey / panel data**, press *Upload respondents to mirror* and pick
   `residents-panel.csv`.
4. Under **Statistics & surveys**, **untick** *Gather automatically when you press Detect & plan*.
   The panel says "Automatic gathering is off" — expected. (Same reason as research off: the frame
   then rests only on your files and the panel. Turn it on for the optional second pass.)
5. Press **Detect & plan**. **Check:** the detected population is Manchester households; the proposed
   dials mention things like space at home, liner cost, smell tolerance, awareness of the scheme
   (these are the question's own dials, chosen for this question).
6. **Check:** a *frame* card appears with dimensions; **deprivation** is one of them, and each
   dimension shows a target share from your files, or says none was found (with gathering off,
   "none found" on some dimensions is normal).
7. **Clarify**: answer one question or tick *skip the questions*.
8. **Plan**. **Check:** four to seven segments such as: flat-dwellers with shared bins, terrace
   households in deprived wards, keen recyclers, people who never heard of it, large shared
   houses. Shares add to 100%.
9. **Review**: change one segment's share and watch the others rescale. Then **Approve & build**.
10. **Check:** twins stream in by segment. Each card has a segment badge and a deprivation band.
   After a minute a small **confidence badge** appears beside twins as validation runs in the
   background. A *sees N/M* chip shows how much of the material each twin can see.

## Step 4 — Run the debate (5 minutes)

1. **Thread** tab → start at intensity **2**.
2. **Check:** every twin posts at least once; flat-dwellers talk about shared bins, deprived-ward
   twins about liner cost and smell; nobody says "the knowledge graph" or "the evidence provided".
3. Let it finish. **Check:** the verdict sidebar fills in with one line per twin, none stuck on
   "summarising…".

## Step 5 — The Journey (10 minutes)

1. **Lab** tab → pick **Journey**.
2. Press **Propose**. Read what it proposes, then edit it to the five steps above (rename, delete
   or add rows until they match). Give each step the one-line definition.
3. Under **People in scope** tick **type my own** and enter `230000`, `households in Manchester`
   and the test source line.
4. Run on everyone.
5. **Check, funnel:** five bars, falling. Every step shows a share, a count of twins and a
   number of households (≈230,000 at step 1, fewer at each step). The line under the funnel names
   the biggest drop-off and its top barrier.
6. **Check, candidates:** one card per drop-off, ranked. Each shows *X% get through* with an
   interval, *N of M stuck*, households behind the gap with a range, a coloured bar split into
   **movable / system / structural**, the barriers in the twins' words with a lever and who could
   pull it, and an equity line comparing Q1 most deprived with Q5 least deprived.
7. **Check, movability:** the bar must be coloured, not say *movability not scored*. If it says not
   scored, run the Journey again once; if it still does, report it as a bug.
8. Change **Read by** to *Q1 most deprived*. **Check:** funnel and candidates recount for that band.
9. Expected shape (not exact numbers): the biggest drops are *Has used it once → Uses it every
   week* and *Uses it every week → Still using it at six months*; top barriers are smell/flies,
   liners running out, no space, shared bin full.

## Step 6 — The rule book and one lever (10 minutes)

1. Press **Rule book 0/0** at the top of the Journey page. **Check:** "No rules yet."
2. On the top candidate, under *Simulate a lever*, type `Free caddy liners`. **Check:** a yellow
   line says no reviewed rule exists. Press **Simulate** anyway. **Check:** it refuses and names
   the missing rule. Nothing runs.
3. Press **Write the rule** and fill in:
   - Lever: `Free caddy liners`
   - Author: your name
   - Description: `Compostable liners are delivered free with the caddy and topped up on request, so nothing has to be bought and the caddy stays clean`
   - Who it applies to: leave empty (everyone)
   - Dial changes: group **friction** → `money_pain` −2, `emotional_resistance` −2; group
     **habit** → `action_simplicity` +2. Bound ±4.
   - Evidence: ref `Pilot monitoring report, liner sub-study (test)`, note `six-month use 57% with free top-ups vs 44% without`
   - Basis: `Free liners remove the cost and the mess objections, so −2 on each and +2 on how easy the action is`
   - **Save as draft**. **Check:** listed as *draft · not yet reviewed*.
4. Close the rule book, press **Simulate** again. **Check:** it still refuses, now saying the rule
   has not been reviewed.
5. Reopen the rule book, type a reviewer name, **Sign off**. **Check:** *reviewed · name*.
6. Back on the card the lever box shows a green *Rule on file* line with the three dial changes.
   Press **Simulate**. Wait one to three minutes.
7. **Check, result block:** conversion at the step *then → now* with a signed shift and an
   interval, how many twins *moved through / fell back / unchanged*, the end of the journey
   *then → now*, rows by deprivation band, and *households moved* with a range. The block names
   the rule and its reviewer.
8. Press the pencil on the rule, change nothing, **Save (back to draft)**. **Check:** status is
   draft again and Simulate refuses until it is re-signed.

## Step 7 — Two more Lab tools, quickly (5 minutes)

1. **Verdict**: run it on everyone with the session question. **Check:** a headline share with an
   interval, positions, a cut picker that recounts, and every twin's words clickable to the twin.
2. **A/B test** on Ask: A = `A text the week before: "Your food-waste caddy arrives Monday. Liners included."`
   B = `A leaflet through the door two weeks before with a picture of the caddy.`
   **Check:** a lift with an interval, who flipped and why, and a split by segment.

## Step 8 — Report, export, compare (10 minutes)

1. **Report** tab → **Generate Report**. **Check:**
   - A direct answer with a confidence band that is *computed* (hover or read the basis), not
     asserted.
   - Figures carry coloured chips: official statistic / evidence / model-inferred. A number with
     no source is struck through.
   - A section **Where the population drops off** listing the candidates in the same order as the
     Journey page, with households and movability.
   - A lever record naming *Free caddy liners*, the rule and its reviewer.
   - Named twins render as names with a trace card; click one → *Talk to this twin*.
2. **Client report**: opens a clean print page with every citation resolved. Save as PDF.
3. **Export data**: a zip. Open `run.json` → the rule with its reviewer is inside; every export
   file carries the synthetic-population statement at the top.
4. **Regenerate** the report once, then **Compare runs**. **Check:** it lists what changed —
   headline and whether the change is real, positions, equity gap, dissent, barriers, evidence
   base, confidence.

## What "pass" looks like

- Every step above shows what it says it should.
- No number of households appears anywhere without the 230,000 denominator behind it.
- Nothing is simulated for a lever without a reviewed rule.
- The report only repeats candidates, barriers, movability and lever shifts that the Journey
  page computed; it never invents its own.

## Things that look like bugs but are not

- With research on, real Manchester and national food-waste material mixes in; that is fine, the test
  files are the anchor.
- Candidates that rest on fewer than five twins say so and have very wide intervals.
- Editing a reviewed rule puts it back to draft on purpose.
- The left-hand Journey builder shows the *current* steps; the results on the right are from the
  *last run*. Pressing *Propose again* changes the left without changing the right.
