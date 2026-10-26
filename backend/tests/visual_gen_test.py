"""Tests for the Visual Lab, steps 2 and 3 (2026-10-26): the keep-list, the authored text layer,
the hero fallback, the check, remake and propose, and the API around them.

Run:  cd backend && pytest tests/visual_gen_test.py -q
"""
import asyncio
import io
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.models.session import AnalysisSession, SessionStatus  # noqa: E402
from app.models.measurement import Probe, SessionImage  # noqa: E402
from app.services.measurement import images as images_mod  # noqa: E402
from app.services.measurement import visual_gen as vg  # noqa: E402
from app.services.simulation import records  # noqa: E402

from tests.measurement_test import _agent, lab_db, api_client, _async  # noqa: E402,F401
from tests.visual_test import _png  # noqa: E402

LAYOUT = {
    "rationale": "lead with the price", "headline": "Dinner, sorted.", "subline": "Fresh meal kits for busy families",
    "body_lines": ["Ready in 20 minutes"], "claim_lines": [], "cta": "Order your first box", "small_print": "Terms apply.",
    "palette": {"bg": "#1e5aa0", "fg": "#ffffff", "accent": "#c81e1e"}, "hero_prompt": "a family at a kitchen table, children laughing",
    "hero_placement": "top", "kept": [],
}
KEEP = ["£3.50 a meal", {"type": "present", "value": "a family"}, {"type": "absent", "value": "children"}]


# ── the keep-list ─────────────────────────────────────────────────────────────

def test_keep_list_is_normalised_and_deduplicated():
    keep = vg.normalise_keep_list(KEEP + ["£3.50 a meal", {"type": "junk", "value": "x"}, "", 7, {"type": "TEXT", "value": "  Terms   apply "}])
    assert keep == [{"type": "text", "value": "£3.50 a meal"}, {"type": "present", "value": "a family"},
                    {"type": "absent", "value": "children"}, {"type": "text", "value": "Terms apply"}]
    assert vg.normalise_keep_list("nope") == [] and vg.normalise_keep_list(None) == []


def test_enforce_keep_list_sets_every_exact_text_item_in_type_and_strips_forbidden_words_from_the_hero():
    keep = vg.normalise_keep_list(KEEP)
    out = vg.enforce_keep_list(LAYOUT, keep)
    assert out["claim_lines"] == ["£3.50 a meal"]                 # the dropped claim is appended, verbatim
    assert "children" not in out["hero_prompt"] and "kitchen table" in out["hero_prompt"]
    # Already present (any case / spacing) → not duplicated.
    again = vg.enforce_keep_list({**LAYOUT, "claim_lines": ["Just £3.50 A MEAL"]}, keep)
    assert again["claim_lines"] == ["Just £3.50 A MEAL"]


def test_mechanical_check_reads_the_layout_not_the_picture():
    keep = vg.normalise_keep_list(KEEP)
    out = vg.mechanical_check(vg.enforce_keep_list(LAYOUT, keep), keep)
    assert out == {0: {"ok": True, "how": "text", "note": "set in type, word for word"}}   # only the text item; the rest is vision
    assert vg.mechanical_check(None, keep) == {}


# ── the text layer and the hero ───────────────────────────────────────────────

def _size(png: bytes):
    from PIL import Image
    return Image.open(io.BytesIO(png)).size


def test_compose_sets_the_words_over_a_hero_at_poster_size():
    hero = vg.placeholder_hero("a family at a kitchen table", (1024, 1366), (200, 30, 30))
    assert vg.placeholder_hero("a family at a kitchen table", (1024, 1366), (200, 30, 30)) == hero   # deterministic
    assert hero != vg.placeholder_hero("a lighthouse", (1024, 1366), (200, 30, 30))
    png = vg.compose(vg.enforce_keep_list(LAYOUT, vg.normalise_keep_list(KEEP)), hero)
    assert _size(png) == vg.CANVAS
    # Type-only and left placements compose too; a broken hero is survived.
    assert _size(vg.compose({**LAYOUT, "hero_placement": "none"}, None)) == vg.CANVAS
    assert _size(vg.compose({**LAYOUT, "hero_placement": "left"}, hero)) == vg.CANVAS
    assert _size(vg.compose(LAYOUT, b"not an image")) == vg.CANVAS


