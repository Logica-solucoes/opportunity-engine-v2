import dataclasses
import math

import pandas as pd

from engine import results
from engine.pipeline import EventOutcome


def _result_data(**overrides) -> dict:
    data = {
        "start_date": "2024-06-03",
        "end_date": "2024-06-16",
        "product_group": "YOUTUBE",
        "absolute_lift": 120.0,
        "absolute_lift_ci_lower": 80.0,
        "absolute_lift_ci_upper": 160.0,
        "relative_lift_pct": 12.5,
        "p_value": 0.01,
        "investment_change_pct": 80.0,
        "cpa_incremental": 3.5,
        "total_investment_post_period": 420.0,
        "total_investment_pre_period": 200.0,
        "mae": 5.0,
        "mape": 4.0,
        "model_r_squared": 0.6,
        "event_period_avg_investment": 30.0,
    }
    return {**data, **overrides}


def _frames():
    line = pd.DataFrame(
        {
            "Date": pd.to_datetime(["2024-06-03", "2024-06-04"]),
            "Actual_KPI": [10.0, 11.0],
            "Investment": [1.0, 2.0],
            "Forecasted_KPI": [9.0, float("nan")],
        }
    )
    inv = pd.DataFrame({"Period": ["Pre-Event", "Event"], "Investment": [200.0, 420.0]}).set_index("Period")
    kpi = pd.DataFrame({"Category": ["Forecasted", "Actual"], "kpi": [900.0, 1020.0]}).set_index("Category")
    acc = pd.DataFrame({"Date": pd.to_datetime(["2024-05-01"]), "kpi": [8.0], "Predicted": [7.5]})
    return line, inv, kpi, acc


def outcome(event_id="YOUTUBE_2024-06-03", group="YOUTUBE", *, passed=True, selected=True, reasons=None, data=None):
    line, inv, kpi, acc = _frames()
    return EventOutcome(
        event_id,
        group,
        "2024-06-03",
        data if data is not None else _result_data(),
        line,
        inv,
        kpi,
        acc,
        passed=passed,
        reasons=reasons or [],
        selected=selected,
    )


def candidates(*rows) -> pd.DataFrame:
    """rows: (group, date, eligible, change)."""
    return pd.DataFrame(
        [
            {
                "event_id": f"{g.replace(' ', '_')}_{d}",
                "start_date": "2024-01-02",
                "intervention_date": d,
                "end_date": "2024-06-16",
                "product_group": g,
                "eligible": e,
                "investment_change_pct": c,
            }
            for g, d, e, c in rows
        ]
    )


def with_events(computed, events, cands=None):
    return dataclasses.replace(
        computed,
        events=events,
        candidates=cands if cands is not None else candidates(("YOUTUBE", "2024-06-03", True, 80.0)),
    )


def test_causal_events_follow_the_outcomes(synthetic_computed):
    causal = results._causal(synthetic_computed)
    assert [e.id for e in causal.events] == [o.event_id for o in synthetic_computed.events]
    for event, source in zip(causal.events, synthetic_computed.events, strict=True):
        assert (event.status == "published") == (source.passed and source.selected)


def test_passed_but_not_selected_is_rejected_with_reason(synthetic_computed):
    causal = results._causal(with_events(synthetic_computed, [outcome(passed=True, selected=False)]))
    event = causal.events[0]
    assert event.status == "rejected" and event.reasons == ["not_selected"] and event.selected is False


def test_gate_reasons_are_carried(synthetic_computed):
    causal = results._causal(
        with_events(synthetic_computed, [outcome(passed=False, selected=False, reasons=["poor_fit"])])
    )
    assert causal.events[0].status == "rejected" and causal.events[0].reasons == ["poor_fit"]


def test_event_fields_come_from_the_results_data(synthetic_computed):
    event = results._causal(with_events(synthetic_computed, [outcome()])).events[0]
    assert (event.start, event.end) == ("2024-06-03", "2024-06-16")
    assert event.lift.abs == 120.0 and event.lift.ci == (80.0, 160.0) and event.lift.rel_pct == 12.5
    assert event.incremental_investment == 420.0 and event.cpa_incremental == 3.5
    assert event.fit.r2 == 0.6 and event.fit.mae == 5.0 and event.fit.mape == 4.0 and event.fit.wmape is None
    assert event.placebo is None and event.channels == ["YOUTUBE"]


def test_series_have_the_four_named_blocks(synthetic_computed):
    series = results._causal(with_events(synthetic_computed, [outcome()])).events[0].series
    assert [p.date for p in series.line] == ["2024-06-03", "2024-06-04"]
    assert series.line[1].forecasted_kpi is not None and math.isnan(series.line[1].forecasted_kpi)  # sanitized at dump
    assert [(p.period, p.investment) for p in series.investment] == [("Pre-Event", 200.0), ("Event", 420.0)]
    assert [(p.category, p.kpi) for p in series.kpi] == [("Forecasted", 900.0), ("Actual", 1020.0)]
    assert series.accuracy[0].predicted == 7.5 and series.accuracy[0].mae == 5.0


def test_analysis_failed_event_has_no_lift_fit_or_series(synthetic_computed):
    failed = EventOutcome("YOUTUBE_2024-06-03", "YOUTUBE", "2024-06-03", None, reasons=["analysis_failed"])
    event = results._causal(with_events(synthetic_computed, [failed])).events[0]
    assert event.status == "rejected" and event.reasons == ["analysis_failed"]
    assert event.lift is None and event.fit is None and event.series is None


def test_zero_lift_gives_null_cpa(synthetic_computed):
    zero = outcome(data=_result_data(absolute_lift=0.0, cpa_incremental=0))
    assert results._causal(with_events(synthetic_computed, [zero])).events[0].cpa_incremental is None


def test_events_detected_lists_every_candidate_including_ineligible(synthetic_computed):
    cands = candidates(("YOUTUBE", "2024-06-03", True, 80.0), ("SEARCH, PMAX", "2024-01-08", False, -35.5))
    detected = results._causal(with_events(synthetic_computed, [outcome()], cands)).events_detected
    assert [(d.date, d.channels, d.investment_change_pct, d.eligible) for d in detected] == [
        ("2024-06-03", ["YOUTUBE"], 80.0, True),
        ("2024-01-08", ["SEARCH", "PMAX"], -35.5, False),
    ]


def test_channel_names_with_spaces_and_slashes_are_kept(synthetic_computed):
    group = "GOOGLE DISPLAY/VIDEO, RTB HOUSE"
    cands = candidates((group, "2024-06-03", True, 10.0))
    event = results._causal(with_events(synthetic_computed, [outcome(f"id_{group}", group)], cands)).events[0]
    assert event.channels == ["GOOGLE DISPLAY/VIDEO", "RTB HOUSE"]


def test_causal_status_reasons(synthetic_computed):
    none_detected = results._causal(with_events(synthetic_computed, [], candidates()))
    assert (none_detected.status, none_detected.reasons) == ("inconclusive", ["no_events_detected"])
    ineligible = results._causal(with_events(synthetic_computed, [], candidates(("YOUTUBE", "2024-06-03", False, 5.0))))
    assert (ineligible.status, ineligible.reasons) == ("inconclusive", ["no_eligible_events"])
    none_passed = results._causal(
        with_events(synthetic_computed, [outcome(passed=False, selected=False, reasons=["poor_fit"])])
    )
    assert (none_passed.status, none_passed.reasons) == ("inconclusive", ["no_event_passed_gates"])
    ok = results._causal(with_events(synthetic_computed, [outcome()]))
    assert (ok.status, ok.reasons) == ("ok", [])
