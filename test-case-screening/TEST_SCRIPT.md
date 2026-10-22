# Demo and test script — "Screening at home"

The one test pack for the tool, built to be shown to clients. It walks every part of a session on
a real, current public-health question with a lot of public figures behind it:

> In August 2026 the NHS in England began inviting around four million women who are overdue for
> cervical screening to order a free **home HPV self-sampling kit**. Who will use it, who still
> won't, where do women drop off, and what one change would move the most of them?

Why this topic demos well:

- **It is real and current**, so research finds plenty: NHS England coverage statistics, Cancer
  Research UK figures, the UK National Screening Committee recommendation, published trials, the
  2040 elimination target.
- **Every tool has something to bite on**: a clear six-step path (Journey), strong personal
  barriers (Barriers), wordings to compare (Test messages, A/B, Choose between), a deprivation and
  ethnicity gap (equity line), professionals who answer for the women they see (scoping).
- **There is a real answer to check against.** `reality-check.md` holds a published trial result
  the twins are not shown: kits handed over in person at the GP were returned four times as often
  as kits posted home. The demo can show the population getting the order right.

The public figures are real (`02-facts`); the working group, the quotes, the panel and the
wordings are invented and say so on the page.

## The files and where they go

| File | Simple view | Pro view |
|---|---|---|
| `01-programme-brief.md` (or `.txt`) | *Add anything* (upload) | 1 Sources → **Documents** |
| `02-facts.txt` | *Add anything* (paste the text) | 1 Sources → **Text** (paste) |
| `03-voices.md` (or `.txt`) | *Add anything* (upload) | 1 Sources → **Documents** |
| `04-materials.md` (or `.txt`) | *Add anything* (upload) | 1 Sources → **Documents**; lines are typed into the Lab later |
| `who-to-ask.txt` | *Who should we ask?* → description (paste) | — |
| `audience-profile.txt` | — | 2 Twins → Studio → **Your inputs → Audience profile** (paste) |
| `respondents-panel.csv` | *Who should we ask?* → survey file | 2 Twins → Studio → **Your inputs → Survey / panel data** |
| `playbook-overdue-women.md` | — | 2 Twins → Studio → **Or bring your own segmentation playbook** → Upload .md (optional) |
| `questionnaire.txt` | Lab tools → *Ask a few questions* → *Already have questions?* | 4 Lab → **Forms** → Import |
| `reality-check.md` | **never upload** — for the presenter | **never upload** |

## What to type (copy exactly)

**Session title (Pro):** `Screening at home — the overdue four million`

**Question:**
> Now that the NHS in England is inviting around four million women who are overdue for cervical screening to order a free home HPV self-sampling kit, who will order and send one back, where do women drop off between the invitation and the follow-up appointment after a positive result, is the drop-off worse in the most deprived areas and among ethnic minority women, and what single change would move the most women through?

**Journey steps** (the tool proposes its own; replace them with these so every run is comparable):

1. `Invited` — has received an invitation by NHS App, text, email or letter to order a home kit
2. `Read and understood it` — has opened the invitation and knows what is offered and why
3. `Ordered a kit` — has ordered a kit through the NHS App or NHS online account
4. `Took the sample and posted it back` — has done the swab and returned it
5. `Got the result and understood it` — has received the result and knows what it means
6. `Went to the follow-up` — if HPV was found, has booked and attended the examination

**People in scope (Pro):** `4000000` · what it counts: `women aged 30 to 65 in England offered a home kit in the first phase` · source: `NHS England, 25 August 2026`

**Lever for the rule:** `Kit handed over in person at any GP or pharmacy visit`

---

## Step 0 — Before you start

- On prod, check nobody else has a build, research run or survey in flight, and do not push to
  main while the demo runs: a deploy kills in-flight jobs.
- Simple view: about 30 minutes. Pro view: about 90 minutes. Read the cost line before research,
  build and debate. This script uses **60 twins, Fast**, debate intensity 2.
- Keep `reality-check.md` open on your own screen, not in the session.

---

## Part A — The client demo in the Simple view (about 30 minutes)

*Talk track in italics: what to say to the client at each step.*

1. **Start.** Landing page → **Simple**. Type the question. In *Add anything* upload
   `01-programme-brief.md`, `03-voices.md` and `04-materials.md`, and paste `02-facts.txt`.
   Press **Start**.
   *"We give it the question and what we already know. It goes and reads the rest."*
   - **Check:** the session opens on *Who should we ask?*; research runs by itself.
