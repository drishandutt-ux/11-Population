"""Tests for the SimBench grouped runner: the authors' score, the subset, the bare-model prompt and
parser, a subgroup read as a segment, the twins' distribution, and a whole run through the API with
the persona writer and the model stubbed.

Run:  cd backend && pytest tests/simbench_test.py -q
"""
import asyncio
import csv
import json
import os
import sys
import time
import uuid

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.kits import simbench as sb  # noqa: E402

FIELDS = ["group_prompt_template", "group_prompt_variable_map", "input_template", "input_variable_map", "output_format", "answer_options",
          "auxiliary", "group_size", "human_answer", "wave", "group_prompt_variable_list", "num_grouping_vars", "grouping_keys",
          "is_allowed_vars", "dataset_name"]


def _row(dataset, template, variables, question, options, human, keys):
    opts = "\n".join(f"({k}): {v}" for k, v in options.items())
    return {"group_prompt_template": template, "group_prompt_variable_map": repr(variables),
            "input_template": f"{question}\n\nOptions:\n{opts}", "input_variable_map": "{}", "output_format": "choice",
            "answer_options": repr(options), "auxiliary": "{}", "group_size": "500", "human_answer": repr(human), "wave": "",
            "group_prompt_variable_list": "frozenset()", "num_grouping_vars": str(len(keys)),
            "grouping_keys": ("{" + ", ".join(repr(k) for k in keys) + "}") if keys else "set()", "is_allowed_vars": "True", "dataset_name": dataset}


def _write_csv(path, n_groups=6, per_group=3):
    rows = []
    for g in range(n_groups):
        country = ["Poland", "France", "Kenya", "Peru", "Japan", "Chile"][g % 6]
        sex = "female" if g % 2 else "male"
        ds = "ESS" if g < n_groups // 2 else "Afrobarometer"
        for q in range(per_group):
            human = {"A": 50.0 + 10 * q, "B": 30.0 - 5 * q, "C": 20.0 - 5 * q}
            rows.append(_row(ds, f"The year is 2016. You are from {country}.\nYour gender is: {{gndr}}.", {"gndr": sex},
                             f"Question {q}: do you trust parliament?", {"A": "Yes", "B": "No", "C": "Refused"}, human, ["cntry", "gndr"]))
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    return rows


@pytest.fixture
def data(tmp_path, monkeypatch):
    path = tmp_path / sb.CSV_NAME
    _write_csv(path)
    monkeypatch.setattr(sb, "fetch_csv", lambda force=False: str(path))
    monkeypatch.setattr(sb, "csv_path", lambda: str(path))
    monkeypatch.setattr(sb, "SUBSET_PATH", str(tmp_path / "subset.json"))
    return path


# ── the score is the authors' score ───────────────────────────────────────────

def test_tvd_and_score_match_the_published_formula():
    human = {"A": 60.0, "B": 30.0, "C": 10.0}
    norm = sb.uniform_tvd(human)
    assert norm == pytest.approx(0.5 * (abs(0.6 - 1 / 3) + abs(0.3 - 1 / 3) + abs(0.1 - 1 / 3)))
    # Perfect = 100, uniform against its own dataset norm = 0, worse than uniform goes negative.
    assert sb.score_case(human, {"A": 6, "B": 3, "C": 1}, norm)["score"] == 100.0
    assert sb.score_case(human, {"A": 1, "B": 1, "C": 1}, norm)["score"] == pytest.approx(0.0, abs=0.01)
    assert sb.score_case(human, {"A": 0, "B": 0, "C": 1}, norm)["score"] < 0
    # Percentages and proportions are the same once normalised; missing options count as zero.
    assert sb.score_case(human, {"A": 0.6, "B": 0.3}, norm)["tvd"] == pytest.approx(0.1, abs=1e-4)
    assert sb.score_case(human, None, norm) is None
    assert sb.score_case(human, {"A": 0, "B": 0, "C": 0}, norm) is None


