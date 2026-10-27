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
