# Test script — "Early kidney disease programme, Northmoor and Coast"

A health-system scenario that walks the whole tool once, from an empty session to a committed
outcome, with **research switched on**. A pharmaceutical company and an integrated care system
propose a joint programme: find adults at risk of chronic kidney disease who have missed their
yearly kidney tests, invite them, test them, record the diagnosis, and start and keep them on
kidney-protective treatment. Before anyone signs, the tool is asked what the programme will
deliver, where people will drop off, what would move them, and what outcome to commit to.

Everything in this folder is invented test data and says so on the page. No real company, care
system or practice is named. The problem is real, so the research pass will bring in genuine
material (national CKD prevalence, the yearly-testing guidance, uACR testing rates in diabetes,
the treatment gap for kidney-protective medicines, the deprivation gradient, dialysis costs,
published NHS case-finding programmes). The test files are the anchor; the research is the check.

## What we are trying to achieve

1. **Who the population is** — a synthetic population of the care system's at-risk adults and
   the professionals who see them, matched to a frame built from the files *and* the statistics the
   Studio gathers. Deprivation is always one dimension; ethnicity should be another.
2. **Where people drop off** on the way from "flagged by the search" to "still on treatment at
   twelve months", with the number of people behind each gap and the barriers in their own words.
3. **Whether the gap is the same in the poorest wards** — the equity line on every candidate.
4. **What one change would do** — a rule the system drafts and a named person signs, then the
   same twins answering again with it in place, so the shift is counted rather than asserted.
5. **What to commit to** — one frozen outcome, signed by name, that the real programme can be
   compared against in twelve months.
6. **A report a commissioner could read**, a client document, an export and a comparison.

If every step below produces what it says it should, the tool works end to end for an NHS
joint-working question with research on.

## The files and where they go

| File | Where to put it | What it is |
|---|---|---|
| `01-programme-brief.txt` | 1 Sources → **Documents** (upload) | The programme, the five steps, what can and cannot change |
| `02-facts.txt` | 1 Sources → **Text** (paste the contents) | Illustrative statistics with test sources, including the sizing rows |
| `03-voices.txt` | 1 Sources → **Documents** (upload) | Fourteen short pilot quotes from patients and professionals |
| `04-materials.txt` | 1 Sources → **Documents** (upload); its lines are typed into the Lab in Steps 6 and 7 | Invitation wordings, leaflet headlines, two result letters |
| `audience-profile.txt` | 2 Twins → Studio → **Your inputs → Audience profile** (paste) | Who to build, in one paragraph |
| `respondents-panel.csv` | 2 Twins → Studio → **Your inputs → Survey / panel data** (*Upload respondents to mirror*) | A 14-row panel: nine patients and five professionals |

## The queries to type (copy exactly)

**Session title:** `Early kidney disease programme — Northmoor and Coast`

**Session question:**
> In a northern English integrated care system, if a pharmacist-led programme finds adults at risk of chronic kidney disease who have had no kidney test in the last year, invites them for a blood and urine test, records the diagnosis and starts those with CKD on kidney-protective treatment, how many will be tested, diagnosed and still on treatment twelve months later, where does the population drop off, and is the drop-off worse in the most deprived wards?

**Journey steps** (the tool proposes its own; replace them with these six so every tester gets the same run):

1. `Flagged by the search` — on an at-risk register with no uACR or no eGFR in the last twelve months
2. `Invited` — has received a letter, text or call asking them to book a kidney check
3. `Tested` — has attended and given a blood sample and a urine sample
4. `Diagnosis recorded and explained` — results reviewed, CKD recorded where present, and the person told what it means
5. `Started on kidney-protective treatment` — has begun a RAS-blocker and, where indicated, an SGLT2 inhibitor
6. `Still on treatment at twelve months` — still collecting and taking it a year later

**People in scope:** `95000` · what it counts: `at-risk adults in Northmoor and Coast ICS with no uACR or no eGFR in the last twelve months` · source: `ICS primary care data 2025 (test figure)`

**Lever for the rule:** `A phone call from a pharmacy technician offering a test slot at the community pharmacy`

---

## Step 0 — Before you start

- On prod, do not push to main while this runs: a deploy kills in-flight research, builds and debates.
- Budget about 90 minutes and read the cost line before research, build and debate. This script
  uses **60 twins, Fast**, intensity 2.

## Step 1 — Create the session with research on (10 minutes, mostly waiting)

