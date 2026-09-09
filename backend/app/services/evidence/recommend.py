"""Tool recommender: from the frame and the evidence brief, rank the instruments worth running
and pre-fill their specs from what was found. Nothing is auto-run; the Tools menu shows these
first with a 'why' chip."""
from __future__ import annotations

from typing import Optional

from .brief import brief_for_prompt
from .frame import frame_for_prompt
from .llm import analyze, arr, enum, n, obj, s

TOOLS = {
    "debate": "Debate — the live multi-agent discussion with stance shift measured before/after",
    "sentiment_stance": "Sentiment & stance — score posts and measure opinion shift by segment",
    "purchase_intent": "Purchase intent — would you buy / adopt, likelihood, drivers",
    "price_sensitivity": "Price sensitivity — reservation prices, Van Westendorp range, demand curve",
    "budget_allocation": "Budget allocation — share of wallet across competing items",
    "ab_experiment": "A/B experiment — same population, two or more variants, paired lift",
    "conjoint": "Conjoint — feature/price trade-offs and part-worths",
    "maxdiff": "MaxDiff — ranked importance of features or messages",
    "kano": "Kano — must-have / performance / delighter classification",
    "message_testing": "Message testing — clarity, believability, persuasion per message",
    "brand_funnel": "Brand funnel — aware → consider → prefer → buy → recommend",
    "churn": "Churn / renewal — retention at price P after N months",
    "nudge_framing": "Nudge & framing test — same offer under two framings",
    "interviews": "Structured interviews — open answers coded into themes",
    "campaign_game": "Campaign game — turn-based launch/policy simulation with events and a score",
}

SCHEMA = obj({
    "recommendations": arr(obj({
        "tool": enum(list(TOOLS.keys())),
        "confidence": n("0-1 how strongly the question and evidence call for this tool"),
        "reason": s("One sentence tying the recommendation to the question or a specific piece of evidence"),
        "spec_summary": s("What to run, in one sentence, pre-filled from the evidence"),
        "variants": arr(s(), "For A/B, message or framing tests: the concrete variants found in the evidence", 4),
        "price_anchors": arr(s(), "Prices, tariffs, bills or willingness-to-pay figures quoted in the evidence", 4),
        "segments": arr(s(), "Stakeholder groups worth splitting results by", 5),
        "attributes": arr(s(), "Features, attributes or messages people argued about (for conjoint/MaxDiff/Kano)", 6),
    }), "3 to 6 tools, best first", 6),
})

SYSTEM = """You recommend which quantitative instruments to run against a synthetic population for a research question, given the research frame and an evidence brief of what real sources and people said. Mapping guidance: named products/proposals/options compared → A/B experiment; prices, tariffs or willingness to pay mentioned → price sensitivity and purchase intent; polarised or live controversy → debate plus sentiment/stance; feature lists or 'what matters most' → conjoint, MaxDiff, Kano; policy, planning, consultation → stance/debate, structured interviews, campaign game with real events; launch/adoption → purchase intent, brand funnel; budgets or household finances → budget allocation; messaging, campaigns, slogans → message testing and framing. Pre-fill every spec from the evidence (real variants, real price figures, real stakeholder groups, real attributes). Prefer fewer, sharper recommendations."""


def _fallback(frame: Optional[dict]) -> list[dict]:
    kinds = {q.get("kind") for q in (frame or {}).get("sub_questions", [])}
    recs = [{"tool": "debate", "confidence": 0.7, "reason": "Every question benefits from the population's debate with measured stance shift.", "spec_summary": "Run the debate at intensity 3 and measure stance before and after.", "variants": [], "price_anchors": [], "segments": (frame or {}).get("angles", [])[:5], "attributes": []}]
    if "reaction" in kinds:
        recs.append({"tool": "sentiment_stance", "confidence": 0.6, "reason": "The question asks about reaction.", "spec_summary": "Score sentiment and stance by stakeholder group.", "variants": [], "price_anchors": [], "segments": (frame or {}).get("angles", [])[:5], "attributes": []})
    if "comparison" in kinds:
        recs.append({"tool": "ab_experiment", "confidence": 0.6, "reason": "The question compares options.", "spec_summary": "Run the compared options as variants on the same population.", "variants": [], "price_anchors": [], "segments": [], "attributes": []})
    return recs


async def recommend_tools(session_id: str, question: str, frame: Optional[dict], brief: Optional[dict]) -> list[dict]:
    try:
        r = await analyze(
            SCHEMA, SYSTEM,
            f"Question: {question}\n" + (f"\nResearch frame:\n{frame_for_prompt(frame)}\n" if frame else "") + (f"\n{brief_for_prompt(brief, 3000)}\n" if brief else "")
            + "\nAvailable tools:\n" + "\n".join(f"- {k}: {v}" for k, v in TOOLS.items()),
            session_id=session_id, label="research_recommend", max_tokens=4000,
        )
        raw = r.get("recommendations", [])
        if isinstance(raw, dict):
            raw = list(raw.values())
        recs = [x for x in raw if isinstance(x, dict) and x.get("tool") in TOOLS]
        for x in recs:
            for k in ("variants", "price_anchors", "segments", "attributes"):
                v = x.get(k)
                x[k] = [str(i) for i in v] if isinstance(v, list) else ([str(v)] if v else [])
        for x in recs:
            x["label"] = TOOLS[x["tool"]].split(" — ")[0]
            x["confidence"] = round(max(0.0, min(1.0, float(x.get("confidence", 0)))), 2)
        recs.sort(key=lambda x: -x["confidence"])
        return recs or _fallback(frame)
    except Exception as e:  # noqa: BLE001
        print(f"[research] recommend failed: {type(e).__name__}: {e}")
        recs = _fallback(frame)
        for x in recs:
            x["label"] = TOOLS[x["tool"]].split(" — ")[0]
        return recs
