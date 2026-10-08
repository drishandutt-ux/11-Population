"""Build the Shattered Britain (2025) kit from its cited evidence.

    python -m app.services.kits.authoring.build_shattered_britain_2025

Sources (app/data/kits/shattered_britain_2025/sources/):
  - segments_2025_evidence.json — every figure from More in Common's "Shattered Britain" (July
    2025, polling of 20,000+ GB adults), chart values read from rendered pages, cited by page;
  - segments_2025_health_evidence.json — segment findings from More in Common / Wellcome's
    mental-health report (fieldwork Sept–Oct 2025, n=4,071);
  - website.json — what the segment pages on moreincommon.org.uk/seven-segments say (keywords,
    worries, where they live, how they get news, focus-group quotes, the pen portraits),
    summarised in our words.
As with the 2020 kit, no number is typed here: belief shares and demographic mixes are looked
up in the evidence and the build fails if one is missing. A 4-point item becomes a belief whose
"agree" side is points 1+2 of the scale."""
from __future__ import annotations

import json
import os
import re

HERE = os.path.dirname(__file__)
KIT_DIR = os.path.join(HERE, "..", "..", "..", "data", "kits", "shattered_britain_2025")
SRC = os.path.join(KIT_DIR, "sources")
REPORT = "More in Common, Shattered Britain (July 2025), polling of 20,000+ GB adults"

ORDER = ["Progressive Activists", "Incrementalist Left", "Established Liberals", "Sceptical Scrollers",
         "Rooted Patriots", "Traditional Conservatives", "Dissenting Disruptors"]
IDS = {n: re.sub(r"[^a-z]+", "_", n.lower()).strip("_") for n in ORDER}

ETHNICITY = {"White": "White (British/Irish/Other)", "Asian/Asian British": "Asian/ Asian British", "Black/Black British": "Black/ Black British",
             "Mixed descent": "Mixed descent (e.g. White & Asian, White & Black)", "Other": "Other"}
EDUCATION = {"University-educated": "Degree", "Not university-educated": "No degree"}
SETTLEMENT = {"Urban/City Centre": "a city centre", "Suburbs": "the suburbs", "Large Town": "a large town", "Small Town": "a small town", "Rural Area/village": "a village or the countryside"}
FINANCES = {"I am very comfortable financially": "high", "I am relatively comfortable financially": "upper-middle",
            "No money for luxuries but can normally comfortably cover the essentials": "middle",
            "I can only just afford my costs and often struggle to make ends meet": "lower-middle",
            "I cannot afford my costs and often have to go without essentials like food and heating": "low"}
RELIGION = {"No religion": "no religion", "Christian": "Christian", "Buddhist": "Buddhist", "Hindu": "Hindu", "Jewish": "Jewish", "Muslim": "Muslim", "Sikh": "Sikh"}
EU = {"Remain": "Remain", "Leave": "Leave", "Would not vote": "Did not vote"}