1. On the landing page type the title and the question above.
2. **Leave Research automatically ticked.** Create.
3. **Check, research frame:** the sub-questions should cover, in some form, (a) how common CKD is
   and how much is undiagnosed, (b) who should be tested each year and how often the urine test
   is actually done, (c) how many people with CKD are on kidney-protective treatment, (d) the
   deprivation and ethnicity gradient, (e) what has worked in NHS case-finding programmes, (f) why
   people stop these medicines. If the frame is only about the medicine, note it: the question is
   about a pathway.
4. **Check, the search:** queries stream with engine names. Expect finds naming the national
   kidney charity's health-economics report, the NICE guideline on CKD, QOF indicators for CKD,
   studies on uACR testing in type 2 diabetes, the SGLT2 inhibitor treatment gap in primary care,
   published NHS case-finding programmes in deprived areas, and the cost of dialysis. Off-topic
   finds are greyed, not hidden.
5. **Check, social listening:** expect it to be thin. Reddit has some material (r/diabetes_uk,
   r/nhs, r/AskUK on "another tablet" and prescription charges), GP forums more. A 403 followed
   by a Chromium retry is normal. A thin social panel is not a failure for this topic.
6. **Regression check:** press **Stop** once, mid-gather. Status goes stopping → finalising →
   stopped within seconds and a brief is still produced. Then start a fresh session and let the
   research run to the end for the real pass.
7. **Check, evidence brief:** the result line reads first. Stakeholder groups should include at
   least *patients at risk*, *GPs*, *pharmacists*, *commissioners* and ideally *people in deprived
   communities* or *minority ethnic groups*. Under *How it searched* the queries, judge notes and
   budget are folded away.
8. **Check, recommended tools:** it should suggest a journey or barriers tool and a survey, each
   mapped to where it lives in this app, with an **Open the Lab** button.

## Step 2 — Add the four files (5 minutes)

1. 1 Sources → **Documents**: upload `01-programme-brief.txt`. Wait for it to finish.
2. 1 Sources → **Text**: paste the whole of `02-facts.txt`. Submit.
3. 1 Sources → **Documents**: upload `03-voices.txt`, then `04-materials.txt`.
4. **Check:** the status dot goes to *ready*. Open **What they know**: expect nodes such as
   *uACR*, *eGFR*, *clinical pharmacist*, *community pharmacy*, *Eastfield*, *Colliery Row*,
   *SGLT2 inhibitor*, *prescription charge*, *dialysis*. Click *uACR*: it should list a test chunk
   and a research chunk. Click *dialysis*: relations should connect it to cost and to late diagnosis.
5. Switch the dropdown to **Ontology**. **Check:** typed nodes include places (the two networks),
   roles (GP, pharmacist, technician, nephrologist, commissioner), tests, medicines by class,
   barriers (cost, side effects, capacity, distrust) and figures.
6. Open **Scoping**. **Check:** the two networks appear as places with a public layer each; a
   professional's role scopes what they can see. This matters in Step 3.

## Step 3 — Build the population (15 minutes)

1. Open **2 Twins**. It is the Population Studio while there are no twins.
2. Set the twin count to **60** and the mode to **Fast**.
3. Under **Your inputs → Audience profile**, paste the contents of `audience-profile.txt`.
4. Under **Your inputs → Survey / panel data**, press *Upload respondents to mirror* and pick
   `respondents-panel.csv`.
5. Under **Statistics**, leave **Gather base rates automatically** on. Tick the sources with a green
   dot; ONS, the national kidney charity, NHS Digital and gov.uk are the useful ones. Optional:
   in the search box type `CKD prevalence by deprivation England` and press Enter; a page with
   usable facts should land in the *pages read* count and in the Sources feed.
6. Press **Detect & plan**. **Check:** the detected population is *at-risk adults in the ICS and
   the professionals who see them*, not *pharmaceutical companies* or *GPs* alone. The proposed
   dials should be this question's own: things like *trust in the NHS*, *understanding of what CKD
   is*, *willingness to attend a test*, *tolerance of side effects*, *cost sensitivity to
   prescriptions*, *appointment fatigue*, and for professionals *capacity* and *willingness to
   let a pharmacist prescribe*. Each dial says where it came from.
7. **Check, frame:** the frame speaks first in one sentence. **Deprivation** is one dimension;
   expect also *condition* (diabetes, hypertension, CVD), *ethnicity*, *age band*, *role* (patient
   or professional), *network*. Each shows a target share from a real source found by gathering,
   from the files, or says none was found. Hover the worst-cell and effective-n chips.