def test_compose_survives_bad_colours_and_empty_fields():
    png = vg.compose({"headline": "", "palette": {"bg": "#111111", "fg": "#121212", "accent": "zzz"}, "hero_placement": "top"}, None)
    assert _size(png) == vg.CANVAS


def test_provider_is_none_without_a_key(monkeypatch):
    from app.core.config import get_settings
    st = get_settings()
    monkeypatch.setattr(st, "image_provider", "auto"); monkeypatch.setattr(st, "openai_api_key", ""); monkeypatch.setattr(st, "google_api_key", "")
    assert vg.provider_name() == "none"
    monkeypatch.setattr(st, "openai_api_key", "k")
    assert vg.provider_name() == "openai"
    monkeypatch.setattr(st, "image_provider", "google")
    assert vg.provider_name() == "none"            # google chosen, no google key → no provider, never a wrong one
    monkeypatch.setattr(st, "google_api_key", "g")
    assert vg.provider_name() == "google"


def test_a_failing_provider_falls_back_to_the_placeholder_and_keeps_the_error(monkeypatch):
    from app.core.config import get_settings
    st = get_settings()
    monkeypatch.setattr(st, "image_provider", "openai"); monkeypatch.setattr(st, "openai_api_key", "k")

    async def boom(prompt):
        raise RuntimeError("quota")
    monkeypatch.setattr(vg, "_openai_hero", boom)
    data, provider, err = asyncio.run(vg.generate_hero("a cat", session_id="s", size=(100, 133), accent=(1, 2, 3)))
    assert provider == "none" and "quota" in err and _size(data) == (100, 133)


# ── the check with a stubbed vision call ──────────────────────────────────────

def test_check_image_mixes_mechanical_and_vision_results(monkeypatch):
    calls = []

    async def fake_analyze(schema, system, user, **kw):
        calls.append(kw)
        content = kw["messages"][0]["content"]
        assert content[1]["type"] == "image"
        listing = content[-1]["text"]
        assert "1. Must show" in listing and "2. Must NOT show" in listing and "Must read exactly" not in listing
        return {"items": [{"index": "1", "ok": True, "note": "a family at a table"}, {"index": "2", "ok": False, "note": "two children visible"}]}
    monkeypatch.setattr(vg, "analyze", fake_analyze)
    keep = vg.normalise_keep_list(KEEP)
    layout = vg.enforce_keep_list(LAYOUT, keep)
    out = asyncio.run(vg.check_image(session_id="s", data=_png(), media_type="image/png", width=40, height=30, layout=layout, keep=keep, model="m"))
    assert [i["ok"] for i in out["items"]] == [True, True, False]
    assert [i["how"] for i in out["items"]] == ["text", "vision", "vision"]
    assert out["passed"] is False and len(calls) == 1


def test_check_on_an_uploaded_image_sends_text_items_to_vision_too(monkeypatch):
    async def fake_analyze(schema, system, user, **kw):
        listing = kw["messages"][0]["content"][-1]["text"]
        assert "Must read exactly" in listing
        return {"items": [{"index": 1, "ok": True, "note": "legible"}]}
    monkeypatch.setattr(vg, "analyze", fake_analyze)
    keep = vg.normalise_keep_list(["£3.50 a meal"])
    out = asyncio.run(vg.check_image(session_id="s", data=_png(), media_type="image/png", width=40, height=30,
                                     layout={"read_from_image": True, "claim_lines": ["£3.50 a meal"]}, keep=keep, model="m"))
    assert out["passed"] and out["items"][0]["how"] == "vision"


# ── generate and remake end to end (stubbed model, no provider) ───────────────