2. **Who should we ask?** Paste `who-to-ask.txt`; add `respondents-panel.csv` as the survey file.
   Press **Run simulation**.
   *"Now it builds the population: sixty women and professionals, matched to the real shape of
   who is overdue, with our fourteen panel members mirrored in."*
   - **Check:** *Getting everyone ready* shows its steps and moves on by itself.
3. **The conversation.** Let it run (a few minutes).
   *"They argue it out in their own words. Nobody is scripted."*
   - **Check:** women talk about the letter on the fridge, the partner reading the post, the
     speculum, doing it after the kids are in bed, instructions in English only, not trusting
     a self-test, having to go in anyway if it is positive. Professionals talk about follow-up
     slots and the word "HPV" on a letter. Nobody says "the knowledge graph" or "the evidence".
   - **Check:** at the end: **Talk to a person**, **Make the report**, **Lab tools**.
4. **Talk to a person.** Pick the self-test doubter (a Marcia-like twin) and ask:
   `What would make you trust a kit you did yourself?`
   *"Any one of them can be interviewed, and they stay themselves."*
   - **Check:** the answer stays in character and refers to her own life.
5. **Make the report.**
   *"A direct answer with a computed confidence, and every figure says where it came from."*
   - **Check:** a direct answer with a confidence band; the 68.8% coverage, the 4 million and
     the 65% deprivation gap carry source chips; names render as clickable people.
6. **Lab tools → Ask a few questions.** Under *Already have questions?* drop in `questionnaire.txt`.
   Press **Ask** for everyone.
   - **Check:** five questions in order (pick-one with 5 options, yes/no, 1–10, pick-any with 5,
     open); the "Thank you… anonymous" line is not a question; the count goes up to 60.
   - **Expected shape:** *A kit handed to me at the GP or pharmacy* and *a plain envelope* among
     the most picked; comfort scores high for examination avoiders and low for self-test doubters.
7. **Lab tools → What stands in the way.** Let the chat recommend the outcome (*Ordering and
   sending back a home kit*, or close to it) and press **Use that**.
   *"Each person names the one thing in the way, and the tool groups and ranks them."*
   - **Check:** it runs by itself; up to seven coded barriers ranked, each traced to the people
     who said it. Expect *never sees the invitation*, *no privacy at home*, *doesn't trust a
     self-test*, *language / needs help*, *time*, *fear of a positive result*.
8. **Lab tools → Where people drop off.** Steps are proposed; edit them one at a time to the six
   above. Run.
   *"Here is where the four million fall away, and why."*
   - **Check:** the path shows one step at a time with the most stuck step open.
   - **Expected shape:** the biggest drops at *Invited → Read and understood it* and *Got the
     result → Went to the follow-up*; the deprived band behind at the first.
   - In the rules chat type: `Hand women a kit in person whenever they are at the GP or the
     pharmacy for anything else`. Press **Add it**, then **See what changes**.
   - **Check:** a picture of the growth with the rule in place.
   *"That change, handing the kit over in person, is the one a real trial tested."* Now show the
   real numbers from `reality-check.md`: 52% returned in person v 12% posted v 5% by letter.
9. **Share it.** Press **Share**, pick a colleague, open the **Chat** step and type
   `@report which group is still left behind if every kit is handed over in person?`
   *"The team discusses the findings with the report agent in the room."*
   - **Check:** the report agent answers in the thread. (Needs a second signed-in colleague.)

---

## Part B — Every tool in the Pro view (about 90 minutes)

### Step 1 — Session and research (10 minutes, mostly waiting)

1. Landing → **Pro**. Type the title and question. Leave **Research automatically** ticked. Create.
2. **Check, research frame:** sub-questions should cover screening coverage and its trend, who
   is under-screened, the home-kit roll-out and eligibility, evidence on self-sampling uptake, the
   follow-up after a positive result, and barriers. If the frame is only about the virus, note it.
3. **Check, the search:** expect finds from NHS England, gov.uk, Cancer Research UK, the UK NSC,
   The Eve Appeal, journal papers on YouScreen / HPValidate, local JSNAs. Off-topic finds greyed.
4. **Check, social listening:** Reddit (r/TwoXChromosomes, r/AskUK, r/NHS) and news comments
   should have real material on smear tests and the home kits. A 403 then a Chromium retry is normal.
