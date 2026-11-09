import math

import numpy as np
import pandas as pd
import pytest

from engine import experiment

Z = 1.96 + 0.84


def ar1(rng, sigma, rho, reps, n):
    x = np.empty((reps, n))
    x[:, 0] = rng.normal(0, sigma, reps)
    innovations = rng.normal(0, sigma * math.sqrt(1 - rho**2), (reps, n))
    for i in range(1, n):
        x[:, i] = rho * x[:, i - 1] + innovations[:, i]
    return x


def design(y, period_days, target=0.05, max_days=3650):
    dates = pd.date_range("2025-01-06", periods=len(y), freq=f"{period_days}D")
    kpi = pd.DataFrame({"Date": dates, "kpi": y})
    spend = pd.DataFrame({"Date": dates, "Product Group": "A", "investment": 100.0})
    return experiment.design(kpi, spend, period_days, target, max_days, 0.2)


def sum_variance(rho, n):
    """Var of the sum of n AR(1) periods with unit marginal variance, from the full covariance matrix."""
    i = np.arange(n)
    return float((rho ** np.abs(i[:, None] - i[None, :])).sum())


def test_exp3_mde_uses_the_exact_variance_of_a_short_sum():
    y = 1000 + ar1(np.random.default_rng(4), 60.0, 0.7, 1, 40)[0]

    d = design(y, 30, target=0.3, max_days=300)

    t, n = d.duration_periods, 30
    assert d.status == "ok" and d.rho > 0.3 and t < 10
    var = sum_variance(d.rho, t) + t**2 * sum_variance(d.rho, n) / n**2
    assert d.mde_abs == pytest.approx(Z * d.sigma * math.sqrt(var))


def test_exp2_rho_has_no_small_sample_bias_on_a_30_period_window():
    rng = np.random.default_rng(2)
    rhos = [design(1000 + h, 7).rho for h in ar1(rng, 60.0, 0.5, 1000, 30)]

    assert np.mean(rhos) == pytest.approx(0.5, abs=0.04)


@pytest.mark.parametrize(
    "period_days,n_hist,sigma,rho",
    [(1, 120, 80.0, 0.3), (1, 120, 50.0, 0.6), (7, 40, 40.0, 0.5)],
)
def test_exp1_designed_test_has_80_percent_power_against_the_window_mean(period_days, n_hist, sigma, rho):
    rng = np.random.default_rng(7)
    reps, horizon = 1000, 400
    series = 1000 + ar1(rng, sigma, rho, reps, n_hist + horizon)
    window = max(30, math.ceil(90 / period_days))
    hit = false_alarm = 0
    for y in series:
        # a capped design still reports the MDE of its capped duration, so it is read like the others
        d = design(y[:n_hist], period_days, max_days=horizon * period_days)
        t = d.duration_periods
        assert d.status == "ok"
        cf = t * y[n_hist - window : n_hist].mean()
        se = d.mde_abs / Z
        noise = y[n_hist : n_hist + t].sum() - cf
        false_alarm += abs(noise / se) > 1.96
        hit += (noise + d.mde_abs) / se > 1.96

    assert hit / reps == pytest.approx(0.80, abs=0.05)
    assert false_alarm / reps < 0.10  # above 5% only by the sampling error of rho on short windows