def _fake_layout(headline="Dinner, sorted.", claims=None, change_seen=None):
    async def fake_analyze(schema, system, user, **kw):
        props = schema.get("properties") or {}
        if "hero_prompt" in props and "visible_items" in props:          # read_image
            return {"description": "a poster", "headline": "Eat well. Spend less.", "subline": "", "body_lines": [], "claim_lines": ["First box free"],
                    "cta": "", "small_print": "", "palette": {"bg": "#147850", "fg": "#ffffff", "accent": "#c81e1e"},
                    "hero_prompt": "an orange circle on a cream card", "hero_placement": "top", "visible_items": ["an orange circle"]}
        if "hero_prompt" in props:                                           # write_layout
            if change_seen is not None:
                change_seen.append(user)
            return {**LAYOUT, "headline": headline, "claim_lines": list(claims or [])}
        if "items" in props:                                                 # check
            return {"items": [{"index": str(k + 1), "ok": True, "note": "seen"} for k in range(6)]}
        if "changes" in props and "base_image_id" in props:                 # propose (the next-version planner)
            base = ""
            for line in user.splitlines():                                  # the planner copies an id from the images block
                if line.startswith("BUILD ON IMAGE id "):
                    base = line.split("BUILD ON IMAGE id ", 1)[1].split(" ")[0]
            if not base:
                ids = [seg.split(")")[0] for seg in user.split("(id ")[1:]]
                base = ids[-1] if ids else ""                                # with a free choice, the fake picks the last image shown
            return {"base_image_id": base, "base_why": "it is the one the room warmed to",
                    "changes": [{"change": "Make the price the headline", "basis": "most said", "share": "1 of 1 who named a change", "why": "most who said no were put off by small print", "cites": ["Anouk Park"]},
                                {"change": "Name a local shelter and a phone number", "basis": "few said, hard-hitting", "share": "said once, by someone it did not work on", "why": "without it there is nowhere to send anyone", "cites": ["Anouk Park"]}],
                    "keep": ["the family photo"], "expected": "the price-led segment moves"}
        raise AssertionError(f"unexpected schema {list(props)}")
    return fake_analyze


def test_generate_writes_a_ready_image_with_layout_brief_and_check(lab_db, monkeypatch):
    Session, loop = lab_db
    monkeypatch.setattr(vg, "analyze", _fake_layout())
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "image_provider", "none")
    sid = str(uuid.uuid4())

    async def run():
        async with Session() as db:
            db.add(AnalysisSession(id=sid, title="t", query="Would families buy meal kits?", status=SessionStatus.COMPLETE))
            await db.commit()
        row = await vg.start_generate(sid, note="a bus-stop poster for the school run", keep_list=KEEP, mode="fast")
        assert row.status == "generating" and row.source == "generated"
        await vg.run_generate(row.id)
        async with Session() as db:
            return await db.get(SessionImage, row.id)
    done = loop.run_until_complete(run())
    assert done.status == "ready", done.error
    assert done.label == "Dinner, sorted." and done.media_type == "image/jpeg" and done.width == 1176 and done.height == 1568
    assert done.layout["claim_lines"] == ["£3.50 a meal"]                 # the keep-list made it into type
    assert done.brief["hero_provider"] == "none" and done.brief["note"].startswith("a bus-stop")
    assert done.check_result["passed"] is True and [i["how"] for i in done.check_result["items"]] == ["text", "vision", "vision"]
    assert done.keep_list[0] == {"type": "text", "value": "£3.50 a meal"}