5. Press **Stop** once mid-gather only if you are testing; for a demo let it finish.
6. **Check, evidence brief:** the result line first; stakeholders include overdue women,
   practice nurses, GPs, pharmacists, commissioners, charities; recommended tools mapped to the Lab.

### Step 2 — Add the files (5 minutes)

1. Sources → **Documents**: `01-programme-brief`, `03-voices`, `04-materials`. Sources →
   **Text**: paste `02-facts.txt`.
2. **Check, What they know:** nodes such as *HPV*, *self-sampling kit*, *NHS App*, *speculum*,
   *practice nurse*, *community pharmacy*, *follow-up examination*, *deprivation*, *2040*.
3. **Ontology:** typed places, roles, tests, barriers, figures.
4. **Scoping:** regions as places with a public layer; a professional's role scopes what they see.

### Step 3 — Build the population (15 minutes)

1. **2 Twins** → Studio. **60** twins, **Fast**.
2. Paste `audience-profile.txt`; upload `respondents-panel.csv` under *Survey / panel data*.
3. Optional: upload `playbook-overdue-women.md` and check *What I understood* shows seven segments,
   *find* on Examination avoiders and Self-test doubters, two dials and one category, three rules,
   two doubts. **Use for this build.**
4. Leave **Gather base rates automatically** on. **Detect & plan**.
   - **Check:** the population is *women overdue for screening and the professionals who see
     them*, not *the NHS* or *HPV*. Proposed dials are this question's own: embarrassment,
     self-test trust, privacy at home, digital confidence, fear of a positive result.
   - **Check, frame:** deprivation is a dimension; also age band, ethnicity, region, role. Each
     shows a target share from a real source, the files, or says none was found.
   - **Check, sizing:** the trio reads about 16 million eligible / 5 million not up to date /
     4 million offered a kit, each with its source (16 million marked derived).
5. Clarify (or skip) → **Plan**.
   - **Check:** five to seven segments, shares add to 100%, registers vary (the professionals
     come back expert; the never-seen-the-invitation women do not).
6. **Mix dials:** press **Adjust mix**, drag *Examination avoiders* up to 30%. **Check:** the
   untouched dials share out the rest and the total stays 100%. **Use this mix**.
7. Reject one segment with a reason (`split by whether she has ever been screened`); it regenerates.
   **Approve & build**.
   - **Check:** twins stream in by segment with a deprivation band; panel-like twins (a
     Shirin-like, a Marcia-like, a Dr Okafor-like) appear; confidence badges and *sees N/M*
     chips appear after a minute. A London patient should not see the West Midlands nurse's notes;
     the GP sees more.
8. **Save lineup** as `screening-home-60`.

### Step 4 — The debate (10 minutes)

1. **3 Debate** → intensity **2**.
2. **Check:** every twin posts; the thread argues about *steps* (the invitation, the order, the
   swab, the result letter, the follow-up), not only about HPV. A post quoting a real national
   figure (68.8%, 4 million, 2040) means research reached the twins.
3. Pause → Resume. Let it finish; the verdict sidebar fills, none stuck on *summarising…*.

### Step 5 — The Lab, part one (15 minutes)

1. **Verdict** on everyone with the session question. **Check:** headline share with an interval,
   a cut picker (deprivation, segment, role, a dynamic dial), every twin's words clickable.
2. **Who answers** (on any tool): set *Deprivation: Q1 most deprived*, then *Region: London*.
   **Check:** head counts show beside each option and the tool runs on that group only.
   Clear it again.
3. **Survey** → template **Reaction**; material: paste *Invitation B* from `04-materials`. Add:
   - single, `Where would you most like to get the kit?` options: `posted home` · `handed to me at the GP` · `over the pharmacy counter` · `at a community event` · `I would not use one`
   - single, `If the kit found HPV, would you go to the follow-up?` options: `yes, straight away` · `yes, if a woman does it` · `only if someone books it for me` · `no`
   Run on 40. **Check:** ranked options, themes coded from the free text, bars click through to twins.
4. **Forms** → Import `questionnaire.txt` → ask everyone. Same checks as Part A step 6.
5. **Barriers**, outcome `Ordering a home kit, sending it back, and going to the follow-up if HPV is found`.
   **Check:** up to seven coded barriers, traced to twins and the evidence they saw.

