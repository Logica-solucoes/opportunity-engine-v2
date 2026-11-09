import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from engine import EngineError
from engine.scenario import (
    DAYS_PER_MONTH,
    NO_CURVE,
    NOT_CONCLUSIVE,
    TCPA_NOTE,
    ScenarioFilters,
    _saturation_index,
    scenario,
)

GOL = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "results" / "gol_anonimizada.json").read_text(encoding="utf-8")
)
# the Gol has no identifiable channel, so its elasticity is inconclusive and scenario() refuses it; the parity tests
# below check the arithmetic against the Streamlit, not the gate, so they run on a copy marked ok
GOL_OK = {**GOL, "elasticity": {**GOL["elasticity"], "status": "ok", "reasons": []}}


# --- oracle: the prototype's filter and saturation, copied as they are (frozen repo opportunity-engine) ---


def find_saturation_point(df, optimal_point, min_investment=None):
    """dashboard_charts.py:15-62, verbatim."""
    search_df = df
    if min_investment is not None:
        search_df = df[df["Daily_Investment"] >= min_investment]
    incremental_kpis = search_df["Projected_Total_KPIs"].diff().fillna(0).values
    investment_steps = search_df["Daily_Investment"].diff().fillna(1).values
    first_derivative = incremental_kpis / investment_steps
    if len(first_derivative) <= 1:
        return optimal_point
    peak_marginal_gain = first_derivative.max()
    if peak_marginal_gain <= 0:
        return optimal_point
    above_threshold = np.where(first_derivative > peak_marginal_gain * 0.1)[0]
    if len(above_threshold) == 0:
        return optimal_point
    saturation_idx = above_threshold[-1] + 1
    if saturation_idx >= len(search_df):
        return optimal_point
    return search_df.iloc[saturation_idx]


def streamlit_pick(doc, filters):
    """streamlit_app.py:1999-2235 on the results.json rows (conversion mode): monthly investment of the recommended
    point (None when nothing passes) and of the saturation point."""
    rows = doc["elasticity"]["response_curve"]
    days_in_month = DAYS_PER_MONTH / doc["validation"]["period_days"]
    current = next(s for s in doc["elasticity"]["scenarios"] if s["name"] == "current")
    df = pd.DataFrame(
        {
            "Daily_Investment": [r["investment"] for r in rows],
            "Projected_Total_KPIs": [r["kpi"] for r in rows],
            "Incremental_Investment": [r["incremental_investment"] for r in rows],
            "Incremental_KPI": [r["incremental_kpi"] for r in rows],
        }
    )
    df["Monthly_Investment"] = df["Daily_Investment"] * days_in_month
    df["Monthly_KPI"] = df["Projected_Total_KPIs"] * days_in_month
    df["CPA"] = (df["Daily_Investment"] / df["Projected_Total_KPIs"]).replace([np.inf, -np.inf], float("nan"))
    df["iCPA"] = np.where(df["Incremental_KPI"] > 0, df["Incremental_Investment"] / df["Incremental_KPI"], np.nan)
    df["Pct_Incrementality"] = np.where(
        df["Projected_Total_KPIs"] > 0, df["Incremental_KPI"] / df["Projected_Total_KPIs"] * 100, 0.0
    )
    out = df[
        (df["Monthly_Investment"] >= filters.get("min_budget", df["Monthly_Investment"].min()))
        & (df["Monthly_Investment"] <= filters.get("max_budget", df["Monthly_Investment"].max()))
    ]
    if "target_cpa" in filters:
        out = out[out["CPA"] <= filters["target_cpa"]]
    if "target_icpa" in filters:
        out = out[out["iCPA"] <= filters["target_icpa"]]
    if "min_kpi" in filters:
        out = out[out["Monthly_KPI"] >= filters["min_kpi"]]
    if "min_incrementality_pct" in filters:
        out = out[out["Pct_Incrementality"] >= filters["min_incrementality_pct"]]
    optimal = out.iloc[-1] if not out.empty else df.iloc[-1]
    saturation = find_saturation_point(df, optimal, min_investment=current["investment"])
    recommended = None if out.empty else out.iloc[-1]["Monthly_Investment"]
    return recommended, saturation["Daily_Investment"] * days_in_month


