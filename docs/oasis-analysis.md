# OASIS (camel-ai/oasis) — what it is, and what we should take from it

*2026-10-27. Drishan: analyse this GitHub repo and find if there is something in here that
we can replicate in our tool.* Repo read at commit `ba892e0` (2026-10-27). Nothing built.

---

## The short answer

OASIS is a **social-media simulator**, not a focus group. It builds a fake Twitter or Reddit,
fills it with LLM agents that each have a bio and a personality type, gives every agent a
**feed** decided by a recommendation algorithm and a **follow network**, and then **runs the
clock**: at each step a small share of agents wake up, read their feed and choose an action —
post, like, repost, quote, comment, follow, or do nothing. Every action is logged with a
timestamp. It was built to study *how a rumour spreads*, *whether groups polarise* and *whether
an early upvote makes a post win* (the herd effect), and it checked its answers against real
Twitter cascades.

Our product is the other way round. We build deep, evidence-grounded twins and ask them
questions. The debate is a room: everyone speaks once per phase and everyone reads the same
transcript. There is no feed, no follow network, no clock, no "I'd scroll past this", and no
way to drop something into the conversation halfway through and see what changes.

So the thing to take from OASIS is **not its agents** — ours are far richer — but its
**platform mechanics**: the parts that turn a panel into a population that behaves over time.
Six things, in order of value:

| # | What | What it answers for a client | Size |
|---|---|---|---|
| 1 | **A Spread tool** — seed one message, run the clock over a follow network with a feed, measure the cascade by segment | *Will this travel, through whom, and how far? Which of two phrasings travels further?* | Big (new instrument) |
| 2 | **Engage or scroll past** — a twin decides whether to react at all | *What share would even notice or bother?* Engagement rate by segment | Small |
| 3 | **Drop-ins and forks** — inject a post mid-run (the brand replies, a journalist weighs in, a correction lands) and continue; fork at that point to compare | *If we respond this way at hour 3, what changes?* The "scenario branching — not built" gap in blueprint §11a.7 | Medium |
| 4 | **Opinion over time** — re-ask the verdict question at intervals during a run | *Did the conversation move people, and who drifted?* Polarisation curves | Small |
| 5 | **A per-twin feed in the existing debate** instead of one shared transcript | Less herd; the independent-voice share becomes a feed setting instead of a patch | Medium |
| 6 | **Social-proof arms** in the A/B test — the same stimulus with or without likes and critical comments | *How much of the reaction is the thing, and how much is the crowd around it?* | Small |

**Not worth copying:** its persona generator (bio + MBTI + profession from a survey
distribution; ours is matched to a sampling frame and grounded in evidence), its agents' web
search tools (they would break our standing model), the one-million-agent scaling, the
e-mall and group-chat extras, and the library itself as a dependency (see *Why re-implement*).

---

## What OASIS is (facts)

- CAMEL-AI; Apache 2.0; PyPI `camel-oasis`; paper arXiv 2411.11581 (Nov 2024); docs at
  docs.oasis.camel-ai.org. About 6,000 lines of Python in the package (`platform.py` 1,642,
  `recsys.py` 797, `agent_action.py` 758, `agents_generator.py` 649), 102 Python files in the
  repo with examples and experiment scripts. Pinned to camel-ai 0.2.90. Last commit the day
  of reading (a QR-code update); the last feature was August 2026 (version bump), before
  that June 2025 (report-post, group chats, interview).
- Models: OpenAI by default, any CAMEL backend (vLLM, Qwen, LLaMA). The published runs used
  Qwen and LLaMA-3 on their own GPUs; the cost reference is **100 agents, all active, one
  step ≈ 335,600 input tokens and 16,750 output tokens** (feeds are dumped into the prompt
  as JSON).
- Storage: one SQLite file per run — `user`, `post`, `comment`, `follow`, `mute`, `like`,
  `dislike`, `rec` and the **`trace`** table that logs every action (sign-up, refresh, post,
  like, repost, interview …) with its sim-time stamp. Every analysis script reads `trace`.
- Interface: a Python library (PettingZoo-style `env.reset()` / `env.step(actions)` /
  `env.close()`), YAML experiment configs, matplotlib and Neo4j for pictures. No UI, no
  statistics inside the product (intervals appear only in the analysis scripts).

### The pieces, one by one