# (id, section, key, the scale points that make up "agree", agree text, disagree text)
BELIEFS = [
    ("own_outcomes", "core_beliefs", "agency_1", ["1", "2"], "People are largely responsible for their own outcomes in life.", "People's outcomes in life are largely determined by forces outside their control."),
    ("preserve_institutions", "core_beliefs", "chaos_1", ["1", "2"], "Our political and social institutions are worth preserving and improving, not destroying.", "When I think about our political and social institutions, part of me thinks: just let them all burn."),
    ("reform_not_restart", "psychology", "fig_67b", ["1", "2"], "We can fix the problems in our institutions through reform, without starting over.", "Our institutions can't be fixed by reform — we need to start over."),
    ("covid_exaggerated", "core_beliefs", "conspiracy_grid_2", ["The COVID-19 pandemic was exaggerated to control people"], "The Covid pandemic was exaggerated to control people.", "The Covid pandemic was not exaggerated to control people."),
    ("protect_from_hate_speech", "core_beliefs", "freespeech_1", ["1", "2"], "We need to protect people from dangerous and hateful speech.", "People should be free to say what they think, even if it's controversial or offensive."),
    ("pc_problem", "core_beliefs", "freespeech_2", ["1", "2"], "Political correctness is a problem in this country.", "Political correctness is necessary to make sure people are treated with respect."),
    ("identity_disappearing", "core_beliefs", "nativism_1", ["4", "3"], "British identity is disappearing nowadays.", "British identity is being strengthened through diversity."),
    ("british_first", "core_beliefs", "nativism_2", ["4", "3"], "The government should put British people first.", "The government should prioritise everyone in Britain equally, whatever their nationality or background."),
    ("compromise", "core_beliefs", "compromise", ["4", "3"], "The people I agree with politically need to be willing to listen and compromise.", "The people I agree with politically need to stick to their beliefs and fight."),
    ("people_not_experts", "core_beliefs", "experts_vs_public", ["1", "2"], "Ordinary people understand the country's problems better than experts.", "Experts understand the country's problems better than ordinary people."),
    ("simple_solutions", "core_beliefs", "simple_vs_complex", ["1", "2"], "The big challenges facing the UK are straightforward and just need plain common sense.", "The big challenges facing the UK are complex and need careful expert solutions."),
    ("too_offended", "core_beliefs", "personal_offence", ["4", "3"], "People are too easily offended nowadays.", "People are right to be more sensitive to offensive language and actions."),
    ("immigration_undermined", "core_beliefs", "immigration_undermined_enriched", ["1", "2"], "Immigration has undermined British culture and society.", "Immigration has enriched British culture and society."),
    ("people_decide", "core_beliefs", "democracy_who_decides", ["4", "3"], "The people, not politicians, should take our most important policy decisions.", "Our most important policy decisions should be taken by elected representatives."),
    ("trust_people", "trust", "fig_54", ["1", "2"], "Most people can be trusted.", "You can't be too careful with most people."),
    ("genuine_democracy", "trust", "fig_32b", ["1", "2"], "Britain's system of government is a genuine democracy.", "Britain's system of government is not a genuine democracy."),
    ("trust_neighbours", "trust", "fig_25", ["A great deal", "Quite a lot"], "I trust my neighbours.", "I don't really trust my neighbours."),
    ("rule_breaking_leader", "polarisation_and_debate", "fig_80", ["1", "2"], "The UK needs a leader who is willing to break the rules.", "The UK needs a leader who follows the rules."),
    ("likes_debate", "polarisation_and_debate", "fig_65", ["1", "2"], "I quite like debating political issues with friends.", "I prefer to avoid talking about politics."),
    ("pressure_on_immigration", "polarisation_and_debate", "fig_53", ["4", "3"], "I feel pressure to speak a certain way about subjects like immigration.", "I feel free to speak about subjects like immigration."),
    ("same_opportunities", "psychology", "fig_34", ["1", "2"], "People like me have the same opportunities in society as other people.", "People like me are not offered the same opportunities as others."),
    ("citizens_change", "psychology", "fig_35", ["1", "2"], "Through their decisions and actions, citizens can change society.", "Citizens' decisions and actions have little influence on society."),
    ("risk_averse", "psychology", "fig_30", ["1", "2"], "A sensible person avoids activities that are dangerous.", "I sometimes like doing things that are a little frightening."),
    ("connected", "charity_giving_and_civic", "fig_55", ["4", "3"], "I feel connected to the society around me.", "I feel disconnected from the society around me."),
    ("too_divided", "charity_giving_and_civic", "fig_61", ["The differences between Britons are too big for us to come together"], "The differences between Britons are too big for us to come together.", "The differences between Britons aren't so big that we can't come together."),
    ("best_years_behind", "wellbeing_and_life", "fig_20", ["1", "2"], "Britain's best years are behind us.", "Britain's best years are ahead of us."),
    ("area_more_dangerous", "wellbeing_and_life", "fig_17", ["A bit more dangerous", "Much more dangerous"], "Where I live is getting more dangerous.", "Where I live isn't getting more dangerous."),
]


def _scale_value(values: dict, point: str):
    """The share at one point of a scale: '1' matches '1 - …', '4' matches '4 - …', exact keys otherwise."""
    for k, v in values.items():
        if k == point or k.startswith(point + " - ") or k.startswith(point + " -"):
            return k, v
    return None, None


