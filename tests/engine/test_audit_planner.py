"""Audit findings F3-F9 of section 4 (curve and planner), on hand-built MMMs where the truth is known."""

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import Ridge
from sklearn.preprocessing import MinMaxScaler
from threadpoolctl import threadpool_limits

from engine import results
from engine.analysis import find_optimal_historical_mix
from engine.config import EngineConfig
from engine.elasticity_analysis import (
    cap_channel_mix_share,
    generate_aggregated_response_curve,
    geometric_adstock,
    hill_transform,
)
from engine.pipeline import load_inputs, run_elasticity
from engine.scenario import ScenarioFilters, scenario
from tests.engine.helpers import full_config
from tests.engine.synthetic_data import identifiable_config, make_identifiable_dataset


def _mmm(cv=0.9, weights=(5.0, 1.0)) -> dict:
    """Channels with spend uniform in [100, 200] and KPI = 1000 + sum(w × spend): today's total is ~300 per period."""
    rng = np.random.default_rng(0)
    n, cols = 120, list("ABCDE")[: len(weights)]
    df = pd.DataFrame({c: rng.uniform(100, 200, n) for c in cols})
    df["kpi"] = 1000 + sum(w * df[c] for w, c in zip(weights, cols, strict=True)) + rng.normal(0, 10, n)
    df["kpi_organic_baseline"] = 1000.0
    params = {"alphas": [0.0] * len(cols), "ks": [1.0] * len(cols), "ss": [150.0] * len(cols)}
    features = np.column_stack([hill_transform(geometric_adstock(df[c].values, 0.0), 1.0, 150.0) for c in cols])
    scaler = MinMaxScaler().fit(features)
    model = Ridge(alpha=1.0, positive=True, fit_intercept=False).fit(scaler.transform(features), df["kpi"] - 1000)
    samples = model.coef_ * rng.uniform(0.8, 1.2, (200, len(cols)))
    model.coef_ = samples.mean(axis=0)
    return {
        "dataframe": df,
        "spend_cols": cols,
        "optimal_params": params,
        "model": model,
        "scaler": scaler,
        "organic_baseline_mean": 1000.0,
        "cv_r_squared": cv,
        "coef_samples": samples,
    }


def _curve(mmm, **config):
    return generate_aggregated_response_curve(mmm, full_config({"investment_limit_factor": 3.0, **config}))


# --- F3: an unreachable target is not a recommendation to spend the most ---


def test_an_unreachable_target_keeps_todays_spend_with_a_reason():
    frame, baseline, _, limit, *_ = _curve(_mmm(cv=0.0), financial_targets={"target_icpa": 1e-6})

    assert limit["Daily_Investment"] == pytest.approx(baseline["Daily_Investment"])
    assert limit["Daily_Investment"] < frame["Daily_Investment"].max()
    assert limit["Reasons"] == ["targets_unreachable"]
    assert limit["Incremental_Investment"] == 0
    assert limit["KPI_Lo"] <= limit["Projected_Total_KPIs"] <= limit["KPI_Hi"]


def test_roas_targets_do_not_filter_a_conversions_run():
    frame, baseline, *_ = _curve(_mmm(cv=0.0))
    above = frame[frame["Daily_Investment"] > baseline["Daily_Investment"]]
    cpa = above["Daily_Investment"] / above["Projected_Total_KPIs"]
    target_cpa = float(cpa.median())  # reachable by part of the curve above today's spend

    limit = _curve(_mmm(cv=0.0), financial_targets={"target_cpa": target_cpa, "target_roas": 0.5})[3]

    # revenue is 0 outside revenue mode (no ticket): a ROAS target would reject every point
    assert limit["Daily_Investment"] == pytest.approx(above.loc[cpa <= target_cpa, "Daily_Investment"].max())
    assert "Reasons" not in limit


def test_the_published_strategic_limit_says_why_it_stays_at_todays_spend():
    _, baseline, max_efficiency, limit, _, _, reallocation = _curve(
        _mmm(cv=0.0), financial_targets={"target_icpa": 1e-6}
    )
    computed = SimpleNamespace(
        effective_config=full_config({}),
        baseline_point=baseline,
        max_efficiency_point=max_efficiency,
        strategic_limit_point=limit,
        diminishing_return_point=None,
        saturation_point=None,
        strategic_reallocation_point=reallocation,
        reallocation_suppressed=True,
    )

    scenarios = {s.name: s for s in results._scenarios(computed, [])}

    assert scenarios["strategic_limit"].investment == pytest.approx(baseline["Daily_Investment"])
    assert scenarios["strategic_limit"].notes == [results.TARGETS_UNREACHABLE_NOTE]


