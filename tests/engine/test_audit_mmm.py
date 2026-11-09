"""Audit findings of the MMM (docs/audit/formulas-do-motor.md): MMM F1–F5, planner F1/F2, PRE-6, G2, G5.

Synthetic data where the truth is known; the KPI with zero media is TRUE_LEVEL.
"""

import dataclasses

import numpy as np
import pandas as pd
import pytest
from threadpoolctl import threadpool_limits

from engine.config import EngineConfig
from engine.data_preprocessor import PreparedData
from engine.elasticity_analysis import (
    block_length,
    bootstrap_coefficients,
    geometric_adstock,
    hill_transform,
    predict_clipped_kpi,
    run_mmm_engine,
)
from engine.identifiability import assess
from engine.pipeline import load_inputs
from tests.engine.csv_factory import days, write_inputs
from tests.engine.synthetic_data import dataset_config

TRUE_LEVEL = 5000.0
WEIGHT, S = 800.0, 1000.0  # y = TRUE_LEVEL + WEIGHT·x/(x+S) per channel, no carry-over


def _prepared(spend: dict[str, np.ndarray], kpi: np.ndarray) -> PreparedData:
    dates = pd.date_range("2024-01-02", periods=len(kpi), freq="D")
    long = pd.concat(
        [pd.DataFrame({"Date": dates, "Product Group": name, "investment": values}) for name, values in spend.items()],
        ignore_index=True,
    )
    return PreparedData(
        kpi_df=pd.DataFrame({"Date": dates, "kpi": kpi}),
        investment_df=long,
        spend_df=long.copy(),
        trends_df=pd.DataFrame(),
        controls_df=pd.DataFrame({"Date": dates}),
        correlation_matrix=pd.DataFrame(),
        period_days=1,
    )


@pytest.fixture(scope="module")
def always_on():
    """A is always on (700–1300 a day), B swings 0–2000: both move the KPI the same way."""
    rng = np.random.default_rng(0)
    n = 365
    spend = {"A": rng.uniform(700, 1300, n), "B": rng.uniform(0, 2000, n)}
    media = sum(WEIGHT * x / (x + S) for x in spend.values())
    kpi = TRUE_LEVEL + media + rng.normal(0, 30, n)
    with threadpool_limits(limits=1):
        mmm = run_mmm_engine(
            {"country_code": "BR", "period_days": 1, "min_marketing_contribution": 0.05}, _prepared(spend, kpi)
        )
    return mmm, spend, media, kpi


def _features(mmm, spend: dict[str, float]) -> list[float]:
    params = mmm["optimal_params"]
    out = []
    for i, name in enumerate(mmm["spend_cols"]):
        gain = (params["alphas"][i] ** np.arange(12)).sum()
        out.append(hill_transform(spend[name] * gain, params["ks"][i], params["ss"][i]))
    return out


def test_the_media_share_is_measured_against_zero_media(always_on):
    """MMM F1/F2: the no-intercept Stage 2 gave ~0.2% media and A = 0; the truth is ~13% split ~50/50."""
    mmm, _, media, kpi = always_on
    true_pct = 100 * media.sum() / kpi.sum()

    assert mmm["marketing_contribution_of_kpi_pct"] == pytest.approx(true_pct, rel=0.3)
    assert 25 < mmm["contribution_pct"]["A"] < 75


def test_zero_spend_predicts_the_kpi_without_media(always_on):
    """Planner F2: the curve's zero is the KPI with no media, not the historical average (which carries the media)."""
    mmm, _, media, kpi = always_on
    zero = predict_clipped_kpi(
        mmm["organic_baseline_mean"], mmm["model"], mmm["scaler"], _features(mmm, {"A": 0, "B": 0})
    )

    assert zero == pytest.approx(mmm["organic_baseline_mean"])
    assert abs(zero - TRUE_LEVEL) < 0.3 * media.mean()
    assert zero < kpi.mean() - 0.5 * media.mean()


def test_spend_below_the_historical_minimum_still_moves_the_kpi(always_on):
    """Planner F1: A never spent under ~700; cutting it from there to 0 must cost KPI, not be free."""
    mmm, spend, _, _ = always_on
    b = spend["B"].mean()

    def kpi(a):
        return predict_clipped_kpi(
            mmm["organic_baseline_mean"], mmm["model"], mmm["scaler"], _features(mmm, {"A": a, "B": b})
        )

    assert kpi(0) < kpi(spend["A"].min() / 2) < kpi(spend["A"].min())


def test_the_band_brackets_the_zero_media_point(always_on):
    mmm, _, _, _ = always_on
    from engine.elasticity_analysis import kpi_band

    features = _features(mmm, {"A": 0, "B": 0})
    lo, hi = kpi_band(mmm["baseline_samples"], mmm["coef_samples"], mmm["scaler"], features)

    assert lo < mmm["organic_baseline_mean"] < hi


def _ar1(rng, n, rho, sd):
    e = rng.normal(0, sd, n)
    x = np.empty(n)
    x[0] = e[0] / np.sqrt(1 - rho**2)
    for t in range(1, n):
        x[t] = rho * x[t - 1] + e[t]
    return x


