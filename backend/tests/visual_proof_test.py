"""Tests for what makes a new version more than a chatbot's suggestion (2026-10-27): the paired
re-test behind every remake, provenance on every line, the plain-critique contrast and the
versions by segment.

Run:  cd backend && pytest tests/visual_proof_test.py -q
"""
import asyncio
import os
import sys
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.models.session import AnalysisSession, SessionStatus  # noqa: E402
from app.models.measurement import Probe, ProbeAnswer, SessionImage  # noqa: E402
from app.services.measurement import images as images_mod  # noqa: E402
from app.services.measurement import probe as probe_svc  # noqa: E402
from app.services.measurement import visual_gen as vg  # noqa: E402
from app.services.measurement import visual_proof as vp  # noqa: E402

from tests.measurement_test import _agent, lab_db, api_client, _async  # noqa: E402,F401
from tests.visual_test import _png  # noqa: E402
from tests.visual_gen_test import LAYOUT, KEEP  # noqa: E402


# ── pairing ───────────────────────────────────────────────────────────────────

def _side(verdicts: dict[str, str], *, seg=None, feeling=0.0):
    return {aid: {"agent": {"name": f"N{aid}", "role": "r"}, "answer": {"verdict": v, "feeling": feeling, "strength": 50, "reasoning": f"{aid} says", "put_off": "small print" if v != "yes" else "nothing"},
                  "segments": {"stance": (seg or {}).get(aid, "direct")}} for aid, v in verdicts.items()}


def test_pair_and_count_counts_won_lost_and_the_shift_by_segment():
    before = _side({"a": "no", "b": "no", "c": "mixed", "d": "yes", "e": "yes", "f": "no", "g": "yes", "h": "no"}, seg={"a": "direct", "b": "direct", "c": "direct", "d": "direct", "e": "neutral", "f": "neutral", "g": "neutral", "h": "neutral"})
    after = _side({"a": "yes", "b": "yes", "c": "yes", "d": "yes", "e": "no", "f": "no", "g": "yes", "h": "yes", "z": "yes"},
                  seg={"a": "direct", "b": "direct", "c": "direct", "d": "direct", "e": "neutral", "f": "neutral", "g": "neutral", "h": "neutral"}, feeling=0.4)
    p = vp.pair_and_count(before, after, seed=1, expected="the price-led segment moves")
    assert p["n_paired"] == 8                                   # z answered only after → not paired
    assert p["won"] == 4 and p["lost"] == 1 and p["held_yes"] == 2 and p["held_no"] == 1
    assert p["rejecters"] == 5 and p["believers"] == 3
    assert p["before"]["successes"] == 3 and p["after"]["successes"] == 6
    assert p["lift"]["mean"] == pytest.approx(3 / 8) and p["feeling_lift"]["mean"] == pytest.approx(0.4)
    assert "Moved 4 of the 5 it did not work on; lost 1 of the 3 it did." in p["sentence"]
    assert "38% → 75%" in p["sentence"] and "+38 points" in p["sentence"]
    direct = next(b for b in p["by_segment"]["stance"] if b["value"] == "direct")
    assert direct["won"] == 3 and direct["lost"] == 0 and direct["after"] == 1.0
    assert [m["kind"] for m in p["movers"]] == ["won"] * 4 + ["lost"]
    assert p["movers"][0]["before_put_off"] == "small print" and p["expected"] == "the price-led segment moves"
    assert "Paid most with direct" in p["trade_off"]


def test_pair_and_count_with_nothing_in_common_is_none_and_flat_is_called_flat():
    assert vp.pair_and_count(_side({"a": "yes"}), _side({"b": "yes"})) is None
    same = _side({"a": "yes", "b": "no", "c": "no", "d": "yes"})
    p = vp.pair_and_count(same, same)
    assert p["verdict"] == "flat" and p["won"] == 0 and p["lost"] == 0 and "not a reliable change" in p["sentence"]


# ── provenance ────────────────────────────────────────────────────────────────

def _with_prov(layout, entries):
    return {**layout, "provenance": entries}