# --- F4: extra budget is not credited with the reallocation of today's budget ---


def test_curve_increments_are_measured_on_the_strategic_curve_itself():
    frame, baseline, _, _, _, _, reallocation = _curve(_mmm(cv=0.9), max_channel_mix_share=0.9)
    gain = reallocation["Projected_Total_KPIs"] - baseline["Projected_Total_KPIs"]
    assert gain > 10  # the test needs a real reallocation gain

    above = frame[frame["Daily_Investment"] > baseline["Daily_Investment"]]
    expected = (above["Projected_Total_KPIs"] - reallocation["Projected_Total_KPIs"]).clip(lower=0)
    np.testing.assert_allclose(above["Incremental_KPI"], expected, rtol=1e-9, atol=1e-9)
    first = above.iloc[0]
    assert first["iCPA"] == pytest.approx(first["Incremental_Investment"] / first["Incremental_KPI"])


def test_curve_incremental_revenue_is_measured_on_the_strategic_curve_itself():
    frame, baseline, _, _, _, _, reallocation = _curve(_mmm(cv=0.9), max_channel_mix_share=0.9, kpi_is_monetary=True)

    above = frame[frame["Daily_Investment"] > baseline["Daily_Investment"]]
    expected = above["Projected_Total_KPIs"] - reallocation["Projected_Total_KPIs"]
    np.testing.assert_allclose(above["Incremental_Revenue"], expected, rtol=1e-9, atol=1e-9)


def test_max_efficiency_increment_is_measured_on_its_own_mix():
    optimized = {"A": 0.8, "B": 0.2}
    _, baseline, max_efficiency, *_ = generate_aggregated_response_curve(
        _mmm(cv=0.0), full_config({"investment_limit_factor": 3.0}), optimized_mix=optimized
    )

    today_on_that_mix = baseline["projected_kpis"]["Pico de Eficiência"]
    assert today_on_that_mix > baseline["Projected_Total_KPIs"] + 10  # the mix alone gains
    assert max_efficiency["Incremental_KPI"] == pytest.approx(
        max(0, max_efficiency["Projected_Total_KPIs"] - today_on_that_mix)
    )


def _strategic_doc():
    def row(investment, kpi, inc_inv=0.0, inc_kpi=0.0):
        return {
            "investment": investment,
            "kpi": kpi,
            "kpi_lo": kpi,
            "kpi_hi": kpi,
            "revenue": None,
            "icpa": None,
            "iroas": None,
            "incremental_investment": inc_inv,
            "incremental_kpi": inc_kpi,
            "extrapolated": False,
            "mix": {},
        }

    # today: 20 spent, 40 on the historical mix, 46 on the strategic mix (+6 just by reallocating)
    curve = [row(0.0, 0.0), row(20.0, 46.0), row(40.0, 56.0, inc_inv=20.0, inc_kpi=10.0)]
    scenarios = [
        {"name": "current", "investment": 20.0, "kpi": 40.0, "kpi_lo": 40.0, "kpi_hi": 40.0, "extrapolated": False},
        {"name": "strategic_reallocation", "investment": 20.0, "kpi": 46.0, "kpi_lo": 46.0, "kpi_hi": 46.0},
    ]
    return {
        "validation": {"period_days": 1},
        "elasticity": {"status": "ok", "response_curve": curve, "scenarios": scenarios},
    }


def test_scenario_table_increments_leave_the_reallocation_gain_out():
    got = scenario(_strategic_doc(), ScenarioFilters(), 0.2)

    factor = got["current"]["investment"] / 20.0
    recommended = got["recommended"]
    assert recommended["incremental_kpi"] == pytest.approx(10.0 * factor)
    assert recommended["icpa"] == pytest.approx(20.0 / 10.0)
    assert got["current"]["kpi"] == pytest.approx(40.0 * factor)  # today's row still shows the historical mix


# --- F5: max efficiency in revenue mode is not the first grid point above today ---


def test_revenue_mode_max_efficiency_is_the_same_knee_as_conversions():
    frame, baseline, conversions, *_ = _curve(_mmm(cv=0.0))
    revenue = _curve(_mmm(cv=0.0), kpi_is_monetary=True)[2]

    first_above = frame.loc[frame["Daily_Investment"] > baseline["Daily_Investment"], "Daily_Investment"].iloc[0]
    assert revenue["Daily_Investment"] == pytest.approx(conversions["Daily_Investment"])
    assert revenue["Daily_Investment"] > first_above


def test_trusted_revenue_mode_max_efficiency_is_not_todays_spend():
    _, baseline, max_efficiency, *_ = _curve(_mmm(cv=0.9), max_channel_mix_share=0.9, kpi_is_monetary=True)

    assert max_efficiency["Daily_Investment"] > baseline["Daily_Investment"]


