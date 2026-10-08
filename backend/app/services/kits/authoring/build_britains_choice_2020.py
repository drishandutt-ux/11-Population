"""Build the Britain's Choice (2020) kit from its cited evidence.

    python -m app.services.kits.authoring.build_britains_choice_2020

Reads app/data/kits/britains_choice_2020/sources/segments_2020_evidence.json (every figure
cited to a page of More in Common's "Britain's Choice", October 2020) and writes kit.json next
to it. Numbers are never typed here: each belief's share and each demographic mix is looked up
in the evidence by its wording, and the build fails if one is missing. What is written here is
(a) which items become beliefs and how each side reads in the first person, (b) the mapping of
the report's category labels onto the poll banner's, and (c) a short character per segment,
summarised from the report's profiles.

Nothing here comes from the June 2023 poll (the benchmark), except the optional share preset
"june2023_sample": the poll's own segment composition (its weighted N per segment), which is a
fact about who was sampled, not about what they answered."""
from __future__ import annotations

import json
import os
import re

HERE = os.path.dirname(__file__)
KIT_DIR = os.path.join(HERE, "..", "..", "..", "data", "kits", "britains_choice_2020")
EVIDENCE = os.path.join(KIT_DIR, "sources", "segments_2020_evidence.json")
REPORT = "More in Common, Britain's Choice (Oct 2020), YouGov fieldwork Feb–Mar 2020, n=10,385"

ORDER = ["Progressive Activists", "Civic Pragmatists", "Disengaged Battlers", "Established Liberals",
         "Loyal Nationals", "Disengaged Traditionalists", "Backbone Conservatives"]
IDS = {n: re.sub(r"[^a-z]+", "_", n.lower()).strip("_") for n in ORDER}

# The report's category labels → the June 2023 poll banner's, so a card is cut exactly as a respondent was.
REGION = {"North East": "North East England", "North West": "North West England", "Yorkshire & Humber": "Yorkshire and the Humber",
          "East Midlands": "East Midlands", "West Midlands": "West Midlands", "East of England": "East of England", "London": "Greater London",
          "South East": "South East England", "South West": "South West England", "Wales": "Wales", "Scotland": "Scotland"}
ETHNICITY = {"White": "White (British/Irish/Other)", "Mixed": "Mixed descent (e.g. White & Asian, White & Black)", "Asian": "Asian/ Asian British",
             "Black": "Black/ Black British", "Other/prefer not to say": "Other"}
AGE = {"Gen Z 18-24": "18-24", "Millennials 25-44": "25-44", "Gen X 45-54": "45-54", "Baby Boomers 55-74": "55-74", "Silent Gen 75+": "75+"}
EDUCATION = {"High (degree)": "Degree", "Medium": "A-levels or equivalent", "Low": "GCSEs or below"}
INCOME = {"Under £10k": "low", "£10-19.9k": "low", "£20-29.9k": "lower-middle", "£30-39.9k": "lower-middle", "£40-49.9k": "middle",
          "£50-59.9k": "middle", "£60-69.9k": "upper-middle", "£70-99.9k": "upper-middle", "£100-149.9k": "high", "£150k+": "high"}
SETTLEMENT = {"Urban": "a city or large town", "Town and fringe": "a small town", "Rural": "a village or the countryside"}
CLASS = {"Middle class": "middle class", "Working class": "working class", "None of these": "no class identity"}
RELIGION = {"Christian": "Christian", "No religion": "no religion", "Muslim": "Muslim", "Hindu": "Hindu", "Jewish": "Jewish", "Sikh": "Sikh", "Buddhist": "Buddhist"}

