import numpy as np
import pandas as pd
import pytest

from engine.analysis import (
    lasso_folds,
    run_causal_impact_analysis,
    run_opportunity_projection,
    screen_controls,
    with_controls,
)
from engine.config import EngineConfig
from engine.pipeline import analyze_events, detect_events, load_inputs
from tests.engine.helpers import full_config
from tests.engine.synthetic_data import dataset_config, make_dataset

DAYS = pd.date_range("2024-01-01", periods=120, freq="D")
PRE, POST = ("2024-01-01", "2024-04-09"), ("2024-04-10", "2024-04-29")


def test_a_control_that_moves_with_the_spend_is_rejected():
    spend = pd.Series(np.arange(30, dtype=float), index=DAYS[:30])
    pre = pd.DataFrame({"Generic Searches": spend * 2 + 1, "bcb_ipca": np.tile([1.0, -1.0], 15)}, index=DAYS[:30])

    screened = screen_controls(pre, spend, 0.5)

    assert screened[0] == {"name": "trends", "corr": pytest.approx(1.0), "accepted": False}
    assert screened[1]["name"] == "bcb_ipca" and screened[1]["accepted"] is True


def test_a_constant_control_has_no_correlation_and_is_kept():
    spend = pd.Series(np.arange(10, dtype=float), index=DAYS[:10])
    pre = pd.DataFrame({"bcb_selic": 11.75}, index=DAYS[:10])

    assert screen_controls(pre, spend, 0.5) == [{"name": "bcb_selic", "corr": None, "accepted": True}]


def test_each_date_takes_the_last_value_published_up_to_it():
    model = pd.DataFrame({"Date": pd.date_range("2024-01-30", "2024-03-05", freq="D"), "kpi": 1.0})
    controls = pd.DataFrame({"Date": pd.to_datetime(["2024-01-01", "2024-02-01"]), "bcb_ipca": [0.4, 0.8]})

    merged = with_controls(model, controls).set_index("Date")

    assert merged.loc["2024-01-31", "bcb_ipca"] == 0.4
    assert merged.loc["2024-03-05", "bcb_ipca"] == 0.8  # after the last release, it still holds
    assert with_controls(model, pd.DataFrame()) is model


def test_a_date_before_the_first_release_takes_the_first_value():
    model = pd.DataFrame({"Date": pd.date_range("2024-01-01", periods=5, freq="D"), "kpi": 1.0})
    controls = pd.DataFrame({"Date": pd.to_datetime(["2024-01-03"]), "bcb_ipca": [0.4]})

    assert with_controls(model, controls)["bcb_ipca"].tolist() == [0.4] * 5


def test_lasso_folds_are_in_time_order_and_fit_a_short_pre_period():
    assert lasso_folds(8).n_splits == 2
    assert lasso_folds(400).n_splits == 5


def _event(control, controls_df=None, controls=(), trends=None):
    rng = np.random.default_rng(3)
    spend = 100 + rng.normal(0, 15, len(DAYS))
    spend[100:] *= 2
    kpi = 50 + 8 * np.sqrt(spend) + rng.normal(0, 2, len(DAYS))
    investment = pd.DataFrame({"Date": DAYS, "Product Group": "TV", "investment": spend})
    kpi_df = pd.DataFrame({"Date": DAYS, "kpi": kpi})
    if trends is None:
        trends = pd.DataFrame({"Date": DAYS, "Generic Searches": control(spend, rng)})
    config = full_config({"controls": list(controls)})
    *_, params, _ = run_opportunity_projection(kpi_df, investment, trends, "TV", config)
    results, *_ = run_causal_impact_analysis(
        kpi_df,
        investment,
        trends,
        pd.DataFrame() if controls_df is None else controls_df,
        PRE,
        POST,
        "TV_2024-04-10",
        "TV",
        params,
        {**config, "period_days": 1},
    )
    assert results is not None, "run_causal_impact_analysis swallowed an exception; see the log"
    return results


def test_trends_that_follow_the_spend_leave_the_causal_model():
    results = _event(lambda spend, rng: spend + rng.normal(0, 1, len(spend)))

    [trends] = results["controls"]
    assert trends["name"] == "trends" and trends["accepted"] is False and trends["corr"] > 0.9


def test_independent_trends_and_a_bcb_series_are_screened_and_kept():
    monthly = pd.DataFrame(
        {"Date": pd.date_range("2023-12-01", periods=6, freq="MS"), "bcb_ipca": [0.5, 0.4, 0.8, 0.2, 0.4, 0.3]}
    )

    results = _event(lambda spend, rng: 50 + rng.normal(0, 5, len(spend)), monthly, ["bcb_ipca"])

    assert [(c["name"], c["accepted"]) for c in results["controls"]] == [("trends", True), ("bcb_ipca", True)]


def test_without_a_trends_file_there_is_no_trends_control():
    results = _event(lambda spend, rng: spend, trends=pd.DataFrame({"Date": [], "Generic Searches": []}))

    assert results["controls"] == []


def _outcomes(inputs):
    config = EngineConfig.from_input(dataset_config())
    prepared = load_inputs(inputs, config)
    cfg = {**config.to_legacy_dict(), "period_days": prepared.period_days}
    return analyze_events(prepared, detect_events(prepared, cfg), cfg)


def test_ad_metrics_in_the_performance_file_do_not_change_the_causal_result(tmp_path):
    plain = make_dataset(tmp_path / "plain", n_days=364)
    with_ads = make_dataset(tmp_path / "ads", n_days=364)
    performance = pd.read_csv(with_ads["performance_file"])
    # an ad metric that tracks the KPI: the prototype took it as a control and absorbed the effect
    performance["Clicks"] = performance["Sessions"] * 0.03
    performance["Impressions"] = performance["Sessions"] * 2
    performance.to_csv(with_ads["performance_file"], index=False)

    expected = [(o.event_id, o.results_data and o.results_data["absolute_lift"]) for o in _outcomes(plain)]
    actual = [(o.event_id, o.results_data and o.results_data["absolute_lift"]) for o in _outcomes(with_ads)]

    assert actual == expected


def test_only_the_calendar_columns_enter_by_name_and_in_the_model_order(monkeypatch):
    from engine import analysis

    seen = []
    real = analysis._select_variance_threshold_features

    def spy(pre, columns, *args, **kwargs):
        seen.append(list(columns))
        return real(pre, columns, *args, **kwargs)

    monkeypatch.setattr(analysis, "_select_variance_threshold_features", spy)
    leaky = pd.DataFrame({"Date": DAYS, "weekday_spend": np.arange(len(DAYS), dtype=float)})

    _event(lambda spend, rng: 50 + rng.normal(0, 5, len(spend)), leaky)

    columns = seen[-1]  # the causal model's call; the response model may call it before
    assert "weekday_spend" not in columns
    calendar = [c for c in columns if c.startswith(("day_", "is_"))]
    assert calendar == ["is_weekend", "is_payday_period", "is_holiday", *(f"day_{i}" for i in range(7))]