def _gol_filters():
    curve = scenario(GOL_OK, ScenarioFilters(), 0.2)["curve"]
    # thresholds between two values: the CPA here and in the oracle may differ in the last bit
    cpas = sorted(r["cpa"] for r in curve if r["cpa"] is not None)
    icpas = sorted(r["icpa"] for r in curve if r["icpa"])  # target_icpa must be > 0
    investments = [r["investment"] for r in curve]
    mid_cpa, mid_icpa = len(cpas) // 2, len(icpas) // 2
    return [
        {},
        {"min_budget": investments[20], "max_budget": investments[70]},
        {"target_cpa": (cpas[mid_cpa] + cpas[mid_cpa + 1]) / 2},
        {"target_icpa": (icpas[mid_icpa] + icpas[mid_icpa + 1]) / 2},
        {"min_kpi": curve[60]["kpi"]},
        {"min_incrementality_pct": 30.0},
        {"max_budget": investments[80], "target_icpa": icpas[-1]},
        {
            "min_budget": investments[-1] * 2
        },  # nothing passes (the zero-spend row has CPA 0, so no CPA target can empty the curve)
    ]


@pytest.mark.parametrize("index", range(8))
def test_same_recommended_and_saturation_as_the_streamlit(index):
    filters = _gol_filters()[index]
    expected_recommended, expected_saturation = streamlit_pick(GOL_OK, filters)

    got = scenario(GOL_OK, ScenarioFilters(**filters), 0.2)

    if expected_recommended is None:
        assert got["recommended"] is None
    else:
        assert got["recommended"]["investment"] == pytest.approx(expected_recommended, rel=1e-9)
    assert got["saturation"]["investment"] == pytest.approx(expected_saturation, rel=1e-9)


def test_the_filter_that_empties_the_curve_still_answers():
    got = scenario(GOL_OK, ScenarioFilters(min_budget=1e12), 0.2)

    assert got["recommended"] is None
    assert not any(r["in_filter"] for r in got["curve"])
    assert got["saturation"] is not None


def test_scenario_is_fast_enough_for_the_slider():
    filters = ScenarioFilters(target_icpa=50.0)
    start = time.perf_counter()
    for _ in range(10):
        scenario(GOL_OK, filters, 0.2)
    assert (time.perf_counter() - start) / 10 < 0.3


def test_the_gol_fixture_gives_monthly_rows_with_its_band():
    got = scenario(GOL_OK, ScenarioFilters(), 0.2)

    assert got["unit"] == "month" and got["revenue_mode"] is False
    assert len(got["curve"]) == len(GOL_OK["elasticity"]["response_curve"])
    assert got["current"]["kpi_lo"] is not None and got["curve"][-1]["kpi_lo"] is not None


# --- hand-made documents ---


def _row(investment, kpi, revenue=None, iroas=None, inc_inv=0.0, inc_kpi=0.0, mix=None):
    return {
        "investment": investment,
        "kpi": kpi,
        "kpi_lo": kpi * 0.9,
        "kpi_hi": kpi * 1.1,
        "revenue": revenue,
        "icpa": None,
        "iroas": iroas,
        "incremental_investment": inc_inv,
        "incremental_kpi": inc_kpi,
        "extrapolated": investment > 30,
        "mix": mix or {},
    }


def _doc(rows, current_investment=20.0, current_kpi=40.0, period_days=1):
    current = {
        "name": "current",
        "investment": current_investment,
        "kpi": current_kpi,
        "kpi_lo": current_kpi * 0.9,
        "kpi_hi": current_kpi * 1.1,
        "extrapolated": False,
    }
    return {
        "validation": {"period_days": period_days},
        "elasticity": {"status": "ok", "response_curve": rows, "scenarios": [current]},
    }


