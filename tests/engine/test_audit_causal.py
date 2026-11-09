"""Causal findings of the math audit (docs/audit/formulas-do-motor.md, section 2 and PRE-4/PRE-5)."""

import warnings
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from engine import grounding, narratives, pipeline
from engine.analysis import (
    _fit_state_space,
    cumulative_p_value,
    find_events,
    geometric_decay,
    hill_transform,
    run_causal_impact_analysis,
)

ALPHA, K, S, BETA = 0.3, 1.5, 1500.0, 4000.0
EVENT_DAY = pd.Timestamp("2025-07-07")
CAUSAL_CFG = {
    "country_code": "BR",
    "period_days": 1,
    "min_pre_period_days": 14,
    "controls": [],
    "control_spend_corr": 0.5,
}


def _media(spend):
    return hill_transform(geometric_decay(spend, ALPHA), K, S)


def _treated_event(factor, seed=3, trend=False):
    """KPI = 5000 + 4000·Hill(adstock(spend)) + noise; spend × factor from EVENT_DAY on; the model knows α, k, s.
    The truth holds the spend at its level of the 12 weeks before the event, the baseline of the spend delta."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2025-01-06", periods=210, freq="D")
    event = dates.get_loc(EVENT_DAY)
    if trend:
        base = np.linspace(500, 1000, len(dates))
        base[event:] = 1000
        spend = base * rng.uniform(0.9, 1.1, len(dates))
    else:
        spend = rng.uniform(800, 1200, len(dates))
    spend[event:] *= factor
    kpi = 5000 + BETA * _media(spend) + rng.normal(0, 60, len(dates))
    counterfactual = spend.copy()
    counterfactual[event:] = spend[event - 84 : event].mean()
    window = slice(event, event + 14)
    true_lift = float((BETA * (_media(spend) - _media(counterfactual)))[window].sum())
    true_spend = float((spend - counterfactual)[window].sum())

    kpi_df = pd.DataFrame({"Date": dates, "kpi": kpi})
    investment = pd.DataFrame({"Date": dates, "Product Group": "A", "investment": spend})
    results, *_, accuracy = run_causal_impact_analysis(
        kpi_df,
        investment,
        pd.DataFrame(columns=["Date"]),
        pd.DataFrame(),
        ["2025-01-06", "2025-07-06"],
        ["2025-07-07", "2025-07-20"],
        "e",
        "A",
        {"alpha": ALPHA, "k": K, "s": S},
        CAUSAL_CFG,
        contested=lambda _: False,
    )
    return results, accuracy, true_lift, true_spend


@pytest.fixture(scope="module", params=[2.0, 0.5], ids=["step_up", "step_down"])
def treated(request):
    return _treated_event(request.param)


def test_causal_1_the_counterfactual_holds_the_treated_spend_and_recovers_the_lift(treated):
    results, _, true_lift, _ = treated
    assert abs(true_lift) > 5000
    assert results["absolute_lift_ci_lower"] <= true_lift <= results["absolute_lift_ci_upper"]
    assert results["absolute_lift"] == pytest.approx(true_lift, rel=0.25)


def test_causal_3_the_in_sample_fit_leaves_out_the_diffuse_burn_in(treated):
    results, accuracy, *_ = treated
    assert results["model_r_squared"] > 0.3  # a well-specified model; the burn-in zeros gave -15
    assert accuracy["Predicted"].min() > 4000  # no 0, 0, ... rows from the diffuse start


def test_causal_4_cpa_is_incremental_spend_over_lift(treated):
    results, *_ = treated
    incremental = results["total_investment_post_period"] - results["total_investment_pre_period"]
    assert results["cpa_incremental"] == pytest.approx(incremental / results["absolute_lift"])
    assert results["cpa_incremental"] > 0  # a drop in spend that loses KPI has a positive cost per unit


@pytest.mark.parametrize("seed", [3, 4])
def test_causal_1_4_lift_and_spend_delta_share_one_counterfactual_under_a_spend_trend(seed):
    results, _, true_lift, true_spend = _treated_event(2.0, seed=seed, trend=True)
    incremental = results["total_investment_post_period"] - results["total_investment_pre_period"]
    assert incremental == pytest.approx(true_spend, rel=1e-9)
    assert results["absolute_lift_ci_lower"] <= true_lift <= results["absolute_lift_ci_upper"]
    assert results["cpa_incremental"] == pytest.approx(true_spend / true_lift, rel=0.05)


def test_causal_4_results_and_narrative_publish_the_spend_delta():
    event = {
        "id": "e",
        "channels": ["A"],
        "status": "published",
        "start": "2025-07-07",
        "end": "2025-07-20",
        "lift": {"abs": -12172.0, "ci": [-12616.0, -11727.0], "rel_pct": -40.1},
        "p_value": 0.0001,
        "incremental_investment": -6597.0,
        "cpa_incremental": 0.542,
    }
    payload = narratives.event_payload(event, "Pedidos", 0.05, [])
    text = narratives.text_of(narratives.deterministic_event(payload))
    assert payload["incremental_investment"] == -6597.0 and payload["post_period_days"] == 14
    assert "Investimento incremental de R$ -6.597,00" in text
    assert grounding.check(text, payload, {"A"}, {"A"}) == []


def _null_llevel(rng, n_pre=180, n_post=15):
    n = n_pre + n_post
    y = 1000 + np.cumsum(rng.normal(0, 3, n)) + rng.normal(0, 20, n)
    return pd.DataFrame({"kpi": y}, index=pd.date_range("2024-01-01", periods=n, freq="D"))


def test_causal_2_cumulative_error_is_calibrated_on_a_null_from_the_model_family():
    rng = np.random.default_rng(1)
    rejected = covered = 0
    reps = 200
    for _ in range(reps):
        data = _null_llevel(rng)
        pre, post = data.iloc[:180], data.iloc[180:]
        fit = _fit_state_space(pre, [], period_days=1)
        lift = float((post["kpi"].to_numpy() - fit.get_forecast(steps=len(post)).predicted_mean.to_numpy()).sum())
        p, se = cumulative_p_value(lift, fit, len(post))
        rejected += p < 0.05
        covered += abs(lift) <= 1.96 * se
    assert 0.02 <= rejected / reps <= 0.09
    assert 0.91 <= covered / reps <= 0.99


def test_causal_2_the_cumulative_error_matches_the_simulated_sum():
    data = _null_llevel(np.random.default_rng(0))
    fit = _fit_state_space(data.iloc[:180], [], period_days=1)
    _, se = cumulative_p_value(0.0, fit, 15)
    sims = np.asarray(fit.simulate(nsimulations=15, repetitions=4000, anchor="end", random_state=0)).reshape(15, -1)
    assert se == pytest.approx(sims.sum(axis=0).std(), rel=0.05)
    assert cumulative_p_value(0.0, fit, 1)[1] == pytest.approx(fit.get_forecast(steps=1).se_mean.iloc[0])


def _daily(start, end, spend=1000.0):
    dates = pd.date_range(start, end, freq="D")
    values = np.full(len(dates), spend) if np.isscalar(spend) else spend
    return pd.DataFrame({"Date": dates, "Product Group": "A", "investment": values})


def test_causal_5_a_sustained_step_is_one_event():
    rng = np.random.default_rng(0)
    df = _daily("2025-01-01", "2025-06-25", rng.uniform(950, 1050, 176))
    df.loc[df["Date"] >= "2025-04-02", "investment"] *= 2
    events, _, _ = find_events(df, "x", 1.5, 0.7, 14)
    assert events["date"].tolist() == ["2025-03-31"]


@pytest.mark.parametrize("end", ["2025-06-19", "2025-06-25"])  # a Thursday and a Wednesday
def test_causal_6_partial_edge_weeks_are_not_a_drop(end):
    events, _, _ = find_events(_daily("2025-01-01", end), "x", 1.5, 0.7, 14)
    assert events.empty


def test_causal_7_the_event_date_is_the_first_day_of_the_flagged_week():
    df = _daily("2025-01-06", "2025-06-29")
    df.loc[df["Date"] == "2025-03-17", "investment"] = 10_000.0  # a Monday
    events, _, _ = find_events(df, "x", 1.5, 0.7, 14)
    assert events["date"].tolist() == ["2025-03-17"]


def _candidates(dates, spike_at, post_event_days, period_days):
    spend = np.full(len(dates), 1000.0)
    spend[spike_at] = 5000.0
    investment = pd.DataFrame({"Date": dates, "Product Group": "A", "investment": spend})
    prepared = SimpleNamespace(investment_df=investment, kpi_df=pd.DataFrame({"Date": dates, "kpi": 1.0}))
    cfg = {
        "advertiser_name": "x",
        "increase_threshold_percent": 50,
        "decrease_threshold_percent": 30,
        "post_event_days": post_event_days,
        "period_days": period_days,
    }
    return pipeline.detect_events(prepared, cfg)


@pytest.mark.parametrize(
    ("freq", "post_event_days", "period_days", "periods"),
    [("D", 14, 1, 14), ("W-MON", 14, 7, 4), ("MS", 90, 30, 4)],
)
def test_causal_7_the_post_window_holds_exactly_the_configured_periods(freq, post_event_days, period_days, periods):
    dates = pd.date_range("2022-01-03", periods=200 if freq == "D" else 40, freq=freq)
    spike_at = 98 if freq == "D" else 20  # daily: a Monday, so the flagged week starts on the spike
    candidates = _candidates(dates, spike_at, post_event_days, period_days)
    event = candidates.iloc[0]
    assert pd.Timestamp(event["intervention_date"]) == dates[spike_at]
    in_post = (dates >= event["intervention_date"]) & (dates <= event["end_date"])
    assert in_post.sum() == periods


@pytest.mark.parametrize(("period_days", "seasonal"), [(1, True), (7, False), (30, False)])
def test_causal_8_the_seasonal_cycle_follows_the_cadence_and_there_is_no_silent_trend(period_days, seasonal):
    data = _null_llevel(np.random.default_rng(0)).iloc[:60]
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        model = _fit_state_space(data, [], period_days=period_days).model
    assert not [w for w in caught if "trend" in str(w.message).lower()]
    assert model.seasonal is seasonal and model.trend is False
    if seasonal:
        assert model.seasonal_periods == 7
