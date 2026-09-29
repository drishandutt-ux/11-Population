"""Report structure (brief L6-02): the report's parts wired to the records underneath.

Run:  cd backend && pytest tests/structure_test.py -q
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.simulation import structure as st  # noqa: E402


# ── direct answer: the band is computed, never asserted ──────────────────────

def test_confidence_band_is_fixed_on_the_record_score():
    assert st.confidence_band(95) == "HIGH" and st.confidence_band(70) == "HIGH"
    assert st.confidence_band(69) == "MEDIUM" and st.confidence_band(45) == "MEDIUM"
    assert st.confidence_band(44) == "LOW" and st.confidence_band(None) == "LOW"


def test_a_confidence_line_the_model_writes_anyway_is_stripped_and_remembered():
    text = "## DIRECT ANSWER\nMost are in favour [[record:x]].\n**Confidence: HIGH**\n\n## QUESTION\nWhy."
    out, claimed = st.strip_confidence_line(text)
    assert claimed == "HIGH" and "Confidence" not in out and "## QUESTION" in out
    inline, claimed2 = st.strip_confidence_line("Most are in favour. Confidence: medium. Next.")
    assert claimed2 == "MEDIUM" and inline == "Most are in favour. Next."
    same, none = st.strip_confidence_line("No label here.")
    assert none is None and same == "No label here."


# ── discussion: positions and the named dissent ──────────────────────────────

def _rows():
    mk = lambda k, pos, conf, can="yes": SimpleNamespace(agent_id=f"a{k}", answer={"position": pos, "confidence": conf, "verdict": f"line {k}", "can_answer": can})
    return [mk(1, "for", 80), mk(2, "for", 60), mk(3, "against", 90), mk(4, "mixed", 40), mk(5, "for", 70), mk(6, "against", 20, can="no")]


def test_positions_leave_out_refusals_and_dissent_is_everyone_off_the_majority_most_confident_first():
    pos = st.positions_from_answers(_rows())
    assert [p["agent_id"] for p in pos] == ["a1", "a2", "a3", "a4", "a5"]      # a6 said it was not theirs to answer
    maj, dissent = st.dissent_for(pos)
    assert maj == "for"
    assert [(d["agent_id"], d["position"]) for d in dissent] == [("a3", "against"), ("a4", "mixed")]
    assert st.dissent_for([]) == (None, [])


def test_positions_block_names_the_dissent_by_handle_with_their_line():
    pos = st.positions_from_answers(_rows())
    block = st.positions_block(pos, {"a3": "A3", "a4": "A4"}, {"a3": "Priya", "a4": "Tom"})
    assert "Majority position: for (3 of 5)" in block
    # The handle only: shown the name as well, the model typed both and the reader saw it twice.
    assert "[[A3]] — against (confidence 90/100): \"line 3\"" in block
    assert "[[A4]] — mixed" in block
    assert "Priya" not in block and "Tom" not in block
    unanimous = st.positions_block([{"agent_id": "a1", "position": "for", "confidence": 50, "verdict": "v"}], {}, {})
    assert "DISSENT: none" in unanimous


# ── source materials: the evidence by class ──────────────────────────────────

def test_evidence_is_grouped_by_class_in_role_order_with_trust_and_top_items():
    ev = lambda cls, title, rel, on=True, trust="medium": SimpleNamespace(id=title, source_class=cls, title=title, author="x", source_ref="u", relevance=rel, on_topic=on, trust_tier=trust)
    rows = [ev("web", "w1", 0.2), ev("quant", "q1", 0.9, trust="high"), ev("web", "w2", 0.8), ev("social", "s1", 0.1, on=False)]
    s = st.evidence_summary(rows)
    assert [x["class"] for x in s] == ["quant", "web", "social"]
    assert s[1]["count"] == 2 and s[1]["top"][0]["title"] == "w2" and s[0]["trust"] == {"high": 1}
    assert s[2]["on_topic"] == 0
    assert "Statistics & datasets: 1 item(s), trust high 1" in st.evidence_block(s)
    assert st.evidence_summary([], chunk_count=12)[0]["class"] == "ingested"
    assert "no evidence on file" in st.evidence_block([])


# ── outcome: the caveats come from the cited records ─────────────────────────

def test_caveats_are_the_union_of_cited_records_deduplicated_with_synthetic_last():
    recs = [
        {"id": "r1", "caveats": ["Synthetic population: simulated twins.", "No sampling frame."]},
        {"id": "r2", "caveats": ["No sampling frame.", "Small population (6).", "Synthetic population: simulated twins."]},
        {"id": "r3", "caveats": ["Never cited."]},
    ]
    out = st.caveats_from_records(recs, ["r1", "r2"])
    assert [c["text"] for c in out] == ["No sampling frame.", "Small population (6).", "Synthetic population: simulated twins."]
    assert out[0]["record_ids"] == ["r1", "r2"] and out[1]["record_ids"] == ["r2"]
    # nothing cited → every record contributes
    assert any(c["text"] == "Never cited." for c in st.caveats_from_records(recs, []))


# ── assembly ─────────────────────────────────────────────────────────────────

def test_build_structure_wires_every_section():
    headline = {"id": "h1", "instrument": "verdict", "estimate": {"n": 5}, "provenance": {"agents": 6},
                "confidence": {"score": 72, "drivers": ["5 twins answered"]}, "caveats": ["Synthetic population: x."]}
    pos = st.positions_from_answers(_rows())
    s = st.build_structure(session_query="Q?", records=[headline], headline=headline, positions=pos, evidence=[], frame={"level": "none"},
                           cited_record_ids=["h1"], claimed_band="LOW")
    assert s["direct_answer"] == {"record_id": "h1", "confidence": {"band": "HIGH", "score": 72, "drivers": ["5 twins answered"]}, "claimed_band": "LOW"}
    assert s["question"] == {"session_query": "Q?", "instrument": "verdict", "asked": 6, "answered": 5}
    assert s["discussion"]["majority"] == "for" and s["discussion"]["n"] == 5
    assert s["discussion"]["positions"][0] == {"value": "for", "count": 3, "share": 0.6}
    assert [d["agent_id"] for d in s["discussion"]["dissent"]] == ["a3", "a4"]
    assert s["outcome"]["caveats"][0]["text"] == "Synthetic population: x."
    empty = st.build_structure(session_query="Q?", records=[], headline=None, positions=[], evidence=[], frame={"level": "none"}, cited_record_ids=[], claimed_band=None)
    assert empty["direct_answer"]["confidence"]["band"] is None and empty["discussion"]["majority"] is None