CONVERSIONS = [
    _row(0.0, 0.0),
    _row(10.0, 25.0),
    _row(20.0, 40.0),
    _row(30.0, 50.0, inc_inv=10.0, inc_kpi=10.0),
    _row(40.0, 55.0, inc_inv=20.0, inc_kpi=15.0),
]


def _mixed(investment, kpi, **kw):
    # A is 60% of the spend at every point, like the engine's historical mix
    mix = {
        "historical": {"A": investment * 0.6, "Não identificados": investment * 0.4},
        "optimized": {"A": investment * 0.7, "Não identificados": investment * 0.3},
        "strategic": {"A": investment * 0.6, "Não identificados": None},
    }
    return _row(investment, kpi, mix=mix, **kw)


MIXED = [
    _mixed(0.0, 0.0),
    _mixed(10.0, 25.0),
    _mixed(20.0, 40.0),
    _mixed(30.0, 50.0, inc_inv=10.0, inc_kpi=10.0),
    _mixed(40.0, 55.0, inc_inv=20.0, inc_kpi=15.0),
]


def _with_channels(doc):
    doc["elasticity"]["channels"] = [
        {
            "name": "A",
            "identifiable": True,
            "observed_spend_range": [2.0, 8.0],
            "curve": [
                {"x": x, "y": y, "lo": y * 0.9, "hi": y * 1.1, "extrapolated": x > 8}
                for x, y in [(0, 10), (4, 20), (8, 26), (12, 28), (16, 29)]
            ],
        },
        {"name": "B", "identifiable": False, "observed_spend_range": [1.0, 3.0], "curve": []},
    ]
    return doc


def test_only_identifiable_channels_come_back_monthly():
    got = scenario(_with_channels(_doc(MIXED, period_days=7)), ScenarioFilters(), 0.2)

    factor = DAYS_PER_MONTH / 7
    assert [c["name"] for c in got["channels"]] == ["A"]
    channel = got["channels"][0]
    assert channel["curve"][1] == pytest.approx(
        {
            "investment": 4 * factor,
            "kpi": 20 * factor,
            "kpi_lo": 18 * factor,
            "kpi_hi": 22 * factor,
            "extrapolated": False,
        }
    )
    assert channel["observed_range"] == pytest.approx([2.0 * factor, 8.0 * factor])
    assert channel["current"] == pytest.approx(0.6 * 20.0 * factor)  # historical share x current investment


def test_a_document_without_channels_or_mix_still_answers():
    got = scenario(_doc(CONVERSIONS), ScenarioFilters(), 0.2)

    assert got["channels"] == []
    assert got["recommended"]["mix"] == {}
    assert got["current"]["mix"] is None


def test_table_rows_carry_the_monthly_mix_of_their_curve_point():
    got = scenario(_doc(MIXED), ScenarioFilters(), 0.2)

    mix = got["recommended"]["mix"]  # the 40.0 row
    assert mix["historical"]["A"] == pytest.approx(40.0 * 0.6 * DAYS_PER_MONTH)
    assert mix["optimized"]["Não identificados"] == pytest.approx(40.0 * 0.3 * DAYS_PER_MONTH)
    assert mix["strategic"]["Não identificados"] is None
    assert got["saturation"]["mix"]["historical"].keys() == {"A", "Não identificados"}
    assert got["current"]["mix"] is None


def test_the_identifiable_fixture_gives_only_strong():
    doc = json.loads(
        (Path(__file__).resolve().parents[1] / "fixtures" / "results" / "identificavel.json").read_text(
            encoding="utf-8"
        )
    )

    got = scenario(doc, ScenarioFilters(), 0.2)

    assert [c["name"] for c in got["channels"]] == ["STRONG"]
    assert got["channels"][0]["current"] is not None
    assert got["channels"][0]["saturation"] is None  # STRONG does not saturate in the simulated range


def test_values_are_monthly_for_the_cadence():
    got = scenario(_doc(CONVERSIONS, period_days=7), ScenarioFilters(), 0.2)

    factor = DAYS_PER_MONTH / 7
    assert got["curve"][1]["investment"] == pytest.approx(10.0 * factor)
    assert got["curve"][1]["kpi"] == pytest.approx(25.0 * factor)
    assert got["curve"][1]["cpa"] == pytest.approx(10.0 / 25.0)
    assert got["current"]["investment"] == pytest.approx(20.0 * factor)


