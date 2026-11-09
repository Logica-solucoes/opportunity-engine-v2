"""Audit findings of the gates (docs/audit/formulas-do-motor.md §5): G1, G3, G4, G6."""

import numpy as np
import pandas as pd
import pytest

from engine import pipeline
from engine.sufficiency import assess, seasonal_naive_wmape, spend_cv
from engine.validation import check_missing_dates, check_outliers, validate
from tests.engine.csv_factory import days, write_inputs
from tests.engine.synthetic_data import dataset_config


def _near_twins(budget_b: float):
    rng = np.random.default_rng(0)
    n = 120
    base = 1000 + 300 * np.sin(np.arange(n) / 9) + rng.normal(0, 60, n)
    a = base + rng.normal(0, 40, n)
    b = budget_b * (0.97 * base + rng.normal(0, 40, n))
    c = rng.normal(500, 80, n)
    investment = [
        (d, name, round(float(x[i]), 2)) for name, x in (("A", a), ("B", b), ("C", c)) for i, d in enumerate(days(n))
    ]
    kpi = [(d, round(float(5000 + 2 * a[i] + 2 * b[i] + rng.normal(0, 200)), 2)) for i, d in enumerate(days(n))]
    return investment, kpi


def test_g1_overlap_twins_are_unresolved_so_identifiability_hides_them(tmp_path):
    report = validate(write_inputs(tmp_path, *_near_twins(1.0)), dataset_config())

    ids = {c.id: c.level for c in report.checks}
    assert ids.get("dv360_cm360_overlap") == "warning" and "collinearity_unresolved" not in ids
    assert report.ok and report.collinearity.unresolved == ["A", "B"]


def test_g1_the_same_pair_with_half_the_budget_is_still_unresolved(tmp_path):
    report = validate(write_inputs(tmp_path, *_near_twins(0.5)), dataset_config())

    assert report.collinearity.unresolved == ["A", "B"]


def _skill_verdict(actual: np.ndarray, forecast: np.ndarray, train: np.ndarray, season: int):
    model = float(np.abs(actual - forecast).sum() / np.abs(actual).sum())
    naive = seasonal_naive_wmape(train, actual, season)
    return assess(
        [{"channels": ["A"], "oos_wmape": model, "naive_wmape": naive}],
        INVESTMENT,
        True,
        0.10,
        0.30,
        oos_skill_min=0.10,
    )


INVESTMENT = pd.DataFrame(
    {
        "Date": pd.date_range("2024-01-01", periods=140),
        "Product Group": "A",
        "investment": np.tile(np.repeat([50.0, 150.0], 7), 10),
    }
)


def test_g3_seasonal_naive_repeats_the_last_season():
    train = np.array([1.0, 2, 3, 4, 5, 6, 7, 10, 20, 30])
    holdout = np.array([10.0, 20, 30, 10])

    assert seasonal_naive_wmape(train, holdout, 3) == 0.0
    assert seasonal_naive_wmape(train[:2], np.array([2.0, 4.0]), 7) == pytest.approx(2 / 6)  # short train: last value
    assert seasonal_naive_wmape(train, np.zeros(3), 3) is None


@pytest.mark.parametrize("level", [3, 5, 8])
def test_g3_a_perfect_model_on_a_low_volume_kpi_passes(level):
    rng = np.random.default_rng(level)
    y = rng.poisson(level, 120).astype(float)
    train, holdout = y[:90], y[90:]

    verdict = _skill_verdict(holdout, np.full(30, float(level)), train, 7)

    assert verdict.pre_wmape > 0.30  # the old absolute gate would have failed it
    assert "high_oos_wmape" not in verdict.reasons


def test_g3_a_biased_model_on_a_high_level_kpi_fails():
    rng = np.random.default_rng(1)
    y = rng.normal(1000, 50, 120)
    train, holdout = y[:90], y[90:]

    verdict = _skill_verdict(holdout, np.full(30, 1150.0), train, 7)

    assert verdict.pre_wmape < 0.30  # the old absolute gate would have passed it
    assert verdict.reasons == ["high_oos_wmape"]


def test_g3_without_a_naive_benchmark_the_absolute_ceiling_still_judges():
    assert assess([{"channels": ["A"], "oos_wmape": 0.9}], INVESTMENT, True, 0.10, 0.30).reasons == ["high_oos_wmape"]
    assert assess([{"channels": ["A"], "oos_wmape": 0.2}], INVESTMENT, True, 0.10, 0.30).passed


