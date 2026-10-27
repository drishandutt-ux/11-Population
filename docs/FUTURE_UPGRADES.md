# Future upgrades

Ideas for the tool that are agreed in spirit but not yet built. Each entry says what it
is in plain words, why it matters, how it would fit the current system, and what order to
build it in. When an entry is built, move its dated summary to the blueprint's Changelog and
delete it here.

Related: `PRODUCT_BLUEPRINT.md` (what exists today), `docs/visual-lab-brief.md` (the
image line this list extends).

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