# --- F6: the share caps never drop budget ---


def _strategic_share(frame, cols):
    spend = frame[[f"Spend_{c}_Strategic" for c in cols]].sum(axis=1)
    positive = frame["Daily_Investment"] > 0
    return spend[positive] / frame.loc[positive, "Daily_Investment"]


def test_two_channels_under_a_40_pct_cap_still_spend_the_whole_budget():
    frame = _curve(_mmm(cv=0.9))[0]  # max_channel_mix_share 0.4 by default: 2 × 0.4 < 1

    np.testing.assert_allclose(_strategic_share(frame, "AB"), 1.0, rtol=1e-9)


def test_budget_past_the_channel_caps_is_spent_and_flagged_extrapolated():
    mmm = _mmm(cv=0.9, weights=(5.0, 1.0, 2.0, 2.0, 2.0))
    frame = _curve(mmm, investment_limit_factor=5.0)[0]

    np.testing.assert_allclose(_strategic_share(frame, "ABCDE"), 1.0, rtol=1e-9)
    cap = mmm["dataframe"][list("ABCDE")].max().sum() * full_config({})["per_channel_investment_limit_factor"]
    assert frame.loc[frame["Daily_Investment"] > cap, "Extrapolated"].all()


def test_an_infeasible_share_cap_is_relaxed_instead_of_dropping_share():
    capped = cap_channel_mix_share({"A": 0.9, "B": 0.1}, {"A": 0.5, "B": 0.5}, max_share=0.4)

    assert sum(capped.values()) == pytest.approx(1.0)
    assert capped == pytest.approx({"A": 0.5, "B": 0.5})


# --- F7: no reallocation on the curve while it is suppressed ---


def test_a_suppressed_reallocation_keeps_the_historical_mix_on_the_curve():
    mmm = _mmm(cv=0.9)
    cfg = full_config({"investment_limit_factor": 3.0, "max_channel_mix_share": 0.9})

    frame, _, _, limit, *_ = generate_aggregated_response_curve(mmm, cfg, suppress_reallocation=True)

    np.testing.assert_allclose(frame["Projected_Total_KPIs"], frame["Projected_Total_KPIs_Historical"], rtol=1e-12)
    np.testing.assert_allclose(frame["Spend_A_Strategic"], frame["Spend_A_Historical"], rtol=1e-12)
    assert limit["projected_kpis"]["Modelo de Elasticidade"] == pytest.approx(
        limit["projected_kpis"]["Média Histórica"]
    )


def test_the_pipeline_curve_follows_the_identifiability_verdict(tmp_path):
    config = EngineConfig.from_input({**identifiable_config(), "reallocation_min_cv_r2": -1.0})  # the CV alone trusts
    prepared = load_inputs(make_identifiable_dataset(tmp_path), config)
    cfg = {**config.to_legacy_dict(), "period_days": prepared.period_days}

    with threadpool_limits(limits=1):
        result = run_elasticity(prepared, cfg)

    assert not result["identifiability"]["NOEFFECT"]["identifiable"]
    frame = result["response_curve_df"]
    np.testing.assert_allclose(frame["Projected_Total_KPIs"], frame["Projected_Total_KPIs_Historical"], rtol=1e-12)


# --- F8: the "efficiency peak" mix favours efficient channels, not low-spend weeks ---


def test_efficiency_peak_mix_follows_incremental_kpi_per_spend():
    days = pd.date_range("2025-01-06", periods=7 * 40, freq="D")
    week = np.arange(len(days)) // 7
    efficient_weeks = week % 2 == 0
    # efficient weeks: high spend, mostly A (5 KPI per R$); the others: low spend, mostly B (0.5 per R$)
    a = np.where(efficient_weeks, 900.0, 10.0)
    b = np.where(efficient_weeks, 100.0, 90.0)
    kpi = 100_000 + 5 * a + 0.5 * b
    kpi_df = pd.DataFrame({"Date": days, "kpi": kpi})
    investment_df = pd.DataFrame(
        {
            "Date": np.tile(days, 2),
            "Product Group": np.repeat(["A", "B"], len(days)),
            "investment": np.concatenate([a, b]),
        }
    )
    organic = pd.Series(100_000.0, index=days)

    mix = find_optimal_historical_mix(kpi_df, investment_df, organic)

    assert mix["A"] > 0.8


# --- F9: a month is 365.25 / 12 days ---


def test_the_scenario_month_has_365_25_over_12_days():
    got = scenario(_strategic_doc(), ScenarioFilters(), 0.2)

    assert got["current"]["investment"] == pytest.approx(20.0 * 365.25 / 12)