def _fill_one_gap(values: dict) -> dict:
    """A chart with exactly one unlabelled bar: its share is what the labelled bars leave of 100."""
    nulls = [k for k, v in values.items() if v is None]
    if len(nulls) == 1:
        rest = sum(v for v in values.values() if v is not None)
        return {**values, nulls[0]: max(0, 100 - rest)}
    if nulls:
        raise ValueError(f"{len(nulls)} unlabelled values: {values}")
    return values


def _fill_age_gaps(values: dict, national: dict) -> dict:
    """Age charts leave the smallest bars unlabelled. One gap is the remainder to 100; several
    share the remainder in proportion to those bands' national shares (recorded as an assumption)."""
    nulls = [k for k, v in values.items() if v is None]
    if len(nulls) <= 1:
        return _fill_one_gap(values)
    rest = max(0.0, 100 - sum(v for v in values.values() if v is not None))
    nat = {k: float(national.get(k) or 0) for k in nulls}
    tot = sum(nat.values()) or len(nulls)
    return {**values, **{k: round(rest * (nat[k] or 1) / tot, 1) for k in nulls}}


def _item(seg: dict, section: str, key: str) -> dict:
    sec = seg.get(section) or {}
    x = sec.get(key) if isinstance(sec, dict) else None
    if not x or not x.get("values_pct"):
        raise KeyError(f"{section}.{key}")
    return x


def _agree_pct(seg: dict, section: str, key: str, points: list[str]):
    x = _item(seg, section, key)
    values = x["values_pct"]
    if any(v is None for v in values.values()):
        values = _fill_one_gap(values)
    total = 0.0
    for p in points:
        k, v = _scale_value(values, p)
        if k is None:
            raise KeyError(f"{section}.{key} point {p}")
        total += float(v)
    # A chart of separate statements (each its own "% true") is not one distribution: read raw.
    is_distribution = 95 <= sum(float(v) for v in values.values()) <= 105
    denom = sum(float(v) for k, v in values.items() if not k.lower().startswith("don't know")) if is_distribution else 100
    nat = x.get("national_pct") or {}
    nat_total = None
    if nat and all(_scale_value(nat, p)[1] is not None for p in points):
        nat_denom = sum(float(v) for k, v in nat.items() if v is not None and not k.lower().startswith("don't know")) if is_distribution else 100
        nat_total = round(sum(float(_scale_value(nat, p)[1]) for p in points) * 100 / (nat_denom or 100))
    return round(total * 100 / (denom or 100)), nat_total, x


def _dist(values: dict, mapping: dict) -> dict:
    values = _fill_one_gap(values)
    out: dict[str, float] = {}
    for k, v in values.items():
        if k in mapping and v:
            out[mapping[k]] = out.get(mapping[k], 0) + float(v)
    return out


