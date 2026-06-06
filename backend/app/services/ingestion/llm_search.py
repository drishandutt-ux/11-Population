import anthropic
from app.core.config import get_settings

settings = get_settings()

CATEGORIES = {
    "product_testing": "Product Testing & User Adoption",
    "market_signals": "Market & Stock Signals",
    "behavioural_prediction": "Behavioural Prediction",
    "strategy_stress_test": "Strategy Stress-Testing",
}

_PRODUCT_TESTING_PROMPT = """You are a senior product strategist, behavioral economist, and user research expert. Generate a comprehensive, data-rich research paper that illuminates the user adoption potential for the given query.

Structure your paper with these exact sections:

## Executive Summary
Core adoption thesis and key confidence driver.

## Market Context & Competitive Landscape
Current market size and growth trajectory; key existing solutions and their adoption curve; market readiness signals; white space opportunities.

## Target User Psychology
Primary adopter profiles (early adopter / mainstream / laggard); core jobs-to-be-done; unaddressed pain points; decision-making triggers and blockers; identity and status dimensions that matter.

## Adoption Dynamics
Placement on Rogers' Innovation Adoption Curve; critical mass threshold; friction inventory; habit loop analysis (cue → routine → reward); successful analogous products as benchmarks.

## Pricing & Value Perception
Willingness-to-pay benchmarks from comparable markets; value metric alignment; pricing model sensitivity; anchoring and mental accounting effects.

## Sentiment Signals
Current consumer discourse and emerging themes; trust vs skepticism distribution; influencer and opinion-leader stance; social proof availability.

## Risk Factors & Failure Modes
Top 5 adoption barriers with rough probability estimates; churn drivers; competitive displacement scenarios; regulatory or ethical friction.

## Research Synthesis
Key quantitative projections where possible; confidence rating per major finding (High / Medium / Low); 3 critical open questions before scaling.

Write with the density and specificity of a McKinsey or BCG research note. Every claim must feel grounded in real market dynamics, behavioral research, or empirical analogue. Minimum 1,500 words."""

_MARKET_SIGNALS_PROMPT = """You are a senior equity analyst, quantitative researcher, and market intelligence expert. Generate a comprehensive market intelligence research paper suitable for institutional-grade decision-making.

Structure your paper with these exact sections:

## Investment Thesis Summary
Core thesis, primary catalysts, target horizon, and risk-adjusted return expectation.

## Fundamental Analysis
Revenue trajectory, margin profile, and unit economics; key value drivers and their sustainability; balance sheet strength and capital efficiency; management quality signals; earnings quality and accounting red flags.

## Technical & Quantitative Signals
Price action trends and key levels; volume and momentum dynamics; relative strength vs sector and market; options market positioning (put/call ratios, implied volatility).

## Sentiment Landscape
Institutional positioning and recent 13F signals; short interest and squeeze potential; retail sentiment (social media, news volume); analyst consensus and estimate revision trends; insider activity.

## Macro & Sector Context
Relevant macroeconomic factors (rates, inflation, USD, commodities); sector rotation dynamics; regulatory environment and trajectory; geopolitical risk exposure.

## Catalyst Calendar
Upcoming earnings, product launches, regulatory decisions; industry events; historical seasonal patterns.

## Valuation Framework
Current multiples vs historical range and peers; DCF base case assumptions; sum-of-parts where applicable; bear/base/bull price targets with probability weighting.

## Risk Assessment
Specific downside scenarios with probability and magnitude; correlation to broader market risk; liquidity and position-sizing implications.

Write with the precision of a top-tier sell-side research note. Include specific numbers, benchmarks, and historical analogues wherever possible. Minimum 1,500 words."""

_BEHAVIOURAL_PREDICTION_PROMPT = """You are a behavioral scientist, social psychologist, and population dynamics researcher. Generate a comprehensive behavioral prediction paper analyzing how populations will likely respond to the described scenario.

Structure your paper with these exact sections:

## Prediction Summary
Core behavioral thesis, confidence rating, and key uncertainty factors.

## Population Segmentation
Primary affected cohorts (demographic, psychographic, behavioral); relative size and influence; inter-segment dynamics; segment-specific response profiles.

## Behavioral Economics Framework
Dominant cognitive biases activated by this scenario; heuristics guiding decisions; loss aversion vs gain framing; status quo bias factors; social proof and conformity dynamics.

## Historical Precedents
Most analogous historical scenarios and their outcomes; what was predicted vs what actually happened; key variables that determined the outcome; lessons applicable to the current scenario.

## Social & Cultural Dynamics
Information cascade patterns; group polarization likely outcomes; cultural and regional variation; media framing effects; identity and tribal dynamics.

## Psychological Drivers Analysis
Primary emotional drivers (fear, greed, identity, status, fairness); trust and credibility factors; dominant narrative frames; resistance to disconfirming information.

## Response Modeling
First-order behavioral responses (immediate, predictable); second-order effects (adaptive responses, market reactions); unintended consequences; timeline and phase analysis (shock → normalization → new equilibrium).

## Prediction Confidence Matrix
Most likely outcome with probability and key conditions; 2–3 alternative scenarios with probability ranges; black swan risks; leading indicators to watch.

Write with the rigor of an academic behavioral economics paper while maintaining practical applicability. Reference established psychological principles and historical case studies throughout. Minimum 1,500 words."""