def test_g3_the_fifth_argument_is_the_ceiling_not_the_skill_threshold():
    event = {"channels": ["A"], "oos_wmape": 0.8, "naive_wmape": 1.0}  # skill 0.2: passes 0.10, fails a 0.30

    assert assess([event], INVESTMENT, True, 0.10, 0.30).passed
    assert assess([event], INVESTMENT, True, 0.10, 0.30, oos_skill_min=0.25).reasons == ["high_oos_wmape"]


def test_g3_the_gate_still_fires_through_the_current_pipeline(synthetic_prepared):
    poor = pipeline.EventOutcome("e1", "YOUTUBE", "2024-10-28", {"oos_wmape": 0.9}, passed=True, selected=True)
    limits = {"spend_cv_min": 0.1, "oos_wmape_max": 0.3}

    _, verdict = pipeline.judge_sufficiency(synthetic_prepared, [poor], {"cv_out_of_sample": True}, limits)

    assert verdict.reasons == ["high_oos_wmape"]


def _cadences(spend: np.ndarray) -> dict[str, pd.DataFrame]:
    daily = pd.DataFrame(
        {"Date": pd.date_range("2025-01-06", periods=len(spend)), "Product Group": "X", "investment": spend}
    )
    by = daily.set_index("Date")["investment"]
    weekly = by.resample("W-MON", label="left", closed="left").sum()
    monthly = by.resample("MS").sum().iloc[1:-1]  # full months only
    return {
        "daily": daily,
        "weekly": weekly.reset_index().assign(**{"Product Group": "X"}),
        "monthly": monthly.reset_index().assign(**{"Product Group": "X"}),
    }


def test_g4_pacing_noise_alone_is_low_variation_at_every_cadence():
    rng = np.random.default_rng(1)
    noise = 1000 * (1 + rng.normal(0, 0.25, 364)).clip(0.05)

    cv = {name: spend_cv(df, ["X"])["X"] for name, df in _cadences(noise).items()}

    assert cv["daily"] == pytest.approx(cv["weekly"], rel=0.1)
    assert all(value < 0.10 for value in cv.values()), cv


def test_g4_a_deliberate_monthly_budget_change_passes_at_every_cadence():
    rng = np.random.default_rng(2)
    dates = pd.date_range("2025-01-06", periods=364)
    budget = np.where(dates.month % 2 == 0, 800.0, 1200.0)
    spend = budget * (1 + rng.normal(0, 0.25, 364)).clip(0.05)

    cv = {name: spend_cv(df, ["X"])["X"] for name, df in _cadences(spend).items()}

    assert all(value > 0.15 for value in cv.values()), cv
    assert max(cv.values()) / min(cv.values()) < 1.3, cv


def test_g4_months_of_different_length_are_not_variation():
    months = pd.date_range("2025-01-01", periods=12, freq="MS")
    flat = pd.DataFrame({"Date": months, "Product Group": "X", "investment": 1000.0 * months.days_in_month})

    assert spend_cv(flat, ["X"])["X"] == pytest.approx(0.0, abs=1e-12)


def _trending_kpi(seed: int = 3) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    n = 365
    t = np.arange(n)
    weekday = np.tile([0, 5, 5, 5, 5, 20, -40], 53)[:n]
    return pd.DataFrame(
        {"Date": pd.date_range("2025-01-01", periods=n), "kpi": 100 + 0.8 * t + weekday + rng.normal(0, 5, n)}
    )


def test_g6_a_spike_on_a_trending_kpi_is_an_outlier():
    kpi = _trending_kpi()
    kpi.loc[200, "kpi"] *= 1.6

    (check,) = check_outliers(kpi, 1)

    assert "2025-07-20" in check.details["dates"]
    assert check.details["count"] <= 5


def test_g6_trend_and_weekday_alone_are_not_outliers():
    checks = check_outliers(_trending_kpi(), 1)

    assert not checks or checks[0].details["count"] <= 4


def test_g6_monthly_missing_dates_are_the_missing_months():
    dates = pd.to_datetime(["2025-01-01", "2025-03-01", "2025-04-01", "2025-06-01", "2025-07-01"])
    frame = pd.DataFrame({"Date": dates})

    (check,) = check_missing_dates(frame, frame, 30)

    assert check.details == {"count": 2, "dates": ["2025-02-01", "2025-05-01"]}


def test_g6_monthly_missing_dates_anchored_at_month_end():
    dates = pd.to_datetime(["2025-01-31", "2025-03-31", "2025-04-30"])
    frame = pd.DataFrame({"Date": dates})

    (check,) = check_missing_dates(frame, frame, 30)

    assert check.details["dates"] == ["2025-02-28"]
