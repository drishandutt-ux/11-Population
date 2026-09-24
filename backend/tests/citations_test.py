"""Citations (brief L3-03): a report line traces back to the twin who said it, and the name
the reader sees is read from the record, never retyped by the model.

Run:  cd backend && pytest tests/citations_test.py -q
"""
import os
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.simulation import citations as c  # noqa: E402

A_ID = "11111111-1111-1111-1111-111111111111"
B_ID = "22222222-2222-2222-2222-222222222222"
C_ID = "33333333-3333-3333-3333-333333333333"
P1 = "aaaaaaaa-1111-1111-1111-111111111111"
P2 = "bbbbbbbb-2222-2222-2222-222222222222"


def agent(id_, name, **kw):
    return SimpleNamespace(
        id=id_, name=name, role=kw.get("role", "GP partner"), age=kw.get("age", 48),
        background=kw.get("background", "Runs a list in Blackpool."), stance=kw.get("stance", "direct"),
        demographics=kw.get("demographics", {"region": "Blackpool"}), segment=kw.get("segment"),
        character=kw.get("character"),
    )


def post(id_, agent_id, content, parent=None):
    return SimpleNamespace(id=id_, agent_id=agent_id, content=content, parent_id=parent, type="comment")


SARAH = agent(A_ID, "Sarah Whitmore", segment="Coastal GPs",
              character={"decision_rules": "Guideline first", "archetype": {"id": "x", "name": "Coastal GP"}})
BOLA = agent(B_ID, "Bola Adeyemi", role="Community pharmacist", segment="Pharmacists")


def test_handles_number_the_roster_and_the_transcript():
    h = c.build_handles([SARAH, BOLA], [post(P1, A_ID, "one"), post(P2, B_ID, "two")])
    assert h.handle_of_agent[A_ID] == "A1" and h.handle_of_agent[B_ID] == "A2"
    assert h.agent_by_handle["a2"] == B_ID
    assert h.handle_of_post[P2] == "P2" and h.post_by_handle["p1"] == P1


def test_roster_and_transcript_carry_the_handles_and_the_origin():
    h = c.build_handles([SARAH, BOLA], [post(P1, A_ID, "Rationing by another name.")])
    roster = c.roster_block([SARAH, BOLA], h)
    assert "[A1] Sarah Whitmore" in roster
    assert "cast from the 'Coastal GP' archetype" in roster       # who he was
    assert "written for segment Pharmacists" in roster
    thread = c.transcript_block([post(P1, A_ID, "Rationing by another name.")], {A_ID: SARAH}, h)
    assert thread.startswith("[P1 · A1 Sarah Whitmore | GP partner]:")


def test_likes_are_not_in_the_transcript():
    h = c.build_handles([SARAH], [])
    like = SimpleNamespace(id=P2, agent_id=A_ID, content=None, parent_id=None, type="like")
    assert c.transcript_block([like], {A_ID: SARAH}, h) == ""


def test_resolve_rewrites_handles_to_ids():
    h = c.build_handles([SARAH, BOLA], [post(P1, A_ID, "x"), post(P2, B_ID, "y")])
    out = c.resolve("[[A1]] argued the opposite of [[A2#P2]].", h)
    assert out == f"[[twin:{A_ID}]] argued the opposite of [[twin:{B_ID}|post:{P2}]]."


@pytest.mark.parametrize("written", ["[[A1 #P1]]", "[[a1#p1]]", "[[A1 | P1]]"])
def test_resolve_is_lenient_about_how_the_model_writes_it(written):
    h = c.build_handles([SARAH], [post(P1, A_ID, "x")])
    assert c.resolve(written, h) == f"[[twin:{A_ID}|post:{P1}]]"


def test_a_handle_that_names_nobody_is_dropped_not_shown():
    h = c.build_handles([SARAH], [])
    assert c.resolve("As [[A9]] said, it is rationing.", h) == "As said, it is rationing."


def test_a_typed_name_becomes_a_citation():
    out = c.repair_names("Sarah Whitmore called it rationing.", [SARAH, BOLA])
    assert out == f"[[twin:{A_ID}]] called it rationing."


def test_a_drifted_surname_is_repaired_to_the_right_twin():
    # The Blackpool failure: the report call paraphrased the surname.
    out = c.repair_names("**Sarah Whitfield** disagreed.", [SARAH, BOLA])
    assert out == f"**[[twin:{A_ID}]]** disagreed."


def test_an_ambiguous_first_name_is_left_alone():
    sarah_two = agent(C_ID, "Sarah Okafor", role="Carer")
    # Two Sarahs: a drifted surname cannot be assigned, so the text is left as written.
    assert c.repair_names("Sarah Whitfield disagreed.", [SARAH, sarah_two]) == "Sarah Whitfield disagreed."
    # An exact full name still resolves, however many share the first name.
    assert c.repair_names("Sarah Okafor disagreed.", [SARAH, sarah_two]) == f"[[twin:{C_ID}]] disagreed."


def test_ordinary_capitalised_pairs_are_not_names():
    out = c.repair_names("The Blackpool ICB refused. Sarah The point stands.", [SARAH])
    assert "Blackpool ICB" in out
    assert "Sarah The point" in out                    # 'The' is never a surname


def test_repair_never_rewrites_an_existing_citation():
    text = f"[[twin:{A_ID}|post:{P1}]] and Sarah Whitmore are the same person."
    out = c.repair_names(text, [SARAH])
    assert out == f"[[twin:{A_ID}|post:{P1}]] and [[twin:{A_ID}]] are the same person."


def test_cited_ids_lists_who_the_answer_rests_on():
    text = f"[[twin:{B_ID}]] then [[twin:{A_ID}]] then [[twin:{B_ID}|post:{P2}]]"
    assert c.cited_ids(text) == [B_ID, A_ID]


def test_a_possessive_keeps_its_apostrophe():
    out = c.repair_names("Sarah Whitfield's list is the largest.", [SARAH])
    assert out == f"[[twin:{A_ID}]]'s list is the largest."
