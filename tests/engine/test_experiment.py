import math

import numpy as np
import pandas as pd
import pytest

from engine import experiment


def kpi_frame(values, period_days=1):
    dates = pd.date_range("2025-01-06", periods=len(values), freq=f"{period_days}D")
    return pd.DataFrame({"Date": dates, "kpi": np.asarray(values, dtype=float)})


def spend_frame(kpi, per_channel):
    return pd.concat(
        [
            pd.DataFrame({"Date": kpi["Date"], "Product Group": ch, "investment": float(v)})
            for ch, v in per_channel.items()
        ]
    )


def run(kpi, spend=None, period_days=1, target=0.05, max_days=90, step=0.2):
    spend = spend_frame(kpi, {"A": 100.0}) if spend is None else spend
    return experiment.design(kpi, spend, period_days, target, max_days, step)


def noisy(n, sd, seed=1, mean=1000.0):
    return mean + np.random.default_rng(seed).normal(0, sd, n)


def test_weekly_duration_and_mde_match_the_manual_formula():
    y = 1000 + 2 * np.arange(60) + np.random.default_rng(3).normal(0, 40, 60)

    d = run(kpi_frame(y, 7), period_days=7, max_days=3650)

    window = y[-30:]  # weekly: max(90 days, 30 periods) is 30 periods
    t = np.arange(30.0)
    e = window - np.polyval(np.polyfit(t, window, 1), t)
    sigma = math.sqrt(e @ e / 28)
    rho = min(max(np.corrcoef(e[1:], e[:-1])[0, 1], 0.0), 0.95)
    f = (1 + rho) / (1 - rho)
    periods = math.ceil((2.8 * sigma * math.sqrt(f) / (0.05 * window.mean())) ** 2)
    assert d.status == "ok" and d.feasible and d.reasons == []
    assert d.sigma == pytest.approx(sigma) and d.rho == pytest.approx(rho)
    assert d.kpi_per_period == pytest.approx(window.mean())
    assert d.duration_periods == periods and d.duration_days == 7 * periods
    assert d.mde_abs == pytest.approx(2.8 * sigma * math.sqrt(f * periods))
    assert d.mde_rel == pytest.approx(d.mde_abs / (window.mean() * periods)) and d.mde_rel <= 0.05


def test_daily_data_takes_the_day_of_week_out_of_the_noise():
    dates = pd.date_range("2025-01-06", periods=120, freq="D")
    y = noisy(120, 20, seed=5) + np.where(dates.dayofweek >= 5, 300.0, 0.0)

    d = run(kpi_frame(y))

    assert d.sigma < 30  # a trend-only fit would leave the 300 weekend jump in the noise


def test_short_history_has_no_numbers():
    d = run(kpi_frame(noisy(29, 10)))

    assert d.status == "insufficient_history" and d.reasons == ["short_history"]
    assert d.sigma is None and d.duration_days is None and d.designs == []
    assert d.period_days == 1 and d.target_lift == 0.05 and d.assumptions


@pytest.mark.parametrize("level", [1000.0, 0.0])
def test_flat_or_zero_kpi_is_degenerate(level):
    d = run(kpi_frame(np.full(60, level)))

    assert d.status == "insufficient_history" and d.reasons == ["degenerate_kpi"]


def test_a_test_longer_than_the_cap_is_not_feasible():
    d = run(kpi_frame(noisy(120, 400)))

    assert d.feasible is False and d.reasons == ["duration_capped"]
    assert d.duration_periods == 90 and d.duration_days == 90 and d.mde_rel > 0.05


def test_cells_per_channel_ordered_by_risk_without_idle_channels():
    kpi = kpi_frame(noisy(120, 20))

    d = run(kpi, spend_frame(kpi, {"A": 100.0, "B": 10.0, "C": 0.0}))

    t = d.duration_periods
    assert [(c.channel, c.test_type) for c in d.designs] == [
        ("B", "on_off"),
        ("B", "step_up"),
        ("A", "on_off"),
        ("A", "step_up"),
    ]
    b_off, b_up = d.designs[0], d.designs[1]
    assert b_off.step is None and b_off.spend_per_period == pytest.approx(10.0)
    assert b_off.budget_at_risk == pytest.approx(10.0 * t)
    assert b_up.step == 0.2 and b_up.budget_at_risk == pytest.approx(0.2 * 10.0 * t)


def test_spend_before_the_window_does_not_count():
    kpi = kpi_frame(noisy(200, 20))
    spend = spend_frame(kpi, {"A": 100.0})
    spend.loc[spend["Date"] < kpi["Date"].iloc[-90], "investment"] = 1e6

    d = run(kpi, spend)

    assert d.designs[0].spend_per_period == pytest.approx(100.0)


def ar1(rng, sigma, rho, reps, n):
    """AR(1) with marginal sd sigma."""
    x = np.empty((reps, n))
    x[:, 0] = rng.normal(0, sigma, reps)
    innovations = rng.normal(0, sigma * math.sqrt(1 - rho**2), (reps, n))
    for i in range(1, n):
        x[:, i] = rho * x[:, i - 1] + innovations[:, i]
    return x


def test_an_effect_of_one_mde_is_detected_about_80_percent_of_the_time():
    rng = np.random.default_rng(11)
    history = 1000 + ar1(rng, 100.0, 0.3, 1, 400)[0]
    d = run(kpi_frame(history), max_days=3650)
    assert d.status == "ok" and d.feasible and d.rho > 0

    t, s, r = d.duration_periods, d.sigma, d.rho
    sums = (ar1(rng, s, r, 2000, t) + d.mde_abs / t).sum(axis=1)
    z = sums / (s * math.sqrt((1 + r) / (1 - r) * t))

    assert (z > 1.96).mean() == pytest.approx(0.80, abs=0.05)


def test_non_finite_kpi_is_degenerate():
    y = noisy(60, 20)
    y[10] = np.nan

    d = run(kpi_frame(y))

    assert d.status == "insufficient_history" and d.reasons == ["degenerate_kpi"]


def test_spend_after_the_last_kpi_date_does_not_count():
    kpi = kpi_frame(noisy(120, 20))
    spend = spend_frame(kpi, {"A": 100.0})
    late = pd.DataFrame(
        {"Date": pd.date_range(kpi["Date"].iloc[-1] + pd.Timedelta(days=1), periods=14), "Product Group": "A"}
    ).assign(investment=1e6)

    d = run(kpi, pd.concat([spend, late]))

    assert d.designs[0].spend_per_period == pytest.approx(100.0)


def test_fractional_target_lift_keeps_its_decimals_in_the_text():
    d = run(kpi_frame(noisy(120, 20)), target=0.025)

    assert any("2,5%" in a for a in d.assumptions)


def test_a_cadence_longer_than_the_cap_has_no_numbers():
    d = run(kpi_frame(noisy(60, 20), 30), period_days=30, max_days=14)

    assert d.status == "insufficient_history" and d.reasons == ["duration_capped"]
    assert d.sigma is None and d.duration_days is None and d.designs == []