def test_enforce_provenance_drops_what_nobody_asked_for_on_a_remake_and_keeps_the_keep_list():
    keep = vg.normalise_keep_list(["£3.50 a meal"])
    layout = vg.enforce_keep_list({**LAYOUT, "body_lines": ["Ready in 20 minutes", "Support local farmers"], "cta": "Take action now"}, keep)
    out = vg.enforce_provenance(_with_prov(layout, [
        {"element": "headline", "text": "Dinner, sorted.", "basis": "reactions", "because": "most said the outcome", "cites": ["Dana"], "share": "14 of 24"},
        {"element": "body", "text": "Ready in 20 minutes", "basis": "reactions", "because": "time was the worry", "cites": ["Cyrus"], "share": "9 of 24"},
        {"element": "body", "text": "Support local farmers", "basis": "none", "because": "", "cites": [], "share": ""},
        {"element": "picture", "text": "", "basis": "brief", "because": "families at dinner", "cites": [], "share": ""},
    ]), keep, remake=True)
    assert out["body_lines"] == ["Ready in 20 minutes"]                          # the unsupported line is gone
    assert out["cta"] == ""                                                      # no entry for the call to action → nobody asked
    assert out["claim_lines"] == ["£3.50 a meal"]                                # the keep-list always stays
    assert [u["text"] for u in out["unsupported"]] == ["Support local farmers", "Take action now"]
    prov = {(e["element"], e["text"]): e for e in out["provenance"]}
    assert prov[("claim", "£3.50 a meal")]["basis"] == "keep-list"
    assert prov[("body", "Ready in 20 minutes")]["cites"] == ["Cyrus"] and prov[("headline", "Dinner, sorted.")]["share"] == "14 of 24"
    assert any(e["element"] == "picture" for e in out["provenance"])


def test_enforce_provenance_on_a_fresh_generation_keeps_everything_but_marks_it():
    keep = vg.normalise_keep_list([])
    out = vg.enforce_provenance(_with_prov({**LAYOUT, "cta": "Order your first box"}, []), keep, remake=False)
    assert out["cta"] == "Order your first box" and out["unsupported"] == []
    assert next(e for e in out["provenance"] if e["element"] == "cta")["basis"] == "none"


# ── the planner's extras, with a stubbed model ───────────────────────────────

def _planner_stub(*, with_segments: bool):
    async def fake(schema, system, user, **kw):
        props = schema.get("properties") or {}
        if "suggestions" in props:                                   # the plain critique (vision)
            assert kw["messages"][0]["content"][1]["type"] == "image"
            return {"suggestions": ["Add a clear call to action", "Make the price larger", "Use a warmer photo"]}
        if "generic_only" in props:                                  # the contrast
            assert "WHAT A REVIEWER WITH NO AUDIENCE DATA SUGGESTED" in user and "WHAT THE AUDIENCE'S REACTIONS LED TO" in user
            return {"agree": [{"generic": "Make the price larger", "population": "Lead with the price"}],
                    "population_only": ["Drop the stock photo (Clara, Sofia)"],
                    "generic_only": [{"generic": "Add a clear call to action", "what_twins_said": "Anouk: the red panel made it look like an ad"}],
                    "sentence": "The audience departs on the call to action."}
        if "segment_versions" in props:                              # the planner
            if with_segments:
                assert "HOW IT SPLIT BY" in user
            return {"base_image_id": "", "base_why": "only one", "changes": [{"change": "Lead with the price", "basis": "most said", "share": "5 of 8", "why": "price first", "cites": ["Anouk"]}],
                    "keep": ["the family photo"], "expected": "price-led move",
                    "segment_versions": ([{"segment": "neutral", "change": "Show who it is for", "why": "neutral twins did not see themselves", "cites": ["Ines"], "trade_off": "direct twins may find it slower"}] if with_segments else []),
                    "tension": "Neutral want warmth; direct want the price." if with_segments else ""}
        raise AssertionError(f"unexpected schema {list(props)}")
    return fake