8. **Check, sizing:** the frame's sizing trio reads from the files: 1.3m registered adults, 180,000
   on the at-risk registers, 95,000 untested. Each carries its test source.
9. **Clarify**: answer one question (for example *are professionals part of the population or a
   separate group?* — answer: part of it, about one in five, answering for the people they see) or
   tick *skip the questions*.
10. **Plan**. **Check:** five to seven segments resembling: never-told patients in the poorest
    wards; working-age patients who cannot take time off; patients who started a tablet and
    stopped for side effects or cost; frightened-by-the-letter older patients; South Asian and
    Somali households where a urine sample at the surgery is a barrier; attend-everything older
    patients; and professionals (GPs with no capacity, pharmacists who want to prescribe, the
    commissioner who wants one number). Shares add to 100%. **Registers must vary** — the
    never-told and stopped-it patients should not come back *expert*; the nephrologist should.
11. **Review**: change one segment's share and watch the others rescale. Reject one with a reason
    (`too generic — split patients by whether they have ever been started on a tablet`); it
    regenerates addressing the reason. Then **Approve & build**.
12. **Check:** twins stream in by segment. Each card has a segment badge and a deprivation band;
    the roster groups by segment. Fourteen of the twins should read like the panel rows (a
    Brian-like never-told patient, a Kevin-like stopped-it patient, a Helen-like GP, a Paul-like
    commissioner), with stances drawn from the panel. After a minute a **confidence badge** appears
    beside twins as validation runs, and a *sees N/M* chip shows how much of the material each twin
    can see. **Scoping check:** an Eastfield patient should see the Eastfield pilot material and the
    public layer, not the Colliery Row practice audit; the commissioner should see everything.
13. On the roster press **Save lineup** and name it `ckd-northmoor-60`.

## Step 4 — Run the debate (10 minutes)

1. **3 Debate** → start at intensity **2**.
2. **Check:** every twin posts at least once. Patients talk about letters in drawers, the chemist
    on the way home, the water tablet at night, £9.90 a box, the word "chronic"; GPs about nine
    minutes and workflow; pharmacists about starting treatment at the result conversation; the
    commissioner about one number for the board. Nobody says *the knowledge graph* or *the
    evidence provided*.
3. **Pathway check:** the thread should argue about *steps* (invitation, where the test is, who
    explains the result, who prescribes, who follows up at month four), not about the medicine
    alone. If every post is about the tablet, the pathway framing did not survive the build; note it.
4. **Check:** a post that quotes a real national figure from the research (the one-in-ten
    prevalence, the uACR testing rate, the dialysis cost) is a good sign; it means research
    reached the twins.
5. Pause → posts stop → Resume → they continue. Let it finish. **Check:** the verdict sidebar
    fills with one line per twin, none stuck on *summarising…*.

## Step 5 — The Lab, part one: will people come, and what stands in the way (15 minutes)

1. **4 Lab** → **Verdict**, run on everyone with the session question. **Check:** a headline
   share with an interval, positions, a cut picker that recounts (read by deprivation first, then
   by segment, then by role, then by the *trust in the NHS* dynamic dial), and every twin's words
   clickable to the twin. Expected shape (not exact): professionals mostly *for* with conditions;
   patients split, with the never-told and the working-age groups *mixed*.
2. **Survey** → template **Consequences**. Material: paste the *Phone call script* from
   `04-materials.txt`. Keep the template questions and add two:
   - single, `If you were offered the test, where would you have it done?` options: `at the
     surgery` · `at the chemist on the high street` · `at a mobile clinic in my area` · `a urine
     kit posted home` · `I would not have it done`
   - single, `If the test showed early kidney disease and a tablet was offered, would you take it?`
     options: `yes` · `only if it was explained properly` · `only if it was free` · `no`
   Run on 40 twins. **Check:** the where question gives a ranking (expect chemist and mobile clinic
   ahead of the surgery in the deprived segments); the tablet question shows *only if explained*
   and *only if free* as large blocks; the free-text worry is coded into themes (expect *do not
   understand why*, *side effects*, *cost*, *time off work*, *the word chronic*). Click a bar to
   see the twins behind it.
3. **Barriers** with the outcome `Being tested, diagnosed and still on kidney-protective treatment a year later`. **Check:** at most seven coded barriers ranked by count then weight, each traced to the twins who said it and the evidence those twins could see; expect *never told why*, *cannot take time off*, *side effects with no follow-up*, *prescription cost*, *frightening result letter*, *results sit in workflow*, *no GP capacity*.