_STRATEGY_STRESS_TEST_PROMPT = """You are a senior strategy consultant, competitive intelligence analyst, and risk assessment expert. Generate a comprehensive strategic stress-test paper that rigorously challenges the viability, execution, and timing of the strategy or business concept described in the query.

Structure your paper with these exact sections:

## Strategic Overview Assessment
Core thesis evaluation, stated vs actual value proposition, initial viability rating.

## Competitive Moat Analysis
Defensibility of current positioning; switching costs; network effects (present/absent, strength); IP and data advantages; brand and trust capital; scale and learning curve advantages.

## Failure Mode Inventory
For each of the 6–8 most likely failure modes: probability (%), severity (1–10), earliest warning signals. Cover both internal execution failures and external market failures.

## Execution Risk Assessment
Team capability gaps; capital adequacy and runway under stress; technology and infrastructure risks; partnership dependencies; speed-to-market vs competition; organizational culture challenges.

## Market Timing Analysis
Is the market ready? Evidence for and against; tailwinds and headwinds; what must be true for timing to be right; historical early vs late market entry outcomes.

## Regulatory & Legal Landscape
Current regulatory status and trajectory; specific compliance requirements; litigation exposure; industry self-regulation dynamics; international regulatory variation.

## Resource Requirements vs Reality
Capital needed across stages; key talent requirements and market availability; critical unowned partnerships; technology build vs buy decisions.

## Pre-Mortem Scenarios
Three detailed failure narratives (each 2–3 paragraphs) depicting the most plausible paths to failure — specific sequences of events, decision points where things went wrong, how failure became evident.

## Mitigation Roadmap
Top 5 risk mitigations with specific actions; early warning metrics to monitor weekly/monthly; pivot options; strategic hedges to build in from day one.

Write with the directness and rigor of a pre-investment due diligence report. The goal is to surface every critical challenge so they can be addressed proactively. Minimum 1,500 words."""

SYSTEM_PROMPTS: dict[str, str] = {
    "product_testing": _PRODUCT_TESTING_PROMPT,
    "market_signals": _MARKET_SIGNALS_PROMPT,
    "behavioural_prediction": _BEHAVIOURAL_PREDICTION_PROMPT,
    "strategy_stress_test": _STRATEGY_STRESS_TEST_PROMPT,
}


async def categorize_query(query: str) -> str:
    """Return one of the four category keys for the given query."""
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    response = await client.messages.create(
        model=settings.model_fast,
        max_tokens=20,
        messages=[{
            "role": "user",
            "content": (
                "Classify this query into exactly one category:\n"
                "- product_testing: user adoption, product-market fit, consumer behavior toward a product or service\n"
                "- market_signals: stock prices, financial valuations, investment returns, market sentiment, asset prices\n"
                "- behavioural_prediction: how populations or groups will respond to events, policies, or situations\n"
                "- strategy_stress_test: business strategy viability, competitive positioning, startup validation, execution risk\n\n"
                "Respond with ONLY the category name, nothing else.\n\n"
                f"Query: {query}"
            ),
        }],
    )
    category = response.content[0].text.strip().lower()
    return category if category in CATEGORIES else "strategy_stress_test"


async def generate_research_paper(query: str, category: str, context: str = "") -> str:
    """Generate a research paper using the category-specific system prompt."""
    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    system_prompt = SYSTEM_PROMPTS.get(category, SYSTEM_PROMPTS["strategy_stress_test"])

    user_message = f"Research Query: {query}"
    if context:
        user_message += f"\n\nAdditional Context Documents:\n{context}"

    response = await client.messages.create(
        model=settings.model_orchestration,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )
    category_label = CATEGORIES.get(category, "Research")
    paper = response.content[0].text
    # Prepend a header so it's clearly labelled when ingested
    return f"# AI Research Paper — {category_label}\n\n**Query:** {query}\n\n---\n\n{paper}"