def test_dataset_norm_is_the_mean_distance_to_uniform_per_dataset():
    cases = [{"dataset": "X", "human": {"A": 100.0, "B": 0.0}}, {"dataset": "X", "human": {"A": 50.0, "B": 50.0}},
             {"dataset": "Y", "human": {"A": 75.0, "B": 25.0}}]
    norms = sb.dataset_norms(cases)
    assert norms["X"] == pytest.approx((0.5 + 0.0) / 2)
    assert norms["Y"] == pytest.approx(0.25)


# ── the subset ────────────────────────────────────────────────────────────────

def test_subset_is_exact_stratified_and_takes_whole_subgroups(data):
    cases = sb.load_cases(str(data))
    assert len(cases) == 18 and len({c["group_id"] for c in cases}) == 6
    chosen = sb.select_subset(cases, n=9, seed=1)
    assert len(chosen) == 9
    by_ds = {}
    for c in chosen:
        by_ds[c["dataset"]] = by_ds.get(c["dataset"], 0) + 1
    assert set(by_ds.values()) <= {4, 5}               # 50/50 split of 9 by largest remainder
    groups = {}
    for c in chosen:
        groups[c["group_id"]] = groups.get(c["group_id"], 0) + 1
    assert sum(1 for v in groups.values() if v < 3) <= 2   # at most one trimmed subgroup per stratum
    assert [c["id"] for c in sb.select_subset(cases, n=9, seed=1)] == [c["id"] for c in chosen]   # seeded


def test_build_subset_writes_ids_strata_and_the_source_hash(data):
    out = sb.build_subset(n=6, seed=3)
    on_disk = json.load(open(sb.SUBSET_PATH))
    assert on_disk["n"] == 6 and out["source"]["sha256"] == sb.sha256_of(str(data))
    assert set(on_disk["cases"][0]) == {"id", "dataset", "group_id", "stratum"}   # ids only — no human answers in the repo
    assert on_disk["dataset_norms"]["ESS"] > 0
    counts = sb.plan_counts(cases=4)
    assert counts["cases"] == 4 and counts["groups"] == 2               # whole subgroups first
    assert counts["datasets"] == ["Afrobarometer", "ESS"]               # a short run is a slice of every stratum, not the first in the file
    assert all("stratum" in r for r in on_disk["cases"])


# ── the bare model, verbatim ──────────────────────────────────────────────────

def test_bare_prompt_is_the_authors_verbalised_prompt():
    case = {"group_text": "The year is 2016. You are from Poland.", "question": "Q?\n\nOptions:\n(A): yes\n(B): no",
            "human": {"A": 0.5, "B": 0.5}}
    system, user = sb.bare_prompts(case)
    assert system == "You are a group of individuals with these shared characteristics:\nThe year is 2016. You are from Poland."
    assert user.startswith("**Question**: Q?\n\nOptions:\n(A): yes\n(B): no\n\nEstimate what percentage of your group would choose each option. Follow these rules:\n")
    assert '4. Use this exact valid JSON format: {"A": X, "B": X} and do NOT include anything else.\n' in user
    assert user.endswith("Replace X with your estimated percentages for each option.\n**Answer**:")


def test_bare_parser_normalises_and_repairs_like_the_authors():
    assert sb.parse_bare('{"A": 30, "B": 70}', ["A", "B"]) == {"A": 0.3, "B": 0.7}
    assert sb.parse_bare('Sure: {"A": 30%, "B": 50%,}', ["A", "B"]) == pytest.approx({"A": 0.375, "B": 0.625})
    assert sb.parse_bare("{A: 1, B: 3}", ["A", "B"]) == pytest.approx({"A": 0.25, "B": 0.75})
    for bad in ('{"A": 30}', "no json here", '{"A": 0, "B": 0}'):
        with pytest.raises(ValueError):
            sb.parse_bare(bad, ["A", "B"])


# ── a subgroup as a segment, a case as a form ─────────────────────────────────