## Step 6 — The Journey, the rule book and one lever (20 minutes)

1. **Journey** → press **Propose**. Read what it proposes, then edit it to the six steps above.
2. Under **People in scope** tick **type my own** and enter `95000`, the what-it-counts line and
   the test source line. Optional: on step 3 (Tested) tick *known headcount at this step* and enter
   `36000` (38% of invited, from the practice audit) to see the funnel anchor to a known figure.
3. Run on everyone.
4. **Check, funnel:** six bars, falling. Every step shows a share, a count of twins and a number
   of people (≈95,000 at step 1, fewer at each step). Professionals are counted as answering for
   the people they serve. The line under the funnel names the biggest drop-off and its top barrier.
5. **Check, candidates:** one card per drop-off, ranked. Each shows *X% get through* with an
   interval, *N of M stuck*, people behind the gap with a range, a coloured bar split into
   **movable / system / structural**, the barriers in the twins' words with a lever and who could
   pull it, and an equity line comparing Q1 most deprived with Q5 least deprived. If the bar says
   *movability not scored*, run once more; if it still does, report it as a bug.
6. Expected shape (not exact numbers): the biggest drops are *Invited → Tested* (letters ignored,
   time off work, urine sample at the surgery) and *Started → Still on at twelve months* (side
   effects with no follow-up, cost, not understanding why). *Invited → Tested* should come out
   mostly **movable** (a partner can change how and where); GP capacity and prescription charges
   should come out **system** or **structural**. The equity line at *Invited → Tested* should show
   the deprived band behind.
7. Change **Read by** to *Q1 most deprived*. **Check:** the funnel and candidates recount for that
   band and the *Invited → Tested* gap widens.
8. **Rank behaviours** on the top candidate. **Check:** one row per behaviour dial, movement per
   point with an interval, direction to push, a backfire flag where a nudge hurts a band. Expect
   *understanding of what CKD is* and *trust in the NHS* near the top; labelled a sensitivity, not
   a forecast.
9. **Test messages** on the *Invited → Tested* candidate with the three invitation wordings from
   `04-materials.txt` (Letter, Text, Phone call script) pasted as three messages. **Check:** paired
   shift per message with a weighted shift, ranked winners → indistinguishable → harmful, a
   backfire block, and the label *a modelled reaction to a framing, not a forecast of uptake*.
   Expect the phone call to win, the text second, the letter last; the deprived band should move
   most on the call.
10. **The rule book.** Press **Rule book 0/0**: *No rules yet*. On the *Invited → Tested*
    candidate, under *Simulate a lever*, type the lever above. **Check:** a yellow line says no
    reviewed rule exists; **Simulate** refuses and names the missing rule; nothing runs.
11. Press **Draft the rule** (let the system write it). **Check:** it fills lever, description,
    who it applies to (patients, not professionals), dial changes and a basis. Because the files
    hold two pilot figures for this lever (57% after a call, 61% at the pharmacy) the basis class
    should come out *evidence-anchored*, citing them by handle; if it comes out *assumption*, note
    it. Expected dial changes, in whatever numbers it picks: friction → *time_cost* down,
    *technical_difficulty* down, *ambiguity* down; trust → *credibility* up; habit →
    *action_simplicity* up. Save as draft. **Check:** *draft · not yet reviewed*; Simulate still refuses.
12. Type a reviewer name, **Sign off**. **Check:** *reviewed · name*; the card shows *Rule on file*
    with the dial changes. Press **Simulate**. Wait one to three minutes.
13. **Check, result block:** conversion at the step *then → now* with a signed shift and an
    interval, twins *moved through / fell back / unchanged*, the end of the journey *then → now*,
    rows by deprivation band, and *people moved* with a range against the 95,000. It names the
    rule, its reviewer and the basis class. Expect the working-age and never-told segments to move
    most, the stopped-it segment not at all (their barrier is later in the journey).
14. Under **Commit to this outcome** on the *Invited → Tested* candidate: sign with your name,
    target `55% of invited people tested within eight weeks`, horizon `12 months from programme
    start`, note `Baseline before the joint-working agreement is signed`. Press commit. **Check:** a
    commitment card appears, frozen, with the population build, the evidence count, the rule and
    the statement. Press the pencil on the rule, change nothing, save: the rule goes back to draft
    and Simulate refuses until it is re-signed; the commitment card is unchanged.

## Step 7 — Two experiments (10 minutes)

