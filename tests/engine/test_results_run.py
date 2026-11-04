import json
import os

import pytest
from threadpoolctl import threadpool_limits

import engine
from engine import pipeline
from engine.config import EngineConfig
from engine.results_schema import ResultsV1
from tests.engine.synthetic_data import dataset_config, make_dataset

SHORT = 364


def _boom(token):
    raise AssertionError(f"non-finite number in results.json: {token}")


@pytest.fixture(scope="module")
def ran(tmp_path_factory):
    """Two runs into the same out_dir (the second proves idempotence), plus the Computed of the first."""
    mp = pytest.MonkeyPatch()
    mp.setenv("LLM_PROVIDER", "none")
    work = tmp_path_factory.mktemp("results_run")
    inputs = make_dataset(work / "data", n_days=SHORT)
    captured = {}
    real = pipeline.compute

    def spy(*args, **kwargs):
        captured.setdefault("computed", None)
        captured["computed"] = captured["computed"] or real(*args, **kwargs)
        return captured["computed"]

    mp.setattr(pipeline, "compute", spy)
    out_dir = work / "out"
    with threadpool_limits(limits=1):
        returned = engine.run(inputs, dataset_config(), out_dir, lambda level, message: None)
        first = (out_dir / "results.json").read_bytes()
        engine.run(inputs, dataset_config(), out_dir, lambda level, message: None)
    second = (out_dir / "results.json").read_bytes()
    mp.undo()
    return {"returned": returned, "first": first, "second": second, "computed": captured["computed"]}


def test_run_writes_results_json_equal_to_the_return(ran):
    assert json.loads(ran["first"]) == ran["returned"]


def test_results_json_has_no_non_finite_numbers(ran):
    json.loads(ran["first"], parse_constant=_boom)
    assert b"NaN" not in ran["first"] and b"Infinity" not in ran["first"]


def test_run_result_validates_against_the_schema(ran):
    results = ResultsV1.model_validate(ran["returned"])
    assert results.status == "succeeded" and results.causal.status == "ok" and results.elasticity.status == "ok"
    assert results.validation is results.sufficiency is results.experiment_design is results.reports is None


def test_running_twice_gives_identical_files(ran):
    assert ran["first"] == ran["second"]


def test_numbers_in_results_match_compute(ran):
    computed, data = ran["computed"], ran["returned"]
    for outcome, event in zip(computed.events, data["causal"]["events"], strict=True):
        if outcome.results_data:
            assert event["lift"]["abs"] == pytest.approx(outcome.results_data["absolute_lift"], rel=1e-9)
            assert event["p_value"] == pytest.approx(outcome.results_data["p_value"], rel=1e-9)
    assert data["elasticity"]["metrics"]["cv_r2"] == pytest.approx(computed.mmm["cv_r_squared"], rel=1e-9)
    curve = data["elasticity"]["response_curve"]
    assert [r["kpi"] for r in curve] == pytest.approx(
        list(computed.response_curve_df["Projected_Total_KPIs"]), rel=1e-9
    )


def test_status_inconclusive_when_no_event_is_eligible(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "none")
    inputs = make_dataset(tmp_path / "data", n_days=SHORT)
    config = {**dataset_config(), "min_intervention_date": "2030-01-01"}
    EngineConfig.from_input(config)  # the key is part of the public config
    with threadpool_limits(limits=1):
        result = engine.run(inputs, config, tmp_path / "out", lambda level, message: None)
    assert result["status"] == "inconclusive"
    assert result["causal"]["status"] == "inconclusive" and result["causal"]["reasons"] == ["no_eligible_events"]
    assert result["elasticity"]["status"] == "ok"
    assert (tmp_path / "out" / "results.json").exists() and os.path.getsize(tmp_path / "out" / "results.json") > 0
