import contextlib
import io
import json
import os
import warnings
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

import engine
from engine import pipeline
from engine.errors import EngineError
from llm.base import LLMBadOutput, LLMUnavailable
from tests.engine.synthetic_data import dataset_config, make_dataset
from tests.fakes.llm import EVENT_NARRATIVE, GLOBAL_NARRATIVE, FakeLLM

SHORT = 364


def _run_once(work: Path, config: dict, inputs: dict, on_log=None):
    calls = []
    out_dir = work / "out"
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        result = engine.run(inputs, config, out_dir, on_log or (lambda level, message: calls.append((level, message))))
    return SimpleNamespace(result=result, out_dir=out_dir, calls=calls, stdout=out.getvalue(), stderr=err.getvalue())


@pytest.fixture(scope="module")
def ran(tmp_path_factory):
    """One real run (no LLM) shared by the read-only assertions; also keeps the Computed for the LLM tests."""
    mp = pytest.MonkeyPatch()
    mp.setenv("LLM_PROVIDER", "none")
    work = tmp_path_factory.mktemp("run")
    inputs = make_dataset(work / "data", n_days=SHORT)
    config = dataset_config()
    snapshot = json.dumps(config, sort_keys=True)
    captured = {}
    real = pipeline.compute

    def spy(*args, **kwargs):
        captured["computed"] = real(*args, **kwargs)
        return captured["computed"]

    mp.setattr(pipeline, "compute", spy)
    cwd = os.getcwd()
    filters = list(warnings.filters)
    run = _run_once(work, config, inputs)
    mp.undo()
    run.work, run.inputs, run.computed = work, inputs, captured["computed"]
    run.config_unchanged = json.dumps(config, sort_keys=True) == snapshot
    run.cwd_unchanged = os.getcwd() == cwd
    run.filters_unchanged = list(warnings.filters) == filters
    return run


def test_run_returns_the_contract_dict(ran):
    r = ran.result
    assert r["schema_version"] == 1 and r["status"] == "succeeded"
    assert isinstance(r["engine_version"], str) and r["engine_version"]
    for section in ("validation", "sufficiency", "causal", "elasticity", "experiment_design", "reports"):
        assert r[section] is None


def test_writes_only_inside_out_dir(ran):
    assert {p.name for p in ran.work.iterdir()} == {"data", "out"}
    assert (ran.out_dir / "global_saturation_analysis" / "response_curve_data.csv").exists()
    assert (ran.out_dir / "global_saturation_analysis" / "SATURATION_CURVE.md").exists()
    selected = [e for e in ran.computed.events if e.selected]
    assert selected
    assert len(list(ran.out_dir.rglob("*_presentation_data.csv"))) == len(selected)


def test_input_config_and_cwd_untouched(ran):
    assert ran.config_unchanged and ran.cwd_unchanged


def test_warning_filters_are_restored(ran):
    assert ran.filters_unchanged


def test_on_log_gets_valid_levels_and_nothing_goes_to_stdout(ran):
    assert ran.calls and {level for level, _ in ran.calls} <= {"info", "warning", "error"}
    assert any(level == "info" for level, _ in ran.calls)
    assert all(message.strip() for _, message in ran.calls)
    assert ran.stdout == "" and ran.stderr == ""


def test_without_an_llm_each_selected_event_gets_the_deterministic_recommendations(ran):
    event_dirs = list(ran.out_dir.rglob("RECOMMENDATIONS.md"))
    assert len(event_dirs) == sum(e.selected for e in ran.computed.events)


def _with_llm(monkeypatch, ran, tmp_path, fake):
    monkeypatch.setattr(pipeline, "compute", lambda *a, **k: ran.computed)
    monkeypatch.setattr(pipeline, "get_llm", lambda *a, **k: fake)
    return _run_once(tmp_path, dataset_config(), ran.inputs)