1. **A/B test**, *Rate each*, on the *Reaction* survey base, with the two result letters from
   `04-materials.txt`:
   - A: Version 1 (the current clinical letter)
   - B: Version 2 (the plain-language letter with the pharmacist call)
   **Check:** a lift with an interval, who flipped with both reasonings, and a split by segment and
   deprivation. Expect B to win overall; watch whether any segment prefers A (some professionals
   may).
2. **Choose between** with the three leaflet headlines A, B, C from `04-materials.txt`.
   **Check:** a preference race with intervals, winner settled or not, per-option themes. C (the
   dialysis line) is the interesting one: if patients pick it and professionals reject it as
   frightening, the report chat should say so.
3. Re-run Barriers with the same seed. **Check:** the same twin sample.

## Step 8 — Report, export, compare (10 minutes)

1. **5 Report** → **Generate Report**. **Check:**
   - A direct answer with a confidence band that is *computed* from the headline record (hover
     for the basis), not asserted; it answers the question as a pathway (tested → diagnosed →
     treated → still treated) with the equity finding, not as a verdict on the medicine.
   - Figures carry coloured chips: official statistic / evidence / model-inferred. A research
     figure and a test figure that disagree (national uACR testing rate versus the ICS's 36%)
     should both be present with their own chips, and any number with no source is struck through.
   - A section **Where the population drops off** in the same order as the Journey page, with
     people and movability.
   - A lever record naming the rule, its reviewer and *evidence-anchored* or *assumption*.
   - The committed outcome listed under committed outcomes.
   - Named twins render as names with a trace card; click one → *Talk to this twin*.
2. **Ask Report:** `If the programme can afford only two changes in year one, which two move the most people through to treatment, and which ward group is left behind by each choice?` **Check:** named twins, the message-test shifts, the movability split and the equity line.
3. **Talk to this twin:** pick the most reluctant stopped-it patient and ask what would have kept them on the tablet. Markdown renders.
4. **Client report**: a clean print page with every citation resolved. Save as PDF.
5. **Export data**: a zip. Open `run.json`: the rule with its reviewer and the commitment are inside; every file carries the synthetic-population statement at the top.
6. **Regenerate** the report once, then **Compare runs**. **Check:** it lists what changed — headline and whether the change is real, positions, equity gap, dissent, barriers, evidence base, confidence.
7. Reload the page. **Check:** the last report and the Ask-Report questions are still there.

## Step 9 — Optional second pass (research off)

Repeat Steps 1 to 6 in a new session with **Research automatically unticked** and **Gather base
rates automatically** off, 40 twins. Compare with the first pass:

- the frame should now say *none found* on more dimensions and the sizing should rest on the test rows only;
- the barriers should be the same shape but with no national figures in the twins' words;
- the report's chips should be almost all *evidence* (the test files) and *model-inferred*.

If the two passes disagree on the *direction* of the headline, that is a finding about the tool, not about the programme. Note it.

## What "great insights" look like from this run

The run has succeeded as research if the report can answer these with named twins and numbers:

1. A predicted share of the 95,000 who are tested, diagnosed, started and still on treatment at
   twelve months, each with an interval, and the equity gap at each step.
2. Which single step loses the most people, and whether that loss is movable by the programme or
   sits with GP capacity and prescription charges.
3. The counted shift from the phone-call-and-pharmacy lever, against the 95,000, by deprivation band.
4. Which invitation wording and which result letter to use, with the segment that disagrees.
5. One committed outcome the joint-working agreement can be checked against in twelve months.

## What "pass" looks like

- Every step above shows what it says it should.
- No number of people appears anywhere without the 95,000 denominator behind it.
- Nothing is simulated for a lever without a reviewed rule.
- Research material and test material both appear in the report, each with its own source chip,
  and the twins' barriers match their own words rather than drifting to web material.
- Professionals are counted as answering for the people they serve, never as patients.
- The report only repeats candidates, barriers, movability, lever shifts and message results that
  the Lab computed; it never invents its own.

## Things that look like bugs but are not

- Real national figures mixing into the debate: expected with research on; the test files are the anchor.
- A thin social-listening panel: expected for this topic.
- Candidates that rest on fewer than five twins say so and have very wide intervals.
- Editing a reviewed rule puts it back to draft on purpose.
- The left-hand Journey builder shows the *current* steps; the results on the right are from the
  *last run*. Pressing *Propose again* changes the left without changing the right.
- Twins may place themselves on a different step in the lever arm; the paired set is the at-risk
  twins in both arms, so the counts can be smaller than the funnel's.
- A message test never refuses for want of a rule; only a lever simulation does.
