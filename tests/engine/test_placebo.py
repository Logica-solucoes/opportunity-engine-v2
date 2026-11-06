from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm
from scipy import stats

from engine.analysis import cumulative_p_value, oos_wmape, placebo_p_value
from tests.engine.test_controls import _event


def _pre(n=120, seed=0, step_at=None, step=0.0, noise=1.0):
    """kpi = level + weekly seasonality + noise (+ an optional step); one exogenous column."""
    rng = np.random.default_rng(seed)
    kpi = 100 + 5 * np.sin(2 * np.pi * np.arange(n) / 7) + rng.normal(0, noise, n)
    if step_at is not None:
        kpi[step_at:] += step
    return pd.DataFrame({"kpi": kpi, "x": rng.normal(0, 1, n)}, index=pd.date_range("2024-01-01", periods=n, freq="D"))


def test_cumulative_p_value_tests_the_lift_against_the_accumulated_forecast_error():
    p, cum_se = cumulative_p_value(10.0, SimpleNamespace(se_mean=np.array([3.0, 4.0])))

    assert cum_se == 5.0 and p == pytest.approx(2 * stats.norm.sf(2.0))
    assert cumulative_p_value(10.0, SimpleNamespace(se_mean=np.array([]))) == (1.0, 0.0)


def test_the_placebo_rejects_a_step_in_the_pre_period():
    assert placebo_p_value(_pre(step_at=60, step=40.0), ["x"], 14, 8) < 0.05


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_the_placebo_finds_nothing_in_a_clean_pre_period(seed):
    assert placebo_p_value(_pre(seed=seed), ["x"], 14, 8) > 0.01


def test_the_placebo_does_not_run_on_a_short_pre_period():
    assert placebo_p_value(_pre(n=14), ["x"], 7, 8) is None  # half (7) < min_pre_periods (8)
    assert placebo_p_value(_pre(n=40), ["x"], 25, 8) is None  # window 25 > second half 20


def test_oos_wmape_is_small_for_a_predictable_series_and_none_when_it_cannot_be_computed():
    assert oos_wmape(_pre(noise=0.1), ["x"], 8) < 0.05
    assert oos_wmape(_pre(n=20), ["x"], 8) is None  # holdout of 4 rows < 7
    zeros = _pre()
    zeros["kpi"] = 0.0
    assert oos_wmape(zeros, ["x"], 8) is None  # nothing to weigh the error by


def test_a_fit_that_raises_is_not_swallowed(monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("fit failed")

    monkeypatch.setattr(sm.tsa, "UnobservedComponents", boom)
    with pytest.raises(RuntimeError):
        placebo_p_value(_pre(), ["x"], 14, 8)
    with pytest.raises(RuntimeError):
        oos_wmape(_pre(), ["x"], 8)


def test_the_event_reports_its_placebo_and_out_of_sample_wmape():
    results = _event(lambda spend, rng: 50 + rng.normal(0, 5, len(spend)))

    assert 0 <= results["placebo_p_value"] <= 1
    assert results["oos_wmape"] is not None and results["oos_wmape"] >= 0