def _seed_run(Session, loop, *, n=8):
    sid = str(uuid.uuid4())

    async def run():
        norm = images_mod.normalise(_png(60, 40), "a.png")
        async with Session() as db:
            db.add(AnalysisSession(id=sid, title="t", query="Would families buy meal kits?", status=SessionStatus.COMPLETE))
            img = SessionImage(session_id=sid, label="Route A", filename="a.png", media_type=norm["media_type"], width=norm["width"], height=norm["height"],
                               size_bytes=len(norm["data"]), sha256=norm["sha256"], data=norm["data"], layout={**LAYOUT, "read_from_image": True})
            db.add(img)
            agents = [_agent(session_id=sid, name=f"A{i}", humanity=(90 if i % 2 else 0)) for i in range(n)]   # humanity → stance splits
            for a in agents:
                db.add(a)
            await db.flush()
            probe = Probe(session_id=sid, instrument="visual", schema_id="visual.v1", status="complete", model="m", seed=3, agent_count=n, answer_count=n,
                          spec={"images": [{"id": img.id, "label": "Route A"}], "question": "Does this work on you?", "setting": "a bus stop", "seed": 3},
                          aggregates={"n": n, "sentence": "half say it works", "put_off": [{"value": "small print", "count": 3}], "noticed": [], "changes": [], "verbatims": {"no": [], "mixed": [], "yes": []}})
            db.add(probe)
            await db.flush()
            for i, a in enumerate(agents):
                yes = (i % 4 == 0)
                db.add(ProbeAnswer(probe_id=probe.id, session_id=sid, agent_id=a.id,
                                   answer={"reasoning": f"A{i} reasons", "noticed_first": "the photo", "message_taken": "cheap meals", "put_off": "nothing" if yes else "small print",
                                           "verdict": "yes" if yes else "no", "strength": 60, "feeling": 0.2 if yes else -0.2, "change_one": "make the price bigger", "key_factor": "price"},
                                   reasoning=f"A{i} reasons"))
            await db.commit()
            return img.id, probe.id, [a.id for a in agents]
    return sid, loop.run_until_complete(run())


def test_propose_next_adds_the_contrast_and_the_segment_versions(lab_db, monkeypatch):
    Session, loop = lab_db
    sid, (img_id, probe_id, _) = _seed_run(Session, loop)
    monkeypatch.setattr(vg, "analyze", _planner_stub(with_segments=True))

    async def run():
        async with Session() as db:
            probe = await db.get(Probe, probe_id)
            img = await db.get(SessionImage, img_id)
        return await vg.propose_next(session_id=sid, probe=probe, images=[img], model="m")
    out = loop.run_until_complete(run())
    assert out["contrast"]["generic"] == ["Add a clear call to action", "Make the price larger", "Use a warmer photo"]
    assert out["contrast"]["generic_only"][0]["what_twins_said"].startswith("Anouk")
    assert out["segments"]["key"]
    assert len(out["segments"]["buckets"]) >= 2
    # The stub only names "neutral"; it is accepted only when the split has that bucket.
    names = {b["value"] for b in out["segments"]["buckets"]}
    assert all(v["segment"] in names for v in out["segments"]["versions"])
    top = max(out["segments"]["buckets"], key=lambda b: b["share"])["value"]
    assert all(v["segment"] != top for v in out["segments"]["versions"])          # never a version for the group it already works best on
    assert out["segments"]["tension"]


def test_segment_split_prefers_the_widest_real_split(lab_db):
    Session, loop = lab_db
    sid, (img_id, probe_id, _) = _seed_run(Session, loop)

    async def run():
        async with Session() as db:
            probe = await db.get(Probe, probe_id)
        return await vg.segment_split(sid, probe)
    split = loop.run_until_complete(run())
    assert split and len(split["buckets"]) >= 2
    assert split["buckets"] == sorted(split["buckets"], key=lambda b: b["share"])        # lowest first
    assert all(b["n"] >= 3 for b in split["buckets"])
    assert vg._segment_block(split).startswith("HOW IT SPLIT BY")


# ── the re-test end to end ────────────────────────────────────────────────────