**1. Agent.** A CAMEL `ChatAgent` with a system prompt — *You're a Twitter user … Your name
is X. You have profile: {bio/persona}. You are a {gender}, {age}, MBTI {type} from
{country}. Please perform actions by tool calling* — and its own memory of what it saw and
did across steps. Each step the agent is shown *"After refreshing, you see some posts
{json} … pick one action that best reflects your current inclination"* and picks one of the
allowed actions as a tool call.

**2. Actions.** 23 of them: refresh, search posts, search users, trend, create post, like /
unlike / dislike / undo, report, follow / unfollow, mute / unmute, repost, quote, comment and
like/dislike comment, **do nothing**, purchase product, interview, and five group-chat
actions. Each run picks the set it allows. Twitter default: post, like, repost, follow,
do-nothing, quote. Reddit default adds comment, dislike, search, trend, refresh, mute.

**3. Feed (the recommendation system).** Recomputed once per step for everyone, then each
refresh draws from it:
- *random* — a baseline;
- *Reddit hot score* — Reddit's own formula: sign × log10(|likes − dislikes|) + age / 45,000,
  so newer and better-voted posts rank first;
- *Twitter personalised* — a TwHIN-BERT (or OpenAI) embedding of the user's bio against each
  post's text, cosine similarity × an engagement score, top-k, then **10% of the slots
  swapped for random posts** so the feed is not a pure echo; posts from accounts the user
  follows (sorted by likes) go on top;
- *trace-based* — similarity to what the user liked before.
Settings: posts per refresh, feed buffer size, posts from followed accounts, whether a user
may vote on their own post, whether to show a net score (Reddit) or likes and dislikes
(Twitter).

**4. Follow network.** Loaded from the profile file (`following_agentid_list`), built either
from real data, by topic (a user follows each influencer in a topic they care about with
probability 0.2), or at random; it then changes as agents follow, unfollow and mute.

