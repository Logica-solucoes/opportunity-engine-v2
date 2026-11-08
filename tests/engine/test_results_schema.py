import pytest
from pydantic import ValidationError

from engine.results import sanitize
from engine.results_schema import (
    SCHEMA_VERSION,
    CausalEvent,
    Collinearity,
    ExperimentCell,
    ExperimentDesign,
    Reports,
    ResultsV1,
    Sufficiency,
)

ROOT_KEYS = {
    "schema_version",
    "engine_version",
    "status",
    "validation",
    "sufficiency",
    "causal",
    "elasticity",
    "experiment_design",
    "reports",
    "baseline",
}


def minimal(**extra) -> dict:
    return {"schema_version": 1, "engine_version": "x", "status": "failed", **extra}


def test_minimal_results_validates():
    results = ResultsV1.model_validate(minimal())
    assert SCHEMA_VERSION == 1
    assert all(getattr(results, key) is None for key in ROOT_KEYS - {"schema_version", "engine_version", "status"})


def test_unknown_field_is_rejected():
    with pytest.raises(ValidationError):
        ResultsV1.model_validate(minimal(surprise=1))
    with pytest.raises(ValidationError):
        CausalEvent.model_validate({"id": "e", "channels": [], "status": "published", "reasons": [], "bogus": 1})


def test_schema_version_must_be_1():
    with pytest.raises(ValidationError):
        ResultsV1.model_validate({**minimal(), "schema_version": 2})


def test_status_values():
    with pytest.raises(ValidationError):
        ResultsV1.model_validate({**minimal(), "status": "ok"})
    for status in ("succeeded", "inconclusive", "failed"):
        ResultsV1.model_validate({**minimal(), "status": status})
    with pytest.raises(ValidationError):
        CausalEvent.model_validate({"id": "e", "channels": [], "status": "maybe", "reasons": []})


def test_reports_global_alias():
    reports = Reports.model_validate({"events": {}, "global": {"a": 1}, "grounding": None})
    assert reports.model_dump(by_alias=True)["global"] == {"a": 1}


def test_json_schema_is_exportable():
    assert set(ResultsV1.model_json_schema()["properties"]) == ROOT_KEYS


def test_sanitize_replaces_non_finite_at_any_depth():
    original = {"a": [float("nan"), {"b": float("inf")}], "c": -float("inf"), "d": 1.5, "e": True, "f": "x", "g": 2}
    assert sanitize(original) == {"a": [None, {"b": None}], "c": None, "d": 1.5, "e": True, "f": "x", "g": 2}
    assert original["c"] == -float("inf")  # input untouched


def test_the_a3_and_a6_fields_are_optional():
    assert Collinearity().unresolved == []
    sufficiency = Sufficiency(passed=False)
    assert sufficiency.reasons == [] and sufficiency.cv_out_of_sample is None


def test_experiment_design_without_history_has_only_the_reason():
    d = ExperimentDesign(status="insufficient_history", reasons=["short_history"], period_days=1, target_lift=0.05)

    assert d.sigma is None and d.designs == [] and d.feasible is None


def test_experiment_design_is_closed():
    with pytest.raises(ValidationError):
        ExperimentDesign(status="ok", period_days=1, target_lift=0.05, extra=1)
    with pytest.raises(ValidationError):
        ExperimentCell(channel="A", test_type="geo", step=None, spend_per_period=1, budget_at_risk=1)
