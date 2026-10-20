"""Standing-based scoping (2026-10-20): who a twin is to the topic, the "who you are not"
block, the footprint a post carries and the scope check's parsing. Pure; no network.

Run:  cd backend && pytest tests/standing_test.py -q
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.scoping import auto, standing  # noqa: E402


def _agent(**kw):
    base = dict(id="a1", session_id="s1", name="A", role="Retail worker", background="", correlation="", humanity=50, demographics={"region": "Blackpool, England"}, standing=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_normalise_cleans_and_keeps_home_first():
    st = standing.normalise({"lived": "Yes", "lived_detail": "type 2 for nine years", "professional": "none", "expertise": "technical",
                             "known_places": ["Oxford", "Blackpool, England", "oxford"]}, home="Blackpool, England")
    assert st["lived"] == "yes" and st["professional"] == "" and st["expertise"] == "technical"
    assert st["known_places"] == ["Blackpool, England", "Oxford"] and st["basis"] == "written"
    assert standing.normalise("nope") is None
    # a trained role with no expertise given is a professional; lived "no" drops the detail
    st = standing.normalise({"lived": "no", "lived_detail": "x", "professional": "GP"}, home="Oxford")
    assert st["expertise"] == "professional" and st["lived_detail"] == "" and st["home"] == "Oxford"


def test_infer_reads_the_record_not_job_words():
    # the three prod cases from the Oxford / Blackpool run
    hca = standing.of(_agent(role="Healthcare Assistant (Nursing Support)"))
    assert hca["professional"] and hca["expertise"] == "professional" and hca["lived"] == "no" and hca["basis"] == "inferred"
    driver = standing.of(_agent(role="Delivery Driver / Gig Worker", background="Drives for three apps across the Fylde."))
    assert driver["professional"] == "" and driver["expertise"] == "lay" and driver["lived"] == "no"
    card = standing.of(_agent(role="NHS Consultant Cardiologist", humanity=85))
    assert card["expertise"] == "technical" and card["professional"] == "NHS Consultant Cardiologist"
    # lived experience comes from the record's words, carers from theirs
    pat = standing.of(_agent(role="Retired cleaner", correlation="Has lived with obesity for twenty years and was offered the jab last spring."))
    assert pat["lived"] == "yes"
    carer = standing.of(_agent(role="Part-time bookkeeper", background="Looks after her mum, who has type 2 diabetes."))
    assert carer["lived"] == "carer"
    past = standing.of(_agent(role="Chef", background="Used to struggle with his weight years ago; recovered after a long programme."))
    assert past["lived"] == "past"
    # the prod misses: "lives with his wife", "patient flow", a clinician's "patients", "years ago" elsewhere in the record
    assert standing.of(_agent(role="Self-Employed Electrician", background="He lives with his partner in a rented flat in Bispham."))["lived"] == "no"
    assert standing.of(_agent(role="College Student", background="Lives with her mum and younger brother; mum has fibromyalgia."))["lived"] == "no"   # living with someone is not living with it
    assert standing.of(_agent(role="NHS Practice Manager", background="Manages a busy GP surgery, overseeing budgets, staffing and patient flow. Hypertensive, BMI 29."))["lived"] == "no"
    card2 = standing.of(_agent(role="NHS Consultant Cardiologist", background="James trained in London and took a consultant post five years ago. He prescribes GLP-1 agonists for diabetic patients who have heart failure.",
                               correlation="He views oral GLP-1 through the lens of his patient caseload."))
    assert card2["lived"] == "no" and card2["expertise"] == "technical"
    acct = standing.of(_agent(role="Senior Accountant", background="Mild type 2 diabetes diagnosed eighteen months ago; on metformin."))
    assert acct["lived"] == "yes" and acct["professional"] == ""
    assert standing.of(_agent(role="Patient advocate"))["lived"] == "no"
    assert standing.of(_agent(role="Patient"))["lived"] == "yes"
    # a stored standing wins, and its home lands in known places
    st = standing.of(_agent(standing={"lived": "carer", "professional": "", "expertise": "lay", "home": "Oxford", "known_places": [], "basis": "set"}))
    assert st["lived"] == "carer" and st["known_places"] == ["Oxford"] and st["basis"] == "set"


def test_register_and_spoke_from():
    assert standing.register_for({"expertise": "technical"}) == "technical" and standing.register_for({}) == "lay"
    assert standing.spoke_from({"lived": "yes"}) == "lived" and standing.spoke_from({"lived": "carer"}) == "carer"
    assert standing.spoke_from({"lived": "no", "professional": "GP"}) == "professional" and standing.spoke_from({"lived": "no"}) == "public"
    assert standing.summary({"lived": "yes", "professional": "", "home": "Layton, Blackpool"}) == "lives with it · no training in it · Layton"


def test_block_says_who_they_are_and_are_not():
    patient = standing.block(None, {"lived": "yes", "lived_detail": "type 2 diabetes", "professional": "", "expertise": "lay", "home": "Blackpool", "known_places": ["Blackpool"], "basis": "written", "elsewhere": ["Oxford"]})
    assert "you live with this yourself — type 2 diabetes" in patient and "does not make you a clinician" in patient
    assert "Training: NONE in this" in patient and "never try to" in patient
    assert "you live in Blackpool" in patient and "Any other place — Oxford — you know only second-hand" in patient
    gp = standing.block(None, {"lived": "no", "professional": "GP", "professional_field": "primary care", "expertise": "professional", "home": "Oxford", "known_places": ["Oxford"], "basis": "written"})
    assert "Lived experience: NONE" in gp and "or your patients," in gp and "trained as GP — primary care" in gp
    assert "professional's" in gp and "Any other place you know only second-hand" in gp
    # an inferred standing speaks less firmly
    soft = standing.block(_agent(role="Retail worker"))
    assert "nothing in your record says" in soft and "NONE" not in soft
    carer = standing.block(None, {"lived": "carer", "professional": "", "expertise": "lay", "home": "", "known_places": [], "basis": "set"})
    assert "as a carer" in carer and "never claim the body's experience" in carer and "Place:" not in carer


def test_footprint_counts_used_and_withheld_by_dimension():
    res = {"visible": [{"unit": {"id": "u1"}, "route": "via Local press"}, {"unit": {"id": "u2"}, "route": "from something you read"}],
           "hidden": [{"unit": {"id": "u3"}, "failed": [("geography", "x"), ("register", "y")]}, {"unit": {"id": "u4"}, "failed": [("geography", "x")]}]}
    fp = standing.footprint(_agent(role="Delivery Driver"), res, scoped=True, snapshot_id="snap")
    assert fp["spoke_from"] == "public" and fp["scoped"] and fp["used"] == 2 and fp["withheld"] == 2
    assert fp["withheld_by"] == {"geography": 2, "register": 1} and fp["routes"] == ["from something you read", "via Local press"]
    assert fp["standing"]["basis"] == "inferred" and fp["snapshot_id"] == "snap"
    unscoped = standing.footprint(_agent(role="GP"), None, scoped=False)
    assert unscoped["scoped"] is False and unscoped["used"] == 0 and unscoped["spoke_from"] == "professional"


def test_check_parsing_and_prompt():
    out = standing.parse_check({"breaches": [
        {"kind": "clinical_claim", "quote": "the half-life means once-daily dosing is fine", "why": "no training"},
        {"kind": "wizardry", "quote": "x", "why": "y"},
        {"kind": "place_as_fact", "quote": "", "why": "no quote"},
    ]})
    assert out["ok"] is False and [b["kind"] for b in out["breaches"]] == ["clinical_claim"] and out["breaches"][0]["label"] == "clinical claim without training"
    assert standing.parse_check({}) == {"ok": True, "breaches": []}
    prompt = standing.check_prompt({"lived": "carer", "lived_detail": "her mum", "professional": "GP", "professional_field": "primary care", "expertise": "professional", "known_places": ["Oxford"]}, "post text", "the question")
    assert "AS A CARER — her mum" in prompt and "GP — primary care" in prompt and "places known first-hand: Oxford" in prompt and "THE POST\npost text" in prompt


ONTO = {"nodes": [
    {"id": "England", "cls": "geography", "level": "nation", "mentions": 9}, {"id": "North West", "cls": "geography", "level": "region", "mentions": 2},
    {"id": "Lancashire", "cls": "geography", "level": "region", "mentions": 1},
    {"id": "Blackpool", "cls": "geography", "level": "local_authority", "mentions": 8}, {"id": "Oxford", "cls": "geography", "level": "local_authority", "mentions": 7},
    {"id": "Claremont", "cls": "geography", "level": "place", "mentions": 1}, {"id": "GP", "cls": "hcp_role"}],
    "edges": [{"head": "Blackpool", "predicate": "within", "tail": "North West"}, {"head": "Blackpool", "predicate": "within", "tail": "Lancashire"},
              {"head": "North West", "predicate": "within", "tail": "England"}, {"head": "Claremont", "predicate": "within", "tail": "Blackpool"}]}


def test_elsewhere_and_settle():
    st = {"known_places": ["Claremont, Blackpool, England"]}
    # Oxford is elsewhere; Blackpool, Claremont and the areas containing them are not; England is never listed
    assert auto.elsewhere_for(st, ONTO) == ["Oxford"]
    assert auto.elsewhere_for({"known_places": ["Oxford"]}, ONTO) == ["Blackpool", "North West", "Lancashire", "Claremont"]
    assert auto.elsewhere_for(st, None) == []
    a = _agent(role="Delivery Driver", demographics={"region": "Claremont, Blackpool, England"})
    assert auto.settle_standing(a, ONTO) is True
    assert a.standing["basis"] == "inferred" and a.standing["elsewhere"] == ["Oxford"] and a.standing["known_places"] == ["Claremont, Blackpool, England"]
    assert auto.settle_standing(a, ONTO) is False          # idempotent