**5. Clock and activation.** A sandbox clock with a magnification factor (one Reddit step ≈
two hours of sim time). Each agent carries **`active_threshold[24]`** — a probability of
acting for each hour of the day — and at each step every agent is woken with that
probability (typical runs: 1–10% awake per step). So cost scales with *awake agents × steps*,
not with population, which is how they reach a million agents. "Controllable" agents (the
researcher's own accounts) act by hand.

**6. Interventions.** `EnvAction(activate_agents=[…], intervention=[post X as agent 0])` at
any step; `ManualAction` for scripted accounts. The misinformation cookbook seeds a true and
a false post on the same topic at step 0 and lets 1% of agents wake per step. The
counterfactual experiment seeds posts with an initial up-vote, down-vote or nothing and
measures how far later commenters agree (an LLM judge scores 1–10, means with 95% CIs per
step across three treatments).

**7. Interview.** `ActionType.INTERVIEW` asks any agent a question at any step, stores prompt
and answer in `trace`, and by default **does not write the exchange into the agent's
memory**, so asking does not change the agent. The group-polarisation experiment asks the
same question ("what should Helen do?") every ten steps and an LLM judge says which of two
answers is more extreme.

**8. Validation.** Information spreading was checked against real cascades: 200 real X user
profiles around each of many real Twitter15/16 rumours, the real source tweet seeded, and the
simulated cascade's scale, depth and max breadth over time compared with the real ones
(`real_world_prop_data`). The Reddit test re-ran real post/comment pairs under up, down and
control treatment. The paper's headline findings: the simulated spread curves track the real
ones; follow networks polarise; an early vote shifts later agreement; larger populations
produce more diverse opinions.

**9. User generation.** Demographic distributions (age bands, gender, MBTI shares,
profession, 2–3 topics of interest) sampled per user, then GPT writes a real name, username,
bio and persona; the Twitter variant uses RAG over real user bios as few-shot examples.

**10. Extras.** External tools for agents (DuckDuckGo search, SymPy, any MCP toolkit),
WhatsApp-style group chats, an "e-mall" where agents buy products, a report-post
moderation action, Neo4j for watching the follow graph change, and the one-million-agent
run.

---

## What we have today, for comparison

| | OASIS | 11 Minds Population |
|---|---|---|
| Who the agents are | name + bio + MBTI + age/gender/country, written by GPT from a survey distribution | frame-matched segments, 112 dials, standing (lived / trained / lay), scoped knowledge, evidence-grounded, validated; kits from published segmentations |
| What an agent reads before speaking | its own feed: followed accounts + recommended + random, a handful of posts | the same last 3,000 characters of the whole transcript for everyone (`thread_manager.build_thread_context`, `agent_runner`); 30% read nothing (independent voices) |
| Who speaks | whoever is awake this step (1–10%), and only if it chooses to | everyone, once per phase, by design (coverage guarantee, §8.1) |
| Can an agent ignore it | yes — `do_nothing` is an action | no — a comment is compulsory in phase 1; likes land on a random recent post |
| Time | a clock; steps of sim minutes or hours; hourly activity per agent | none; phases |
| Network | a follow graph that changes | none; parents for replies are random among the last 25 posts |
| Mid-run changes | inject posts, activate chosen agents, interview any agent at any step | run → pause → stop; nothing can be inserted; branching "not built" (§11a.7) |
| Measurement | the `trace` table, scripts afterwards (judge scores, CIs, cascade depth/breadth/scale) | the Lab: instruments, Wilson and bootstrap intervals, A/B lifts, flips, benchmarks against a real poll, refusal as a result, unanimity check |
| Validation | real Twitter cascades; real Reddit pairs | a real poll (`mic_11london_june2023`) |
| Product | a Python library | a web product with a pro workspace and a simple view |

The gap is clear: we are stronger on *who* and on *measurement*; OASIS is stronger on
*exposure, time and intervention*. Those three are exactly what a client means by "will this
travel", "what if we respond", and "did the conversation move people".

---

## What to build, in detail

### 1. The Spread tool — *will this travel, and through whom?*

**Before:** virality is a dashboard score read off the dials (§7.5). Nobody is ever *exposed*
to anything; everyone posts.

**Now, if built:** a Lab instrument that takes a message (a post, a headline, a poster from
the image store — anything the probe runner can show), seeds it from a named source (the
brand, a news account, a chosen twin), and runs the clock.

- **A follow network built at spawn.** From the frame and the plan: twins in the same segment
  and place follow each other with a high weight, across segments with a low one; a few
  cross-links; and, where the plan names them, "influencer" twins with many followers. No
  real data needed; the structure is what matters, and OASIS's own networks were generated.
- **A per-twin feed.** Each step a woken twin sees: posts from the accounts it follows (most
  liked first), a few hot posts (likes minus age, Reddit's formula), one or two random. No
  embeddings: interest match from the twin's segment, standing and dials, or a cheap topic
  tag per post. OASIS needs a BERT model for this; we do not.
- **Hourly activity.** Each twin carries an activity curve derived from its dials (the
  `habit` group, unused by the debate today) and the frame's heavy / light social-user figures
  where published. A step wakes the share due; the rest sleep.
- **The engage decision (item 2).** A woken twin chooses: scroll past, like, reply, share,
  quote — one cheap call with the standing block and the feed.
- **An exposures log** — OASIS's `trace`: who saw what, when, and what they did. Reach needs
  *who saw it*, not just who posted.
- **Results:** reach over time (seen / engaged / shared) by segment; depth and breadth of the
  cascade; who amplified and who pushed back, in their own words; which phrasing travelled
  when two seeds are run as A/B arms. Labelled *relative reach: A vs B, by segment* until a
  cascade benchmark exists (see *Validation* below).

Cost: Haiku for every step action. 200 twins × 20 steps × 10% awake ≈ 400 calls — a Fast
debate's worth. Fits the instrument contract (§11a.3): inputs, schema, aggregator, KPIs,
metrics for the A/B, its own page.

### 2. Engage or scroll past

**Before:** every twin must write a comment; we never learn what share would have noticed or
bothered. The report cannot say *72% would have scrolled past*.

**Now:** a decision step before a post — *you've just seen this in your feed: scroll past,
like, reply, share, quote?* — Haiku, 50 tokens, with the standing block and dials. In the
Spread tool it is the core mechanic; in the debate it can be a run option (the coverage
guarantee stays the default: a focus group gives everyone a turn). Engagement rate by segment
is a KPI clients already use. It also sits well with our refusal rule: not engaging is a
result, kept out of nothing.

### 3. Drop-ins and forks

**Before:** a run goes start → stop. The analyst cannot put *the company responds with X* into
the conversation at hour three. Branching (re-running the whole debate under two stimuli) is
listed as not built.

**Now:** a **Drop in** control on the Thread tab: a named actor — the brand's official
account, a journalist, a regulator, a chosen twin — posts a given text at the current point
and the run continues (OASIS's `ManualAction`). A **Fork** snapshots the run at that point
and runs two continuations (drop-in A vs B, or with vs without), then compares them the way
the experiments layer compares arms: verdict share, engagement, who moved. In the simple
view: *Add a reply from…* and *See what changes*.

### 4. Opinion over time

**Before:** the verdict is read once, after the run. Journey work in October showed how often
the real question is *what changed between then and now*.

**Now:** a `snapshots` option on a run: at phases or steps {0, k, end} the verdict instrument
is asked of everyone, blind to its own earlier answers (the Visual Lab's re-test already does
this through `Probe.spec.retest`). Then: for / against / mixed and confidence over time by
segment, and the polarisation index (`stats.py` already has it) over time. OASIS asked the
same question every ten steps and judged which answer was more extreme; we can plot the
drift directly. Cheap: three × N Haiku calls.

This does not break the *no re-polling twins* rule: that rule is about fixing a weak report
by asking the same question again. Here the re-ask is the measurement — same question,
different time; what they have read in between is the variable.

### 5. A per-twin feed in the debate

**Before:** everyone reads the same transcript window, so the first few posts set the tone;
the independent-voice share and the dissent rule (§7.13) patch that.

**Now:** once the feed exists for Spread, the debate's phase engine can hand each twin its
own feed instead of the shared snapshot — people like them, the hottest posts, a random one.
The independent share becomes a feed parameter ("posts from your own head only"). Less
herd, and the debate reads more like a real thread, where nobody has read all of it.

### 6. Social-proof arms

**Before:** an A/B arm differs in the stimulus. Nothing tests the crowd around it.

**Now:** a variant option *shown with social proof*: the same stimulus with an engagement
line (*1.2k likes · 340 comments · top comment: …*) or with critical comments, against the
bare version. OASIS's herd experiment in miniature. Almost no code — a spec field in Ask or
Visuals and a line in the directive — and the report must say *shown with / without*, since
it measures susceptibility, not the thing itself.

### Validation

OASIS earned its claims against real cascades. For Spread we need the equivalent: a real post
with known reach over time (a tweet's, or a YouTube video's view and like curve — the same
calibration the Video Lab brief asks for before the report may say *would get more likes*).
Until that exists the Spread output is *relative* — A vs B, by segment — and the page says so.

---

## Why re-implement rather than depend on `camel-oasis`

- It drags in CAMEL plus torch, transformers (TwHIN-BERT) and scikit-learn — heavy for the
  Railway image and pointless for us, since we do not need embeddings for the feed.
- It is OpenAI-centred and one SQLite file per run, in-process; our runs are rows in Postgres
  with pub/sub streaming and startup recovery.
- The platform mechanics are about 1,600 lines of plain Python; the ideas (feed, follow
  graph, clock, activation, exposures log, interventions, interview-without-memory) port in
  a week or two onto our async SQLAlchemy and Claude stack, and then they speak our
  instrument contract, our statistics and our standing model.
- Apache 2.0, so reading and borrowing its formulas (the hot score, the 10% random swap, the
  hourly activation) is fine; attribution in the file header is enough.

---

## Build order

1. **Engage or scroll past** (item 2) and **social-proof arms** (item 6) — days; both show
   up in the debate and the A/B test at once.
2. **Opinion over time** (item 4) — days; reuses the verdict instrument and the re-test path.
3. **Drop-ins and forks** (item 3) — about a week; fills the branching gap.
4. **The Spread tool** (item 1: follow network, per-twin feed, clock and activation,
   exposures log, cascade metrics, A/B of two seeds) — two to three weeks; then the feed can
   replace the shared transcript in the debate (item 5).
5. **A cascade benchmark** — alongside the Video Lab's calibration.

**Open questions.** Whether the engage decision runs on every debate by default or only in
Spread; how the follow network should be shown to the analyst (the Studio plan is the natural
place: *who follows whom* beside *who is in the room*); whether Spread lands in the simple
view as *Will this travel?* before or after the Video Lab's Watch.