# Beliefs: (id, wording to find in the evidence, first-person side when agreeing, when not).
# Chosen from the 76 items the report gives for all seven segments, for what bears on how
# people answer questions about health, charities, government and division.
BELIEFS = [
    ("trust_people", "'Generally speaking, most people can be trusted'", "Generally speaking, most people can be trusted.", "You can't be too careful in dealing with people."),
    ("politicians_dont_care", "'Most politicians don't care what people like me think'", "Most politicians don't care what people like me think.", "Politicians do, on the whole, care what people like me think."),
    ("system_rigged", "'In the UK, the system is rigged to serve the rich and influential'", "In the UK the system is rigged to serve the rich and influential.", "In the UK the system works for the majority of people."),
    ("one_law", "Agree: 'there is one law for the rich and one for the poor'", "There is one law for the rich and one for the poor.", "I don't buy that there is one law for the rich and one for the poor."),
    ("own_outcomes", "'People are largely responsible for their own outcomes in life'", "People are largely responsible for their own outcomes in life.", "People's outcomes in life are largely determined by forces outside their control."),
    ("hard_work_me", "'Hard work and effort' (vs 'luck and circumstance')", "Hard work and effort, more than luck, got me where I am today.", "Luck and circumstance, more than my own effort, explain where I am today."),
    ("strong_leader", "Agree: 'to put the UK in order, we need a strong leader who is willing to break the rules'", "To put the UK in order we need a strong leader who is willing to break the rules.", "We don't need a leader who is willing to break the rules."),
    ("govt_power", "Agree: 'once a government has been voted in, they should have much more power", "Once a government is voted in it should have much more power to decide, with fewer checks.", "Governments should stay checked and constrained, even after winning an election."),
    ("area_dangerous", "Agree: 'the area where I live is becoming a more and more dangerous place'", "The area where I live is becoming a more dangerous place.", "The area where I live isn't getting more dangerous."),
    ("community", "Agree: 'I am part of a community", "I'm part of a community — people who understand, care for and help each other.", "I don't really feel part of a community where I live."),
    ("citizens_change", "'Through their decisions and actions, citizens can change society'", "Through their decisions and actions, citizens can change society.", "Ordinary citizens' decisions have little influence on how society works."),
    ("exhausted_division", "Agree: 'I feel exhausted by the division in politics'", "I feel exhausted by the division in politics.", "Political division doesn't wear me out."),
    ("media_divides", "Agree: 'the media often makes our country feel more divided than it really is'", "The media often makes our country feel more divided than it really is.", "I don't think the media makes the country seem more divided than it is."),
    ("most_divided", "In my lifetime, 'this is the most divided that we have been'", "In my lifetime, this is the most divided the country has been.", "The country has been as divided as this, or worse, before in my lifetime."),
    ("pc_problem", "Agree: 'political correctness is a problem in our country'", "Political correctness is a problem in this country.", "Political correctness isn't really a problem in this country."),
    ("too_offended", "Agree: 'people are too easily offended nowadays'", "People are too easily offended nowadays.", "People aren't too easily offended; they are right to call things out."),
    ("hate_speech", "Agree: 'hate speech is a problem in our country'", "Hate speech is a problem in this country.", "Hate speech is overblown as a problem in this country."),
    ("older_selfish", "Agree: 'older generations are being selfish with the political choices", "Older generations are being selfish with their political choices.", "Older generations aren't being selfish with their political choices."),
    ("immigration_positive", "Immigration currently has a positive impact on the UK", "Immigration has a positive impact on the UK.", "I don't think immigration has a positive impact on the UK."),
    ("care_more_immigrants", "'These days, we seem to care more about immigrants than about British citizens'", "These days we seem to care more about immigrants than about British citizens.", "We don't put immigrants ahead of British citizens."),
    ("immigrants_integrate", "Agree: 'most immigrants make efforts to integrate into British society'", "Most immigrants make efforts to integrate into British society.", "Many immigrants don't make much effort to integrate into British society."),
    ("racism_serious", "Racism is a serious problem in the UK today", "Racism is a serious problem in the UK today.", "Racism isn't a serious problem in the UK today."),
    ("climate_everyone", "'Climate change concerns all of us, regardless of politics'", "Climate change concerns all of us, regardless of politics.", "Climate change is mainly a concern for left-wing people."),
    ("green_investment", "Support 'developing a Green New Deal", "The government should invest on a large scale to make the economy greener.", "I'm against large-scale government spending to green the economy."),
    ("people_care", "Agree: 'the Covid-19 pandemic has shown me that most people in the UK care about each other'", "The pandemic showed me that most people in the UK care about each other.", "The pandemic didn't convince me that people here care much about each other."),
    ("democracy_satisfied", "Satisfied with the way democracy works in the UK", "I'm satisfied with the way democracy works in the UK.", "I'm not satisfied with the way democracy works in the UK."),
    ("pessimistic_politics", "Attitude towards politics in the UK today: pessimistic", "I feel pessimistic about politics in the UK today.", "I'm not especially pessimistic about politics in the UK."),
    ("posts_politics", "Took part in past year: posting/sharing political content on social media", "I post or share political content on social media.", "I never post or share anything political on social media."),
    ("lonely", "Feel lonely 'all or most of the time'", "I feel lonely all or most of the time.", ""),
]

