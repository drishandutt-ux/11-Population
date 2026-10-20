"""The lay layer and the softer segment rule (2026-10-20, item 4): street-level units derived
from the specialist ones, the base vocabulary under the ontology's, a segment miss that demotes
instead of hiding, and staleness that ignores derived units. Pure, with the model stubbed.

Run:  cd backend && pytest tests/lay_layer_test.py -q
"""
import asyncio
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.scoping import engine, lay_layer, profiles, registry, tagger  # noqa: E402

ONTO = {"nodes": [{"id": "Blackpool", "cls": "geography", "level": "local_authority"}, {"id": "Oxford", "cls": "geography", "level": "local_authority"},
                  {"id": "GP", "cls": "hcp_role"}, {"id": "oral route", "cls": "channel"}, {"id": "TikTok", "cls": "channel"},
                  {"id": "Gig Worker", "cls": "attitude_segment"}, {"id": "Most deprived areas", "cls": "attitude_segment"}],
        "edges": [], "entity_count": 7}


def _u(k, text, **facets):
    prov = facets.pop("provenance_class", "official_statistic")
    return {"id": f"u{k}", "text": text, "source_ref": "[SOURCE quant | ONS | https://ons.gov.uk/x | 2024]", "provenance_class": prov, "trust_tier": "high",
            "facets": {"geography": facets.pop("geography", ["Blackpool"]), "role": facets.pop("role", ["GP"]), "channel": [], "condition": ["Obesity"], "stage": [],
                       "segment": facets.pop("segment", ["Most deprived areas"]), "register": facets.pop("register", "technical"), "time": "2024", "project": "s1"}}


def test_candidates_are_the_specialist_real_units():
    units = [_u(0, "41% dropout in the audit"), _u(1, "a lay line", register="lay"), _u(2, "debate line", provenance_class="model_inference"),
             _u(3, "prescribing rose 12% in deprived deciles", register="professional")]
    assert lay_layer.candidates(units) == [0, 3]
    assert lay_layer.candidates(units, limit=1) == [3]       # a cap keeps the newest


def test_rows_from_keeps_place_time_and_provenance_but_not_the_segment():
    units = [_u(0, "Obesity prevalence is 34-41% in the most deprived decile (ONS 2024)", segment=["Most deprived areas"])]
    rows = lay_layer.rows_from(units, {0: ("yes", "Round here a good third of adults are a lot overweight, the news said.")}, session_id="s1", snapshot_id="snap", now=datetime(2026, 10, 20))
    assert len(rows) == 1
    r = rows[0]
    assert r["text"].startswith("Round here") and r["source_ref"] == units[0]["source_ref"] and r["provenance_class"] == "official_statistic"
    f = r["facets"]
    assert f["register"] == "lay" and f["layer"] == "lay" and f["derived_from"] == "u0" and f["role"] == ["patient", "public"]
    assert f["geography"] == ["Blackpool"] and f["time"] == "2024" and f["segment"] == [] and f["channel"] == []
    # not knowable, or empty, or out of range → no row
    assert lay_layer.rows_from(units, {0: ("no", ""), 1: ("yes", "x"), 5: ("yes", "y")}, session_id="s1", snapshot_id="snap", now=None) == []


def test_derive_calls_the_model_per_batch_and_survives_a_failed_one(monkeypatch):
    calls = []

    async def fake_analyze(schema, system, user, **kw):
        calls.append(user)
        if "methods appendix" in user:
            raise RuntimeError("boom")
        out = []
        for line in user.splitlines():
            if line[:1].isdigit():
                k = int(line.split(".", 1)[0])
                out.append({"index": k, "knowable": "no" if "audit" in line else "yes", "lay": "" if "audit" in line else f"people say thing {k}"})
        return {"units": out}

    monkeypatch.setattr(lay_layer, "analyze", fake_analyze)
    monkeypatch.setattr(lay_layer, "LAY_BATCH", 2)
    units = [_u(0, "41% dropout in the audit"), _u(1, "waits average three weeks for a GP", register="professional"),
             _u(2, "methods appendix: logistic regression"), _u(3, "lay already", register="lay")]
    rows = asyncio.run(lay_layer.derive(units, session_id="s1", snapshot_id="snap", now=None))
    assert len(calls) == 2 and "[place: Blackpool]" in calls[0]
    assert [r["facets"]["derived_from"] for r in rows] == ["u1"] and rows[0]["text"] == "people say thing 1"