def test_llm_unavailable_stops_further_calls(monkeypatch, ran, tmp_path):
    assert sum(e.selected for e in ran.computed.events) >= 2
    fake = FakeLLM([LLMUnavailable("timeout")])
    run = _with_llm(monkeypatch, ran, tmp_path, fake)
    assert len(fake.calls) == 1
    assert run.result["status"] == "succeeded"
    assert len(list(run.out_dir.rglob("RECOMMENDATIONS.md"))) == sum(e.selected for e in ran.computed.events)
    assert not list(run.out_dir.rglob("global_report.html"))
    assert any(level == "warning" for level, _ in run.calls)


def test_other_llm_error_only_fails_that_report(monkeypatch, ran, tmp_path):
    selected = sum(e.selected for e in ran.computed.events)
    assert selected >= 2
    fake = FakeLLM(
        [LLMBadOutput("invalid_json")] + [json.dumps(EVENT_NARRATIVE)] * (selected - 1) + [json.dumps(GLOBAL_NARRATIVE)]
    )
    run = _with_llm(monkeypatch, ran, tmp_path, fake)
    assert len(fake.calls) == selected + 1
    # every selected event has its RECOMMENDATIONS.md (narrative-based, or the deterministic fallback)
    assert len(list(run.out_dir.rglob("RECOMMENDATIONS.md"))) == selected
    assert len(list(run.out_dir.rglob("report_*.html"))) == selected - 1  # only the failed one has no narrative
    assert (run.out_dir / "global_saturation_analysis" / "global_report.html").exists()


def test_weekly_cadence_run_completes(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "none")
    inputs = make_dataset(tmp_path / "data", cadence_days=7)
    run = _run_once(tmp_path, dataset_config(), inputs)
    assert run.result["status"] == "succeeded"


def test_failed_when_mmm_fails_and_no_event_passes(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "none")
    days = pd.date_range("2025-01-01", periods=60, freq="D").strftime("%Y-%m-%d")
    data = tmp_path / "data"
    data.mkdir()
    (data / "i.csv").write_text("dates,product_group,total_revenue\n" + "".join(f"{d},A,0\n" for d in days))
    (data / "p.csv").write_text("date,Sessions\n" + "".join(f"{d},10\n" for d in days))
    inputs = {"investment_file": data / "i.csv", "performance_file": data / "p.csv", "generic_trends_file": None}
    config = {
        **dataset_config(),
        "column_mapping": {k: v for k, v in dataset_config()["column_mapping"].items() if k != "generic_trends_file"},
    }
    run = _run_once(tmp_path, config, inputs)
    assert run.result["status"] == "failed"


def test_unknown_config_key_is_an_engine_error(tmp_path):
    with pytest.raises(EngineError, match="require_significance"):
        engine.run({}, {"require_significance": True}, tmp_path / "out", lambda level, message: None)


def test_unknown_llm_provider_fails_fast_before_any_computation(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "gemin")  # a typo in the deployment env

    def must_not_run(*args, **kwargs):
        raise AssertionError("the analysis must not start with a broken LLM setup")

    monkeypatch.setattr(pipeline, "compute", must_not_run)
    with pytest.raises(EngineError, match="LLM_PROVIDER"):
        engine.run({}, dataset_config(), tmp_path / "out", lambda level, message: None)


def test_unexpected_analysis_error_becomes_an_engine_error_without_the_details(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "none")

    def explode(*args, **kwargs):
        raise ValueError("None of the event channels were found in /srv/data/ws/1/sim/2/inputs/abc.csv")

    monkeypatch.setattr(pipeline, "compute", explode)
    with pytest.raises(EngineError) as raised:
        engine.run({}, dataset_config(), tmp_path / "out", lambda level, message: None)
    assert "Erro inesperado" in str(raised.value)
    assert "/srv/data" not in str(raised.value) and "event channels" not in str(raised.value)
    assert isinstance(raised.value.__cause__, ValueError)  # the detail stays in the chain for the server log