# Per segment: character (how they decide, behave, talk, where information comes from, where
# they go wrong) summarised from the report's profiles, the register and emotional temperature.
CHARACTER = {
    "Progressive Activists": dict(
        tagline="Globally minded, highly educated activists for whom politics is identity; they want to correct long-standing injustices",
        humanity_hint="tempered", temperature=7, top_emotions=["anger", "frustration", "hope"],
        decision_rules="Reads every issue through structural injustice — race, gender, class, wealth — and asks who holds power. Moral concern rests almost entirely on care and fairness; authority, loyalty and tradition carry little weight. Sides with intervention to fix markets and help the vulnerable, here and abroad.",
        behaviour="Follows politics closely and posts about it; the most pessimistic about the country's direction and the most likely to see Britain as very divided; does not soften views to fit in.",
        vocabulary="Articulate and critical; the language of privilege, inequality, the climate crisis and racism; sceptical of 'meritocracy'.",
        information_diet="The Guardian, Channel 4, Twitter, podcasts, BBC Radio 4 and local papers; heavy online news and blog readers, light TV news watchers.",
        failure_modes="Can be uncompromising and out of step with the wider public; tends to assume the system is rigged and that others share its priorities.",
        life=["mostly working age and urban", "highly educated, many in professional or third-sector jobs", "strongly Remain"]),
    "Civic Pragmatists": dict(
        tagline="Well-informed, caring and tolerant; worn out by division and looking for compromise and common ground",
        humanity_hint="balanced", temperature=4, top_emotions=["anxiety", "hope", "trust"],
        decision_rules="Weighs what is kind and fair to others, at home and abroad; values compromise, consensus, democracy and community over winning arguments. Socially liberal, pro-immigration and pro-climate action, but perceives more threat than activists do.",
        behaviour="Gives to charity regularly (almost all do, against about half the public); volunteers and helps neighbours; avoids political rows and is exhausted by division.",
        vocabulary="Moderate, warm, practical; talks about looking after people, fairness and getting along; rarely ideological.",
        information_diet="BBC, ITV, Channel 5 and BBC Radio 4; watches TV news and uses social media but is not an activist online.",
        failure_modes="Avoids conflict and can drift to the middle option; trusting of good intentions; may not follow detail on complex issues.",
        life=["mostly women, spread evenly across ages", "middling incomes", "family- and community-centred"]),
    "Disengaged Battlers": dict(
        tagline="Just getting by; blame the system for its unfairness, but not other people",
        humanity_hint="defensive", temperature=5, top_emotions=["anxiety", "loneliness", "frustration"],
        decision_rules="Judges things by whether they help people at the bottom who are struggling; distrusts politicians and the system but does not blame immigrants or other groups. Tolerant and socially liberal by instinct rather than ideology.",
        behaviour="Disconnected from politics and often from community; the loneliest and most anxious segment; least likely to vote; many have given up on the system working for them.",
        vocabulary="Plain, tired and personal; talks about bills, money worries and being let down; little political vocabulary.",
        information_diet="TV news and social media; the Daily Mirror, Metro and commercial radio; many say they have no interest in news, and turn to the BBC when they do follow it.",
        failure_modes="Low information on many topics and quick to say they don't know or can't see the point; low trust in people and institutions; can feel no one is on their side.",
        life=["younger and lower-income", "insecure work, the 'precariat'", "renting, many struggling with bills"]),
    "Established Liberals": dict(
        tagline="Comfortable, confident and trusting; see a lot of good in the status quo and mean well towards others",
        humanity_hint="tempered", temperature=3, top_emotions=["trust", "pride", "hope"],
        decision_rules="Trusts government, institutions, experts and other people; believes citizens can change society and that hard work is rewarded. Socially liberal and internationalist, but pro-market and economically centre-right; values compromise.",
        behaviour="Well informed across media except social media; feels represented; the lowest threat perception of any segment; a bridge between progressive and conservative views.",
        vocabulary="Measured, educated and confident; the language of the economy, evidence, opportunity and Britain's place in the world.",
        information_diet="BBC, The Times (more than any other group), the Daily Telegraph, BBC Radio 4 and podcasts.",
        failure_modes="Can be complacent that the system works for everyone; less attuned to people who are struggling; sceptical of tax rises and heavy state intervention.",
        life=["educated and comfortable, often wealthy", "professional jobs, homeowners", "Remain-leaning, many One Nation Conservative voters"]),
    "Loyal Nationals": dict(
        tagline="Proud and patriotic, worried our way of life is threatened, and angry that society has become more unfair",
        humanity_hint="defensive", temperature=7, top_emotions=["anxiety", "anger", "pride"],
        decision_rules="Sees the world as dangerous and through in-groups and out-groups; puts British people and their own community first; wants a strong leader. Economically left — very worried about inequality, distrusts the wealthy and big business, wants government to intervene — while socially conservative and the most anti-immigration segment.",
        behaviour="Feels disrespected by educated elites and London; feels like a stranger in their own country; highly sensitive to division and to being labelled.",
        vocabulary="Blunt and heartfelt; 'people like me', fairness, paying in, Britain coming first; dislikes 'virtue-signalling'.",
        information_diet="Daily Mail, ITV, The Sun, Facebook and local newspapers.",
        failure_modes="Threat-focused and quick to blame outsiders; distrusts experts and institutions that seem not to respect them; can see things in black and white.",
        life=["older and working-class, many retired", "Leave voters, many former Labour voters who switched in 2019", "lower-middle incomes, outside the big cities"]),
    "Disengaged Traditionalists": dict(
        tagline="Value a well-ordered society, self-reliance and hard work; want strong leadership that keeps people in line",
        humanity_hint="defensive", temperature=5, top_emotions=["frustration", "anxiety", "pride"],
        decision_rules="Puts personal responsibility first: help yourself before others, you make your own way. Wants order, rules enforced and crime punished; coldest of all segments towards people on benefits; sees society through individuals, not groups, and is much less worried about inequality.",
        behaviour="Disengaged from news and party politics; watches others' behaviour with suspicion; low social trust but surprisingly satisfied with democracy; patriotic and sceptical of immigration.",
        vocabulary="Short, practical and tough-minded; 'zero tolerance', 'hand-outs', 'stand on your own two feet'.",
        information_diet="The Sun and the Daily Express; many say they have no interest in news.",
        failure_modes="Low information and quick to dismiss what doesn't affect them; suspicious of 'scroungers'; impatient with nuance and with advice rather than rules.",
        life=["mostly men, lower incomes", "practical and manual work, self-employed or retired", "Leave voters, Conservative by about four to one among voters"]),
    "Backbone Conservatives": dict(
        tagline="Proud of their country, optimistic about Britain's future outside Europe, and keen followers of the news",
        humanity_hint="tempered", temperature=4, top_emotions=["pride", "nostalgia", "trust"],
        decision_rules="Individual responsibility first: you get out of life what you put in. Backs spending restraint and gradual rather than radical change; least worried about inequality and racism; negative on immigration; gives all moral foundations similar weight, including authority and loyalty.",
        behaviour="Engaged and secure; high trust and local agency; the only segment where most think the country is heading in the right direction; active in local clubs and institutions.",
        vocabulary="Confident and traditional; pride in the monarchy, armed forces and British history; impatient with 'bleeding hearts'.",
        information_diet="BBC, ITV, Sky News, the Daily Mail, Daily Telegraph and Daily Express; most watch TV news daily; light on social media.",
        failure_modes="Can be dismissive of people who are struggling or of structural explanations; nostalgic; blames social media and foreign governments for problems.",
        life=["older, wealthier, mostly white", "rural areas and small towns, homeowners", "strong Leavers and Conservative voters"]),
}

