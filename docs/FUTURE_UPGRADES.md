# Future upgrades

Ideas for the tool that are agreed in spirit but not yet built. Each entry says what it
is in plain words, why it matters, how it would fit the current system, and what order to
build it in. When an entry is built, move its dated summary to the blueprint's Changelog and
delete it here.

Related: `PRODUCT_BLUEPRINT.md` (what exists today), `docs/visual-lab-brief.md` (the
image line this list extends), `docs/doorda-sources-analysis.md` (2026-10-27: what Doorda
aggregates, which publishers sit underneath, and the open-data layer — spreadsheet reader,
publisher APIs, new registry entries — we should build instead of buying it),
`docs/oasis-analysis.md` (2026-10-27: what the OASIS social-media simulator does and the six
mechanics worth taking — a Spread tool, engage-or-scroll, drop-ins and forks, opinion over
time, a per-twin feed, social-proof arms).

---

## 1. The Video Lab — populations watch videos from a shared link

*Raised by Drishan, 2026-10-27, as a brainstorm.*

**The idea in one line.** A user pastes a YouTube (or TikTok, Instagram, X) link into the
tool, the population watches the video, and the analyst can ask which of several videos is
better, where people would have swiped away, and which could have earned more likes.

### The core idea: a video is just another "piece" the twins look at

Today a Visuals run shows one to six images under captions. A video would become a stored
piece made of three things the model can actually read:

- a **strip of frames** sampled through the clip, each stamped with its time;
- the **transcript** (auto-captions, or speech-to-text when there are none);
- the **on-screen text and captions**, read once by a vision call.

Claude cannot watch video, so the pipeline turns a clip into those parts **once per video**,
stores them the way images are stored now (bytes on the row, see §6.15 of the blueprint),
and the probe runner shows them to every twin with the same *what you are looking at*
paragraph. Everything downstream — Compare, the A/B test, themes, the report, the "next
version" flow — works unchanged.

### Getting the video from a link

- **YouTube** is the easy one. The official Data API gives title, description, views,
  likes, comments, duration and publish date with a key. The clip and its auto-captions
  come down with yt-dlp. Both run fine from Railway.
- **TikTok, Instagram, X** have no usable public API for this. yt-dlp handles many of
  them but is blocked often. Bright Data has YouTube, TikTok and Instagram scrapers that
  return clean JSON (the plugin is already in the workspace). That is the honest route.
- **Fallback** is a plain file upload, so the feature never dead-ends on a blocked link.

### What the twins can be asked

Three instruments, in order of value:

1. **Watch** — the Visuals instrument for video: what hooked them in the first three
   seconds, where they would have swiped away, what they took it to say, the one thing
   they would change. Because the frames carry timestamps, *where they dropped off*
   becomes a drop-off curve by segment.
2. **Compare** two or more videos through the existing choose-between A/B: which one
   they would watch to the end, like, share or comment on. That is the "which video is
   better" answer, by segment, with the words behind it.
3. **Thumbnail and title test** — cheap, and probably where most of the likes decision
   really lives. It is the image lab with a title string attached.

### "Which could have got more likes" needs care

The twins give a **reaction, not a forecast**. To make it a prediction, anchor it: pull the
real metrics for both videos, ask the population blind, then show the analyst how the twins'
preference matched the actual gap. Over a few runs that gives a calibration number that can
be quoted. Until that calibration exists the report must not say *would get more likes*;
it says *preferred by X%, and here is why*.

### Cost and limits to design around

- A 60-second clip at one frame every three seconds is about 20 frames. At current image
  pricing (≈ width × height / 750 tokens per frame) that is roughly 30,000 tokens per twin
  per showing, so a 200-twin run costs about ten times a poster run.
- Sample smarter: scene-change detection instead of fixed intervals; fewer frames on the
  Standard tier; and a short written **shot list** the model writes once that the twins
  read instead of the frames themselves (frames only for the hook and the end).
- Store the derived parts, not the full video, for the same reason images live on the row:
  the disk is wiped on every deploy and a Lab result must keep what it was measured on.