def test_remake_reads_an_uploaded_parent_then_answers_the_change_and_the_reactions(lab_db, monkeypatch):
    Session, loop = lab_db
    seen = []
    monkeypatch.setattr(vg, "analyze", _fake_layout(headline="Eat well for £3.50", change_seen=seen))
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "image_provider", "none")
    sid = str(uuid.uuid4())

    async def run():
        norm = images_mod.normalise(_png(60, 40), "b.png")
        async with Session() as db:
            db.add(AnalysisSession(id=sid, title="t", query="q", status=SessionStatus.COMPLETE))
            parent = SessionImage(session_id=sid, label="Route B", filename="b.png", media_type=norm["media_type"], width=norm["width"], height=norm["height"],
                                  size_bytes=len(norm["data"]), sha256=norm["sha256"], data=norm["data"], keep_list=vg.normalise_keep_list(["First box free"]))
            db.add(parent)
            await db.flush()
            # A Visuals run on the parent, with answers the remake should read.
            db.add(Probe(session_id=sid, instrument="visual", schema_id="visual.v1", status="complete", model="m", seed=1, agent_count=2, answer_count=2,
                         spec={"images": [{"id": parent.id, "label": "Route B"}], "question": "q"},
                         aggregates={"n": 2, "sentence": "50% say it works", "put_off": [{"value": "tiny small print", "count": 1}],
                                     "changes": [{"name": "Anouk Park", "verdict": "no", "change_one": "make the price bigger"}],
                                     "verbatims": {"no": [{"name": "Anouk Park", "reasoning": "I saw the QR code first. It leaves me cold.", "put_off": "tiny small print"}], "mixed": [], "yes": []}}))
            await db.commit()
            pid = parent.id
        async with Session() as db:
            parent = await db.get(SessionImage, pid)
        child = await vg.start_remake(sid, parent, change="Make the price the headline", keep_list=None, probe_id=None, proposal=None, mode="fast")
        await vg.run_remake(child.id)
        async with Session() as db:
            return await db.get(SessionImage, pid), await db.get(SessionImage, child.id)
    parent, child = loop.run_until_complete(run())
    assert child.status == "ready", child.error
    assert child.parent_id == parent.id and child.source == "remake" and child.change_note == "Make the price the headline"
    assert parent.layout and parent.layout.get("read_from_image") is True and parent.layout["headline"] == "Eat well. Spend less."
    assert child.keep_list == [{"type": "text", "value": "First box free"}]      # inherited from the parent
    assert child.layout["claim_lines"] == ["First box free"]
    prompt = seen[0]
    assert "THE PREVIOUS VERSION'S LAYOUT" in prompt and "Eat well. Spend less." in prompt
    assert "THE CHANGE TO MAKE" in prompt and "Make the price the headline" in prompt
    assert "WHAT THE AUDIENCE SAID" in prompt and "tiny small print" in prompt and "Anouk Park" in prompt
    assert child.brief["reactions_probe_id"]


def test_record_from_a_visual_probe_carries_the_images_and_the_block_names_them():
    class P:  # a probe row stand-in
        id = "p1"; instrument = "visual"; model = "m"; seed = 1; schema_id = "visual.v1"; prompt_hash = ""; agent_count = 8; answer_count = 8; created_at = None
        spec = {"images": [{"id": "i1", "label": "Route A"}], "question": "Does this work on you?"}
        aggregates = {"n": 8, "headline": {"metric": "yes_share", "label": "Works on them", "share": 0.5, "low": 0.2, "high": 0.8, "n": 8, "successes": 4},
                      "sentence": "50% say it works on them", "verdict": [{"value": "yes", "count": 4, "share": 0.5}], "segments": {}}
    r = records.record_from_probe(P())
    assert r["images"] == [{"id": "i1", "label": "Route A"}] and r["label"].startswith("Shown Route A")
    block, _ = records.records_block([r])
    assert "shown: Route A" in block


# ── the API ───────────────────────────────────────────────────────────────────

