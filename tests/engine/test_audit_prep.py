"""Audit findings of the preprocessing (docs/audit/formulas-do-motor.md, section 1): PRE-3, PRE-7, PRE-8, PRE-9."""

import numpy as np
import pandas as pd

from engine import data_preprocessor
from engine.analysis import find_events
from engine.data_preprocessor import detect_cadence, drop_partial_periods, treat_outliers


def _split_year_week():
    """Flat 7000/week on Mondays; the tool cuts the week of 29/12 at 1/1 into 3000 + 4000."""
    weeks = list(pd.date_range("2025-06-02", "2025-12-22", freq="7D")) + list(
        pd.date_range("2026-01-05", "2026-04-27", freq="7D")
    )
    rows = [(d, "TV", 7000.0) for d in weeks]
    rows += [(pd.Timestamp("2025-12-29"), "TV", 3000.0), (pd.Timestamp("2026-01-01"), "TV", 4000.0)]
    return (
        pd.DataFrame(rows, columns=["Date", "Product Group", "investment"]).sort_values("Date").reset_index(drop=True)
    )


def test_pre3_year_boundary_fragment_is_merged_into_its_week():
    df = _split_year_week()

    kept = drop_partial_periods(df, "Date", detect_cadence(df["Date"]))

    assert pd.Timestamp("2026-01-01") not in set(kept["Date"])
    assert kept.loc[kept["Date"] == "2025-12-29", "investment"].tolist() == [7000.0]
    assert kept["investment"].sum() == df["investment"].sum()
    assert not kept.duplicated(["Date", "Product Group"]).any()


def test_pre3_flat_spend_has_no_event_at_the_year_boundary():
    df = _split_year_week()
    kept = drop_partial_periods(df, "Date", 7)

    events, _, _ = find_events(kept, "x", 1.5, 0.7, 14, period_days=7)

    assert events is None or events.empty


def test_pre3_merge_keeps_channels_apart_and_sums_the_kpi():
    a = _split_year_week()
    b = a.assign(**{"Product Group": "SEARCH", "investment": a["investment"] / 7})
    both = pd.concat([a, b], ignore_index=True)
    kpi = a[["Date"]].assign(kpi=a["investment"] / 10, source="total")

    kept = drop_partial_periods(both, "Date", 7)
    kept_kpi = drop_partial_periods(kpi, "Date", 7)

    boundary = kept[kept["Date"] == "2025-12-29"].set_index("Product Group")["investment"]
    assert boundary.to_dict() == {"SEARCH": 1000.0, "TV": 7000.0}
    assert kept_kpi.loc[kept_kpi["Date"] == "2025-12-29", "kpi"].tolist() == [700.0]
    assert kept_kpi["Date"].is_unique


def _lifted_kpi(rng):
    k = 1000 + 50 * rng.standard_normal(365)
    k[300:315] += 300
    return k


def test_pre7_capping_keeps_a_real_post_period_lift():
    rng = np.random.default_rng(0)
    kept = []
    for _ in range(100):
        k = _lifted_kpi(rng)
        capped = treat_outliers(pd.DataFrame({"kpi": k.copy()}), "kpi")["kpi"].to_numpy()
        kept.append((capped[300:315] - 1000).sum() / (k[300:315] - 1000).sum())

    assert np.mean(kept) > 0.9


def test_pre7_capping_still_flattens_an_isolated_spike():
    rng = np.random.default_rng(1)
    k = 1000 + 50 * rng.standard_normal(365)
    k[200] += 1000

    capped = treat_outliers(pd.DataFrame({"kpi": k.copy()}), "kpi")["kpi"].to_numpy()

    assert capped[200] < 1300


def test_pre7_capping_leaves_a_level_shift_alone():
    rng = np.random.default_rng(2)
    k = np.linspace(1000, 2000, 365) + 50 * rng.standard_normal(365)
    k[:120] *= 0.6

    capped = treat_outliers(pd.DataFrame({"kpi": k.copy()}), "kpi")["kpi"].to_numpy()

    assert (np.abs(capped - k) > 50).sum() <= 5


def test_pre8_four_week_cadence_is_not_snapped_to_monthly():
    dates = pd.Series(pd.date_range("2025-01-06", periods=13, freq="28D"))

    assert detect_cadence(dates) == 28


def test_pre8_calendar_months_still_snap_to_30():
    assert detect_cadence(pd.Series(pd.date_range("2025-01-01", periods=12, freq="MS"))) == 30
    assert detect_cadence(pd.Series(pd.date_range("2025-01-31", periods=12, freq="ME"))) == 30


def test_pre9_the_preprocessor_has_no_second_geometric_decay():
    # its only caller was the negative-correlation adstock, removed by PRE-6: only analysis.geometric_decay is left
    assert not hasattr(data_preprocessor, "geometric_decay")
    assert not hasattr(data_preprocessor, "ewm_smooth")