def test_a_document_without_band_gives_rows_without_band():
    doc = _doc([{**row, "kpi_lo": None, "kpi_hi": None} for row in CONVERSIONS])  # written before A8
    doc["elasticity"]["scenarios"][0].update(kpi_lo=None, kpi_hi=None)

    got = scenario(doc, ScenarioFilters(), 0.2)

    assert got["current"]["kpi_lo"] is None and got["curve"][1]["kpi_lo"] is None


def test_the_table_rows_compare_against_the_current_scenario():
    got = scenario(_doc(CONVERSIONS), ScenarioFilters(), 0.2)

    assert got["current"]["incremental_investment"] == 0 and got["current"]["icpa"] == 0.0
    assert got["current"]["ramp"] is None and got["current"]["notes"] == []
    recommended = got["recommended"]
    assert recommended["investment"] == pytest.approx(40.0 * DAYS_PER_MONTH)
    assert recommended["incremental_investment"] == pytest.approx(20.0 * DAYS_PER_MONTH)
    assert recommended["incremental_kpi"] == pytest.approx(15.0 * DAYS_PER_MONTH)
    assert recommended["icpa"] == pytest.approx(20.0 / 15.0)
    assert recommended["extrapolated"] is True
    assert recommended["notes"] == [TCPA_NOTE]
    assert [s["investment"] for s in recommended["ramp"]] == pytest.approx(
        [24.0 * DAYS_PER_MONTH, 28.8 * DAYS_PER_MONTH, 34.56 * DAYS_PER_MONTH, 40.0 * DAYS_PER_MONTH]
    )


def test_roas_filters_apply_only_in_revenue_mode():
    revenue = [
        _row(10.0, 10.0, revenue=50.0),
        _row(20.0, 20.0, revenue=80.0),
        _row(30.0, 25.0, revenue=90.0, iroas=1.0, inc_inv=10.0, inc_kpi=5.0),
    ]
    got = scenario(_doc(revenue, current_kpi=20.0), ScenarioFilters(min_roas=3.5), 0.2)

    assert got["revenue_mode"] is True
    assert got["recommended"]["investment"] == pytest.approx(20.0 * DAYS_PER_MONTH)  # roas 50/10=5, 80/20=4, 90/30=3
    assert got["recommended"]["roas"] == pytest.approx(4.0)

    got = scenario(_doc(revenue, current_kpi=20.0), ScenarioFilters(min_iroas=0.5), 0.2)
    assert got["recommended"]["investment"] == pytest.approx(30.0 * DAYS_PER_MONTH)  # the only row with iROAS >= 0.5

    got = scenario(_doc(CONVERSIONS), ScenarioFilters(min_roas=100.0), 0.2)
    assert got["recommended"]["investment"] == pytest.approx(40.0 * DAYS_PER_MONTH)  # no revenue: ROAS filter ignored


def test_a_budget_cut_has_no_incremental_return():
    revenue = [_row(10.0, 10.0, revenue=50.0), _row(20.0, 20.0, revenue=80.0)]

    got = scenario(_doc(revenue, current_kpi=20.0), ScenarioFilters(max_budget=10.0 * DAYS_PER_MONTH), 0.2)

    assert got["recommended"]["incremental_kpi"] < 0
    assert got["recommended"]["icpa"] is None and got["recommended"]["iroas"] is None


@pytest.mark.parametrize(
    ("status", "reasons"),
    [
        ("inconclusive", ["no_identifiable_channel"]),
        ("inconclusive", ["no_identifiable_channel", "cv_in_sample"]),
        ("failed", ["model_failed"]),
    ],
)
def test_an_elasticity_without_identifiable_channels_is_refused(status, reasons):
    doc = _doc(CONVERSIONS)
    doc["elasticity"].update(status=status, reasons=reasons)

    with pytest.raises(EngineError, match=NOT_CONCLUSIVE):
        scenario(doc, ScenarioFilters(), 0.2)