def _null_ci_clear_of_zero_rate(block: int, reps: int = 100) -> float:
    """Share of draws where the 95% CI of a channel with ZERO effect excludes zero (adstocked spend, AR(1) residuals)."""
    rng = np.random.default_rng(0)
    n, hits = 365, 0
    for _ in range(reps):
        cols = []
        for _ in range(2):
            adstocked = geometric_adstock(100 * np.exp(_ar1(rng, n, 0.5, 0.4)), 0.8)
            cols.append(hill_transform(adstocked, 0.8, adstocked.mean()))
        X = np.column_stack(cols) / np.column_stack(cols).max(axis=0)
        y = 0.3 * X[:, 0] + _ar1(rng, n, 0.7, 0.1)
        coefs, _ = bootstrap_coefficients(X, y, n_bootstrap=100, seed=int(rng.integers(1 << 31)), block=block)
        hits += np.percentile(coefs[:, 1], 2.5) > 0
    return hits / reps


def test_the_block_bootstrap_stops_clearing_a_null_channel_of_zero():
    """MMM F3 / G2: with iid rows the CI of a zero-effect channel excludes zero ~20% of the time (300 draws: 0.20 iid,
    0.06 with blocks of 12, nominal 0.025)."""
    engine_block = block_length(365, [0.8, 0.8])

    assert engine_block >= 12
    assert _null_ci_clear_of_zero_rate(block=1) > 0.12
    assert _null_ci_clear_of_zero_rate(block=engine_block) <= 0.10


def test_the_block_length_covers_the_adstock_memory_and_the_cube_root():
    assert block_length(1000, [0.0]) == 10
    assert block_length(104, [0.0]) == 5
    assert block_length(104, [0.5]) == 5  # 0.5^5 < 0.05
    assert block_length(104, [0.9]) == 12  # the adstock window
    assert block_length(10, [0.9]) == 10


def test_a_resample_is_made_of_contiguous_blocks():
    X = np.arange(40, dtype=float)[:, None]
    y = np.arange(40, dtype=float)
    coefs, intercepts = bootstrap_coefficients(X, y, n_bootstrap=5, seed=1, block=8)

    assert coefs.shape == (5, 1) and intercepts.shape == (5,)
    np.testing.assert_allclose(coefs[:, 0], 1.0, atol=0.02)  # y = x in every block: slope 1, no matter the draw


def _verdict(samples: np.ndarray) -> dict:
    mmm = {
        "spend_cols": ["A"],
        "coef_samples": samples[:, None],
        "channel_totals": np.array([1.0]),
        "model": type("M", (), {"coef_": samples.mean(keepdims=True)}),
    }
    return assess(mmm)["A"]


def test_the_width_rule_is_a_point_over_se_of_about_four():
    """G5: hi - lo <= point asks for point/se >= ~3.92, twice the 1.96 of a CI clear of zero (kept, see assess)."""
    draws = np.random.default_rng(0).standard_normal(4000)

    clear_but_imprecise = _verdict(3.0 + draws)
    precise = _verdict(4.5 + draws)

    assert clear_but_imprecise["reasons"] == ["coef_ci_too_wide"]
    assert precise["identifiable"] is True


def test_a_channel_against_the_kpi_keeps_its_real_spend(tmp_path):
    """PRE-6: spend negatively correlated with the KPI was swapped for an EWM picked on that same correlation."""
    ds = days(60)
    rng = np.random.default_rng(1)
    spend = rng.uniform(100, 1000, 60).round(2)
    investment = [(d, "NEG", s) for d, s in zip(ds, spend, strict=True)]
    kpi = [(d, round(5000 - 2 * s, 2)) for d, s in zip(ds, spend, strict=True)]
    prepared = load_inputs(write_inputs(tmp_path, investment, kpi), EngineConfig.from_input(dataset_config()))

    np.testing.assert_allclose(prepared.investment_df["investment"].to_numpy(), spend)
    pd.testing.assert_frame_equal(prepared.investment_df, prepared.spend_df)


def test_the_mmm_reads_the_spend_as_sent():
    """MMM F4: the MMM adstocks once; it must not stack its adstock on a smoothed investment_df."""
    rng = np.random.default_rng(2)
    n = 60
    spend = {"A": rng.uniform(100, 1000, n)}
    prepared = _prepared(spend, TRUE_LEVEL + spend["A"] + rng.normal(0, 10, n))
    smoothed = prepared.investment_df.assign(investment=prepared.investment_df["investment"].ewm(alpha=0.1).mean())
    prepared = dataclasses.replace(prepared, investment_df=smoothed)

    with threadpool_limits(limits=1):
        mmm = run_mmm_engine({"country_code": "BR", "period_days": 1, "min_marketing_contribution": 0.05}, prepared)

    np.testing.assert_allclose(mmm["dataframe"]["A"].to_numpy(), spend["A"])


def test_cv_r2_is_scored_on_rows_the_whole_fit_never_saw(monkeypatch):
    """MMM F5: Stage 1 and the adstock/Hill search ran on every row, test folds included, before scoring them.

    The spy records how many rows each Stage-1 fit saw: the CV ones must be the TimeSeriesSplit training folds."""
    from engine import elasticity_analysis

    seen = []
    real = elasticity_analysis.fit_baseline

    def spy(X, y):
        seen.append(len(y))
        return real(X, y)

    monkeypatch.setattr(elasticity_analysis, "fit_baseline", spy)
    rng = np.random.default_rng(3)
    n = 80
    spend = {"A": rng.uniform(100, 1000, n)}
    with threadpool_limits(limits=1):
        mmm = run_mmm_engine(
            {"country_code": "BR", "period_days": 1, "min_marketing_contribution": 0.05},
            _prepared(spend, TRUE_LEVEL + spend["A"] + rng.normal(0, 50, n)),
        )

    assert sorted(seen) == [20, 40, 60, 80]  # 3 folds of 20 + the final fit on all rows
    assert mmm["cv_out_of_sample"] is True and mmm["cv_r_squared"] > 0.5
