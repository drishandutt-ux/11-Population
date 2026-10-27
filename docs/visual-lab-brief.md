# Visual Lab — build brief

Drafted 2026-10-26 from a conversation with Drishan. Not from Matthew Hunt's brief; Drishan's own item.
Status: **steps 1–3 built 2026-10-26 on branch `visual-lab`, not deployed** (held until Drishan says go). Step 1 verified in the browser; steps 2–3 pass their tests and generate was verified in the browser; the remake / propose / compare chain in the studio is still to be hand-tested.

---

## The idea in one line

Today the Lab shows twins words and gets words back. The Visual Lab lets a session make pictures, show
pictures to its twins, compare pictures, and remake a picture from what the twins said, without losing
anything that must stay on it. Any of those operations, in any order, as many times as the user wants.

## Before → now

| | Before | Now |
|---|---|---|
| Making creative | The user brings finished artwork from outside, or nothing at all. | The session can draw a first version from a brief the agent writes out of the debate and the Lab results. |
| Showing it to the population | Twins only react to a description of a poster, typed as text. | Twins see the actual image and react to what they see: what caught them first, what put them off, would they act. |
| Comparing routes | Only text variants can be A/B tested. | Two to six images go through the same twins and are scored side by side, with the same lift, flips and segment map the A/B test gives today. |
| Improving it | The user reads the results and goes back to the designer. | The agent reads the twins' reactions, says what it would change and why, and makes the next version. The user can also type the change themselves. |
| Keeping what matters | Nothing checks that a claim, a price, a logo or a mandatory survived the redesign. | A keep-list is pinned on the image. Every new version is checked against it before a twin sees it. Anything that drifted is rejected and shown. |
| Order of work | A Lab tool is one run: set it up, run it, read it. | Generate, compare, change, re-compare, generate again. Each step is a card in the session's history; any step can start from any earlier card. |

## Where it lives

Inside a session, as a Lab tool, next to Forms, Barriers and Journey. The user still runs the whole
session as today: question, sources, population, debate. Then they open the Lab and pick **Visuals**.
Nothing about it runs outside a session, and it works on the population that session built.

## The operations

Each is its own action. None requires another to have happened first, except that compare and remake
need at least one image to exist (uploaded or generated).

1. **Upload.** Bring in one or more images. Pin a keep-list on each (see below). This is the entry point
   for testing existing creative without generating anything.
2. **Generate.** The agent writes a brief from the session: the question, the debate's themes, the
   Barriers and Journey findings if they exist, the brand rules if a playbook or kit carries them, and an
   optional note from the user ("a kitchen, not a clinic"). It produces an image. Words that must be exact
   are laid as a text layer the agent authors, not drawn by the image model. The brief is kept with the
   image so the user can read why it looks the way it does.
3. **Show.** Pick an image, pick who sees it (the usual *Who answers* filter), pick the questions. The
   default form asks: first thing noticed, what you took it to be saying, what put you off, would you act,
   and the one line you would change. Twins answer from what they can see and know; a lay twin does not
   critique a reference footnote. Results read like every other Lab run: headline, cuts by segment and
   deprivation, verbatims traced to twins, confidence badges.
4. **Compare.** Two to six images through the same twins. The three existing designs apply: rate each
   (blind, paired), choose between (all at once, one pick), split population. Output is the existing
   A/B comparison with images in place of text variants.