def test_image_generation_api_round_trip(api_client, monkeypatch):
    client, Session = api_client
    monkeypatch.setattr(vg, "analyze", _fake_layout())
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "image_provider", "none")
    sid = client.post("/api/v1/sessions", json={"title": "Posters", "query": "Which poster lands?"}).json()["id"]

    g = client.post(f"/api/v1/sessions/{sid}/images/generate", json={"note": "a bus-stop poster", "keep_list": KEEP})
    assert g.status_code == 200, g.text
    # BackgroundTasks run inside the TestClient request, so the image is ready on return of the next call.
    listed = client.get(f"/api/v1/sessions/{sid}/images").json()["images"]
    gen = next(i for i in listed if i["id"] == g.json()["id"])
    assert gen["status"] == "ready" and gen["source"] == "generated" and gen["layout"]["headline"] == "Dinner, sorted."
    assert gen["check_result"]["passed"] is True and gen["brief"]["hero_provider"] == "none"
    assert client.get(f"/api/v1/sessions/{sid}/images/{gen['id']}/file").status_code == 200

    # No run on it yet → propose refuses; the keep-list can be edited; a remake needs a change.
    assert client.post(f"/api/v1/sessions/{sid}/images/{gen['id']}/propose", json={}).status_code == 409
    assert client.patch(f"/api/v1/sessions/{sid}/images/{gen['id']}", json={"keep_list": ["£3.50 a meal", "x"]}).json()["keep_list"][1] == {"type": "text", "value": "x"}
    assert client.post(f"/api/v1/sessions/{sid}/images/{gen['id']}/remake", json={"change": ""}).status_code == 400

    r = client.post(f"/api/v1/sessions/{sid}/images/{gen['id']}/remake", json={"change": "Lead with the price"})
    assert r.status_code == 200, r.text
    child = next(i for i in client.get(f"/api/v1/sessions/{sid}/images").json()["images"] if i["id"] == r.json()["id"])
    assert child["status"] == "ready" and child["parent_id"] == gen["id"] and child["source"] == "remake"
    assert child["keep_list"][1] == {"type": "text", "value": "x"}            # inherited
    # The parent cannot go while its remake exists; the child can.
    assert client.delete(f"/api/v1/sessions/{sid}/images/{gen['id']}").status_code == 409
    assert client.delete(f"/api/v1/sessions/{sid}/images/{child['id']}").status_code == 200
    # A re-check stores a fresh result.
    assert client.post(f"/api/v1/sessions/{sid}/images/{gen['id']}/check", json={}).json()["passed"] is True


# ── step 4: from a finished run to the next version ───────────────────────────

