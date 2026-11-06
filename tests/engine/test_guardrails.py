import math

import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import MinMaxScaler

from engine import results
from engine.elasticity_analysis import (
    generate_aggregated_response_curve,
    generate_individual_response_curves,
    geometric_adstock,
    hill_transform,
)
from engine.scenario import ScenarioFilters, scenario
from tests.engine.helpers import full_config


def _small_mmm() -> dict:
    """Two channels with spend uniform in [100, 200]: the historical total sits in ~[200, 400], the average ~300."""
    rng = np.random.default_rng(0)
    n = 120
    a, b = rng.uniform(100, 200, n), rng.uniform(100, 200, n)
    df = pd.DataFrame({"A": a, "B": b, "kpi": 1000 + 5 * a + b + rng.normal(0, 10, n)})
    df["kpi_organic_baseline"] = 1000.0
    params = {"alphas": [0.0, 0.0], "ks": [1.0, 1.0], "ss": [150.0, 150.0]}
    features = np.column_stack(
        [hill_transform(geometric_adstock(df[c].values, params["alphas"][i]), 1.0, 150.0) for i, c in enumerate("AB")]
    )
    scaler = MinMaxScaler().fit(features)
    y = df["kpi"] - df["kpi_organic_baseline"]
    model = Ridge(alpha=1.0, positive=True, fit_intercept=False).fit(scaler.transform(features), y)
    samples = model.coef_ * rng.uniform(0.8, 1.2, (200, 2))
    model.coef_ = samples.mean(axis=0)
    return {
        "dataframe": df,
        "spend_cols": ["A", "B"],
        "optimal_params": params,
        "model": model,
        "scaler": scaler,
        "organic_baseline_mean": 1000.0,
        "contribution_pct": {"A": 80.0, "B": 20.0},
        "cv_r_squared": 0.9,
        "coef_samples": samples,
    }


def _curve(mmm):
    cfg = full_config({"investment_limit_factor": 3.0, "max_channel_mix_share": 0.9})
    return generate_aggregated_response_curve(mmm, cfg)


def test_every_curve_row_has_a_band_around_the_point():
    frame = _curve(_small_mmm())[0]

    assert frame[["KPI_Lo", "KPI_Hi"]].notna().all().all()
    tol = 1e-6 * frame["Projected_Total_KPIs"].abs()
    assert (frame["KPI_Lo"] <= frame["Projected_Total_KPIs"] + tol).all()
    assert (frame["Projected_Total_KPIs"] <= frame["KPI_Hi"] + tol).all()
    # below the historical spend the scaled features clip to 0 and the band collapses on the baseline; those rows are extrapolated
    inside = frame[~frame["Extrapolated"]]
    assert (inside["KPI_Hi"] - inside["KPI_Lo"]).gt(0).all()


def test_rows_outside_the_historical_total_are_extrapolated():
    mmm = _small_mmm()
    frame = _curve(mmm)[0]
    total = mmm["dataframe"][["A", "B"]].sum(axis=1)

    outside = (frame["Daily_Investment"] < total.min()) | (frame["Daily_Investment"] > total.max())
    assert frame.loc[outside, "Extrapolated"].all()
    assert bool(frame["Extrapolated"].iloc[0]) is True


def test_the_notable_points_carry_band_and_flag():
    _, baseline, max_efficiency, strategic_limit, _, _, reallocation = _curve(_small_mmm())

    for point in (baseline, max_efficiency, strategic_limit, reallocation):
        assert point["KPI_Lo"] <= point["KPI_Hi"]
        assert point["Extrapolated"] in (True, False)
    assert bool(baseline["Extrapolated"]) is False


def test_individual_curves_stay_within_the_channel_cap_even_past_the_recommended_spend():
    mmm = _small_mmm()
    cfg = full_config({"investment_limit_factor": 3.0, "per_channel_investment_limit_factor": 1.2})
    cap = mmm["dataframe"]["A"].max() * 1.2
    far_recommendation = {"Spend_A_Strategic": cap * 2, "Spend_B_Strategic": cap * 2}

    curves = generate_individual_response_curves(mmm, cfg, strategic_limit_point=far_recommendation)

    for channel in ("A", "B"):
        own = curves[curves["Channel"] == channel]
        assert own["Channel_Spend"].max() <= mmm["dataframe"][channel].max() * 1.2 + 1e-9


def test_individual_curve_points_carry_band_and_flag():
    mmm = _small_mmm()
    curves = generate_individual_response_curves(mmm, full_config({}))

    assert (curves["KPI_Lo"] <= curves["KPI_Hi"]).all()
    own = curves[curves["Channel"] == "A"]
    low, high = mmm["dataframe"]["A"].min(), mmm["dataframe"]["A"].max()
    expected = (own["Channel_Spend"] < low) | (own["Channel_Spend"] > high)
    assert (own["Extrapolated"] == expected).all()


def test_results_publish_band_flag_ramp_and_notes(identifiable_computed):
    doc = results.dump_results(results.build_results(identifiable_computed, "test"))
    elasticity = doc["elasticity"]

    assert all(r["kpi_lo"] is not None and r["kpi_hi"] is not None for r in elasticity["response_curve"])
    assert all(r["extrapolated"] in (True, False) for r in elasticity["response_curve"])

    scenarios = {s["name"]: s for s in elasticity["scenarios"]}
    current = scenarios["current"]["investment"]
    assert scenarios["current"]["ramp"] is None and scenarios["current"]["notes"] == []
    for s in scenarios.values():
        assert s["kpi_lo"] is not None and s["kpi_hi"] is not None and s["extrapolated"] in (True, False)
        assert (s["ramp"] is not None) == (abs(s["investment"] / current - 1) > 0.2 + 1e-9)
        assert bool(s["notes"]) == (not math.isclose(s["investment"], current))

    published = [c for c in elasticity["channels"] if c["identifiable"]]
    assert published and all(
        p["lo"] is not None and p["extrapolated"] is not None for c in published for p in c["curve"]
    )


def test_the_scenario_reads_what_a_real_run_publishes(identifiable_computed):
    doc = results.dump_results(results.build_results(identifiable_computed, "test"))
    # the fixture skips validate(); run() hands its report to compute(), which is where period_days comes from
    doc["validation"] = {"period_days": identifiable_computed.prepared.period_days}

    out = scenario(doc, ScenarioFilters(), 0.2)

    assert all(r["kpi_lo"] is not None and r["kpi_hi"] is not None for r in out["curve"])
    assert out["recommended"]["kpi_lo"] <= out["recommended"]["kpi"] <= out["recommended"]["kpi_hi"]
    assert out["recommended"]["ramp"] and out["recommended"]["notes"]
