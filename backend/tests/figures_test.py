"""Source figures with provenance (brief L6-03): every quoted number cites its source and class;
a number the model typed with nothing behind it is flagged.

Run:  cd backend && pytest tests/figures_test.py -q
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.simulation import figures as fg  # noqa: E402


def _ev(**kw):
    base = dict(id="e1", source_class="web", source_ref="https://example.org/x", author="example.org", title="A page", text="excerpt",
                published_at="2024", relevance=0.5, on_topic=True, trust_tier="medium", structured={})
    base.update(kw)
    return SimpleNamespace(**base)


def test_provenance_class_follows_the_tagger_rules():
    assert fg.class_for_evidence(_ev(source_class="quant")) == "official_statistic"
    assert fg.class_for_evidence(_ev(source_class="social")) == "social_signal"
    assert fg.class_for_evidence(_ev(source_class="personal")) == "client_data"
    assert fg.class_for_evidence(_ev(source_class="synthetic")) == "model_inference"
    assert fg.class_for_evidence(_ev(source_ref="https://www.bmj.com/content/1")) == "peer_reviewed"
    assert fg.class_for_evidence(_ev(source_ref="https://www.ons.gov.uk/people")) == "official_statistic"
    assert fg.class_for_evidence(_ev(source_ref="https://blackpoolgazette.co.uk/a")) == "grey_literature"


def test_ledger_numbers_typed_facts_and_items_with_their_class():
    q = _ev(id="q1", source_class="quant", author="ons.gov.uk", title="Obesity 2024", relevance=0.9, trust_tier="high",
            structured={"source_label": "ONS", "facts": [
                {"statistic": "adults living with obesity", "value": "34%", "group": "adults 18+", "geography": "Blackpool", "year": "2024", "quote": "34% of adults …"},
                {"statistic": "redacted teaser", "value": "<redacted>"},
            ]})
    w = _ev(id="w1", source_ref="https://www.nice.org.uk/ta1026", author="nice.org.uk", title="NICE TA1026", relevance=0.7)
    s = _ev(id="s1", source_class="social", author="u/coastalmum", title="r/ukhealth", relevance=0.3, on_topic=False, trust_tier="low")
    led = fg.ledger_from_evidence([s, w, q])
    assert [f["id"] for f in led["facts"]] == ["q1#0"]                       # the redacted fact is not a fact
    assert led["facts"][0]["provenance_class"] == "official_statistic" and led["facts"][0]["source"] == "ONS"
    assert [i["id"] for i in led["items"]] == ["q1", "w1", "s1"]              # on-topic and relevance first
    assert led["items"][2]["provenance_class"] == "social_signal"
    facts_text, items_text, handles = fg.ledger_block(led)
    assert facts_text.startswith("[[F1]] 34% — adults living with obesity (adults 18+, Blackpool, 2024) — ONS [Official statistic] \"34% of adults …\"")
    assert "[[E2]] [Grey literature, trust medium] NICE TA1026" in items_text
    assert handles == {"f1": "[[fact:q1#0]]", "e1": "[[evidence:q1]]", "e2": "[[evidence:w1]]", "e3": "[[evidence:s1]]"}
    out = fg.resolve_handles("Obesity is 34% [[F1]] per the guideline [[E2]]; a stray [[F9]] and [[E7]] vanish.", handles)
    assert out == "Obesity is 34% [[fact:q1#0]] per the guideline [[evidence:w1]]; a stray and vanish."
    assert fg.cited_ids(out) == (["q1#0"], ["w1"])


def test_empty_ledger_tells_the_model_to_use_words():
    facts_text, items_text, handles = fg.ledger_block({"facts": [], "items": []})
    assert "no typed statistics" in facts_text and "no evidence items" in items_text and handles == {}


def test_unsourced_figures_are_flagged_unless_their_sentence_cites_something():
    text = ("Most are in favour 75% [[record:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa]]. About 12% said so. "
            "Obesity is 34% [[fact:bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb#0]] in 2024.\n"
            "It costs £9.90 a month and 3.1 million people qualify; the lift is 8 points (95% CI 2 to 14).\n"
            "The 2021 census and the NHS 10-year plan are not figures.")
    out, flagged = fg.mark_unsourced(text)
    assert flagged == ["12%", "£9.90", "3.1 million", "8 points"]
    assert "About [[unsourced:12%]] said so." in out
    assert "75% [[record:" in out and "34% [[fact:" in out                     # cited sentences untouched
    assert "95% CI 2 to 14" in out and "[[unsourced:95" not in out
    assert "2021 census" in out and "10-year" in out
    assert fg.UNSOURCED_TOKEN_RE.findall(out) == ["12%", "£9.90", "3.1 million", "8 points"]


def test_unsourced_check_leaves_clean_text_alone():
    out, flagged = fg.mark_unsourced("## DIRECT ANSWER\nMost twins agree [[record:cccccccc-cccc-cccc-cccc-cccccccccccc]].\n\nNo numbers here.")
    assert flagged == [] and out == "## DIRECT ANSWER\nMost twins agree [[record:cccccccc-cccc-cccc-cccc-cccccccccccc]].\n\nNo numbers here."