def test_group_profile_reads_country_year_age_gender_and_traits():
    ess = {"dataset": "ESS", "group_text": "The year is 2016. You are from Poland. Your gender is: female.", "group_vars": {"cntry": "Poland", "gndr": "female"}}
    p = sb.group_profile(ess)
    assert (p["country"], p["year"], p["gender"], p["traits"]) == ("Poland", "2016", "female", [])
    seg = sb.segment_for(ess, 40)
    assert seg["count"] == 40 and seg["demographics"]["gender_female_pct"] == 100 and seg["demographics"]["regions"] == ["Poland"]
    afro = {"dataset": "Afrobarometer", "group_text": "The year is 2023. You are from Kenya. Your age is 65+.", "group_vars": {"country": "Kenya", "age_group": "65+"}}
    assert sb.group_profile(afro)["age"] == (65, 88)
    us = {"dataset": "OpinionQA", "group_text": "You are from the United States. The year is 2019. Your religion is atheist.", "group_vars": {"RELIG": "atheist"}}
    p = sb.group_profile(us)
    assert p["country"] == "United States" and p["traits"] == [("Religion", "atheist")]
    assert "Religion — atheist" in sb.segment_for(us, 10)["description"]


def test_probe_spec_strips_the_option_list_and_asks_for_chances():
    case = {"id": 7, "group_id": "g", "dataset": "ESS", "group_text": "The year is 2016. You are from Poland.", "group_vars": {},
            "question": "Trust parliament?\n\nOptions:\n(A): Yes\n(B): Yes\n(C): No", "options": {"A": "Yes", "B": "Yes", "C": "No"},
            "human": {"A": 40.0, "B": 20.0, "C": 40.0}}
    spec = sb.probe_spec(case, "run")
    q = spec["questions"][0]
    assert q["text"] == "Trust parliament?" and q["likelihood"] is True
    assert q["options"] == ["Yes", "Yes (2)", "No"]                      # repeated texts made distinct, order kept
    assert spec["context"] == {"kg": False, "own_posts": False, "prior_answers": False}
    from app.services.measurement.instruments.survey import validate
    assert validate(spec) == []


def test_twins_distribution_averages_chances_and_counts_refusals():
    case = {"human": {"A": 50.0, "B": 50.0}, "options": {"A": "Yes", "B": "No"}}
    answers = [{"q": "Yes", "_dist": {"q": {"o1": 80, "o2": 20}}},
               {"q": "No", "_dist": {"q": {"o1": 40, "o2": 60}}},
               {"q": "Yes", "can_answer": "no", "_dist": {"q": {"o1": 100, "o2": 0}}}]
    d = sb.twins_distributions(case, answers)
    assert d["refused"] == 1 and d["answers"] == 3
    assert d["likelihood"] == {"A": 0.6, "B": 0.4}
    assert d["draws"] == {"A": 0.5, "B": 0.5}


def test_a_short_run_is_proportional_across_strata():
    refs = [{"id": k, "dataset": ds, "group_id": f"{ds}{k // 2}", "stratum": ds} for k, ds in
            [(k, "Big") for k in range(0, 60)] + [(k, "Small") for k in range(60, 80)]]
    first = sb.first_refs(refs, 20, seed=1)
    big = sum(1 for r in first if r["dataset"] == "Big")
    assert len(first) == 20 and 14 <= big <= 16                        # 3:1 in the subset, 3:1 in the slice
    assert len({r["group_id"] for r in first}) == 10                    # whole subgroups of two
    assert sb.first_refs(refs, 20, seed=1) == first
    assert len(sb.first_refs(refs, 80, groups_limit=3, seed=1)) == 6