### Step 6 — Journey, rules and one lever (20 minutes)

1. **Journey** → **Propose**, then edit to the six steps above. **People in scope** → *type my
   own* → `4000000` with its line and source.
2. Run on everyone.
   - **Check, funnel:** six falling bars with share, twins and people (≈4,000,000 at step 1).
   - **Check, candidates:** one card per drop-off with *X% get through*, *N of M stuck*, people
     behind the gap, the movable / system / structural bar, barriers in the twins' words, and an
     equity line Q1 v Q5.
3. **Read by** *Q1 most deprived*: the first drop widens.
4. **Rank behaviours** on the top candidate. **Check:** movement per point with an interval,
   direction, backfire flags; labelled a sensitivity.
5. **Test messages** on *Invited → Ordered a kit* with Invitations A, B and C pasted as three
   messages. **Check:** paired shift per message, winners → indistinguishable → harmful, a
   backfire block, the *modelled reaction, not a forecast* label.
   **Reality check:** C (in person) should win, then B (text), then A (App). Compare with the
   trial in `reality-check.md` — 52% / 12% / 5%. Say whether the order matches and whether the
   gap is compressed.
6. **Rule book**: type the lever above → **Simulate** refuses (no reviewed rule). **Draft the
   rule** → check it applies to women, not professionals; basis *assumption* unless research
   found the trials (then *evidence-anchored*, citing them). Sign with your name → **Simulate**.
   - **Check:** conversion then → now with an interval, moved / fell back / unchanged, rows by
     deprivation band, people moved against the 4,000,000, the rule and reviewer named.
7. **Commit**: target `45% of invited women order and return a kit within 12 weeks`, horizon
   `12 months from the start of the roll-out`, note `Baseline before local support is funded`.
   **Check:** a frozen commitment card.

### Step 7 — Two experiments (10 minutes)

1. **A/B test**, *Rate each*, the two positive-result letters from `04-materials`.
   **Check:** a lift with an interval, who flipped and why, split by segment and deprivation.
   Expect Version 2 (plain language, named nurse) to win, most among the fear-of-a-positive twins.
2. **Choose between** the three leaflet headlines. **Check:** a preference race with intervals.
   C (*Nobody else needs to know*) should win among the private-at-home and examination-avoider
   segments; B (*Most cervical cancers can be prevented*) among professionals.

### Step 8 — Report, export, compare, share (10 minutes)

1. **5 Report** → **Generate Report**. **Check:** a computed confidence band; a direct answer
   about the path, the equity gap and the one change; source chips (official / evidence /
   model-inferred), unsourced numbers struck through; *Where the population drops off* in Journey
   order; the lever record with reviewer and basis; the commitment; named twins with trace cards.
2. **Ask Report:** `If we can fund only two local changes in year one, which two move the most women through to the follow-up, and who is left behind by each?`
3. **Client report** → save as PDF. **Export data** → zip; `run.json` holds the rule and the
   commitment; every file opens with the synthetic-population statement.
4. Regenerate once → **Compare runs**.
5. **Share** with a colleague → **Chat** tab → `@report` question, as in Part A step 9.

### Step 9 — Optional blind pass (research off)

New session, **Research automatically** unticked, **Gather base rates automatically** off, 40
twins. Run Steps 2–6. This is the clean check against `reality-check.md`: the twins have only the
files, which do not contain the trial result. If the in-person offer still wins Test messages,
that is the strongest demo result the tool can give.

---

## What "great" looks like (the client takeaway)

1. A predicted share of the four million at every step, with intervals, and the equity gap at
   each step.
2. The one step that loses the most women, and whether the loss is movable locally.
3. The in-person offer winning, in the same order as the real trial.
4. The plain-language result letter winning, with the segment that disagrees.
5. One committed outcome the real roll-out can be checked against in twelve months.

## Things that look like bugs but are not

- Real national figures in the twins' words: expected with research on.
- Candidates resting on fewer than five twins say so and have wide intervals.
- Editing a reviewed rule puts it back to draft on purpose.
- Twins may place themselves on a different step in the lever arm; the paired set can be smaller
  than the funnel.
- A message test never refuses for want of a rule; only a lever simulation does.
- The confidence badge appears a minute or so after the build.
- The 2024-25 national coverage figure does not exist yet (NHS England delayed it); research
  finding only 2023-24 is correct.
