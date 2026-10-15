# Quick test script — "PedalPass e-bike subscription"

A short, everyday scenario for a **quick (about 20 minute) end-to-end check**: one question, a
few files, a population, a debate, a report and one form. Everything in this folder is invented
test data and says so on the page.

Pass A uses the **Simple view** (the fastest path). Pass B is optional: the same question in the
**Pro** view with a segmentation playbook, to check the newest Studio feature.

## The query (copy exactly)

**Question:**
> Will London commuters pay £15 a month for an e-bike subscription, and what would stop them signing up or keeping it?

**Session title (Pro pass only):** `PedalPass — London commuters`

## The files and where they go

| File | Pass A — Simple view | Pass B — Pro view |
|---|---|---|
| `01-offer-brief.md` (or `.txt`) | *Add anything* box (upload) | Sources → **Documents** |
| `02-facts.txt` | *Add anything* box (paste the text) | Sources → **Text** (paste) |
| `03-commuter-quotes.md` (or `.txt`) | *Add anything* box (upload) | Sources → **Documents** |
| `who-to-ask.txt` | *Who should we ask?* → description (paste) | — |
| `commuters-panel.csv` | *Who should we ask?* → survey file | Twins → Studio → **Your inputs → Survey / panel data** |
| `questionnaire.txt` | Lab tools → Forms → *Already have questions?* | Lab → **Forms** → Import |
| `playbook-commuters.md` | — | Twins → Studio → **Or bring your own segmentation playbook** → Upload .md |

---

## Pass A — Simple view (about 15 minutes)

1. **Start.** On the landing page switch to **Simple**. Type the question above. In *Add anything*
   upload `01-offer-brief.md` and `03-commuter-quotes.md`, and paste the contents of `02-facts.txt`.
   Press **Start**.
   - **Check:** the session opens on *Who should we ask?*.
2. **Who should we ask?** Paste `who-to-ask.txt` into the description. Add `commuters-panel.csv` as
   the survey file. Press **Run simulation**.
   - **Check:** *Getting everyone ready* shows its three steps and moves on by itself to the
     conversation (40 people, nothing else to press).
3. **The conversation.** Let it run to the end (a few minutes).
   - **Check:** people talk about docks near stations, Old Kent Road / main-road safety, showers at
     work, the school run, rain, already owning a bike, the free month. Nobody says "the knowledge
     graph" or "the evidence provided".
   - **Check:** when it ends, three buttons appear: **Talk to a person**, **Make the report**,
     **Lab tools**.
4. **Talk to a person.** Pick a parent or a nurse. Ask: `Would a free helmet change your mind?`
   - **Check:** the answer stays in character and refers to their own commute.
5. **Make the report.**
   - **Check:** a direct answer with a computed confidence band; figures carry source chips (the
     £200 Travelcard and the 38% / 61% pilot figures should appear as evidence, not model-inferred);
     named people render as names you can click.
6. **Lab tools → Forms.** Under *Already have questions?* drop in `questionnaire.txt`.
   - **Check:** five questions land in order: a pick-one (6 options), a yes/no, a 1–10 score, a
     pick-any (4 options), and an open question. The "Thank you… anonymous" line is not a question.
   - Press **Ask the 40 people**. **Check:** *Asking 40 people · N of 40 answered* counts up, then the
     results show. Expected shape: the dock and the free month are the most picked in Q4; safety
     scores are lower for parents and older commuters.
7. Optional, 1 minute: back in Forms, type `price` in *What about?* and press **Write them for me**.
   **Check:** a short form appears that is about the £15 vs £9 decision.

## Pass B — Pro view with a playbook (optional, about 10 minutes)

1. Switch to **Pro**. New session with the title and question above. **Untick Research
   automatically** (keeps the files as the only material). Add the three source files as in the table.
2. **Twins** tab → Studio. Under **Or bring your own segmentation playbook** press **Upload .md**
   and pick `playbook-commuters.md`.
   - **Check:** *What I understood* shows your document section by section; the six segments with
     35% and 15% stated, *find* on Shift workers and Existing cyclists, the planner to estimate the
     rest; *Traffic fear* and *Dock luck* as dials, *Workplace facilities* as a category; the
     three rules; the two doubts. **Use for this build.**
3. Add `commuters-panel.csv` under *Survey / panel data*. Set **40** twins, **Fast**. **Detect &
   plan** → skip the questions → **Plan**.
   - **Check:** the plan keeps your six segments and names (no extra segments); a *Your playbook*
     card lists flags, if any (a flag never changes your numbers).
4. **Approve & build.** **Check:** parents on the school run have high traffic fear (7–9) and mention
   the nursery; existing cyclists compare everything to owning a bike.
5. Optional: run the debate at intensity 2 and generate the report. **Check:** the report's source
   materials name the playbook and list *Dock luck* as an analyst hypothesis.

## What "pass" looks like

- Every **Check** above holds.
- No number of commuters appears without a source; the illustrative figures are traced to `02-facts`.
- The Forms import keeps every question and drops the intro line.
- In Pass B, the build keeps the analyst's six segments.

## Things that look like bugs but are not

- The Simple view turns research on by itself, so real London cycling material can appear beside the
  test files. The test files remain the anchor.
- With research off in Pass B, *find* segments may come back as "none found" — expected.
- The confidence badge beside each person appears a minute or so after the build, not at once.