def test_summary_pairs_twins_against_the_bare_model():
    def case(ds, tw, bare):
        return {"status": "complete", "dataset": ds, "scores": {"likelihood": {"score": tw}, "draws": {"score": tw - 5}, "bare": {"score": bare}}}
    state = {"cases": {"1": case("ESS", 40, 30), "2": case("ESS", 20, 30), "3": case("OpinionQA", 50, 10), "4": {"status": "failed"}}}
    s = sb.summarise({"bare": True}, state)
    assert s["overall"]["likelihood"]["mean"] == pytest.approx(36.67, abs=0.01)
    assert s["overall"]["bare"]["mean"] == pytest.approx(23.33, abs=0.01)
    assert s["overall"]["twins_minus_bare"]["mean"] == pytest.approx(13.33, abs=0.01)
    assert s["overall"]["twins_minus_bare"]["twins_ahead_share"] == pytest.approx(0.67, abs=0.01)
    assert s["by_dataset"]["ESS"]["cases"] == 2 and s["failed_cases"] == 1
    assert s["by_grouping"] == {}
    state["cases"]["1"]["grouping"] = "cntry+gndr"
    assert sb.summarise({"bare": True}, state)["by_grouping"]["Country + Gender"]["cases"] == 1


# ── a whole run, through the API ──────────────────────────────────────────────

def test_a_run_builds_lineups_scores_every_case_and_reports(data, api_client, monkeypatch):
    from app.services.agents.profiles import AgentProfile
    client, Session = api_client
    sb.build_subset(n=6, seed=3)

    written = []

    async def fake_writer(session_id, query, segments, constraints, *, mode="fast", **kw):
        seg = segments[0]
        written.append((session_id, seg["name"], seg["count"], seg["demographics"]["regions"]))
        return [AgentProfile(id=str(uuid.uuid4()), session_id=session_id, name=f"P{k}", age=40, role="teacher", background="b",
                             stance="neutral", correlation="c", personality=["calm"], debate_style="d", segment=seg["name"])
                for k in range(seg["count"])]
    monkeypatch.setattr("app.services.agents.agent_factory.generate_agents_from_plan", fake_writer)

    async def fake_analyze(schema, system, user, **kw):
        assert "THE QUESTION" in user and "Options:" not in user
        return {"reasoning": "as I see it", "q": {"o1": 60, "o2": 30, "o3": 10}, "can_answer": "yes"}
    monkeypatch.setattr("app.services.measurement.probe.analyze", fake_analyze)

    class _Block:
        text = '{"A": 34, "B": 33, "C": 33}'

    class _Resp:
        content = [_Block()]

    async def fake_create(client_, **kw):
        assert kw["label"] == "simbench:bare" and kw["max_tokens"] == 250 and kw["system"].startswith("You are a group of individuals")
        return _Resp()
    monkeypatch.setattr("app.core.monitoring.tracked_messages_create", fake_create)

    est = client.get("/api/v1/admin/benchmarks/simbench/estimate", params={"cases": 6, "twins": 10}).json()
    assert est["cases"] == 6 and est["groups"] == 2 and est["twin_calls"] == 60 and est["total_usd"] > 0

    run = client.post("/api/v1/admin/benchmarks/simbench/runs", json={"cases": 6, "twins": 10, "parallel_groups": 2}).json()
    assert client.post("/api/v1/admin/benchmarks/simbench/runs", json={"cases": 6}).status_code in (200, 409)
    deadline = time.time() + 60
    while time.time() < deadline:
        got = client.get(f"/api/v1/admin/benchmarks/simbench/runs/{run['id']}", params={"cases": True}).json()
        if got["status"] in ("complete", "failed"):
            break
        time.sleep(0.2)
    assert got["status"] == "complete", got.get("error")
    assert len(written) == 2 and all(n == 10 for _, _, n, _ in written)
    assert got["progress"]["cases_done"] == 6 and got["progress"]["groups_built"] == 2
    case = got["cases"][0]
    assert case["answers"] == 10 and case["twins_likelihood"] == {"A": 0.6, "B": 0.3, "C": 0.1}
    assert set(case["scores"]) == {"likelihood", "draws", "bare"}
    assert set(got["summary"]["by_grouping"]) == {"Country + Gender"}
    overall = got["summary"]["overall"]
    assert overall["cases"] == 6 and overall["likelihood"]["n"] == 6 and overall["bare"]["n"] == 6
    # The human answers lean to A, so the twins' 60/30/10 beat the bare model's even split.
    assert overall["twins_minus_bare"]["mean"] > 0

    # The lineups are benchmark sessions: kept, but out of the person's session list.
    listed = {s["id"] for s in client.get("/api/v1/sessions").json()}
    assert not ({sid for sid, _, _, _ in written} & listed)

    # Resume after a restart reuses the lineups and the scored cases.
    async def mark_interrupted():
        from app.models.benchmark import BenchmarkRun
        async with Session() as db:
            r = await db.get(BenchmarkRun, run["id"])
            r.status = "interrupted"
            await db.commit()
    asyncio.run(mark_interrupted())
    assert client.post(f"/api/v1/admin/benchmarks/simbench/runs/{run['id']}/resume").status_code == 200
    deadline = time.time() + 30
    while time.time() < deadline:
        again = client.get(f"/api/v1/admin/benchmarks/simbench/runs/{run['id']}").json()
        if again["status"] == "complete":
            break
        time.sleep(0.2)
    assert again["status"] == "complete" and len(written) == 2          # no lineup written twice

    body = client.get(f"/api/v1/admin/benchmarks/simbench/runs/{run['id']}/cases.csv").text
    assert body.splitlines()[0].startswith("case_id,dataset,group") and len(body.splitlines()) == 7