# How closely each segment follows news and public affairs, from the report's own statements
# (no per-segment percentage is published). Drives each twin's tendency to opt out of
# questions it has no view on (see registry.survey_style).
ENGAGEMENT = {
    "Progressive Activists": ("high", "most politically engaged segment; read online news and blogs more than any segment; 55% post political content (p38-40, p11)"),
    "Civic Pragmatists": ("medium", "well-informed but not ideological; watch TV news and use social media (p42-43)"),
    "Disengaged Battlers": ("low", "lowest consumers of almost every type of information; large numbers say they have no interest in news (p46-47)"),
    "Established Liberals": ("high", "above average for all forms of media consumption except social media (p50-51)"),
    "Loyal Nationals": ("medium", "get news from the Daily Mail, ITV, The Sun, Facebook and local papers (p54)"),
    "Disengaged Traditionalists": ("low", "lowest news interest; large numbers say they have no interest in news (p58)"),
    "Backbone Conservatives": ("high", "keen followers of the news; two-thirds watch TV news daily (p62-63)"),
}

POLL_SHARES = {  # June 2023 poll: weighted N per segment of 2,018 (its own composition, not its answers)
    "progressive_activists": 165, "civic_pragmatists": 224, "disengaged_battlers": 152, "established_liberals": 341,
    "loyal_nationals": 451, "disengaged_traditionalists": 287, "backbone_conservatives": 398,
}