5. **Remake.** Start from one image and its results. Either the agent proposes the change (what it would
   alter, which twins' reactions drove that, what it is keeping) or the user types the change. A new image is
   made, checked against the keep-list, and placed next to its parent. The user can then show it, compare
   it with the parent, or remake again.

A chain might be: upload two routes → compare → remake the loser with the agent's change → compare the
remake against the winner → remake the winner with the user's own change → show to one segment only.
Every card remembers its parent, so the history reads as a tree, not a list.

## The keep-list

The safety story. Each image carries a list of things that must survive any remake:

- exact text (claims, prices, legal lines, calls to action) — checked by reading the rendered text layer
  and matching it word for word;
- presence items (logo, product, a specific person, a colour) — checked by a vision pass that answers
  yes/no per item with a short reason;
- forbidden items (anything the brand rules or the user bans).

The agent fills the keep-list on first generation from the brand material it has, and the user edits it.
A remake that fails any item is kept but marked rejected, with the failing items named. It is never shown to
twins. For pharma sessions the claims matrix is the source of the exact-text items.

## What is reused and what is new

Reused as is: the population and its scoping, the probe runner and its sampling, the A/B experiment
layer (three designs, lift, flips, segment map), themes coding on free-text answers, confidence badges,
twin citations, the records and report blocks, the cost ledger and model tiers.

New:

- an image store on the session (uploaded and generated, with parent links, brief, keep-list, check result);
- a vision probe: a probe whose stimulus is an image, answered with the model looking at it;
- an image-generation step behind a provider the backend calls, with the text layer composited by us;
- the keep-list check (text match plus vision yes/no);
- the remake planner: reactions in, a change note and a new brief out, keep-list enforced;
- the Visuals Lab page: a tree of cards, each with its image, results and the actions above;
- a report ability: cite a visual run like a survey, and embed the winning image.

## Cost and limits

- Vision calls cost more than text. Default to a sample per segment plus a hold-out, not every twin.
  The cost estimate shows before each run as it does for other tools.
- Image models draw words badly. Hence the authored text layer. If a user insists on model-drawn text,
  the keep-list check will reject most of it, and that is the correct behaviour.
- A population will pull a remake toward safe and bland. The hold-out and the per-segment view are the
  guard. The agent must also say what each remake gives up with the segments it did not target.
- Generation is an external dependency with its own failures and bills. It needs the same ledger
  entries and recovery handling as the LLM calls, and a stuck generation must not strand the page.
- Standard and Advanced tiers apply: Standard for the vision reactions, Advanced for the brief and remake
  planning when the session is Advanced.

## Open questions for Drishan

1. Which image provider first? (One is enough to start; the step is behind an interface.)
2. Should Simple view get Visuals on day one, or Pro only until it settles?
3. Does a visual run count as a record the report must mention, or only when the user pins it?
4. Hold-out size: fixed share of the sample, or a fixed count?

## Suggested build order

- **Step 1 — Upload, Show, Compare. Built 2026-10-26.** No generation yet. Image store, vision probe, A/B with image
  variants, the Visuals page as a flat list. Already useful: test existing creative on the population.
- **Step 2 — Keep-list and Remake with user-typed change. Built 2026-10-26.** Generation behind one provider, authored text
  layer, the check, parent links, the tree view.
- **Step 3 — Generate from the session and agent-proposed Remake. Built 2026-10-26.** The brief writer, the remake planner,
  the report citation and embedded image.
- **Step 4 — From the run to the next version. Built 2026-10-26.** Drishan's gap after the first prod run: the results page
  had no way on. A *Next version* panel reads the whole run, proposes the changes in order (what most said, then what few
  said that is still hard-hitting), lets the user tick, edit and add, makes the new version, and offers *Show it* and
  *Compare it with the original* straight away.

Each step is hand-testable on its own before the next starts.

## Addendum (2026-10-27) — what makes it more than chat

Drishan's test: the remake read like a generic critique. The fix is to show what only a population can give.

| | Before | Now |
|---|---|---|
| What a remake ends with | A picture. | A picture **and a result**: re-shown to the same twins, paired by twin — who it won, who it lost, the shift with its interval, where it paid and where it cost, the movers in their own words. |
| Why a line is on the poster | Nothing. | Every line carries who asked for it and how many; a line nobody asked for is left out and the card says so. |
| How it compares with a chatbot | Not shown. | Every proposal is set against one call with no audience data: where they agree, what only the twins said, what the reviewer would add that the twins contradict. |
| One version for everyone | The consensus version. | One version per group the piece is losing, with the trade-off said out loud; the proof shows the trade-off by group. |