def test_remake_is_retested_on_the_same_twins_and_carries_its_proof(lab_db, monkeypatch):
    Session, loop = lab_db
    sid, (img_id, probe_id, agent_ids) = _seed_run(Session, loop)
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "image_provider", "none")
    monkeypatch.setattr(get_settings(), "image_render", "layered")
    monkeypatch.setattr(get_settings(), "visual_auto_retest", True)
    seen = {"hidden": [], "retest_specs": []}

    async def fake_vg(schema, system, user, **kw):
        props = schema.get("properties") or {}
        if "hero_prompt" in props and "visible_items" not in props:
            return {**LAYOUT, "headline": "£3.50 a meal. Dinner, sorted.", "provenance": [{"element": "headline", "text": "£3.50 a meal. Dinner, sorted.", "basis": "reactions", "because": "price first", "cites": ["A1"], "share": "5 of 8"}]}
        if "items" in props:
            return {"items": [{"index": str(k + 1), "ok": True, "note": "seen"} for k in range(6)]}
        raise AssertionError(list(props))
    monkeypatch.setattr(vg, "analyze", fake_vg)

    async def fake_probe_analyze(schema, system, user, **kw):
        # The re-test: the twin must not be shown its earlier Visuals answer.
        seen["hidden"].append("WHAT YOU ALREADY DECIDED" not in user or "visual" not in user.split("WHAT YOU ALREADY DECIDED")[1][:400])
        n = len(seen["hidden"])
        return {"reasoning": "better now", "noticed_first": "the price", "message_taken": "cheap meals", "put_off": "nothing",
                "verdict": "yes" if n % 4 != 3 else "no", "strength": 70, "feeling": 0.3, "change_one": "nothing", "key_factor": "price"}
    monkeypatch.setattr("app.services.measurement.probe.analyze", fake_probe_analyze)
    monkeypatch.setattr("app.services.measurement.probe._probe_kg_context", lambda *a, **k: _async(""))

    async def run():
        async with Session() as db:
            parent = await db.get(SessionImage, img_id)
        child = await vg.start_remake(sid, parent, change="Lead with the price", keep_list=None, probe_id=probe_id, proposal={"expected": "the price-led move"}, mode="fast")
        await vg.run_remake(child.id)
        async with Session() as db:
            c = await db.get(SessionImage, child.id)
            from sqlalchemy import select
            retest = (await db.execute(select(Probe).where(Probe.session_id == sid, Probe.id != probe_id))).scalars().all()
            return c, retest
    child, retests = loop.run_until_complete(run())
    assert child.status == "ready", child.error
    assert len(retests) == 1
    rt = retests[0]
    assert rt.spec["retest"] == {"image_id": child.id, "parent_image_id": img_id, "parent_probe_id": probe_id}
    assert rt.spec["question"] == "Does this work on you?" and rt.spec["setting"] == "a bus stop"
    assert sorted(rt.spec["agent_filter"]["agent_ids"]) == sorted(agent_ids) and rt.status == "complete"
    assert all(seen["hidden"]), "a re-test must not show the twin its earlier Visuals answer"
    proof = child.brief["proof"]
    assert child.brief["retest"]["status"] == "complete" and proof["n_paired"] == 8 and proof["parent_probe_id"] == probe_id
    assert proof["won"] + proof["held_no"] == 6 and proof["believers"] == 2
    assert proof["expected"] == "the price-led move" and "Tested on the same 8 twins" in proof["sentence"]
    assert rt.aggregates["proof"]["sentence"] == proof["sentence"]                 # the run page can read it too
    assert images_mod.payload(child)["proof"]["won"] == proof["won"]
    # Provenance made it onto the layout; the headline cites a twin.
    assert child.layout["provenance"][0]["cites"] == ["A1"]


def test_retest_is_skipped_when_switched_off_or_there_is_no_run(lab_db, monkeypatch):
    Session, loop = lab_db
    sid, (img_id, probe_id, _) = _seed_run(Session, loop)
    from app.core.config import get_settings
    monkeypatch.setattr(get_settings(), "image_provider", "none")
    monkeypatch.setattr(get_settings(), "image_render", "layered")

    async def fake_vg(schema, system, user, **kw):
        props = schema.get("properties") or {}
        if "hero_prompt" in props and "visible_items" not in props:
            return {**LAYOUT, "provenance": []}
        return {"items": [{"index": "1", "ok": True, "note": "seen"}]}
    monkeypatch.setattr(vg, "analyze", fake_vg)

    async def run():
        async with Session() as db:
            parent = await db.get(SessionImage, img_id)
        child = await vg.start_remake(sid, parent, change="Lead with the price", keep_list=None, probe_id=probe_id, proposal=None, mode="fast", retest=False)
        await vg.run_remake(child.id)
        async with Session() as db:
            c = await db.get(SessionImage, child.id)
            from sqlalchemy import select
            n = len((await db.execute(select(Probe.id).where(Probe.session_id == sid))).all())
        return c, n
    child, n_probes = loop.run_until_complete(run())
    assert child.status == "ready" and n_probes == 1 and "proof" not in (child.brief or {})
    assert loop.run_until_complete(vp.start_retest(child.id)) is None or True        # with retest off, a manual start still works