- Keep the real metrics (views, likes, comments, publish date) on the piece so the report
  can cite them and the calibration step has something to compare against.

### Build order

1. **Link in, Watch out.** Paste a YouTube link → metadata + frames + transcript stored as
   a piece → shown through a *Watch* instrument with a drop-off curve. Upload as fallback.
2. **Compare and the thumbnail test.** Video arms in the A/B test; thumbnail + title as an
   image run.
3. **Calibration and the next version.** Blind preference vs real likes; then the existing
   propose → tick → make flow proposes a re-cut, a new hook or a new thumbnail.
4. **The other platforms** via Bright Data (TikTok, Instagram, X).

**Open questions.** Which tier runs vision on frames by default; whether the shot list
replaces frames entirely on Standard; whether the Simple view gets Watch before Visuals
settles there.

---

## 2. Opinion over time — did the conversation move anyone?

*From the OASIS analysis (`docs/oasis-analysis.md`), chosen by Drishan, 2026-10-27.*

**The idea in one line.** Ask the population the verdict question at the start of a run,
part-way through and at the end, and show how minds moved and who moved them.

### What it does

Today the verdict is read once, after the debate. The question clients ask afterwards is
*did anyone change their mind, and why?* — the same question the Journey work kept running
into in October (*what changed between then and now*). With this, a run carries snapshots:
at the first phase, at a chosen middle point and at the end, the verdict instrument is put
to everyone, blind to their own earlier answers (the Visual Lab's re-test already hides a
twin's earlier answers through `Probe.spec.retest`). The result is a line per group — for,
against, mixed and confidence over time — and the polarisation index (already in
`stats.py`) as a curve rather than a single number. OASIS does the same thing by asking its
agents the same question every ten steps and having a judge say which answer is more
extreme; we can plot the drift directly, with intervals.

### How it fits

- A `snapshots` option on the run (default off; the simple view could turn it on for every
  run, since it is cheap). Each snapshot is an ordinary verdict probe tagged with the phase
  or step it was taken at, so the Verdict page's cuts and *in their own words* work
  unchanged.
- A new picture on the Thread tab and in the report: the lines by segment, and the twins who
  moved, with their before and after reasoning side by side.
- This does not break the *no re-polling twins* rule. That rule is about fixing a weak
  report by asking the same question again. Here the re-ask is the measurement: same
  question, different time; what they have read in between is the variable.

### Cost and limits

Three snapshots on a 200-twin run is 600 Haiku calls, about the cost of one more phase. The
snapshots sit between phases, so they do not slow the posting.

### Build order

1. The snapshot option and the tagged verdict probes.
2. The lines by segment and the movers, on the Thread tab.
3. The same block in the report and the simple view (*How minds changed*).

---

## 3. Drop-ins and forks — "if we respond this way, what changes?"

*From the OASIS analysis, chosen by Drishan, 2026-10-27.*

**The idea in one line.** Put a post into the debate at the current point — the brand
replies, a journalist weighs in, a correction lands — and let the debate continue; fork the
run there to compare two responses.

### What it does

A run today goes start → stop and nothing can be inserted. OASIS lets the researcher inject
a post from any account at any step and carry on. Here it becomes a **Drop in** control on
the Thread tab: pick who speaks — the brand's official account, a named outsider (a
journalist, a regulator, a local councillor), or one of the twins — write the post, and it
lands in the thread; the next phases read it like any other post, and the drop-in is marked
so the report knows it was not a twin's own words. A **Fork** snapshots the run at that
point and runs two continuations — drop-in A against drop-in B, or with against without —
and compares them the way the A/B test compares arms: verdict share, engagement, who moved,
in their words. This closes the *scenario branching — not built* line in blueprint §11a.7.

### How it fits

- A drop-in is a `SimulationPost` with an `actor` field instead of an agent, carrying the
  name and role shown to the twins (*Official account of …*, *Local reporter*).
