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
from tests.engine.csv_factory import with_twin
from tests.engine.synthetic_data import NULL, STRONG, dataset_config, make_dataset, make_strong_effect_dataset
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
    inputs = make_dataset(work / "data")  # the full history: with the placebo gate (A6) one year keeps a single event
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
    for section in ("experiment_design", "reports"):
        assert r[section] is None  # owned by A7-A9
    assert r["sufficiency"]["passed"] is True and r["sufficiency"]["validated_events"] >= 1
    assert r["validation"]["ok"] is True
    assert r["causal"]["status"] == "ok" and r["elasticity"]["status"] == "ok"


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
    assert run.result["elasticity"]["status"] == "failed" and run.result["elasticity"]["reasons"] == ["model_failed"]
    assert run.result["causal"]["status"] == "inconclusive"


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
        engine.run(make_dataset(tmp_path / "data", n_days=60), dataset_config(), tmp_path / "out", lambda *a: None)
    assert "Erro inesperado" in str(raised.value)
    assert "/srv/data" not in str(raised.value) and "event channels" not in str(raised.value)
    assert isinstance(raised.value.__cause__, ValueError)  # the detail stays in the chain for the server log


def test_run_stops_on_unresolved_collinearity(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "none")
    inputs = with_twin(make_dataset(tmp_path / "data", n_days=SHORT))
    with pytest.raises(EngineError) as raised:
        _run_once(tmp_path, dataset_config(), inputs)
    assert raised.value.check_id == "collinearity_unresolved"
    assert not (tmp_path / "out" / "results.json").exists()


def test_run_with_group_publishes_only_the_group(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "none")
    inputs = with_twin(make_dataset(tmp_path / "data", n_days=SHORT))
    config = {**dataset_config(), "channel_groups": [["SEARCH", "SEARCH2"]]}
    run = _run_once(tmp_path, config, inputs)
    document = run.result
    names = [c["name"] for c in document["elasticity"]["channels"]]
    assert "SEARCH + SEARCH2" in names and "SEARCH" not in names and "SEARCH2" not in names
    assert [g["name"] for g in document["elasticity"]["groups"]] == ["SEARCH + SEARCH2"]
    assert document["validation"]["collinearity"]["pairs"] == []
    assert "SEARCH + SEARCH2" in document["validation"]["channels"]


def test_run_with_block_per_channel_runs(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "none")
    inputs = with_twin(make_dataset(tmp_path / "data", n_days=SHORT))
    run = _run_once(tmp_path, {**dataset_config(), "block_per_channel": True}, inputs)
    assert run.result["status"] == "succeeded"
    assert "collinearity_blocked" in [c["id"] for c in run.result["validation"]["checks"]]


def test_rejected_control_reaches_results_json_without_failing_the_event(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "none")
    inputs = make_dataset(tmp_path / "data", n_days=SHORT)
    investment = pd.read_csv(inputs["investment_file"])
    youtube = investment[investment["product_group"] == "YOUTUBE"].set_index("dates")["total_revenue"]
    trends = pd.read_csv(inputs["generic_trends_file"])
    trends["Like_YT"] = youtube.reindex(trends["Day"]).to_numpy() * 1.01
    trends.to_csv(inputs["generic_trends_file"], index=False)
    run = _run_once(tmp_path, {**dataset_config(), "controls": ["Like_YT"]}, inputs)
    events = [e for e in run.result["causal"]["events"] if e["channels"] == ["YOUTUBE"] and e["controls"]]
    assert events
    for event in events:
        assert [c["name"] for c in event["controls"]["rejected"]] == ["Like_YT"]
        assert not any("control" in reason for reason in event["reasons"])


# --- A5: identifiability ---------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def strong_run(tmp_path_factory):
    mp = pytest.MonkeyPatch()
    mp.setenv("LLM_PROVIDER", "none")
    work = tmp_path_factory.mktemp("strong")
    run = _run_once(work, dataset_config(), make_strong_effect_dataset(work / "data"))
    mp.undo()
    return run


def test_strong_effect_channel_is_identifiable_and_null_channel_is_not(strong_run):
    channels = {c["name"]: c for c in strong_run.result["elasticity"]["channels"]}
    strong, null = channels[STRONG], channels[NULL]
    assert strong["identifiable"] is True and strong["reasons"] == []
    assert strong["hill"] is not None and strong["adstock"] is not None and strong["curve"]
    assert null["identifiable"] is False and null["reasons"] == ["ci_crosses_zero"]
    assert null["hill"] is None and null["adstock"] is None and null["curve"] == []
    assert null["contribution_pct"] is None and null["coef_ci"] is not None


def test_a_hidden_channel_has_no_curve_or_mix_in_the_results(strong_run):
    elasticity = strong_run.result["elasticity"]
    assert elasticity["unidentified"]["channels"] == [NULL]
    assert elasticity["status"] == "ok" and "no_identifiable_channel" not in elasticity["reasons"]
    for row in elasticity["response_curve"]:
        for variant, mix in row["mix"].items():
            assert NULL not in mix and set(mix) == {STRONG, "nao_identificavel"}, variant
        assert sum(row["mix"]["historical"].values()) == pytest.approx(row["investment"], rel=1e-6)


def test_block_per_channel_marks_collinear_channels_as_not_identifiable(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_PROVIDER", "none")
    inputs = with_twin(make_dataset(tmp_path / "data", n_days=SHORT))
    run = _run_once(tmp_path, {**dataset_config(), "block_per_channel": True}, inputs)
    channels = {c["name"]: c for c in run.result["elasticity"]["channels"]}
    for name in ("SEARCH", "SEARCH2"):
        assert channels[name]["identifiable"] is False and "collinearity" in channels[name]["reasons"]


def test_the_run_log_does_not_show_the_share_of_a_hidden_channel(strong_run):
    lines = [message for _, message in strong_run.calls]
    assert not any(NULL in line and "%" in line for line in lines)
    assert any("Identificabilidade" in line and "1 de 2" in line for line in lines)
    assert any(line.strip().startswith(f"- {STRONG}:") and "%" in line for line in lines)