def test_stop_reaches_the_persona_writer_and_resume_rewrites_the_cut_lineup(data, api_client, monkeypatch):
    """Stop must abandon the lineups being written (2026-10-28: they kept calling the model for
    minutes), and a lineup cut short must be rewritten on resume, in the same session."""
    from app.services.agents.profiles import AgentProfile
    client, Session = api_client
    sb.build_subset(n=6, seed=3)
    calls = []

    async def slow_writer(session_id, query, segments, constraints, *, mode="fast", should_stop=None, **kw):
        calls.append(session_id)
        assert should_stop is not None
        for _ in range(100):                       # a long build that only Stop can end
            if should_stop():
                return []
            await asyncio.sleep(0.05)
        seg = segments[0]
        return [AgentProfile(id=str(uuid.uuid4()), session_id=session_id, name=f"P{k}", age=40, role="r", background="b",
                             stance="neutral", correlation="c", personality=["x"], debate_style="d") for k in range(seg["count"])]
    monkeypatch.setattr("app.services.agents.agent_factory.generate_agents_from_plan", slow_writer)

    async def fake_analyze(schema, system, user, **kw):
        return {"reasoning": "r", "q": {"o1": 50, "o2": 30, "o3": 20}, "can_answer": "yes"}
    monkeypatch.setattr("app.services.measurement.probe.analyze", fake_analyze)

    run = client.post("/api/v1/admin/benchmarks/simbench/runs", json={"cases": 6, "twins": 10, "parallel_groups": 2, "bare": False}).json()
    time.sleep(0.5)
    assert client.post(f"/api/v1/admin/benchmarks/simbench/runs/{run['id']}/stop").status_code == 200
    deadline = time.time() + 10
    while time.time() < deadline:
        got = client.get(f"/api/v1/admin/benchmarks/simbench/runs/{run['id']}").json()
        if got["status"] == "stopped":
            break
        time.sleep(0.1)
    assert got["status"] == "stopped" and got["progress"]["cases_done"] == 0
    assert {g["status"] for g in got["groups"]} == {"stopped"}
    first_sessions = {g["session_id"] for g in got["groups"]}

    assert client.post(f"/api/v1/admin/benchmarks/simbench/runs/{run['id']}/resume").status_code == 200
    deadline = time.time() + 30
    while time.time() < deadline:
        again = client.get(f"/api/v1/admin/benchmarks/simbench/runs/{run['id']}").json()
        if again["status"] == "complete":
            break
        time.sleep(0.2)
    assert again["status"] == "complete" and again["progress"]["cases_done"] == 6
    assert {g["session_id"] for g in again["groups"]} == first_sessions          # rewritten in place, nothing orphaned
    assert all(g["agents"] == 10 for g in again["groups"])


from tests.measurement_test import api_client  # noqa: E402,F401