- A fork is a second run that starts from a copy of the thread up to the fork point; the
  phase engine already takes the thread as a snapshot per phase, so the continuation is the
  same code with a different starting transcript. The comparison reuses the experiments
  layer's lift, flips and sentence, with the debate's verdict as the metric.
- Simple view: *Add a reply from…* and *See what changes*, in the same spirit as the
  Journey's rules box.

### Cost and limits

A drop-in costs nothing until the next phase runs. A fork costs a second continuation
(the remaining phases × twins). The drop-in's text is the analyst's, so the report must
show it as a stimulus, never as evidence of what people said.

### Build order

1. Drop in (actor, text, lands in the thread, marked in the report).
2. Fork at the current point, two continuations, the comparison page.
3. The simple-view wording.

---

## 4. Engage or scroll past — what share would even notice?

*From the OASIS analysis, chosen by Drishan, 2026-10-27.*

**The idea in one line.** Before a twin writes anything, let it decide whether it would
react at all, so *engagement rate* becomes a number the report can quote.

### What it does

The debate guarantees every twin a comment, by design: a focus group gives everyone a turn.
The cost of that guarantee is that we can never say *72% would have scrolled past*. In
OASIS *do nothing* is an action every agent may pick, so the share who ignore a post is
measured. Here it is one cheap call before the post — *you have just seen this in your feed:
scroll past, like, reply, share or quote?* — with the standing block and the dials, on
Haiku, a few dozen tokens. The answer is stored as the twin's engagement decision; a
*scroll past* is a result, kept out of nothing, in the same spirit as the Lab's refusals.

### How it fits

- A run option, off by default in the pro debate so the coverage guarantee stays; on by
  default in the Spread tool (entry 6), where it is the core mechanic; and available as a
  flag on any Lab instrument that shows a piece (Ask, Visuals, Forms with material), so a
  poster run can say *noticed and read it: 41%* before *works on them: 38%*.
- Engagement rate by segment joins the headline strip; the report gets one line: *most of
  this population would not have stopped for it*.

### Cost and limits

One short Haiku call per twin per phase where it is on. A twin that scrolls past still
posts in the debate when the guarantee is on; the decision is recorded, not enforced.

### Build order

1. The decision call and its stored field.
2. The share by segment on the Lab page and in the report.
3. On by default in Spread.

---

## 5. Social-proof arms — the thing, or the crowd around it?

*From the OASIS analysis, chosen by Drishan, 2026-10-27.*

**The idea in one line.** In the A/B test, show the same stimulus with and without an
engagement line and critical comments, and measure how much the crowd changes the reaction.

### What it does

OASIS's herd experiment seeds the same post with an early up-vote, a down-vote or nothing
and finds that later agents follow the early signal. The marketing version: a variant
option *shown with social proof* — the stimulus with a line such as *1.2k likes · 340
comments · top comment: "…"* — or *shown with pushback* — two critical comments under it —
against the bare version. The lift between the arms is the share of the reaction that comes
from the crowd rather than the piece.

### How it fits

- A field on the variant's spec (`social_context`: none / proof / pushback, with the text)
  and a line in the directive telling the twin what it sees under the piece. Works on Ask,
  Visuals and, later, Forms with material. No new instrument.
- The report must say *shown with / without*, because the number measures susceptibility,
  not the piece itself.

### Cost and limits

No extra calls beyond the arms themselves. The engagement line is invented by the analyst,
so it is a stimulus, labelled as one.

### Build order

One step: the spec field, the directive line, the label on the results page.

---

## 6. The Spread tool — will this travel, and through whom?

*From the OASIS analysis, chosen by Drishan, 2026-10-27. The biggest item; build it after
entries 2–5, which supply most of its parts.*

**The idea in one line.** Drop one message into a population that knows each other, run
the clock, and watch where it goes: how far, how fast, through which people, and which of
two phrasings travels further.

### The core idea: the twins know each other

Today the twins are strangers in a room who all hear everything. In Spread they are a
small society where each one knows a few others, and a message only moves along those
links. Nobody types the links in; they are drawn when the population is built, from what
the plan already knows:

- **same segment, same place** — two young renters in Hackney are very likely linked; a
  retired homeowner in Surrey and a student in Leeds almost never are;
- **same job or situation** — nurses follow nurses, parents at the same kind of school
  follow each other;
- **a few bridges** — twins with a foot in two worlds, through whom a message crosses;
- **a few loud ones** — the local councillor, the community page, the influencer, with many
  followers, where the plan names them.

The result is a real-looking social map: dense clusters of similar people, thin threads
between clusters, a few hubs. The map shows in the Studio beside the lineup (*who knows
whom*), and the analyst can change it (*make these groups more connected*, *add a local
news account half of them follow*). The links are plausible, not real — a reasonable guess
that shapes the run, as the dials are.

### What a run does

1. **One message, one source.** A post, a headline, a poster from the image store, a claim;
   put out by the brand's account, a news outlet or a chosen twin.
2. **The clock runs.** Steps of sim time (say an hour each over three days). At each step
   only some twins are awake — an activity curve per twin from the `habit` dials (unused by
   the debate today) and the frame's heavy / light social-user figures where published.
3. **Each awake twin sees its own feed**, not the thread: a couple of posts from people it
   follows, one that is doing well (Reddit's hot score: votes against age), one at random
   (OASIS swaps 10% of slots for random posts so a feed is never a pure echo). No
   embeddings: interest from segment, standing and dials, or a cheap topic tag per post.
4. **It decides** (entry 4): scroll past, like, share, reply, quote. Sharing is what moves
   the message: the twin's followers see it at their next wake-up. If nobody in a group
   shares, it dies there.
5. **Everything is logged** — who saw what, when, and what they did (OASIS's `trace`
   table). Reach needs *who saw it*, not just who posted.

### What you get

- **A reach curve** — seen / engaged / shared after an hour, six hours, a day, three days.
- **Reach by segment** — it took off among young renters and never reached retired
  homeowners, because nobody who bridges those groups shared it.
- **The shape** — wide and shallow (one big account, everyone saw it once) or narrow and
  deep (hand to hand through a chain of friends): depth, breadth, scale, as OASIS measures.
- **Who carried it and who pushed back**, in their own words.
- **A versus B** — two phrasings as A/B arms: which travels further, through whom.

*Example.* A council announces a cycle-lane scheme two ways: *New protected cycle lanes
coming to your high street* and *Fewer parking spaces on the high street from March*. The
first spreads among commuters and parents and dies among shopkeepers; the second spreads
twice as far, through shopkeepers and older residents, mostly with an angry comment. Not a
forecast, but the shape says where the fight will be and who to reach first.

### How it fits

An ordinary Lab instrument (§11a.3): inputs (the message, the source, the clock settings),
its own aggregator and KPIs, metrics so two seeds can be A/B arms, its own page. New
pieces: the follow network on the population (built at spawn, editable in the Studio), an
activity curve per twin, a per-twin feed, an exposures log, and a step engine beside the
phase engine. Once the feed exists it can also replace the shared transcript in the debate
(each twin reads what a real feed would show it; the independent-voice share becomes a feed
setting), but that is a change to how every debate reads and should wait until Spread has
earned it.

### What it is not

It cannot say *this will get 40,000 views*: real spread depends on the platform's
algorithm, the news that day and luck. OASIS earned its claims against real Twitter
cascades (real profiles, the real source tweet, the real cascade's depth and breadth over
time). Until we test against a real post with a known history — a tweet's or a YouTube
video's view and like curve, the same calibration the Video Lab asks for — the honest
reading is *A travels further than B, through these people*, and the page says so.

### Cost and limits

Haiku for every step action. 200 twins × 20 steps × 10% awake ≈ 400 calls, a Fast
debate's worth. Store the exposures log on the run, since it is what the result was
measured on.

### Build order

1. The follow network at spawn, shown in the Studio.
2. The step engine: clock, activity curve, per-twin feed, the engage decision, the
   exposures log.
3. The Spread instrument: reach curve, reach by segment, shape, carriers and pushback.
4. Two seeds as A/B arms.
5. A cascade benchmark, alongside the Video Lab's calibration.
6. The feed in the debate, if Spread shows it reads better.

**Open questions.** Whether the engage decision runs on every debate by default or only
in Spread; how the follow network is presented in the Studio (a map, or a sentence per
group); whether Spread lands in the simple view as *Will this travel?* before or after the
Video Lab's Watch.

---

## 7. The million-twin tier — Jev decides, Claude speaks for the few

*Raised by Drishan, 2026-10-27, after the OASIS analysis: use a decision model (Jev) for
large-scale runs — no reasoning or advice from the twins, only actions, which we analyse to
work out the reasons; and manufacture a million twins with their sentiment dials and a much
smaller system message. Extends entry 6 (Spread), which supplies the clock, the network and
the feed. Nothing built; nothing calibrated.*

**The idea in one line.** A million twins built from the sampling frame without a model,
each one a short card; a decision model that returns probabilities instead of text decides
what every twin does when it sees something; Claude writes only for the few who reply; the
reasons come out of the numbers.

### What Jev is

TypeSafe AI's "decision model" (early access since September 2026; `typesafe/jev-1.14` on
OpenRouter, also TypeSafe's own API and Python SDK). You send a **state** — text or a JSON
object, up to 32k tokens with any one question, 64k per request — and any number of typed
**questions**, answered together in one pass:

- **choice** — pick one of a set of options; returns the chosen option, a probability for
  every option and a confidence;
- **noul** — a yes/no, returned as a probability 0–1;
- **score** — a rating on up to ten described levels, returned as a probability-weighted
  number.

It never writes text. Input is $0.042 per million tokens, output is free, answers take about
100 ms. Its own docs say it is weak on numbers, dates and adversarial text, and that
thresholds should be set from your own labelled data. No published use for behavioural or
social simulation yet; the REFLEX preprint uses it as the decision layer of an agent, with
the strong model called only when words are needed — the same split proposed here.

### Manufacturing a million twins

- **Drawn, not written.** The frame already knows the published distributions. Draw a
  million from its cells (segment × place × age × tenure …) by raking, which exists. Names
  from lists. No model call per twin.
- **Dials from the segment.** Pro spawning already gives each segment a dial profile; store
  a centre and spread per dial per segment and draw each twin's dials from it with one
  latent score so they cohere (the way kits draw beliefs). Only the four behaviour groups
  (sentiment, motivation, friction, trust) need drawing; the rest lazily, if ever.
- **A card instead of a system message.** Today's prompt is about 4,000 characters. The
  card is a JSON object of about 60 tokens, built once at spawn and stored on the row:

  ```json
  {"age":34,"gender":"female","job":"nurse","tenure":"renter","place":"Hackney",
   "segment":"Loyal National","anger":7,"anxiety":6,"trust_institutions":2,
   "social_use":"heavy, evenings","follows":["local news","nurses","parents group"],
   "seen_before":["shared the cycle-lane post"]}
  ```

  Because Jev is weak on numbers, keep a words form too (*angry*, *distrusts
  institutions*) and test both.
- **Two tiers.** A few thousand full twins as today — they write, reply, get interviewed —
  and the million as cards that act. A card twin that needs to speak is **promoted on
  demand**: its full persona generated from the card, then Haiku writes the post.

### What a twin does when it sees something

One Jev call per exposure, three questions on one state (the card, the post, where it was
seen):

1. **choice** — scroll past / like / share / reply / quote / mute. The whole distribution is
   kept: a segment's share rate is the mean of its probabilities; the cascade samples an
   action from it.
2. **noul** — would this person stop and read it at all (the engage decision of entry 4).
3. **score** — how angry it makes them, how much more or less they trust the source. **The
   sentiment dials move during the run**: one cheap number per exposure, written back to the
   card, so a twin that has seen three hostile posts is angrier by step four.

A twin whose reply or quote probability clears a threshold goes to Claude for the words.
Everything is stored: the probabilities, the sampled action, the dial deltas.

### Where the reasons come from

Not from the twins. From the numbers, in order of weight:

- **the structure** — which dials and segments raise the share probability, with intervals,
  and a small fitted model over the cards (*trust below 3 and renter is what moves it*);
- **the same twins across variants** — seeds are deterministic, so each twin sees both
  phrasings in two runs; paired comparison shows which feature of the post moved which
  group;
- **words from a sample afterwards** — a few hundred high-probability sharers and
  scrollers interviewed with the full prompt, memory-free (entry 2's mechanism). The words
  illustrate; the numbers come from the million.

### Cost

| | Figure |
|---|---|
| One pass, every twin decides on one post | ~300M input tokens, about $13 |
| A 20-step Spread run, 10% awake per step | about $25 in Jev |
| Haiku for the ~1% who reply | about $20 |
| A whole million-twin Spread run | roughly $50 |
| Time at 50 calls in flight, 100 ms each | about 35 minutes per full pass |

At this price every twin decides for itself; no sample-and-extend model is needed.
Storage is not the problem: a million rows with a card and four dial groups is a small
Postgres table, written in batches of a few thousand.

### What has to be proved before any number is quoted

1. **Jev was built for software decisions, not for predicting a described person.** On the
   same 1,000 twins and the same post: Jev on cards against the full Haiku twins — does the
   action mix by segment match within a few points? If not, the card needs another line, or
   Jev is the wrong tool for this and a fine-tuned small model (the LLM-as-Jev route) is the
   fallback.
2. **It is known to under-pick the fallback option.** The LLM-as-Jev paper reports
   suppression of "none of these" and a yes bias. *Scroll past* is our fallback and the
   most common real answer, so the thresholds come from labelled data, and the poll
   benchmark (§11a.8) is the second check: does the share by segment track a real poll's
   shape.
3. **Numbers and dates.** Test the words form of the card against the numeric one.
4. **A second provider.** All intelligence is Claude today, with OpenAI for images as the
   precedent. The key must come from OpenRouter or TypeSafe directly; the write-ups warn
   about clone services under the same name.

### How it fits

- The builder is a new path in the Population Studio (*build a million*): the frame, the
  segment dial profiles, the card schema, batch inserts; the roster shows a sample and the
  counts by cell, never a million rows on screen.
- The decision call is a new tier in the model pipeline (§7.6) beside Fast and Pro:
  **Mass**, Jev for decisions, Haiku for the speakers.
- Spread (entry 6) runs on it unchanged in shape: clock, activity curve, feed, exposures
  log; only the decision step changes.
- The Lab's "who answers" draws a weighted sample from the million for any instrument that
  needs words, so a million twins also mean finer cuts (a borough, an age band within a
  segment) with enough people in each.
- Live streaming, the per-post graph update and the verdict sidebar all assume the whole
  population is on screen; at this scale they show a sample.

### Build order

1. The calibration first, before any product work: 1,000 card twins on Jev against the same
   1,000 full twins on Haiku, plus the poll benchmark by segment. A week, mostly evaluation.
2. The million builder: frame cells → rows → cards; a sample on the roster.
3. The Mass tier: Jev decisions with the three questions, dial write-back, promotion to
   Claude for speakers, the exposures log.
4. Spread on the Mass tier; the structure and paired analyses; the interview sample.
5. The Lab's weighted sampling from the million.

**Open questions.** Whether the words-form card beats the numeric one; where the reply
threshold sits; whether dial drift should decay back between steps; what the Simple view
shows for a million (probably nothing new: the same screens, a note on the sample).

---

## 8. Unjudged ideas from the October 2026 reading — judge before building

*Drishan, 2026-10-27: add all of them with the note that they have not been judged yet; when
one is picked up, first judge whether it is even worth it.*

**Status of everything in this section: NOT JUDGED.** These came out of one day's reading —
the OASIS code and paper, the Jev decision model, SimBench, Twin-2K-500, the GSS/WVS
synthetic-users benchmark, the Stanford 1,000-person agents, the NIM review of 285
silicon-to-human comparisons, PyMC Labs' Semantic Similarity Rating, and the vendor practices
of Fairgen, Electric Twin and Outset. Nobody has weighed any of them against the roadmap,
the cost of building, or what the product actually needs next. **The first step on any of
them is a judgement, not a build:** is the finding real for our twins (test it on the poll
benchmark or a 100-twin run), does it change a number a client reads, and is it cheaper than
what we do now. Drop the ones that fail that; promote the ones that pass to their own entry
above, with a build order. Each item below says where it comes from, what it is, how it
would fit, and what the first check is.

### Accuracy

**8.1 Answer as a distribution, not a pick.** *From SimBench (instruction-tuned models
collapse towards one answer) and Jev (calibrated probabilities by design).* Ask each twin for
a probability over the options — *60% yes, 30% unsure, 10% no* — instead of one choice;
shares are the mean of the probabilities. Smoother, better calibrated, same number of calls,
and it attacks the variance compression every review reports. *Fits:* a schema change in the
probe runner; aggregators read expected shares. *First check:* the poll benchmark with and
without; does mean error fall and does the spread of answers widen towards the real one.

**8.2 Score scales from words.** *From PyMC Labs' Semantic Similarity Rating: free text mapped
onto the scale by similarity to anchor statements reached 90% of human retest reliability
across 57 surveys.* For scale, NPS and grid questions in Forms, ask for a sentence and place
it on the scale by similarity to the anchors, rather than asking the model for a number.
*Fits:* Forms already codes free text into themes; one more post-process. *First check:*
the benchmark's scale items, SSR against the direct number.

**8.3 An over-split check, the mirror of the unanimity check.** *From the GSS/WVS benchmark:
models inflate gaps between segments two to four times and invent splits that are not there,
sending teams to the wrong segment half the time.* When a split the instrument computed is
wider than the published gap for that dimension (the kits carry those), flag it and shrink it
towards the published figure, showing the correction. *Fits:* beside `unanimity.py`, same
place on the Lab page. *First check:* count how often our splits exceed the kit's published
gaps on past runs.

**8.4 Learned corrections from benchmarks.** *From "When can you trust your synthetic users":
diagnose, trust the full sample, correct the subgroups — 83–94% bias reduction on Twin-2K-500
pricing.* Every scored benchmark run already yields per-segment errors; store them as
offsets and apply them, labelled, to later runs on the same population. *Fits:* the raking
code is most of the machinery; the benchmark scorer writes the offsets. *First check:* do
offsets learned on one poll reduce error on a second poll of the same population, or only on
the one they were learned from.

**8.5 Price from choices, not stated walk-away prices.** *From Twin-2K-500's pricing study:
demand curves from binary buy decisions at randomised prices.* Run price arms between
subjects and derive the curve from yes/no decisions; stated maximum prices stay as a
secondary line. *Fits:* the A/B split design already exists; purchase intent gains a
`price_arms` mode. *First check:* compare the two curves on one offer; which matches a real
Gabor-Granger or the benchmark's pricing items.

**8.6 Treat pricing and framing results as too rational.** *From the same consumer-panel
paper: twins calibrate well on demographics, badly on cognitive-bias tasks (r 0.34–0.50).*
Carry a warning on Van Westendorp, framing and message tools, and add two or three classic
bias items (anchoring, framing, sunk cost) to the validation battery as a check on how human a
lineup is. *Fits:* §7.12 battery; a label on three instruments. *First check:* run the three
items on a lineup; if the twins show no bias at all, the warning is earned.

**8.7 Shorter persona, same accuracy — or proof that ours is better.** *From Twin-2K-500:
fourteen demographic variables scored the same as the full persona (74.6% vs 74.8%); what
beat demographics was grounding in the person's own interview (Stanford, 85% of retest).*
Test the current ~4,000-character prompt against a compact card on the poll benchmark. If
the card scores the same, cut the prompt and the cost; if standing and evidence grounding
score better, that difference goes on the accuracy card. *First check:* this *is* the check;
one benchmark run each.

### Usage and cost

**8.8 Order the prompt for the cache.** *From how our phases work: every twin in a phase
shares the same thread snapshot, graph context, brief and date block; only the persona
differs.* Put the shared block first with cache control and the persona last; probes
likewise (stimulus and directive shared). *First check:* read the token ledger (§12.5) for
one phase and see how much is shared; confirm whether cache control is set today.

**8.9 Jev as the judge and the coder.** *From Jev's price ($0.042 per million input tokens,
output free) and shape (choice / yes-no / score).* The research pipeline scores every page
and every Reddit post for relevance and on-topic with Haiku, and codes reasons into themes
with another call; those are classifications. Keep Claude for quote extraction and anything
needing words; move the scores to a decision model. *First check:* Jev against the Haiku
judge on 200 already-judged pages; agreement rate and cost per page.

**8.10 Batch API for runs nobody is watching.** *From Anthropic's batch pricing (half) and
the fact that a 1,000-twin Pro probe or an overnight benchmark need not be live.* A *run
overnight* option on the Lab and on benchmarks. *First check:* how many past probes took
longer than ten minutes — the share of spend that could have gone through batch.

**8.11 Stop when the interval is tight enough.** *From our own Wilson intervals.* Run probes
in waves of fifty and stop when the primary metric's interval is narrower than the target
the analyst set, instead of always asking everyone. *First check:* on past probes, at what
n did the headline settle within two points of its final value.

**8.12 No extended thinking for twins.** *From SimBench: simulation ability tracks knowledge,
not inference-time compute.* Spend the strong model on the plan and the brief; never on the
twins' answers. *First check:* confirm no twin path sets a thinking budget today; if one
does, benchmark with it off.

**8.13 Report effective sample size.** *From how the Fast bank samples above its size (with
replacement, jittered).* Show the effective number of distinct people behind a lineup, so
300 twins that are 150 people are read as 150. *First check:* count distinct bank ids on
past Fast lineups above 500.

### New features

**8.14 Twins from real interviews.** *From Stanford's interview-grounded agents (85% of
retest, versus 74% for demographic agents, with less bias across groups) and Outset's
product.* Upload interview transcripts; one twin per interviewee, grounded in their own
words; fits the Agent Builder and the survey-curation path. *First check:* does 11 London
have transcripts it may use, and does a transcript-grounded twin score better than a
frame-drawn one on a question the interviewee actually answered.