def test_next_version_reads_a_joint_run_picks_the_base_and_remakes_from_the_chosen_changes(api_client, monkeypatch):
    client, Session = api_client
    seen: list[str] = []
    monkeypatch.setattr(vg, "analyze", _fake_layout(change_seen=seen))
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "image_provider", "none")
    sid = client.post("/api/v1/sessions", json={"title": "Posters", "query": "Which poster lands?", "auto_research": False}).json()["id"]
    a = client.post(f"/api/v1/sessions/{sid}/images", files={"file": ("a.png", _png(60, 40), "image/png")}, data={"label": "Sad dog"}).json()
    b_ = client.post(f"/api/v1/sessions/{sid}/images", files={"file": ("b.png", _png(60, 40), "image/png")}, data={"label": "Happy dog"}).json()

    async def seed():
        async with Session() as db:
            p = Probe(session_id=sid, instrument="visual", schema_id="visual.v1", status="complete", model="m", seed=1, agent_count=3, answer_count=3,
                      spec={"images": [{"id": a["id"], "label": "Sad dog"}, {"id": b_["id"], "label": "Happy dog"}], "question": "Would you share this?"},
                      aggregates={"n": 3, "sentence": "24% say it works", "verdict": [{"value": "mixed", "count": 2}, {"value": "no", "count": 1}],
                                  "put_off": [{"value": "Missing shelter details", "count": 2}], "noticed": [{"value": "Happy dog", "count": 3}],
                                  "changes": [{"name": "Anouk Park", "verdict": "no", "change_one": "add a local shelter name"},
                                              {"name": "Ray Timmins", "verdict": "mixed", "change_one": "swap the stock dog for a real one"}],
                                  "verbatims": {"no": [{"name": "Anouk Park", "reasoning": "Nowhere to send anyone.", "put_off": "no shelter named"}], "mixed": [], "yes": []}})
            db.add(p)
            await db.commit()
            return p.id
    pid = asyncio.run(seed())

    # A run that has not finished, or a run id from nowhere, is refused.
    assert client.post(f"/api/v1/sessions/{sid}/images/propose", json={"probe_id": str(uuid.uuid4())}).status_code == 404

    # The planner reads the whole run, picks the base (the fake picks the last image shown) and proposes two changes.
    r = client.post(f"/api/v1/sessions/{sid}/images/propose", json={"probe_id": pid})
    assert r.status_code == 200, r.text
    prop = r.json()
    assert prop["base_image_id"] == b_["id"] and prop["base_label"] == "Happy dog" and prop["probe_id"] == pid
    assert [c["basis"] for c in prop["changes"]] == ["most said", "few said, hard-hitting"]
    assert prop["change"] == "Make the price the headline" and prop["cites"] == ["Anouk Park"]
    # The analyst can fix the base; an image outside the run is refused.
    assert client.post(f"/api/v1/sessions/{sid}/images/propose", json={"probe_id": pid, "base_image_id": a["id"]}).json()["base_image_id"] == a["id"]
    assert client.post(f"/api/v1/sessions/{sid}/images/propose", json={"probe_id": pid, "base_image_id": str(uuid.uuid4())}).status_code == 409
    # The per-image call still works after a run that showed the image among others, with the base fixed to it.
    one = client.post(f"/api/v1/sessions/{sid}/images/{a['id']}/propose", json={})
    assert one.status_code == 200, one.text
    assert one.json()["base_image_id"] == a["id"]

    # Make it: only the second change ticked, plus a note → the change note carries exactly that, and the run's reactions reach the layout call.
    r = client.post(f"/api/v1/sessions/{sid}/images/{b_['id']}/remake", json={"proposal": prop, "selected": [1], "note": "keep it to one page", "probe_id": pid,
                                                                             "keep_list": [{"type": "present", "value": "the happy dog"}]})
    assert r.status_code == 200, r.text
    child = next(i for i in client.get(f"/api/v1/sessions/{sid}/images").json()["images"] if i["id"] == r.json()["id"])
    assert child["status"] == "ready" and child["parent_id"] == b_["id"]
    assert child["change_note"] == "Name a local shelter and a phone number\nAlso: keep it to one page"
    assert child["brief"]["proposal"]["changes"][1]["basis"] == "few said, hard-hitting"
    assert child["brief"]["selected"] == [1] and child["brief"]["note"] == "keep it to one page"
    # The keeps chosen on the page, plus the claim read off the old poster, locked because the change did not name it.
    assert child["keep_list"] == [{"type": "present", "value": "the happy dog"}, {"type": "text", "value": "First box free"}]
    layout_prompt = next(u for u in seen if "THE CHANGE TO MAKE" in u)
    assert "Name a local shelter" in layout_prompt and "Missing shelter details" in layout_prompt and "Ray Timmins" not in layout_prompt or "Anouk Park" in layout_prompt
    # Nothing ticked and no change typed → refused.
    assert client.post(f"/api/v1/sessions/{sid}/images/{b_['id']}/remake", json={"proposal": prop, "selected": []}).status_code == 400
    # Both changes → numbered.
    assert vg.change_text(prop) == "1) Make the price the headline\n2) Name a local shelter and a phone number"


# ── full render: the provider draws the whole poster ──────────────────────────

def test_render_mode_follows_the_provider_and_the_setting(monkeypatch):
    from app.core.config import get_settings
    st = get_settings()
    monkeypatch.setattr(st, "image_provider", "none"); monkeypatch.setattr(st, "openai_api_key", ""); monkeypatch.setattr(st, "image_render", "auto")
    assert vg.render_mode() == "layered"
    monkeypatch.setattr(st, "image_provider", "openai"); monkeypatch.setattr(st, "openai_api_key", "k")
    assert vg.render_mode() == "full"
    monkeypatch.setattr(st, "image_render", "layered")
    assert vg.render_mode() == "layered"
    monkeypatch.setattr(st, "image_render", "full"); monkeypatch.setattr(st, "image_provider", "google"); monkeypatch.setattr(st, "google_api_key", "g")
    assert vg.render_mode() == "layered"                                     # Imagen never draws the words