def test_a_short_history_alone_still_answers():
    doc = _doc(CONVERSIONS)
    doc["elasticity"].update(status="inconclusive", reasons=["cv_in_sample"])

    assert scenario(doc, ScenarioFilters(), 0.2)["recommended"] is not None


def test_a_channel_saturation_is_searched_from_its_current_spend():
    doc = _with_channels(_doc(MIXED))
    curve = [(0, 10), (4, 20), (8, 21), (12, 21.1), (16, 21.15), (20, 21.16), (24, 21.161)]
    doc["elasticity"]["channels"][0]["curve"] = [{"x": x, "y": y, "extrapolated": False} for x, y in curve]

    channel = scenario(doc, ScenarioFilters(), 0.2)["channels"][0]

    # from zero the gain fades at x=8 per day, below A's current 0.6 × 20 = 12 per day
    assert channel["current"] == pytest.approx(0.6 * 20.0 * DAYS_PER_MONTH)
    assert channel["saturation"] == pytest.approx(24 * DAYS_PER_MONTH)


def test_the_gol_is_refused_because_no_channel_is_identifiable():
    with pytest.raises(EngineError, match=NOT_CONCLUSIVE):
        scenario(GOL, ScenarioFilters(), 0.2)


def test_an_ok_elasticity_without_curve_is_still_no_curve():
    with pytest.raises(EngineError, match=NO_CURVE):
        scenario(_doc([]), ScenarioFilters(), 0.2)


def test_a_run_without_curve_is_an_engine_error():
    with pytest.raises(EngineError):
        scenario({"validation": {"period_days": 1}, "elasticity": None}, ScenarioFilters(), 0.2)


@pytest.mark.parametrize("key", ["investment", "kpi"])
def test_a_null_number_on_the_curve_is_an_engine_error(key):
    rows = [dict(row) for row in CONVERSIONS]
    rows[2][key] = None
    with pytest.raises(EngineError):
        scenario(_doc(rows), ScenarioFilters(), 0.2)


def test_a_null_current_kpi_is_an_engine_error():
    doc = _doc(CONVERSIONS)
    doc["elasticity"]["scenarios"][0]["kpi"] = None
    with pytest.raises(EngineError):
        scenario(doc, ScenarioFilters(), 0.2)


def test_filters_reject_bad_values():
    with pytest.raises(ValidationError):
        ScenarioFilters(min_budget=-1)
    with pytest.raises(ValidationError):
        ScenarioFilters(min_budget=10, max_budget=5)
    with pytest.raises(ValidationError):
        ScenarioFilters(foo=1)


# --- find_saturation_point, ported from opportunity-engine/tests/test_dashboard_charts.py ---


def _curve(xs, ys):
    return [{"investment": float(x), "kpi": float(y)} for x, y in zip(xs, ys, strict=True)]


def test_saturation_skips_a_transient_dip():
    curve = _curve(range(0, 100, 10), [0, 1000, 1900, 1950, 2750, 3450, 4050, 4080, 4100, 4110])

    assert curve[_saturation_index(curve, 0.0)]["investment"] == 70


def test_saturation_floor_keeps_the_ceiling_at_or_above_current_spend():
    curve = _curve(range(0, 100, 10), [0, 1000, 1500, 1700, 1780, 1860, 1940, 2020, 2100, 2180])

    assert curve[_saturation_index(curve, 0.0)]["investment"] < 50
    floored = _saturation_index(curve, 50.0)
    assert floored is None or curve[floored]["investment"] >= 50


def test_saturation_falls_back_when_the_curve_never_rises_or_is_too_short():
    assert _saturation_index(_curve([0, 10, 20], [100, 90, 80]), 0.0) is None
    assert _saturation_index(_curve([0], [100]), 0.0) is None


def test_the_e2e_scenario_fixture_is_up_to_date():
    from tests.fixtures.results.scenario_fixture import TARGET, build

    assert json.loads(TARGET.read_text(encoding="utf-8")) == json.loads(json.dumps(build()))
