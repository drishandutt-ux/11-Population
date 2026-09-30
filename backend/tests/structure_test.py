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


# ── report overhaul (2026-09-30): what was run, and the questions the records raise ───────────

def _rec(kind, **kw):
    base = {"id": kw.pop("id", kind), "kind": kind, "instrument": kw.pop("instrument", "journey"), "label": kw.pop("label", kind), "estimate": {"n": 40}, "provenance": {}}
    base.update(kw)
    return base


def test_coverage_names_what_ran_and_what_did_not_with_the_tool_to_run_it():
    recs = [_rec("headline", instrument="verdict", estimate={"n": 40}),
            _rec("probe", instrument="journey", candidates=[{"stuck": 9}, {"stuck": 14}], label="Where the population drops off"),
            _rec("messaging", id="m1"), _rec("messaging", id="m2")]
    cov = st.coverage(recs, posts=80, evidence_items=0)
    ran = {x["key"]: x for x in cov["ran"]}
    assert ran["debate"]["phrase"] == "a debate of 80 posts" and ran["verdict"]["phrase"] == "a verdict poll of 40 twins"
    assert ran["journey"]["phrase"] == "a journey with 2 candidate steps" and ran["messaging"]["phrase"] == "2 message tests"
    missing = {x["key"]: x for x in cov["not_run"]}
    assert set(missing) == {"barriers", "lever", "targeting", "commitment"}
    assert missing["lever"]["instrument"] == "journey" and missing["lever"]["needs"] is None  # a journey exists
    based, not_run = st.coverage_line(cov)
    assert based.startswith("a debate of 80 posts, a verdict poll of 40 twins, a journey with 2 candidate steps") and "barriers ranking" in not_run
    block = st.coverage_block(cov)
    assert block.startswith("Ran: a debate of 80 posts") and "Not run: barriers ranking" in block and "do not estimate what it would have shown" in block
    # nothing run at all: every journey-dependent tool needs a journey first
    empty = st.coverage([], posts=0)
    assert st.coverage_line(empty)[0] == "the session's material only"
    assert next(x for x in empty["not_run"] if x["key"] == "messaging")["needs"] == "a journey first"


def test_follow_up_questions_are_written_from_the_records():
    recs = [
        _rec("probe", instrument="journey", label="Where the population drops off",
             candidates=[{"from": {"label": "Tries it"}, "to": {"label": "Keeps it up"}, "stuck": 14, "n": 25}, {"from": {"label": "Hears"}, "to": {"label": "Tries it"}, "stuck": 9, "n": 40}]),
        _rec("probe", instrument="barriers", label="What's in the way", barriers=[{"theme": "communal bin mismanagement", "count": 6}]),
        _rec("lever", label="Lever: door-knock — shift at Hears → Aware", lever={"rule": {"lever": "door-knock"}}, estimate={"value": 0.23, "significant": True, "n": 40}),
        _rec("messaging", label="Messages tested at Hears → Tries it", messaging={"any_significant": False, "messages": [{}, {}, {}]}),
        _rec("headline", instrument="verdict", equity={"available": True, "significant": True, "gap": -60.0}, label="Population verdict on the question"),
    ]
    pos = st.positions_from_answers(_rows())
    qs = st.follow_ups(recs, pos, names={"a3": "Gary Pendleton"})
    assert qs[0] == "Why do 14 of 25 twins stall at 'Tries it → Keeps it up'?"
    assert qs[1] == "What would it take to remove 'communal bin mismanagement' for the 6 twins who raised it?"
    assert qs[2] == "What would have to be true for Gary Pendleton to be right?"
    assert qs[3] == "Where does the gain from 'door-knock' go after 'Aware'?"
    assert qs[4] == "Why do the most deprived twins differ so much from the least deprived on 'Population verdict on the question'?" and len(qs) == 5
    # a session with no records still gets something to ask, in the twins' vocabulary
    generic = st.follow_ups([], [], {})
    assert len(generic) == 3 and all("agent" not in q for q in generic)


def test_build_structure_carries_coverage_follow_ups_and_no_zero_for_an_unasked_question():
    s = st.build_structure(session_query="Q?", records=[], headline=None, positions=[], evidence=[], frame={"level": "none"}, cited_record_ids=[], claimed_band=None,
                           activity={"posts": 12, "evidence_items": 3})
    assert s["version"] == 2 and s["question"]["asked"] is None and s["question"]["answered"] is None
    assert [x["key"] for x in s["coverage"]["ran"]] == ["debate", "evidence"] and s["follow_ups"]
