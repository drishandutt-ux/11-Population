"""Tests for the Visual Lab, step 1 (2026-10-26): the image store, the vision path through the
probe runner, the Visuals instrument and image variants in the A/B test.

Run:  cd backend && pytest tests/visual_test.py -q
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
from app.models.measurement import Probe, ProbeAnswer, SessionImage  # noqa: E402
from app.services.measurement import experiment as exp_svc  # noqa: E402
from app.services.measurement import images as images_mod  # noqa: E402
from app.services.measurement import instruments  # noqa: E402
from app.services.measurement import probe as probe_svc  # noqa: E402

from tests.measurement_test import _agent, lab_db, api_client, _async  # noqa: E402,F401

VISUAL = instruments.get("visual")
CHOICE = instruments.get("choice")


def _png(w=40, h=30, alpha=False, colour=(200, 30, 30)):
    from PIL import Image
    img = Image.new("RGBA" if alpha else "RGB", (w, h), colour + ((120,) if alpha else ()))
    out = io.BytesIO()
    img.save(out, format="PNG")
    return out.getvalue()


# ── declaration ───────────────────────────────────────────────────────────────

def test_visual_is_registered_and_testable():
    assert VISUAL is not None and not VISUAL.hidden
    assert VISUAL.stimulus_key == "images" and VISUAL.question_from == "question"
    assert VISUAL.supports_experiments() and VISUAL.primary_metric().key == "verdict"
    assert VISUAL.decision_key == "verdict" and VISUAL.driver_key == "theme"
    assert list(VISUAL.answer_schema["properties"])[0] == "reasoning"
    assert [f.key for f in VISUAL.inputs] == ["images", "setting", "question"]
    assert VISUAL.inputs[0].type == "images" and not VISUAL.inputs[0].required   # the list is checked by validate()


def test_validate_requires_at_least_one_image():
    assert VISUAL.validate({}) and VISUAL.validate({"images": []})
    assert VISUAL.validate({"images": [{"id": "x", "label": "Poster"}]}) == []
    assert VISUAL.validate({"images": [{"id": f"i{k}"} for k in range(7)]})


def test_refs_tolerate_bare_ids_and_drop_junk():
    refs = images_mod.refs_in({"images": ["a", {"id": "b", "label": "B", "option": "A"}, {"nope": 1}, "", 7]})
    assert refs == [{"id": "a", "label": ""}, {"id": "b", "label": "B", "option": "A"}]
    assert images_mod.refs_in({"images": "a"}) == [] and images_mod.refs_in({}) == []


# ── normalising an upload ─────────────────────────────────────────────────────

def test_normalise_downscales_and_reencodes():
    big = _png(4000, 2000)
    out = images_mod.normalise(big, "poster.png")
    assert out["media_type"] == "image/jpeg"            # opaque → JPEG
    assert max(out["width"], out["height"]) == images_mod.MAX_EDGE
    assert out["width"] == 1568 and out["height"] == 784
    assert len(out["data"]) < len(big) and len(out["sha256"]) == 64


def test_normalise_keeps_transparency_as_png_and_small_images_as_is():
    out = images_mod.normalise(_png(40, 30, alpha=True), "logo.png")
    assert out["media_type"] == "image/png" and (out["width"], out["height"]) == (40, 30)


def test_normalise_rejects_non_images_and_empties():
    with pytest.raises(images_mod.ImageError):
        images_mod.normalise(b"not an image at all", "x.jpg")
    with pytest.raises(images_mod.ImageError):
        images_mod.normalise(b"", "x.jpg")


def test_tokens_follow_pixels():
    assert images_mod.tokens_for(1500, 1500) == 3000
    assert images_mod.tokens_for(0, 0) == 1600            # unknown size: a sensible guess, never zero


# ── the vision message ────────────────────────────────────────────────────────

def _img(id_="i1", label="Poster", option=""):
    return {"id": id_, "label": label, "option": option, "media_type": "image/jpeg", "data_b64": "QUJD", "width": 10, "height": 10}


def test_vision_content_lays_out_caption_image_then_the_message():
    blocks = images_mod.vision_content([_img(), _img("i2", "Leaflet")], "THE QUESTION: does it work?")
    assert [b["type"] for b in blocks] == ["text", "image", "text", "image", "text"]
    assert blocks[0]["text"].startswith("IMAGE 1 of 2 — Poster")
    assert blocks[1]["source"] == {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"}
    assert blocks[-1]["text"] == "THE QUESTION: does it work?"
    one = images_mod.vision_content([_img()], "q")
    assert one[0]["text"] == "THE IMAGE — Poster"


def test_choice_captions_carry_the_option_key():
    blocks = images_mod.vision_content([_img(option="A"), _img("i2", "Route B", option="B")], "q")
    assert blocks[0]["text"] == "OPTION A — Poster" and blocks[2]["text"] == "OPTION B — Route B"


def test_user_message_describes_the_images_and_never_stringifies_the_list():
    spec = {"images": [{"id": "i1", "label": "Poster"}], "setting": "a poster at the bus stop", "question": "Would you stop?"}
    msg = probe_svc._build_user_message(
        agent=_agent(), instrument=VISUAL, spec=spec, query="Should we run the campaign?",
        kg_context="", said=[], decided=[], images=[_img()],
    )
    assert "WHAT YOU ARE LOOKING AT: the image attached above." in msg
    assert "a poster at the bus stop" in msg
    assert "{'id'" not in msg and "[{" not in msg           # the list never reaches the prompt as text
    assert "WHAT YOU ARE BEING ASKED ABOUT" not in msg      # no text stimulus block for an image stimulus
    assert "THE QUESTION: Would you stop?" in msg


def test_looking_at_block_names_the_options_for_a_choice():
    block = images_mod.looking_at_block([_img(option="A"), _img("i2", option="B")], {})
    assert "labelled by option (A, B)" in block and "do not invent text" in block


# ── aggregate ─────────────────────────────────────────────────────────────────

def _row(k, verdict, noticed, put_off, change="make the price bigger", theme="", coded_noticed="", coded_put_off=""):
    a = {"reasoning": f"r{k}", "noticed_first": noticed, "message_taken": "cheap meals", "put_off": put_off,
         "verdict": verdict, "strength": 60 + k, "feeling": 0.1 * (1 if verdict == "yes" else -1),
         "change_one": change, "key_factor": f"factor {k}"}
    if theme:
        a["theme"] = theme
    if coded_noticed:
        a["noticed_first__theme"] = coded_noticed
    if coded_put_off:
        a["put_off__theme"] = coded_put_off
    return {"agent_id": f"a{k}", "agent": {"name": f"N{k}", "role": "r"}, "answer": a,
            "segments": {"stance": "direct" if k % 2 else "neutral", "age_band": "25-34"}}


def test_aggregate_before_coding_reads_the_raw_words():
    rows = [_row(0, "yes", "the photo", "nothing"), _row(1, "no", "the photo", "tiny small print"),
            _row(2, "mixed", "the headline", "Nothing."), _row(3, "yes", "the photo", "tiny small print")]
    agg = VISUAL.aggregate(rows, {"seed": 1})
    assert agg["n"] == 4 and agg["headline"]["share"] == 0.5 and agg["headline"]["label"] == "Works on them"
    assert agg["noticed"][0]["value"] == "the photo" and agg["noticed_coded"] is False
    assert [(d["value"], d["count"]) for d in agg["put_off"]] == [("tiny small print", 2)] and agg["put_off_coded"] is False
    assert agg["nothing_put_off"]["successes"] == 2        # "nothing" and "Nothing." both count as nothing
    assert len(agg["changes"]) == 4
    assert "most eyes went first to \"the photo\"" in agg["sentence"]
    assert "put people off is \"tiny small print\"" in agg["sentence"]
    assert set(agg["verbatims"]) == {"yes", "mixed", "no"} and agg["verbatims"]["no"][0]["put_off"] == "tiny small print"
    assert "stance" in agg["segments"]


def test_aggregate_prefers_the_coded_themes_once_they_exist():
    rows = [_row(k, "yes", "x", "y", theme="price", coded_noticed="the hero photo", coded_put_off="legibility") for k in range(3)]
    agg = VISUAL.aggregate(rows, {})
    assert agg["themes"][0]["value"] == "price" and agg["themes_coded"]
    assert agg["noticed"][0]["value"] == "the hero photo" and agg["noticed_coded"]
    assert agg["put_off"][0]["value"] == "legibility" and agg["put_off_coded"]


def test_aggregate_with_no_rows_is_safe():
    assert VISUAL.aggregate([], {})["n"] == 0


# ── the choice design with image variants ─────────────────────────────────────

def test_compose_choice_spec_tags_each_variants_images_with_its_option():
    variants = [
        {"key": "A", "label": "Route A", "spec": {"images": [{"id": "i1", "label": "Poster A"}], "setting": "a bus stop", "question": "Which?"}},
        {"key": "B", "label": "Route B", "spec": {"images": [{"id": "i2", "label": "Poster B"}, {"id": "i3"}]}},
    ]
    spec = exp_svc.compose_choice_spec(VISUAL, variants, {}, "Which would you go for?", 7)
    assert spec["images"] == [
        {"id": "i1", "label": "Poster A", "option": "A"},
        {"id": "i2", "label": "Poster B", "option": "B"},
        {"id": "i3", "label": "", "option": "B"},
    ]
    assert "OPTION A — Route A\n(image attached, labelled OPTION A)" in spec["stimulus"]
    assert "OPTION B — Route B\n(images attached, labelled OPTION B)" in spec["stimulus"]
    assert spec["setting"] == "a bus stop" and spec["option_keys"] == ["A", "B"]
    assert "[{" not in spec["stimulus"]


def test_compose_choice_spec_is_unchanged_for_text_tools():
    ask = instruments.get("ask")
    spec = exp_svc.compose_choice_spec(ask, [{"key": "A", "spec": {"material": "Hello"}}, {"key": "B", "spec": {"material": "Hi"}}], {}, "", 1)
    assert "images" not in spec and spec["stimulus"] == "OPTION A — A\nHello\n\nOPTION B — B\nHi"


def test_referenced_by_finds_an_image_inside_probe_specs_and_experiment_variants():
    assert images_mod.referenced_by({"images": [{"id": "i1"}]}, "i1")
    assert images_mod.referenced_by([{"key": "A", "spec": {"images": ["i1"]}}], "i1")
    assert not images_mod.referenced_by({"images": [{"id": "i2"}], "setting": "i1"}, "i1")


# ── end to end: the image reaches the model call ──────────────────────────────

def test_run_probe_shows_the_image_to_every_twin(lab_db, monkeypatch):
    Session, loop = lab_db
    session_id = str(uuid.uuid4())
    calls = []

    async def fake_analyze(schema, system, user, **kw):
        calls.append({"system": system, "user": user, "messages": kw.get("messages")})
        n = len(calls)
        return {"reasoning": f"r{n}", "noticed_first": "the photo", "message_taken": "cheap meals",
                "put_off": "nothing" if n % 2 else "small print", "verdict": "yes" if n % 2 else "no",
                "strength": 70, "feeling": 0.2, "change_one": "bigger price", "key_factor": "the price"}

    monkeypatch.setattr("app.services.measurement.probe.analyze", fake_analyze)
    monkeypatch.setattr("app.services.measurement.probe._probe_kg_context", lambda *a, **k: _async(""))

    async def run():
        async with Session() as db:
            db.add(AnalysisSession(id=session_id, title="Posters", query="Which poster?", status=SessionStatus.COMPLETE))
            for i in range(3):
                db.add(_agent(session_id=session_id, name=f"A{i}"))
            norm = images_mod.normalise(_png(60, 40), "poster.png")
            img = SessionImage(session_id=session_id, label="Poster A", filename="poster.png", media_type=norm["media_type"],
                               width=norm["width"], height=norm["height"], size_bytes=len(norm["data"]), sha256=norm["sha256"], data=norm["data"])
            db.add(img)
            await db.flush()
            p = Probe(session_id=session_id, instrument="visual", schema_id="visual.v1", model="test-model", seed=3,
                      spec={"images": [{"id": img.id, "label": "Poster A"}], "setting": "a bus stop", "question": "Would you stop?", "seed": 3})
            db.add(p)
            await db.commit()
            return p.id

    probe_id = loop.run_until_complete(run())
    loop.run_until_complete(probe_svc.run_probe(probe_id))

    async def read():
        async with Session() as db:
            return await db.get(Probe, probe_id)
    done = loop.run_until_complete(read())
    assert done.status == "complete" and done.answer_count == 3, done.error
    assert len(calls) == 3
    for c in calls:
        content = c["messages"][0]["content"]
        assert content[0] == {"type": "text", "text": "THE IMAGE — Poster A"}
        assert content[1]["type"] == "image" and content[1]["source"]["media_type"] == "image/jpeg"
        assert content[-1]["text"].endswith("Record your answer with the tool.")
        assert "WHAT YOU ARE LOOKING AT" in content[-1]["text"] and "a bus stop" in content[-1]["text"]
        assert "LOOKING AT A PICTURE" in c["system"]
    assert done.aggregates["headline"]["successes"] == 2 and done.aggregates["put_off"][0]["value"] == "small print"


def test_run_probe_fails_cleanly_when_an_image_is_gone(lab_db, monkeypatch):
    Session, loop = lab_db
    session_id = str(uuid.uuid4())
    monkeypatch.setattr("app.services.measurement.probe._probe_kg_context", lambda *a, **k: _async(""))

    async def run():
        async with Session() as db:
            db.add(AnalysisSession(id=session_id, title="t", query="q", status=SessionStatus.COMPLETE))
            db.add(_agent(session_id=session_id))
            p = Probe(session_id=session_id, instrument="visual", schema_id="visual.v1", model="m", seed=1,
                      spec={"images": [{"id": "missing"}], "question": "x", "seed": 1})
            db.add(p)
            await db.commit()
            return p.id
    probe_id = loop.run_until_complete(run())
    loop.run_until_complete(probe_svc.run_probe(probe_id))

    async def read():
        async with Session() as db:
            return await db.get(Probe, probe_id)
    done = loop.run_until_complete(read())
    assert done.status == "failed" and "no longer in the session" in done.error


# ── the API ───────────────────────────────────────────────────────────────────

def test_image_api_round_trip(api_client):
    client, Session = api_client
    sid = client.post("/api/v1/sessions", json={"title": "Posters", "query": "Which poster lands?"}).json()["id"]

    up = client.post(f"/api/v1/sessions/{sid}/images", files={"file": ("poster.png", _png(2000, 1000), "image/png")}, data={"label": "Route A"})
    assert up.status_code == 200, up.text
    img = up.json()
    assert img["label"] == "Route A" and img["media_type"] == "image/jpeg" and img["width"] == 1568
    assert img["tokens_per_showing"] > 0 and "data" not in img

    listed = client.get(f"/api/v1/sessions/{sid}/images").json()["images"]
    assert [i["id"] for i in listed] == [img["id"]]

    f = client.get(f"/api/v1/sessions/{sid}/images/{img['id']}/file")
    assert f.status_code == 200 and f.headers["content-type"].startswith("image/jpeg") and len(f.content) == img["size_bytes"]

    assert client.patch(f"/api/v1/sessions/{sid}/images/{img['id']}", json={"label": "Route A v2"}).json()["label"] == "Route A v2"
    assert client.post(f"/api/v1/sessions/{sid}/images", files={"file": ("x.txt", b"hello", "text/plain")}).status_code == 400

    # The estimate prices the image into every call.
    plain = client.post(f"/api/v1/sessions/{sid}/probes/estimate", json={"instrument": "visual", "spec": {"question": "q"}}).json()
    with_img = client.post(f"/api/v1/sessions/{sid}/probes/estimate", json={"instrument": "visual", "spec": {"question": "q", "images": [{"id": img["id"]}]}}).json()
    assert plain["image_tokens"] == 0 and with_img["image_tokens"] == img["tokens_per_showing"]

    # A run that names the image protects it from deletion; a run without images is refused outright.
    assert client.post(f"/api/v1/sessions/{sid}/probes", json={"instrument": "visual", "spec": {"question": "q"}}).status_code == 400
    assert client.get(f"/api/v1/sessions/{sid}/images/nope").status_code == 404
    other = client.post("/api/v1/sessions", json={"title": "Other", "query": "q"}).json()["id"]
    assert client.get(f"/api/v1/sessions/{other}/images/{img['id']}").status_code == 404   # scoped to its session

    assert client.delete(f"/api/v1/sessions/{sid}/images/{img['id']}").status_code == 200
    assert client.get(f"/api/v1/sessions/{sid}/images").json()["images"] == []