def test_lay_unit_reaches_a_lay_twin_with_its_own_route_and_a_segment_miss_only_demotes():
    anc = engine.ancestors_map(ONTO)
    twin = {"geography": ["Blackpool"], "role": ["public"], "channel": ["Local press"], "register": "lay", "segment": ["Gig Worker"], "project": "s1"}
    audit = _u(0, "41% dropout in the audit")
    lay = lay_layer.rows_from([audit], {0: ("yes", "Loads of people stop taking it after a few weeks, round here.")}, session_id="s1", snapshot_id="snap", now=None)[0]
    assert engine.evaluate(audit, twin, [], anc)["visible"] is False
    ev = engine.evaluate(lay, twin, [], anc)
    assert ev["visible"] is True and ev["demoted"] == []
    # a real unit about another group is visible, demoted, and says so
    about_others = _u(1, "GP access is the first barrier", register="lay", role=["public"], segment=["Most deprived areas"])
    ev = engine.evaluate(about_others, twin, [], anc)
    assert ev["visible"] is True and ev["demoted"][0][0] == "segment" and ev["boost"] == -registry.DEMOTE_WEIGHT and "demote:segment" in ev["applied"]
    res = engine.retrieve([audit, lay, about_others], ONTO, {"values": twin}, [], "dropout GP")
    assert [r["unit"]["id"] for r in res["visible"]][0] == lay["id"] and res["visible"][0]["route"] == engine.LAY_ROUTE
    assert [h["unit"]["id"] for h in res["hidden"]] == ["u0"]


def test_base_vocabulary_sits_under_the_ontology():
    voc = registry.vocab(profiles.nodes_by_class(ONTO))
    assert voc["hcp_role"][:2] == ["GP", "practice nurse"] and "community pharmacist" in voc["hcp_role"]   # ontology spelling first, base merged without duplicates
    assert voc["channel"][:2] == ["oral route", "TikTok"] and "Word of mouth" in voc["channel"]
    text = tagger._vocab_text(profiles.nodes_by_class(ONTO))
    assert "roles: GP, practice nurse" in text and "channels: oral route, TikTok, Local press" in text
    # a twin trained as a pharmacist matches the base role even though the ontology never extracted one;
    # a lay twin's channels are the public ones of both lists
    ph = profiles.profile_for(type("A", (), {"id": "a", "session_id": "s1", "role": "Community pharmacist", "background": "", "correlation": "", "humanity": 30,
                                             "demographics": {"region": "Blackpool"}, "segment": None, "exposure": None, "standing": None})(), ONTO)
    assert "community pharmacist" in ph["values"]["role"] and ph["values"]["register"] == "professional"
    lay = profiles.profile_for(type("A", (), {"id": "a", "session_id": "s1", "role": "Cleaner", "background": "", "correlation": "", "humanity": 70,
                                              "demographics": {"region": "Blackpool"}, "segment": None, "exposure": None, "standing": None})(), ONTO)
    assert "TikTok" in lay["values"]["channel"] and "Word of mouth" in lay["values"]["channel"] and "Professional journal" not in lay["values"]["channel"]


def test_stale_ignores_the_lay_layer(monkeypatch):
    from app.services.scoping import service
    units = [_u(0, "a"), _u(1, "b")]
    lay = lay_layer.rows_from(units, {0: ("yes", "x"), 1: ("yes", "y")}, session_id="s1", snapshot_id="snap", now=None)
    bundle = {"units": units + lay, "snapshot_id": "snap", "onto": ONTO, "rules": [], "policy_version": 1, "cache": {}}

    async def fake_bundle(sid):
        return bundle

    class FakeKG(dict):
        pass

    monkeypatch.setattr(service, "_load_bundle", fake_bundle)
    import app.services.knowledge_graph.lightrag_service as lr

    async def fake_get(sid):
        return None

    monkeypatch.setattr(lr, "get_lightrag", fake_get)
    monkeypatch.setattr(lr, "_load_kg", lambda sid: {"chunks": ["a", "b"]})
    st = asyncio.run(service.state("s1"))
    assert st["unit_count"] == 4 and st["lay_count"] == 2 and st["stale"] is False
    assert "derived_from" not in st["counts"] and st["counts"]["layer"] == {"lay": 2}
