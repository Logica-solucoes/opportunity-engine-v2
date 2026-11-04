import json

import pandas as pd
import pytest

from engine import reports
from llm.base import LLMBadOutput, LLMUnavailable
from tests.fakes.llm import EVENT_NARRATIVE, GLOBAL_NARRATIVE, FakeLLM

RESULTS = {
    "product_group": "YOUTUBE",
    "p_value": 0.01,
    "absolute_lift": 1000.0,
    "investment_change_pct": 50.0,
    "total_investment_post_period": 3000.0,
    "model_r_squared": 0.6,
    "mae": 10.0,
    "mape": 5.0,
}
EVENT_CONFIG = {
    "advertiser_name": "Adv",
    "client_business_goal": "grow",
    "primary_business_metric_name": "Leads",
    "p_value_threshold": 0.1,
    "average_ticket": 0,
    "conversion_rate_from_kpi_to_bo": 0.1,
}
PROJECTIONS = {
    "current": {"Daily_Investment": 1000.0, "Projected_Total_KPIs": 500.0, "Incremental_KPI": 0},
    "optimized": {"Daily_Investment": 1200.0, "Projected_Total_KPIs": 550.0, "Incremental_KPI": 50.0},
    "strategic": {"Daily_Investment": 1500.0, "Projected_Total_KPIs": 600.0, "Incremental_KPI": 100.0},
    "reallocation": {"Daily_Investment": 1000.0, "Projected_Total_KPIs": 520.0, "Incremental_KPI": 20.0},
}


def _event(llm):
    return reports._generate_full_report_narrative(llm, RESULTS, EVENT_CONFIG, pd.DataFrame())


def _global(llm, tmp_path, **config_extra):
    (tmp_path / "SATURATION_CURVE.md").write_text("# dummy\n", encoding="utf-8")
    config = {"average_ticket": 0, "conversion_rate_from_kpi_to_bo": 0, "primary_business_metric_name": "Leads"}
    config.update(config_extra)
    reports.generate_global_report(
        llm, config, scenarios=[], total_investment=1000.0, kpi_projections=PROJECTIONS, global_output_dir=tmp_path
    )


def test_event_narrative_uses_generate_text_with_60s_timeout():
    llm = FakeLLM([json.dumps(EVENT_NARRATIVE)])
    assert _event(llm) == EVENT_NARRATIVE
    assert len(llm.calls) == 1 and llm.timeouts == [60]


def test_event_narrative_accepts_a_fenced_json_answer():
    llm = FakeLLM(["```json\n" + json.dumps(EVENT_NARRATIVE) + "\n```"])
    assert _event(llm) == EVENT_NARRATIVE


def test_llm_unavailable_propagates_unwrapped():
    with pytest.raises(LLMUnavailable):
        _event(FakeLLM([LLMUnavailable("timeout")]))


def test_other_llm_error_is_wrapped_in_runtime_error():
    with pytest.raises(RuntimeError):
        _event(FakeLLM([LLMBadOutput("invalid_json")]))


def test_event_report_without_llm_raises_value_error():
    with pytest.raises(ValueError):
        _event(None)


def test_global_report_writes_into_the_given_dir(tmp_path):
    llm = FakeLLM([json.dumps(GLOBAL_NARRATIVE)])
    _global(llm, tmp_path)
    assert (tmp_path / "global_report.html").exists()
    assert json.loads((tmp_path / "global_narrative.json").read_text(encoding="utf-8")) == GLOBAL_NARRATIVE
    assert llm.timeouts == [60]


def test_global_report_weekly_period_scales_by_30_over_7_not_flat_30(tmp_path):
    _global(FakeLLM([json.dumps(GLOBAL_NARRATIVE)]), tmp_path, period_days=7)
    html_out = (tmp_path / "global_report.html").read_text(encoding="utf-8")
    assert "R$ 4.3k" in html_out and "R$ 30.0k" not in html_out


@pytest.mark.parametrize("extra", [{"period_days": 1}, {}])
def test_global_report_daily_or_missing_period_uses_flat_30(tmp_path, extra):
    _global(FakeLLM([json.dumps(GLOBAL_NARRATIVE)]), tmp_path, **extra)
    assert "R$ 30.0k" in (tmp_path / "global_report.html").read_text(encoding="utf-8")


def test_global_llm_unavailable_propagates_and_writes_nothing(tmp_path):
    with pytest.raises(LLMUnavailable):
        _global(FakeLLM([LLMUnavailable("timeout")]), tmp_path)
    assert not (tmp_path / "global_report.html").exists()


def test_global_other_error_raises_runtime_error_and_writes_nothing(tmp_path):
    with pytest.raises(RuntimeError):
        _global(FakeLLM([LLMBadOutput("invalid_json")]), tmp_path)
    assert not (tmp_path / "global_report.html").exists()


def test_global_report_without_llm_raises_value_error(tmp_path):
    with pytest.raises(ValueError):
        _global(None, tmp_path)