def test_full_render_draws_the_whole_poster_from_the_reference_and_retries_a_wrong_line(lab_db, monkeypatch):
    Session, loop = lab_db
    from app.core.config import get_settings
    st = get_settings()
    monkeypatch.setattr(st, "image_provider", "openai"); monkeypatch.setattr(st, "openai_api_key", "k"); monkeypatch.setattr(st, "image_render", "auto")
    calls: list[dict] = []

    async def fake_render(prompt, *, quality="medium", references=None):
        calls.append({"prompt": prompt, "quality": quality, "ref": bool(references), "refs": len(references or [])})
        return _png(80, 100)
    monkeypatch.setattr(vg, "_openai_render", fake_render)
    checks: list[int] = []

    async def fake_analyze(schema, system, user, **kw):
        props = schema.get("properties") or {}
        if "hero_prompt" in props and "visible_items" in props:          # read the uploaded parent
            return {"description": "a poster", "headline": "Dog shelters need your help", "subline": "", "body_lines": ["Call 01282 000000"], "claim_lines": ["First box free"],
                    "cta": "Adopt. Donate. Volunteer.", "small_print": "Registered charity 1234567", "palette": {"bg": "#147850", "fg": "#ffffff", "accent": "#c81e1e"},
                    "hero_prompt": "a dog behind bars", "hero_placement": "top", "visible_items": ["a dog"]}
        if "hero_prompt" in props:                                           # the new layout
            return {**LAYOUT, "headline": "Give a dog a brighter tomorrow", "claim_lines": ["First box free"], "cta": "Call Burnley Dogs Home on 01282 000000"}
        if "items" in props:                                                 # the vision check: the exact line is wrong first time
            checks.append(1)
            ok = len(checks) > 1
            # The numbered requirements travel in the vision message, not in `user`.
            text = " \n".join(str(b.get("text", "")) for m in (kw.get("messages") or []) for b in (m.get("content") or []) if isinstance(b, dict))
            n = len([l for l in text.splitlines() if l.strip()[:1].isdigit() and ". " in l])
            items = [{"index": str(k + 1), "ok": True, "note": "seen"} for k in range(max(n, 2))]
            items[0] = {"index": "1", "ok": ok, "note": "legible" if ok else "it reads 'Frist box free'"}
            return {"items": items}
        raise AssertionError(f"unexpected schema {list(props)}")
    monkeypatch.setattr(vg, "analyze", fake_analyze)
    sid = str(uuid.uuid4())

    async def run():
        norm = images_mod.normalise(_png(60, 40), "a.png")
        async with Session() as db:
            db.add(AnalysisSession(id=sid, title="t", query="q", status=SessionStatus.COMPLETE))
            parent = SessionImage(session_id=sid, label="Sad dog", filename="a.png", media_type=norm["media_type"], width=norm["width"], height=norm["height"],
                                  size_bytes=len(norm["data"]), sha256=norm["sha256"], data=norm["data"], keep_list=vg.normalise_keep_list(["First box free", {"type": "present", "value": "a dog"}]))
            other = SessionImage(session_id=sid, label="Happy dog", filename="b.png", media_type=norm["media_type"], width=norm["width"], height=norm["height"],
                                 size_bytes=len(norm["data"]), sha256=norm["sha256"], data=norm["data"])
            db.add(parent); db.add(other)
            await db.flush()
            # The run that showed both posters as one piece — its reactions and the other poster go to the image model.
            probe = Probe(session_id=sid, instrument="visual", schema_id="visual.v1", status="complete", model="m", seed=1, agent_count=3, answer_count=3,
                          spec={"images": [{"id": parent.id, "label": "Sad dog"}, {"id": other.id, "label": "Happy dog"}], "question": "Would you share this?", "setting": "a bus stop"},
                          aggregates={"n": 3, "sentence": "24% say it works on them; the happy dog drew every eye.", "put_off": [{"value": "Missing shelter details", "count": 2}],
                                      "noticed": [{"value": "Happy dog", "count": 3}], "changes": [], "verbatims": {"no": [], "mixed": [], "yes": []}})
            db.add(probe)
            await db.commit()
            pid, probe_id = parent.id, probe.id
        async with Session() as db:
            parent = await db.get(SessionImage, pid)
        proposal = {"changes": [{"change": "Name a real local shelter and its phone number", "why": "nowhere to send anyone", "share": "2 of 3"}], "expected": "sharing moves"}
        child = await vg.start_remake(sid, parent, change="Name a real local shelter and its phone number", keep_list=None, probe_id=probe_id, proposal=proposal, mode="fast")
        await vg.run_remake(child.id)
        gen = await vg.start_generate(sid, note="a bus-stop poster", keep_list=["First box free"], mode="fast")
        await vg.run_generate(gen.id)
        async with Session() as db:
            return await db.get(SessionImage, child.id), await db.get(SessionImage, gen.id)
    child, gen = loop.run_until_complete(run())

    # The remake: an edit from the uploaded parent, high quality, the whole poster asked for — and a second attempt that names the miss.
    assert child.status == "ready", child.error
    assert child.brief["render"] == "full" and child.brief["render_attempts"] == 2 and child.brief["reference_used"] is True and child.brief["hero_provider"] == "openai"
    assert calls[0]["ref"] is True and calls[0]["refs"] == 2 and calls[0]["quality"] == "high"   # the base first, the compared poster after it
    p1 = calls[0]["prompt"]
    assert "Image 1 is the poster to remake" in p1 and 'image 2 = "Happy dog"' in p1 and "Name a real local shelter" in p1
    # The whole story goes with it: the campaign question, the run, what they said, the changes and why.
    assert "THE STORY" in p1 and "The campaign question: q" in p1 and "3 people were shown the last version (a bus stop) and asked: Would you share this?" in p1
    assert "the happy dog drew every eye" in p1 and "Missing shelter details (2)" in p1 and "- Name a real local shelter and its phone number — nowhere to send anyone (2 of 3)" in p1
    # Facts on the old poster are locked unless the change names them by number or address: here none are named, so all stay.
    assert "FACTS THAT MUST NOT CHANGE" in p1 and "Registered charity 1234567" in p1 and "Never invent a phone number" in p1
    assert {"type": "text", "value": "Registered charity 1234567"} in child.keep_list
    assert child.brief["locked_facts"] == ["First box free", "Registered charity 1234567", "Call 01282 000000"] and child.brief["other_posters"] == ["Happy dog"] and child.brief["references_used"] == 2
    assert "NOT an infographic" in p1 and 'HEADLINE (largest): "Give a dog a brighter tomorrow"' in p1 and 'CALL TO ACTION (a clear button or band): "Call Burnley Dogs Home on 01282 000000"' in p1
    assert '"First box free"' in p1 and "MUST SHOW: a dog" in p1
    assert "The previous attempt got these wrong" in calls[1]["prompt"] and "Frist box free" in calls[1]["prompt"]
    assert child.check_result["passed"] is True and all(i["how"] == "vision" for i in child.check_result["items"])
    # The layout writer was told the locked facts too.
    assert vg.change_touches("Call 01282 000000", "Name a real local shelter and its phone number") is False       # the number itself is not named…
    assert vg.change_touches("Call 01282 000000", "replace 01282 000000 with the new line") is True
    assert vg.change_touches("Registered charity 1234567", "Add a charity registration number") is False
    # A fresh generation: a generation (no reference), one attempt once the check passes.
    assert gen.status == "ready" and gen.brief["render"] == "full" and gen.brief["render_attempts"] == 1 and gen.brief["reference_used"] is False
    assert calls[2]["ref"] is False and "print-ready portrait poster" in calls[2]["prompt"]
