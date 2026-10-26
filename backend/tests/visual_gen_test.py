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
        if "change" in props:                                                # propose
            return {"change": "Make the price the headline", "keep": ["the family photo"], "why": "most who said no were put off by small print",
                    "cites": ["Anouk Park"], "expected": "the price-led segment moves"}
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
