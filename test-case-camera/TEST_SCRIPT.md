# Concept test script — "Pip", the programmable keychain camera

A consumer concept test that walks the whole tool once, from an empty session to an exported
report, with **research switched on**. The concept is a camera the size of a keyring fob that you
fix anywhere, connect to an app, and tell in plain words what to do (watch my wardrobe and build me
a shopping-style website of what I own; watch the fridge for food going off; watch the baby in the
next room; watch the doorstep). The app trains a small vision model for that camera from expert and
open-source templates.

Everything in this folder is invented test data and says so on the page. The topic itself is real,
so the research pass will bring in genuine material (Ring, Blink, Wyze, Nanit, Whering, Raspberry Pi
projects, privacy stories, the rules on cameras that see a neighbour's property). That is the point
of this script: the test files are the anchor, the research is the check.

## What we are trying to achieve

1. **Who the population is** — a synthetic population of UK households, matched to a frame built
   from the files *and* the statistics the Studio gathers (deprivation is always one dimension).
2. **Whether people want a camera they programme**, or just another security camera, and which job
   they would set up first.
3. **What a camera is worth** — a demand curve for one camera around £49, and whether anyone pays
   £3.99 a month for Plus.
4. **Where people drop off** between hearing about it and still using it three months on, with the
   number of households behind each gap and what stands in the way in the twins' own words.
5. **Whether "nothing leaves your home" persuades the privacy-worried** — first as a message test,
   then as a written, reviewed rule and a counted shift.
6. **A report a client could read**, an export, a comparison between two runs, and one committed
   outcome the next test can check against.

If every step below produces what it says it should, the tool works end to end on a consumer
concept with research on.

## The files and where they go

| File | Where to put it | What it is |
|---|---|---|
| `01-concept-brief.md` | 1 Sources → **Documents** (upload) | The concept as a respondent would see it, prices, levers, what cannot change |
| `02-market-facts.md` | 1 Sources → **Text** (paste the contents) | Illustrative statistics with test sources, including the sizing rows |
| `03-early-reactions.md` | 1 Sources → **Documents** (upload) | Fourteen short concept-screener quotes |
| `04-use-case-cards.md` | 1 Sources → **Documents** (upload), and copied into the Lab as material | The six one-paragraph use-case cards |
| `audience-profile.txt` | 2 Twins → Studio → **Your inputs → Audience profile** (paste) | Who to build, in one paragraph |
| `respondents-panel.csv` | 2 Twins → Studio → **Your inputs → Survey / panel data** (*Upload respondents to mirror*) | A 14-row panel the Studio reads as a survey |

## The queries to type (copy exactly)

**Session title:** `Pip programmable camera — UK concept test`

**Session question:**
> Would UK households buy a £49 keychain-sized camera that they can teach to do a job in plain words (track my wardrobe, watch the fridge for food going off, watch the baby, watch the doorstep), which job would they set up first, and what stops them between being interested and using it every day?

**Journey steps** (the tool proposes its own; replace them with these six so every tester gets the same run):

1. `Has heard of Pip` — has seen or been told about a camera you can teach to do a job
2. `Interested enough to look` — has read the concept and one use-case card
3. `Buys a camera` — has bought one camera or the three-pack
4. `Sets it up with a first job` — camera connected and a first task chosen and trained
5. `Task working after a week` — the alerts or website are useful, not ignored
6. `Still using it at three months` — the camera is still where it was put, doing the job

**People in scope:** `25600000` · what it counts: `UK households with home broadband and at least one smartphone` · source: `Ofcom Technology Tracker 2025 (test figure)`

**Lever for the rule:** `No cloud, ever mode with a what-it-sees screen`

**Purchase-intent stimulus (run 1):** `One Pip camera: keyring-sized, 1080p, night vision, magnetic back, three-day battery or plug-in. Fix it anywhere, connect it in the app, tell it in plain words what to watch for. Everything is processed on the camera and your phone. Price £49, one-off.` Price `49`, GBP.

**Purchase-intent stimulus (run 2):** `Pip Plus: the private shopping-style website of your wardrobe, sharing with family, 30 days of event history, unlimited retraining. £3.99 a month, cancel any time.` Price `3.99`, GBP.

---

## Step 0 — Before you start

- On prod, do not push to main while this runs: a deploy kills in-flight research, builds and
  debates.
- Budget about 90 minutes and read the cost line before research, build and debate. This script
  uses **60 twins, Fast**, intensity 2.

## Step 1 — Create the session with research on (10 minutes, mostly waiting)

1. On the landing page type the title and the question above.
2. **Leave Research automatically ticked.** Create.
3. **Check, research frame:** the sub-questions it writes should cover, in some form, (a) what
   home cameras cost and what people pay monthly, (b) baby monitors, (c) fridge or food-waste
   cameras and apps, (d) wardrobe apps, (e) whether people trust on-device claims, (f) the rules on
   home cameras that see other people's property. If the frame is only about security cameras, note
   it: the concept is broader and the frame should be too.
4. **Check, the search:** queries stream with engine names. Expect finds naming things like Ring,
   Blink, Wyze, Eufy, Nanit or Owlet, Whering or Stylebook, Samsung Family Hub or fridge cameras,
   Raspberry Pi or Edge Impulse projects, the ICO's guidance on domestic CCTV, and at least one
   story about a camera brand's privacy promise being broken. Off-topic finds are greyed, not hidden.
5. **Check, social listening:** Reddit items land with a relevance score. Likely homes:
   r/homeautomation, r/smarthome, r/raspberry_pi, r/homesecurity, r/UKParenting, r/beyondthebump,
   r/femalefashionadvice (wardrobe apps), r/privacy. A 403 in the log followed by a Chromium retry
   is normal.
6. **Regression check:** press **Stop** once, mid-gather. Status goes stopping → finalising →
   stopped within seconds and a brief is still produced. Then start a fresh session and let the
   research run to the end for the real pass. (Or do the Stop check on the optional second pass.)
7. **Check, evidence brief:** the result line reads first. Stakeholder groups should include at
   least *parents*, *privacy-worried adults*, *existing camera owners* and ideally *tenants and
   landlords* or *neighbours*. The stance tile is blank rather than 0/0/0 if it found no stances.
   Under *How it searched* the queries, judge notes and budget are folded away.
8. **Check, recommended tools:** it should suggest purchase intent or price sensitivity and a
   concept survey, each mapped to where it lives in this app, with an **Open the Lab** button.

## Step 2 — Add the four files (5 minutes)

1. 1 Sources → **Documents**: upload `01-concept-brief.md`. Wait for it to finish.
2. 1 Sources → **Text**: paste the whole of `02-market-facts.md`. Submit.
3. 1 Sources → **Documents**: upload `03-early-reactions.md`, then `04-use-case-cards.md`.
4. **Check:** the status dot goes to *ready*. Open **What they know**: you should see nodes such as
   *Pip*, *Pip Plus*, *on-device*, *wardrobe*, *fridge*, *baby monitor*, *false alerts*, *Ring*.
   Click *Ring*: it should list both a test chunk (Derek's quote) and a research chunk. Click
   *on-device*: relations should connect it to trust and to the privacy figures.
5. Switch the dropdown to **Ontology**. **Check:** typed nodes include products (Pip, Ring, Blink),
   use cases (wardrobe, fridge, baby, doorstep, pet, older relative), concerns (privacy, false
   alerts, battery, subscription), and prices.

## Step 3 — Build the population (15 minutes)

1. Open **2 Twins**. It is the Population Studio while there are no twins.
2. Set the twin count to **60** and the mode to **Fast**.
3. Under **Your inputs → Audience profile**, paste the contents of `audience-profile.txt`.
4. Under **Your inputs → Survey / panel data**, press *Upload respondents to mirror* and pick
   `respondents-panel.csv`.
5. Under **Statistics**, leave **Gather base rates automatically** on. Tick the sources with a
   green dot; ONS, Ofcom and YouGov are the useful ones here. Optional: in the search box type
   `UK households smart home camera ownership 2025` and press Enter; a page with usable facts
   should land in the *pages read* count and in the Sources feed.
6. Press **Detect & plan**. **Check:** the detected population is *UK households* or *UK adults
   at home*, not *camera makers* or *parents* alone (the files mention all three; the question is
   about households). The proposed dials should be this question's own: things like *privacy
   comfort*, *belief in on-device claims*, *tolerance of false alerts*, *willingness to set up
   tech alone*, *food waste at home*, *interest in clothes*. Each dial says where it came from.
7. **Check, frame:** the frame speaks first in one sentence. Dimensions are named by label, and
   **deprivation** is one of them. Expect also something like *life stage* (child under three),
   *already owns a camera*, *tenure* (owner / renter), *region*. Each shows a target share from a
   real source found by gathering, or from the files, or says none was found. Hover the worst-cell
   and effective-n chips.
8. **Check, sizing:** the frame's sizing trio reads from the files: 28.4m households, 25.6m with
   broadband and a smartphone, and a third figure (owners of a camera, or the 31% who would
   consider one at £49). Each carries its test source.
9. **Clarify**: answer one question (for example *are we asking people who already own a camera, or
   everyone?* — answer: everyone) or tick *skip the questions*.
10. **Plan**. **Check:** five to seven segments resembling: new parents weighing a smarter monitor;
   settled security-camera owners who are content; tinkerers who have built it themselves;
   fashion-led wardrobe users; food-waste-conscious households; privacy sceptics who believe no
   on-device claim; adult children caring for a parent; renters and over-60s who will not set it
   up alone. Shares add to 100%. **Registers must vary** — the sceptics and the over-60s should
   not come back *expert*.
11. **Review**: change one segment's share and watch the others rescale. Reject one with a reason
   (`too generic — split by whether they already own a camera`); it regenerates addressing the
   reason. Then **Approve & build**.
12. **Check:** twins stream in by segment. Each card has a segment badge and a deprivation band;
   every number on a card has a hover; the roster groups by segment. Fourteen of the twins should
   read like the panel rows (a Hannah-like parent, a Marcus-like sceptic, a Tom-like tinkerer, a
   Margaret-like set-it-up-for-me retiree), with stances drawn from the panel. After a minute a
   **confidence badge** appears beside twins as validation runs, and a *sees N/M* chip shows how
   much of the material each twin can see. A Marcus-like twin should *see* the privacy figures and
   the broken-promise research; a Chloe-like twin should see the wardrobe material.
13. On the roster press **Save lineup** and name it `pip-uk-60`.

## Step 4 — Run the debate (10 minutes)

1. **3 Debate** → start at intensity **2**.
2. **Check:** every twin posts at least once. Parents talk about the cot and what is uploaded;
   sceptics about brands that broke the promise; tinkerers about templates and Raspberry Pis;
   renters about mounts and drilling; over-60s about who sets it up; students about £49 versus
   £29. Nobody says *the knowledge graph* or *the evidence provided*.
3. **Feature-level check:** the thread should argue about the *jobs* (wardrobe versus fridge versus
   baby versus doorstep) and about Plus as a separate thing, not review "the camera" as one lump.
   If every post is about security, the composite concept did not survive the build; note it.
4. **Check:** a post that names a real product or figure from the research (a Ring subscription
   price, the Eufy story, the ICO rule) is a good sign; it means research reached the twins.
5. Pause → posts stop → Resume → they continue. Let it finish. **Check:** the verdict sidebar
   fills with one line per twin, none stuck on *summarising…*.

## Step 5 — The Lab, part one: does anyone want it, and at what price (15 minutes)

1. **4 Lab** → **Verdict**, run on everyone with the session question. **Check:** a headline
   share with an interval, positions, a cut picker that recounts (read by deprivation first, then
   by segment, then by the *privacy comfort* dynamic dial), and every twin's words clickable to
   the twin. Expected shape (not exact): *for* somewhere between a third and a half, with the
   parent and tinkerer segments for and the sceptics and content-owners against.
2. **Survey** → template **Concept test**. Material: paste the concept section of
   `01-concept-brief.md` (from *Pip is a camera…* to the end of the price table). Keep the six
   template questions and add two:
   - single, `Which job would you set up first?` options: `wardrobe website` · `fridge and food` ·
     `baby in the next room` · `doorstep and parcels` · `pet` · `older relative living alone` ·
     `none of these`
   - multi, `Which of these would you pay £3.99 a month for?` same six options plus `none`.
   Run on 40 twins. **Check:** appeal shows a mean with an interval and top-two box; *need* and
   *intent* show distributions; the first-job question gives a ranking (expect doorstep and fridge
   near the top, wardrobe low overall but high in one segment); the pay question shows far fewer
   ticks than the first-job question; the free-text answer to *what would you change* is coded
   into themes (expect *prove the on-device claim*, *battery*, *false alerts*, *price*,
   *someone to set it up*). Click a bar to see the twins behind it.
3. **Purchase intent** → stimulus run 1 (one camera at £49). **Check:** the cost line reads in
   words before you press run; live dots fill; buy share with an interval; driver mix (expect
   *need* and *price* to dominate, *trust* strong in the sceptic segment); a **demand curve** with
   a revenue-optimal price (the panel's ceilings run £29 to £70, so expect it to land near or a
   little under £49); the share whose walk-away price clears £49 and the contradiction count.
4. **Purchase intent** → stimulus run 2 (Plus at £3.99 a month). **Check:** a much lower buy share
   than run 1; *subscription fatigue* or *another monthly fee* appears in the reasons; the
   wardrobe segment is the one that buys.
5. **Barriers** with the outcome `Buying one Pip camera and using it every day`. **Check:** at
   most seven coded barriers ranked by count then weight, each traced to the twins who said it and
   the evidence those twins could see; expect *does not believe on-device*, *false alerts*,
   *battery and charging*, *another subscription*, *setup alone*, *mount falls off*, *legal risk
   with tenants or neighbours*.

## Step 6 — The Journey, the rule book and one lever (20 minutes)

1. **Journey** → press **Propose**. Read what it proposes, then edit it to the six steps above.
2. Under **People in scope** tick **type my own** and enter `25600000`, the what-it-counts line
   and the test source line.
3. Run on everyone.
4. **Check, funnel:** six bars, falling. Every step shows a share, a count of twins and a number of
   households (≈25.6m at step 1, fewer at each step). The line under the funnel names the biggest
   drop-off and its top barrier.
5. **Check, candidates:** one card per drop-off, ranked. Each shows *X% get through* with an
   interval, *N of M stuck*, households behind the gap with a range, a coloured bar split into
   **movable / system / structural**, the barriers in the twins' words with a lever and who could
   pull it, and an equity line comparing Q1 most deprived with Q5 least deprived. If the bar says
   *movability not scored*, run once more; if it still does, report it as a bug.
6. Expected shape (not exact numbers): the biggest drops are *Interested enough to look → Buys a
   camera* (price and the trust question) and *Task working after a week → Still using it at three
   months* (false alerts, charging, the mount). Battery and mounts should come out **structural**
   (the company said it cannot change battery life quickly); the trust and setup barriers should
   come out **movable**.
7. Change **Read by** to *Q1 most deprived*. **Check:** the funnel and candidates recount for that
   band, and the price barrier grows.
8. **Rank behaviours** on the top candidate. **Check:** one row per behaviour dial, movement per
   point with an interval, direction to push, a backfire flag where a nudge hurts a band. Expect
   *privacy comfort* and *technical difficulty* near the top; it is labelled a sensitivity, not a
   forecast.
9. **Test messages** on the same candidate with these three:
   - `Everything is processed on the camera and your phone. Nothing is uploaded.`
   - `Everything is processed on the camera and your phone. The app shows a live log of every byte the camera sends, and an independent lab checks it every year.`
   - `Your footage stays in your home. If it ever leaves without your say-so, we pay you £500.`
   **Check:** paired shift per message with a weighted shift, ranked winners → indistinguishable →
   harmful, a backfire block, and the label *a modelled reaction to a framing, not a forecast of
   uptake*. Expect the second to beat the first among sceptics; the third may backfire (reads as
   a gimmick).
10. **The rule book.** Press **Rule book 0/0**: *No rules yet*. On the top candidate, under
    *Simulate a lever*, type the lever above. **Check:** a yellow line says no reviewed rule
    exists; **Simulate** refuses and names the missing rule; nothing runs.
11. Press **Draft the rule** (let the system write it). **Check:** it fills lever, description,
    who it applies to, dial changes and a basis, with the basis class shown as *assumption* unless
    it cites the privacy figures (then *evidence-anchored*). Expected dial changes, in whatever
    exact numbers it picks: trust group → *privacy_comfort* up, *transparency* up; friction group
    → *emotional_resistance* down, *technical_difficulty* down. If it drafts something wildly
    different, edit it to that shape and note the difference. Save as draft. **Check:** *draft ·
    not yet reviewed*; Simulate still refuses.
12. Type a reviewer name, **Sign off**. **Check:** *reviewed · name*; the card shows *Rule on
    file* with the dial changes. Press **Simulate**. Wait one to three minutes.
13. **Check, result block:** conversion at the step *then → now* with a signed shift and an
    interval, twins *moved through / fell back / unchanged*, the end of the journey *then → now*,
    rows by deprivation band, and *households moved* with a range. It names the rule, its reviewer
    and the basis class. Expect the sceptic segment to move most and the content-owners not at all.
14. Under **Commit to this outcome** on the top candidate, sign with your name, target `30% still using
    at three months`, horizon `Q2 2027`, note `Baseline before pricing change`. Press commit. **Check:** a commitment card appears, frozen, with the population build, the evidence
    count, the rule and the statement. Press the pencil on the rule, change nothing, save: the rule
    goes back to draft and Simulate refuses until it is re-signed; the commitment card is unchanged.

## Step 7 — Two experiments (10 minutes)

1. **A/B test**, *Rate each*, purchase-intent base, stimulus run 1 for both arms, with one line
   changed:
   - A: `Pip Plus: £3.99 a month for the wardrobe website, sharing and 30-day history.`
   - B: `Pip Home Box: £29 one-off. The wardrobe website and history are served from a small box in your home. Nothing online, ever.`
   **Check:** a lift with an interval, who flipped with both reasonings, and a split by segment.
   The direction is genuinely open (one-off beats monthly for most; the box adds setup for the
   over-60s); that is the point.
2. **Choose between** with three launch lines:
   - A `One tiny camera. Any job you can describe.`
   - B `It learns your home. Not the internet's.`
   - C `The baby monitor that tells you, not just shows you.`
   **Check:** a preference race with intervals, winner settled or not, per-option themes. If the
   whole population picks C, the launch is a baby monitor and the report chat should say so.
3. Re-run purchase intent run 1 with the same seed. **Check:** the same twin sample.

## Step 8 — Report, export, compare (10 minutes)

1. **5 Report** → **Generate Report**. **Check:**
   - A direct answer with a confidence band that is *computed* from the headline record (hover
     for the basis), not asserted; the answer engages with £49 *and* separates the jobs (which
     drive purchase, which are dead weight).
   - Figures carry coloured chips: official statistic / evidence / model-inferred. A research
     figure and a test figure that disagree should both be present with their own chips, and any
     number with no source is struck through.
   - A section **Where the population drops off** in the same order as the Journey page, with
     households and movability.
   - A lever record naming the rule, its reviewer and *assumption* or *evidence-anchored*.
   - The committed outcome listed under committed outcomes.
   - Named twins render as names with a trace card; click one → *Talk to this twin*.
2. **Ask Report:** `If we could ship only two use-case templates at launch, which two, and which segment do we lose with each cut?` **Check:** named twins, the survey's first-job ranking, and the Plus attach figure.
3. **Talk to this twin:** pick the most hostile privacy sceptic and ask what, if anything, would
   make them believe an on-device claim. Markdown renders.
4. **Client report**: a clean print page with every citation resolved. Save as PDF.
5. **Export data**: a zip. Open `run.json`: the rule with its reviewer and the commitment are
   inside; every file carries the synthetic-population statement at the top.
6. **Regenerate** the report once, then **Compare runs**. **Check:** it lists what changed —
   headline and whether the change is real, positions, equity gap, dissent, barriers, evidence
   base, confidence.
7. Reload the page. **Check:** the last report and the Ask-Report questions are still there.

## Step 9 — Optional second pass (research off)

Repeat Steps 1 to 6 in a new session with **Research automatically unticked** and **Gather base
rates automatically** off, 40 twins. Compare with the first pass:

- the frame should now say *none found* on more dimensions and the sizing should rest on the
  test rows only;
- the barriers should be the same shape but with no real product names in the twins' words;
- the report's chips should be almost all *evidence* (the test files) and *model-inferred*, with
  no *official statistic* chips.

If the two passes disagree on the *direction* of the headline, that is a finding about the tool,
not about the concept. Note it.

## What "great insights" look like from this run

The run has succeeded as research if the report can answer these with named twins and numbers:

1. A predicted top-two-box appeal band and buy share at £49, and which two segments carry it.
2. The first-job ranking, and whether the launch should lead on doorstep, fridge or baby.
3. The revenue-optimal price for one camera versus £49, and the Plus attach rate versus the
   one-off Home Box.
4. The size of the trust gap (twins who like the idea but do not believe on-device) and how far
   the what-it-sees screen closes it, as a counted shift with an interval.
5. Which barriers are structural (battery, the mount, "it is a camera") and therefore not worth a
   marketing pound.

## What "pass" looks like

- Every step above shows what it says it should.
- No number of households appears anywhere without the 25.6m denominator behind it.
- Nothing is simulated for a lever without a reviewed rule.
- Research material and test material both appear in the report, each with its own source chip,
  and the twins' barriers match their own words rather than drifting to web material.
- The report only repeats candidates, barriers, movability, lever shifts and message results that
  the Lab computed; it never invents its own.

## Things that look like bugs but are not

- Real product names and prices mixing into the debate: expected with research on; the test files
  are the anchor.
- Candidates that rest on fewer than five twins say so and have very wide intervals.
- Editing a reviewed rule puts it back to draft on purpose.
- The left-hand Journey builder shows the *current* steps; the results on the right are from the
  *last run*. Pressing *Propose again* changes the left without changing the right.
- Twins may place themselves on a different step in the lever arm; the paired set is the at-risk
  twins in both arms, so the counts can be smaller than the funnel's.
- A message test never refuses for want of a rule; only a lever simulation does.
- Reddit 403s over plain HTTP followed by a Chromium retry are normal. Statista teasers with no
  number are dropped by design.