def build() -> dict:
    with open(os.path.join(SRC, "segments_2025_evidence.json")) as f:
        ev = json.load(f)
    with open(os.path.join(SRC, "segments_2025_health_evidence.json")) as f:
        health = json.load(f)
    with open(os.path.join(SRC, "website.json")) as f:
        web = json.load(f)
    with open(os.path.join(KIT_DIR, "..", "britains_choice_2020", "sources", "segments_2020_evidence.json")) as f:
        uk2020 = json.load(f)["segments"]["Progressive Activists"]["demographics"]["region"]
    segments = []
    for name in ORDER:
        s = ev["segments"][name]
        d = s["demographics"]
        w = web[IDS[name]]
        age = _fill_age_gaps(d["fig_147"]["values_pct"], d["fig_147"].get("national_pct") or {})
        dists = {
            "age_band": {"dist": {k: float(v) for k, v in age.items() if v}, "source": f"Fig 147, p{d['fig_147']['page']}"},
            "gender": {"dist": {k.lower(): float(v) for k, v in d["fig_158"]["values_pct"].items()}, "source": f"Fig 158, p{d['fig_158']['page']}"},
            "ethnicity": {"dist": _dist(d["fig_153"]["values_pct"], ETHNICITY), "source": f"Fig 153, p{d['fig_153']['page']}"},
            "education": {"dist": _dist(d["fig_148"]["values_pct"], EDUCATION), "source": f"Fig 148, p{d['fig_148']['page']}"},
            "income_band": {"dist": _dist(d["fig_149"]["values_pct"], FINANCES), "source": f"Fig 149 (how well off they feel), p{d['fig_149']['page']}"},
            "settlement": {"dist": _dist(d["fig_150"]["values_pct"], SETTLEMENT), "source": f"Fig 150, p{d['fig_150']['page']}"},
            "religion": {"dist": _dist(d["fig_152"]["values_pct"], RELIGION), "source": f"Fig 152, p{d['fig_152']['page']}"},
        }
        eu = s["politics"].get("fig_67eu")
        if eu:
            dists["eu2016"] = {"dist": _dist(eu["values_pct"], EU), "source": f"EU referendum vote, p{eu['page']}"}
        beliefs = []
        for bid, section, key, points, agree, disagree in BELIEFS:
            pct, nat, x = _agree_pct(s, section, key, points)
            beliefs.append({"id": bid, "agree": agree, "disagree": disagree, "agree_pct": pct, "uk_pct": nat,
                            "source": f"{x.get('figure') or key}: {x.get('title') or x.get('question')} (p{x.get('page')})"})
        hs = health["segments"].get(name) or {}
        findings = [f"{f['topic']}: {f['finding']}" + (f" ({f['value']})" if f.get("value") else "") + f" [mental-health report p{f.get('page')}]" for f in hs.get("findings") or []]
        distinct = [f"{x.get('finding')} [p{x.get('page')}]" for x in s.get("distinctive_findings") or [] if isinstance(x, dict) and x.get("finding")]
        voice = [{"quote": q["quote"], "speaker": q.get("speaker", ""), "page": q.get("page")} for q in (s.get("voice") or [])[:4]]
        voice += [{"quote": q["quote"], "speaker": q.get("speaker", ""), "page": q.get("page"), "source": "mental-health report"} for q in (hs.get("quotes") or [])[:2]]
        voice += [{"quote": q["quote"], "speaker": q["speaker"], "source": "moreincommon.org.uk segment page"} for q in w.get("voice") or []]
        ages = list(dists["age_band"]["dist"])
        segments.append({
            "id": IDS[name], "name": name, "share_pct": s["share_pct"]["value"],
            "tagline": w["tagline"], "summary": w["summary"],
            "priorities": w["priorities"], "psychology": w["keywords"], "life": w["life"],
            "humanity_hint": w["humanity_hint"], "temperature": w["temperature"], "top_emotions": w["top_emotions"],
            "character": {k: w[k] for k in ("decision_rules", "behaviour", "vocabulary", "information_diet", "failure_modes")},
            "pen_portrait": w.get("vignette", ""),
            "findings": (distinct + findings)[:14],
            "distributions": dists,
            "beliefs": beliefs,
            "voice": voice,
            "url": w["url"],
            "plan_demographics": {"age_min": 18, "age_max": 90 if "75+" in ages else 74, "gender_female_pct": round(dists["gender"]["dist"].get("female", 50))},
        })
    nat = ev["segments"][ORDER[0]]["demographics"]
    age_nat = _fill_one_gap(nat["fig_147"]["national_pct"])
    region_map = {"North East": "North East England", "North West": "North West England", "Yorkshire & Humber": "Yorkshire and the Humber",
                  "East Midlands": "East Midlands", "West Midlands": "West Midlands", "East of England": "East of England", "London": "Greater London",
                  "South East": "South East England", "South West": "South West England", "Wales": "Wales", "Scotland": "Scotland"}
    frame = [
        {"key": "age", "label": "Age", "attribute": "age", "source": f"{REPORT}, national row of Fig 147 (p{nat['fig_147']['page']})",
         "categories": [{"label": k, "share_pct": v, "age_min": int(k.split("-")[0].rstrip("+")), "age_max": int(k.split("-")[1]) if "-" in k else 120} for k, v in age_nat.items()]},
        {"key": "gender", "label": "Gender", "attribute": "gender", "source": f"{REPORT}, national row of Fig 158 (p{nat['fig_158']['page']})",
         "categories": [{"label": k, "share_pct": v} for k, v in nat["fig_158"]["national_pct"].items()]},
        {"key": "ethnicity", "label": "Ethnicity", "attribute": "ethnicity", "source": f"{REPORT}, national row of Fig 153 (p{nat['fig_153']['page']})",
         "categories": [{"label": ETHNICITY[k], "share_pct": v} for k, v in _fill_one_gap(nat["fig_153"]["national_pct"]).items() if k in ETHNICITY]},
        {"key": "region", "label": "Region", "attribute": "region", "source": f"More in Common, Britain's Choice (2020), UK average p{uk2020['page']} — Shattered Britain publishes no region mix",
         "categories": [{"label": region_map[k], "share_pct": v} for k, v in uk2020["uk_avg"].items() if k in region_map]},
    ]
    return {
        "title": "Shattered Britain — the Seven Segments (2025)",
        "publisher": "More in Common",
        "year": 2025,
        "population": "Great Britain, adults 18+",
        "description": "More in Common's current segmentation (July 2025): seven segments built on new fault lines — appetite for change, simple vs complex solutions, agency, conspiracy and 'own truth', multiculturalism, disconnection, free speech.",
        "sources": [{"title": "Shattered Britain", "publisher": "More in Common", "published": "July 2025", "url": "https://www.moreincommon.org.uk/research/shattered-britain/"},
                    {"title": "The Seven Segments", "url": "https://www.moreincommon.org.uk/seven-segments/"},
                    {"title": "Heading for Hope? Public opinion on mental health (with Wellcome)", "published": "September 2026", "url": "https://www.moreincommon.org.uk/wp-content/uploads/2026/09/mic-Wellcome-Mental-Health-Report.pdf"}],
        "share_presets": {"published_2025": {"label": "Published shares (Shattered Britain, 2025)", "source": f"{REPORT}; moreincommon.org.uk/seven-segments",
                                             "shares": {IDS[n]: ev["segments"][n]["share_pct"]["value"] for n in ORDER}}},
        "default_preset": "published_2025",
        "frame": frame,
        "person_facts": "population_health_gb/person_facts.json",
        "frame_defaults": {"region": {"dist": {c["label"]: c["share_pct"] for c in frame[3]["categories"]}, "source": frame[3]["source"]}},
        "segments": segments,
        "benchmarks": [],
        "assumptions": [
            "Shattered Britain publishes no region mix per segment: every segment's agents are spread over GB regions in the national proportions (Britain's Choice 2020 UK average).",
            "No 2019 or 2024 general-election vote mix is published for every segment, so agents carry their EU referendum vote and no general-election vote.",
            "Thirteen of the 21 segmentation-quiz items (authority, care, autonomy, parenting, the left-right grid, self-efficacy, victimhood) have no published by-segment figures; the beliefs use the 27 items that do.",
            "Where an age chart leaves more than one small bar unlabelled (Sceptical Scrollers: 65-74 and 75+), the unlabelled remainder is split across those bands in proportion to their national shares.",
            "Each agent also draws personal health facts (long-term condition, prescribed medicine, unpaid caring, health literacy, recent anxiety/depression, smoking, obesity) at the published national rate for its age and sex (population_health_gb: Census 2021, HSE, APMS 2023/4, ONS 2025, Rowlands 2015), independently of its segment and of each other.",
            "Beliefs are drawn item by item at each segment's published share, linked by one latent 'how typical of the segment' score per person.",
            "The June 2023 11 London poll is broken down by the 2020 segments, not these — use the Britain's Choice kit to score against it.",
        ],
        "evidence_coverage": f"Every demographic mix and belief share is cited to a figure and page of {REPORT} (chart values read from the rendered pages); health findings from More in Common/Wellcome (2026); character text summarises the segment pages on moreincommon.org.uk.",
    }


if __name__ == "__main__":
    kit = build()
    with open(os.path.join(KIT_DIR, "kit.json"), "w") as f:
        json.dump(kit, f, ensure_ascii=False, indent=1)
    print(f"shattered_britain_2025: {len(kit['segments'])} segments, {sum(len(s['beliefs']) for s in kit['segments'])} cited beliefs")