**8.15 Boost a thin survey.** *From Fairgen (a 1,000-respondent survey raised to an
effective 2,790 by filling thin cells).* Twins conditioned on the real respondents fill the
thin cells; real rows kept, synthetic ones marked, a holdout score beside the boosted result.
*First check:* take one real survey, hide half of a thin cell, boost, compare.

**8.16 Holdout before go-live.** *From Electric Twin's practice on every client.* Hide
twenty percent of the client's own survey questions, predict them, show the accuracy card.
Reuses the benchmark scorer. *First check:* run it on the 11 London poll as if it were a
client's; is the card readable by a non-analyst.

**8.17 The accuracy card as a product page.** *From the public benchmarks (SimBench,
Twin-2K-500's pricing task, our poll benchmarks) and the fact that competitors do not
publish.* Run them on every release, published with the top published scores beside ours.
*First check:* one SimBench run; is our score above the bare model's, and is the run
reproducible.

**8.18 A backtest library.** *From MiroFish's weakness: no prediction was ever scored
against an outcome.* Run the tool on questions whose answers are known — past polls, past
launches, the 2023 poll in the kits — and keep a dated list. *First check:* three past
questions with known answers; what the tool said, what happened.

**8.19 A herd index.** *From OASIS: LLM agents follow the crowd more than people do.* The
social-proof arm (entry 5) measures it for a lineup; put the number on the validation page:
how much this population's answers move when shown that others agreed. *First check:* after
entry 5 exists, run it on one lineup; is the movement large enough to matter.