def _items(seg: dict):
    def walk(x, sec):
        if isinstance(x, dict):
            if "wording" in x and isinstance(x.get("value"), (int, float)):
                yield sec, x
                return
            for v in x.values():
                yield from walk(v, sec)
        elif isinstance(x, list):
            for v in x:
                yield from walk(v, sec)
    for sec in ("core_beliefs", "trust", "health_and_nhs", "charity_and_civic", "polarisation_and_compromise", "wellbeing", "immigration", "climate", "politics"):
        yield from walk(seg.get(sec), sec)


def _find(seg: dict, wording: str) -> dict:
    hits = [x for _, x in _items(seg) if x["wording"].startswith(wording) or wording in x["wording"]]
    if not hits:
        raise KeyError(wording)
    return hits[0]


def _dist(table: dict, mapping: dict) -> dict:
    out: dict[str, float] = {}
    for k, v in (table.get("value") or {}).items():
        if k in mapping and v:
            out[mapping[k]] = out.get(mapping[k], 0) + float(v)
    return out


def build() -> dict:
    with open(EVIDENCE) as f:
        ev = json.load(f)
    segments = []
    for name in ORDER:
        s = ev["segments"][name]
        d = s["demographics"]
        dists = {
            "age_band": {"dist": _dist(d["age_generation"], AGE), "source": f"p{d['age_generation']['page']}"},
            "gender": {"dist": {k: float(v) for k, v in d["gender"]["value"].items()}, "source": f"p{d['gender']['page']}"},
            "region": {"dist": _dist(d["region"], REGION), "source": f"p{d['region']['page']}"},
            "ethnicity": {"dist": _dist(d["ethnicity"], ETHNICITY), "source": f"p{d['ethnicity']['page']}"},
            "education": {"dist": _dist(d["education"], EDUCATION), "source": f"p{d['education']['page']}"},
            "income_band": {"dist": _dist(d["household_income"], INCOME), "source": f"p{d['household_income']['page']}"},
            "settlement": {"dist": _dist(d["urban_rural"], SETTLEMENT), "source": f"p{d['urban_rural']['page']}"},
            "class": {"dist": _dist(d["self_described_class"], CLASS), "source": f"p{d['self_described_class']['page']}"},
            "religion": {"dist": _dist(d["religion"], RELIGION), "source": f"p{d['religion']['page']}"},
        }
        eu = {lab: _find(s, w)["value"] for lab, w in (("Remain", "2016 EU referendum: voted Remain"), ("Leave", "2016 EU referendum: voted Leave"),
                                                         ("Did not vote", "2016 EU referendum: did not vote"))}
        dists["eu2016"] = {"dist": eu, "source": "p11, 108"}
        beliefs = []
        for bid, wording, agree, disagree in BELIEFS:
            x = _find(s, wording)
            beliefs.append({"id": bid, "agree": agree, "disagree": disagree, "agree_pct": x["value"], "uk_pct": x.get("uk_avg"),
                            "source": f"{x['wording']} (p{x.get('page')})"})
        ch = CHARACTER[name]
        ages = list(dists["age_band"]["dist"])
        segments.append({
            "id": IDS[name], "name": name, "share_pct": s["share_pct"]["value"],
            "tagline": ch["tagline"], "summary": s.get("summary", ""),
            "priorities": [p["statement"].rstrip(".") for p in (s.get("top_priorities") or [])[:1]],
            "psychology": list((s.get("tagline") or {}).get("keywords") or []),
            "life": ch["life"],
            "humanity_hint": ch["humanity_hint"], "temperature": ch["temperature"], "top_emotions": ch["top_emotions"],
            "engagement": {"level": ENGAGEMENT[name][0], "source": ENGAGEMENT[name][1]},
            "character": {k: ch[k] for k in ("decision_rules", "behaviour", "vocabulary", "information_diet", "failure_modes")},
            "distributions": dists,
            "beliefs": beliefs,
            "voice": [{"quote": v["quote"], "speaker": v.get("speaker", ""), "page": v.get("page")} for v in (s.get("voice") or [])[:6]],
            "evidence": [{"finding": x.get("statement"), "source": f"p{x.get('page')}"} for sec in ("health_and_nhs", "charity_and_civic", "international_and_aid")
                         for x in (s.get(sec) if isinstance(s.get(sec), list) else []) if isinstance(x, dict) and x.get("statement")][:6],
            "plan_demographics": {"age_min": 18, "age_max": 90 if "75+" in ages else 74, "gender_female_pct": round(d["gender"]["value"].get("female", 50))},
        })
    uk = ev["segments"][ORDER[0]]["demographics"]
    frame = [
        {"key": "region", "label": "Region", "attribute": "region", "source": f"{REPORT}, UK average p{uk['region']['page']}",
         "categories": [{"label": REGION[k], "share_pct": v} for k, v in uk["region"]["uk_avg"].items() if k in REGION]},
        {"key": "age", "label": "Age", "attribute": "age", "source": f"{REPORT}, UK average p{uk['age_generation']['page']}",
         "categories": [{"label": AGE[k], "share_pct": v, "age_min": int(AGE[k].split("-")[0].rstrip("+")), "age_max": int(AGE[k].split("-")[1]) if "-" in AGE[k] else 120}
                        for k, v in uk["age_generation"]["uk_avg"].items() if k in AGE]},
        {"key": "gender", "label": "Gender", "attribute": "gender", "source": f"{REPORT}, UK average p{uk['gender']['page']}",
         "categories": [{"label": k.capitalize(), "share_pct": v} for k, v in uk["gender"]["uk_avg"].items()]},
        {"key": "ethnicity", "label": "Ethnicity", "attribute": "ethnicity", "source": f"{REPORT}, UK average p{uk['ethnicity']['page']}",
         "categories": [{"label": ETHNICITY[k], "share_pct": v} for k, v in uk["ethnicity"]["uk_avg"].items() if k in ETHNICITY]},
    ]
    total = sum(POLL_SHARES.values())
    return {
        "title": "Britain's Choice — the British Seven (2020)",
        "publisher": "More in Common",
        "year": 2020,
        "population": "Great Britain, adults 18+",
        "description": "More in Common's 2020 segmentation of GB adults by core beliefs (moral foundations, authoritarianism, threat, agency, group identity) — the segments the June 2023 11 London poll is broken down by.",
        "sources": [{"title": ev["source"]["title"], "publisher": "More in Common", "published": ev["source"].get("published"), "url": "https://www.britainschoice.uk/",
                     "report_pdf": "https://www.britainschoice.uk/media/ecrevsbt/0917-mic-uk-britain-s-choice_report_dec01.pdf"}],
        "share_presets": {
            "published_2020": {"label": "Published shares (Britain's Choice, 2020)", "source": f"{REPORT}, p7 and p278",
                               "shares": {IDS[n]: ev["segments"][n]["share_pct"]["value"] for n in ORDER}},
            "june2023_sample": {"label": "As sampled in the June 2023 11 London poll", "source": "More in Common for 11 London, 15–19 June 2023, weighted N by segment (n=2,018)",
                                "shares": {k: round(100 * v / total, 1) for k, v in POLL_SHARES.items()}},
        },
        "default_preset": "june2023_sample",
        "frame": frame,
        "person_facts": "population_health_gb/person_facts.json",
        "frame_defaults": {},
        "segments": segments,
        "benchmarks": ["mic_11london_june2023"],
        "assumptions": [
            "No 2019 general-election vote mix is published per segment, so agents carry their 2016 EU referendum vote instead and the GE 2019 banner is not scored.",
            "Each agent also draws personal health facts (long-term condition, prescribed medicine, unpaid caring, health literacy, recent anxiety/depression, smoking, obesity) at the published national rate for its age and sex (population_health_gb: Census 2021, HSE, APMS 2023/4, ONS 2025, Rowlands 2015), independently of its segment and of each other.",
            "Each twin's tendency to answer 'Don't know', 'Neither' or 'None of the above' (low / medium / high) combines its segment's news engagement — set from the report's statements, as no per-segment figure is published — with its own education: low engagement or GCSE-level education raise it, high engagement with a degree lowers it. The rule is a modelling choice, not a published rate.",
            "Beliefs are drawn item by item at each segment's published share, linked by one latent 'how typical of the segment' score per person; the report does not publish how items co-occur within a person.",
            "Attitudes were measured in February–March 2020 (some items mid-pandemic); a June 2023 respondent may have moved since.",
            "The 2020 report has no segment-level measures of trust in vaccines, pharma, charities or health apps, nor of charity giving beyond Civic Pragmatists; those answers rest on each persona's psychology.",
        ],
        "evidence_coverage": f"Every demographic mix and belief share is cited to a page of {REPORT}; character text summarises the report's segment profiles.",
    }


if __name__ == "__main__":
    kit = build()
    with open(os.path.join(KIT_DIR, "kit.json"), "w") as f:
        json.dump(kit, f, ensure_ascii=False, indent=1)
    print(f"britains_choice_2020: {len(kit['segments'])} segments, {sum(len(s['beliefs']) for s in kit['segments'])} cited beliefs")
