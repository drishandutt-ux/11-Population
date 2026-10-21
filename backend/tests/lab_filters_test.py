"""Demographic and geography "who answers" filters for every Lab tool (2026-10-21).

Run:  cd backend && pytest tests/lab_filters_test.py -q
"""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("DATABASE_URL", "")
os.environ["ANTHROPIC_API_KEY"] = "test-key"

from app.services.measurement import probe as probe_svc  # noqa: E402


def _twin(i, **demo):
    return SimpleNamespace(id=f"a{i}", dials={}, stance=SimpleNamespace(value="direct"), age=40, humanity=50,
                           segment=demo.pop("segment", None), demographics=demo or None)


def test_filters_are_read_off_the_population_with_counts_commonest_first():
    agents = [
        _twin(1, gender="female", region="Blackpool", frame={"region": "North West"}),
        _twin(2, gender="female", region="Lancaster", frame={"region": "North West"}),
        _twin(3, gender="male", region="Oxford", frame={"region": "South East"}),
    ]
    out = {f["key"]: f for f in probe_svc.filter_options(agents)}
    assert out["gender"]["group"] == "demographics"
    assert out["gender"]["options"] == [{"value": "female", "n": 2}, {"value": "male", "n": 1}]
    assert out["area"]["group"] == "geography" and out["area"]["label"] == "Region"
    assert [o["value"] for o in out["area"]["options"]] == ["North West", "South East"]
    assert out["region"]["label"] == "Place" and len(out["region"]["options"]) == 3
    # Nobody differs on income, and quick-spawn twins carry no demographics at all: no filter.
    assert "income_band" not in out
    assert probe_svc.filter_options([_twin(4), _twin(5)]) == []


def test_a_picked_filter_narrows_who_answers():
    agents = [_twin(1, region="Blackpool", frame={"region": "North West"}), _twin(2, region="Oxford", frame={"region": "South East"})]
    chosen = probe_svc._select_agents(agents, {"agent_filter": {"segments": {"area": "North West"}}}, 0)
    assert [a.id for a in chosen] == ["a1"]
