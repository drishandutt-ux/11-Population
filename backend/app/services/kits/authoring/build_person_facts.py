"""Personal health facts at published national rates, for kit agents to draw by age (and sex).

    python -m app.services.kits.authoring.build_person_facts

Reads app/data/kits/population_health_gb/health_facts.json (every figure from an official or
peer-reviewed source, URL and table recorded — ONS Census 2021, Health Survey for England,
APMS 2023/4, ONS smoking 2025, Rowlands et al. 2015) and writes person_facts.json: for each
fact the first-person line an agent holds when it applies (or when it does not), the rate by
age band (by sex where published) and the source. No figure here comes from a benchmark poll.
Facts are drawn independently of one another — the sources do not publish their overlap."""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(__file__)
DIR = os.path.join(HERE, "..", "..", "..", "data", "kits", "population_health_gb")

# (source key, yes line, no line, age-limited: only drawn inside the published age bands)
FACTS = [
    ("census_any_condition", "I have a long-term physical or mental health condition or illness.", "I don't have any long-term health condition.", False),
    ("prescribed_medicine_any", "I take prescribed medicine regularly.", "I'm not on any regular prescribed medicine.", False),
    ("unpaid_carer", "I provide unpaid care for a family member, friend or neighbour.", "", False),
    ("health_literacy", "I often find written health information — leaflets, letters, dosage instructions — hard to make sense of.", "", True),
    ("cisr_12plus", "I've been living with symptoms of anxiety or depression lately.", "", False),
    ("current_smoker", "I smoke.", "", False),
    ("obesity", "I'm living with obesity (BMI 30 or more).", "", False),
]


def build() -> dict:
    with open(os.path.join(DIR, "health_facts.json")) as f:
        src = {x["key"]: x for x in json.load(f)["facts"]}
    out = []
    for key, yes, no, age_limited in FACTS:
        x = src[key]
        out.append({
            "key": key, "yes": yes, "no": no or None, "age_limited": age_limited,
            "by_age": x.get("by_age"), "by_age_sex": x.get("by_age_sex"), "overall": x.get("overall"),
            "measure": x.get("measure"), "source": f"{x.get('source')} ({x.get('year')})", "url": x.get("url"), "table": x.get("table"),
        })
    return {"population": "Great Britain / England adults", "person_facts": out,
            "note": "Drawn per agent at the published rate for its age (and sex where published); independent of each other."}


if __name__ == "__main__":
    data = build()
    with open(os.path.join(DIR, "person_facts.json"), "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"person_facts: {len(data['person_facts'])} facts")
