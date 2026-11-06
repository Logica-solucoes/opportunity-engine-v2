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


# --- elasticity, baseline and status ---

import json

import numpy as np
import pytest
from threadpoolctl import threadpool_limits

from engine.config import EngineConfig
from engine.pipeline import compute
from engine.results_schema import Causal, Elasticity, ResultsV1
from tests.engine.synthetic_data import dataset_config, make_dataset


def _dump(model) -> dict:
    return results.sanitize(model.model_dump(mode="json", by_alias=True))


def test_elasticity_metrics_and_channels(synthetic_computed):
    synthetic_computed = dataclasses.replace(synthetic_computed, identifiability=None)  # the unfiltered shape
    elasticity = results.build_results(synthetic_computed, "v").elasticity
    mmm = synthetic_computed.mmm
    assert elasticity.status == "ok" and elasticity.reasons == []
    assert elasticity.metrics.cv_r2 == mmm["cv_r_squared"] and elasticity.metrics.r2 == mmm["r_squared"]
    assert elasticity.metrics.media_contribution_pct == mmm["marketing_contribution_of_kpi_pct"]
    assert [c.name for c in elasticity.channels] == list(mmm["spend_cols"])
    for i, channel in enumerate(elasticity.channels):
        assert channel.hill.K == mmm["optimal_params"]["ks"][i] and channel.hill.n == mmm["optimal_params"]["ss"][i]
        assert channel.adstock == mmm["optimal_params"]["alphas"][i]
        assert channel.observed_spend_range[0] <= channel.observed_spend_range[1]
        assert len(channel.curve) == 100 and channel.identifiable is None and channel.coef_ci is None


def test_response_curve_rows_map_the_columns(synthetic_computed):
    synthetic_computed = dataclasses.replace(synthetic_computed, identifiability=None)  # the unfiltered shape
    curve = results.build_results(synthetic_computed, "v").elasticity.response_curve
    frame = synthetic_computed.response_curve_df
    assert len(curve) == len(frame)
    first = curve[0]
    assert first.investment == frame["Daily_Investment"].iloc[0] and first.kpi == frame["Projected_Total_KPIs"].iloc[0]
    assert set(first.mix) == {"historical", "optimized", "strategic"}
    assert set(first.mix["historical"]) == set(synthetic_computed.mmm["spend_cols"])
    assert first.kpi_lo is None and first.extrapolated is None


def test_non_finite_curve_values_are_null_after_the_dump(synthetic_computed):
    frame = synthetic_computed.response_curve_df.copy()
    frame.loc[frame.index[0], "Incremental_ROI"] = np.inf
    frame.loc[frame.index[1], "iCPA"] = np.nan
    built = results.build_results(dataclasses.replace(synthetic_computed, response_curve_df=frame), "v")
    rows = _dump(built)["elasticity"]["response_curve"]
    assert rows[0]["iroas"] is None and rows[1]["icpa"] is None
    json.dumps(_dump(built), allow_nan=False)


def test_scenarios_use_the_known_names_and_skip_missing_points(synthetic_computed):
    scenarios = results.build_results(synthetic_computed, "v").elasticity.scenarios
    names = [s.name for s in scenarios]
    assert names == [n for n in names if n in results.SCENARIO_SOURCES]
    assert "current" in names
    without = dataclasses.replace(synthetic_computed, saturation_point=None, diminishing_return_point=None)
    assert {"saturation", "diminishing_return"}.isdisjoint(
        s.name for s in results.build_results(without, "v").elasticity.scenarios
    )
    current = next(s for s in scenarios if s.name == "current")
    assert current.investment == synthetic_computed.baseline_point["Daily_Investment"]
    assert current.cpa is None and current.roas is None and current.ramp is None


def test_groups_come_from_the_config(synthetic_computed):
    cfg = {**synthetic_computed.effective_config, "channel_groups": [["PMAX", "SEARCH"]]}
    built = results.build_results(dataclasses.replace(synthetic_computed, effective_config=cfg), "v")
    assert [(g.name, g.members) for g in built.elasticity.groups] == [("PMAX + SEARCH", ["PMAX", "SEARCH"])]


def test_baseline_monthly_sums_match_the_prepared_data(synthetic_computed):
    baseline = results.build_results(synthetic_computed, "v").baseline
    prepared = synthetic_computed.prepared
    assert sum(m.kpi for m in baseline.monthly) == pytest.approx(prepared.kpi_df["kpi"].sum())
    assert sum(m.investment for m in baseline.monthly) == pytest.approx(prepared.investment_df["investment"].sum())
    for month in baseline.monthly:
        assert sum(month.by_channel.values()) == pytest.approx(month.investment)
    assert baseline.monthly[0].month == prepared.kpi_df["Date"].min().strftime("%Y-%m")


def test_run_status_matrix():
    def causal(status):
        return Causal(status=status)

    def elasticity(status):
        return Elasticity(status=status)

    assert results.run_status(causal("ok"), elasticity("ok")) == "succeeded"
    assert results.run_status(causal("inconclusive"), elasticity("ok")) == "inconclusive"
    assert results.run_status(causal("ok"), elasticity("failed")) == "inconclusive"
    assert results.run_status(causal("inconclusive"), elasticity("failed")) == "failed"


def test_failed_model_yields_a_failed_elasticity_section(synthetic_computed):
    broken = dataclasses.replace(synthetic_computed, mmm=None, response_curve_df=None, individual_curves_df=None)
    built = results.build_results(broken, "v")
    assert built.elasticity.status == "failed" and built.elasticity.reasons == ["model_failed"]
    assert built.elasticity.metrics is None and built.elasticity.channels == []


def test_build_results_validates_and_leaves_the_future_sections_null(synthetic_computed):
    built = results.build_results(synthetic_computed, "abc123")
    assert built.engine_version == "abc123" and built.schema_version == 1
    assert built.validation is built.experiment_design is built.reports is None
    assert built.sufficiency is synthetic_computed.sufficiency and built.sufficiency is not None
    ResultsV1.model_validate(_dump(built))
    json.dumps(_dump(built), allow_nan=False)


@pytest.mark.parametrize("dataset", [{"cadence_days": 7}, {"with_trends": False}], ids=["weekly", "no-trends"])
def test_other_shapes_build_a_valid_document(tmp_path, dataset):
    files = make_dataset(tmp_path, n_days=364 if "cadence_days" not in dataset else 728, **dataset)
    with threadpool_limits(limits=1):
        computed = compute(files, EngineConfig.from_input(dataset_config()))
    built = results.build_results(computed, "v")
    ResultsV1.model_validate(_dump(built))
    json.dumps(_dump(built), allow_nan=False)
    assert built.baseline.monthly


# --- final review: zero sentinels in the curve and the scenarios ---


def _curve_with(computed, rows, **config):
    frame = computed.response_curve_df.iloc[: len(rows)].copy()
    for column in ("Incremental_Investment", "Incremental_KPI", "Incremental_ROI", "iCPA", "Projected_Revenue"):
        frame[column] = [row[column] for row in rows]
    cfg = {**computed.effective_config, **config}
    return dataclasses.replace(computed, response_curve_df=frame, effective_config=cfg)


def test_revenue_and_iroas_are_null_outside_revenue_mode(synthetic_computed):
    assert synthetic_computed.effective_config["optimization_target"] == "CONVERSIONS"
    rows = results.build_results(synthetic_computed, "v").elasticity.response_curve
    assert all(r.iroas is None and r.revenue is None for r in rows)


def test_iroas_needs_incremental_investment_in_revenue_mode(synthetic_computed):
    base = {"Incremental_Investment": 0.0, "Incremental_KPI": 0.0, "Incremental_ROI": 0.0, "iCPA": 0.0}
    rows = [
        {**base, "Projected_Revenue": 100.0},
        {
            **base,
            "Incremental_Investment": 5.0,
            "Incremental_KPI": 2.0,
            "Incremental_ROI": 2.0,
            "iCPA": 2.5,
            "Projected_Revenue": 110.0,
        },
    ]
    curve = _curve_with(synthetic_computed, rows, optimization_target="REVENUE")
    first, second = results.build_results(curve, "v").elasticity.response_curve
    assert first.iroas is None and first.revenue == 100.0  # 0/0 was filled with 0
    assert second.iroas == 2.0 and second.revenue == 110.0


def test_icpa_is_null_when_it_is_undefined(synthetic_computed):
    base = {"Incremental_ROI": 0.0, "Projected_Revenue": 0.0}
    rows = [
        {**base, "Incremental_Investment": 0.0, "Incremental_KPI": 0.0, "iCPA": 0.0},
        {**base, "Incremental_Investment": 10.0, "Incremental_KPI": 5.0, "iCPA": 2.0},
        {**base, "Incremental_Investment": 10.0, "Incremental_KPI": 0.0, "iCPA": float("nan")},
    ]
    icpa = [r.icpa for r in results.build_results(_curve_with(synthetic_computed, rows), "v").elasticity.response_curve]
    assert icpa == [None, 2.0, None]


def test_scenario_icpa_is_null_without_incremental_investment(synthetic_computed):
    point = {
        "Daily_Investment": 10.0,
        "Projected_Total_KPIs": 5.0,
        "Incremental_Investment": 0,
        "Incremental_KPI": 0,
        "iCPA": 0,
    }
    computed = dataclasses.replace(synthetic_computed, strategic_reallocation_point=point, identifiability=None)
    built = results.build_results(computed, "v")  # unfiltered: the scenario is withheld while a channel is hidden
    scenario = next(s for s in built.elasticity.scenarios if s.name == "strategic_reallocation")
    assert scenario.icpa is None and scenario.incremental_investment == 0.0


def test_controls_come_from_the_results_data_and_do_not_touch_reasons(synthetic_computed):
    data = _result_data(controls_used=["Macro"], controls_rejected=[{"name": "Generic Searches", "r": 0.73}])
    event = results._causal(with_events(synthetic_computed, [outcome(data=data)])).events[0]
    assert event.controls.used == ["Macro"]
    assert [(c.name, c.r) for c in event.controls.rejected] == [("Generic Searches", 0.73)]
    assert event.reasons == [] and event.status == "published"


def test_event_without_controls_in_the_data_has_none(synthetic_computed):
    assert results._causal(with_events(synthetic_computed, [outcome()])).events[0].controls is None
    failed = EventOutcome("YOUTUBE_2024-06-03", "YOUTUBE", "2024-06-03", None, reasons=["analysis_failed"])
    assert results._causal(with_events(synthetic_computed, [failed])).events[0].controls is None


# --- A5: only identifiable channels are published ---------------------------------------------------------------


def _assessed(computed, identifiable: set[str], *, reason="ci_crosses_zero"):
    verdicts = {
        name: {
            "identifiable": name in identifiable,
            "reasons": [] if name in identifiable else [reason],
            "coef_ci": (0.5, 2.0) if name in identifiable else (0.0, 3.0),
            "point": 1.0,
        }
        for name in computed.mmm["spend_cols"]
    }
    return dataclasses.replace(computed, identifiability=verdicts)


def test_unidentified_channel_loses_curve_hill_adstock_and_contribution(synthetic_computed):
    keep, hidden = synthetic_computed.mmm["spend_cols"][:2]
    elasticity = results.build_results(_assessed(synthetic_computed, {keep}), "v").elasticity
    channels = {c.name: c for c in elasticity.channels}
    assert channels[keep].identifiable is True and channels[keep].hill is not None and len(channels[keep].curve) == 100
    assert channels[keep].contribution_pct is not None and channels[keep].coef_ci == (0.5, 2.0)
    gone = channels[hidden]
    assert gone.identifiable is False and gone.reasons == ["ci_crosses_zero"] and gone.coef_ci == (0.0, 3.0)
    assert gone.hill is None and gone.adstock is None and gone.curve == [] and gone.contribution_pct is None
    assert gone.observed_spend_range is not None


def test_mix_pools_hidden_channels_and_keeps_the_row_sum(synthetic_computed):
    from engine.identifiability import UNIDENTIFIED_KEY

    spend_cols = list(synthetic_computed.mmm["spend_cols"])
    keep, hidden = spend_cols[0], set(spend_cols[1:])
    plain = results.build_results(dataclasses.replace(synthetic_computed, identifiability=None), "v")
    filtered = results.build_results(_assessed(synthetic_computed, {keep}), "v")
    for before, after in zip(plain.elasticity.response_curve, filtered.elasticity.response_curve, strict=True):
        for variant in ("historical", "optimized", "strategic"):
            assert not hidden & set(after.mix[variant])
            assert set(after.mix[variant]) == {keep, UNIDENTIFIED_KEY}
            assert sum(after.mix[variant].values()) == pytest.approx(sum(before.mix[variant].values()))


def test_unidentified_section_lists_names_and_summed_contribution(synthetic_computed):
    spend_cols = list(synthetic_computed.mmm["spend_cols"])
    elasticity = results.build_results(_assessed(synthetic_computed, {spend_cols[0]}), "v").elasticity
    assert elasticity.unidentified.channels == spend_cols[1:]
    expected = sum(synthetic_computed.mmm["contribution_pct"][c] for c in spend_cols[1:])
    assert elasticity.unidentified.contribution_pct == pytest.approx(expected)
    assert "no_identifiable_channel" not in elasticity.reasons


def test_no_identifiable_channel_still_publishes_the_total(synthetic_computed):
    elasticity = results.build_results(_assessed(synthetic_computed, set()), "v").elasticity
    assert elasticity.status == "ok" and elasticity.reasons == ["no_identifiable_channel"]
    assert elasticity.unidentified.channels == list(synthetic_computed.mmm["spend_cols"])
    assert elasticity.response_curve and elasticity.scenarios and elasticity.metrics is not None
    assert all(set(row.mix["historical"]) == {"nao_identificavel"} for row in elasticity.response_curve)


def test_special_characters_in_channel_names_are_never_mix_keys(synthetic_computed):
    mmm = dict(synthetic_computed.mmm)
    old = mmm["spend_cols"][0]
    new = "GOOGLE DISPLAY/VIDEO"
    mmm["spend_cols"] = [new, *mmm["spend_cols"][1:]]
    frame = synthetic_computed.response_curve_df.rename(columns=lambda c: c.replace(f"_{old}_", f"_{new}_"))
    mmm["contribution_pct"] = {(new if k == old else k): v for k, v in mmm["contribution_pct"].items()}
    mmm["dataframe"] = mmm["dataframe"].rename(columns={old: new})
    computed = dataclasses.replace(synthetic_computed, mmm=mmm, response_curve_df=frame)
    computed = _assessed(computed, set(mmm["spend_cols"][1:]))
    rows = results.build_results(computed, "v").elasticity.response_curve
    assert all(new not in row.mix["historical"] for row in rows)


def test_without_identifiability_nothing_is_filtered(synthetic_computed):
    elasticity = results.build_results(dataclasses.replace(synthetic_computed, identifiability=None), "v").elasticity
    assert elasticity.unidentified is None and all(c.reasons == [] for c in elasticity.channels)
    assert all("nao_identificavel" not in row.mix["historical"] for row in elasticity.response_curve)


def test_reallocation_is_suppressed_while_any_channel_is_hidden(synthetic_computed):
    spend_cols = list(synthetic_computed.mmm["spend_cols"])
    plain = results.build_results(dataclasses.replace(synthetic_computed, identifiability=None), "v").elasticity
    assert (
        "strategic_reallocation" in [s.name for s in plain.scenarios] and plain.metrics.reallocation_suppressed is None
    )

    hidden = results.build_results(_assessed(synthetic_computed, set(spend_cols[:-1])), "v").elasticity
    assert "strategic_reallocation" not in [s.name for s in hidden.scenarios]
    assert hidden.metrics.reallocation_suppressed is True
    assert {"current", "max_efficiency"} <= {s.name for s in hidden.scenarios}  # the other scenarios stay

    all_ok = results.build_results(_assessed(synthetic_computed, set(spend_cols)), "v").elasticity
    assert (
        "strategic_reallocation" in [s.name for s in all_ok.scenarios]
        and all_ok.metrics.reallocation_suppressed is None
    )


def test_event_carries_the_placebo_and_the_oos_wmape(synthetic_computed):
    data = {**_result_data(), "placebo_ran": True, "placebo_p_value": 0.62, "placebo_passed": True, "oos_wmape": 0.08}
    event = results._causal(with_events(synthetic_computed, [outcome(data=data)])).events[0]
    assert event.placebo.p_value == 0.62 and event.placebo.passed is True and event.fit.wmape == 0.08


def test_a_placebo_that_did_not_run_is_published_as_null(synthetic_computed):
    data = {**_result_data(), "placebo_ran": False, "placebo_p_value": None, "placebo_passed": None, "oos_wmape": None}
    event = results._causal(with_events(synthetic_computed, [outcome(data=data)])).events[0]
    assert event.placebo.p_value is None and event.placebo.passed is None and event.fit.wmape is None


def test_a_failed_placebo_is_published_as_not_passed(synthetic_computed):
    data = {**_result_data(), "placebo_ran": True, "placebo_p_value": 0.01, "placebo_passed": False, "oos_wmape": 0.1}
    event = results._causal(with_events(synthetic_computed, [outcome(data=data)])).events[0]
    assert event.placebo.passed is False


# --- A6: sufficiency in the document ---


def _with_sufficiency(computed, events, **kw):
    from engine.results_schema import Sufficiency

    return dataclasses.replace(with_events(computed, events), sufficiency=Sufficiency(**kw))


def test_the_document_carries_the_sufficiency(synthetic_computed):
    computed = _with_sufficiency(
        synthetic_computed,
        [outcome()],
        passed=True,
        validated_events=1,
        pre_wmape=0.1,
        spend_variation={"YOUTUBE": 0.4},
    )
    doc = results.build_results(computed, "x")
    assert doc.sufficiency.passed is True and doc.sufficiency.validated_events == 1


def test_an_insufficient_run_is_inconclusive_with_the_reason_and_no_published_event(synthetic_computed):
    demoted = outcome(passed=False, selected=False, reasons=["insufficient_run"])
    computed = _with_sufficiency(
        synthetic_computed, [demoted], passed=False, reasons=["high_oos_wmape"], validated_events=1, pre_wmape=0.6
    )
    doc = results.build_results(computed, "x")
    assert doc.status == "inconclusive" and doc.causal.status == "inconclusive"
    assert doc.causal.reasons == ["high_oos_wmape", "no_event_passed_gates"]
    assert [e.status for e in doc.causal.events] == ["rejected"] and doc.causal.events[0].reasons == [
        "insufficient_run"
    ]


def test_no_validated_event_does_not_repeat_the_causal_reason(synthetic_computed):
    computed = _with_sufficiency(
        synthetic_computed, [outcome(passed=False, selected=False)], passed=False, reasons=["no_validated_event"]
    )
    assert results.build_results(computed, "x").causal.reasons == ["no_event_passed_gates"]


def test_an_in_sample_cv_makes_the_run_inconclusive_but_keeps_the_elasticity(synthetic_computed):
    computed = _with_sufficiency(
        synthetic_computed, [outcome()], passed=False, reasons=["cv_in_sample"], cv_out_of_sample=False
    )
    doc = results.build_results(computed, "x")
    assert doc.causal.status == "ok" and doc.status == "inconclusive"
    assert doc.elasticity.status == "ok" and "cv_in_sample" in doc.elasticity.reasons and doc.elasticity.response_curve


def test_run_status_never_succeeds_with_a_failed_sufficiency():
    from engine.results_schema import Causal, Elasticity, Sufficiency

    ok_c, ok_e = Causal(status="ok"), Elasticity(status="ok")
    assert results.run_status(ok_c, ok_e, Sufficiency(passed=False)) == "inconclusive"
    assert results.run_status(ok_c, ok_e, Sufficiency(passed=True)) == "succeeded"
    assert (
        results.run_status(Causal(status="inconclusive"), Elasticity(status="failed"), Sufficiency(passed=False))
        == "failed"
    )


def test_event_carries_the_robustness(synthetic_computed):
    data = {**_result_data(), "robust_p_value": 0.4, "robust_passed": False}
    event = results._causal(with_events(synthetic_computed, [outcome(data=data, passed=False, selected=False)])).events[
        0
    ]
    assert event.robustness.p_value == 0.4 and event.robustness.passed is False


def test_event_without_the_robustness_keys_publishes_none(synthetic_computed):
    assert results._causal(with_events(synthetic_computed, [outcome()])).events[0].robustness is None


def test_an_event_demoted_by_an_insufficient_run_publishes_no_lift(synthetic_computed):
    data = {**_result_data(), "placebo_ran": True, "placebo_p_value": 0.5, "placebo_passed": True, "oos_wmape": 0.6}
    demoted = outcome(data=data, passed=False, selected=False, reasons=["insufficient_run"])
    event = results._causal(with_events(synthetic_computed, [demoted])).events[0]
    assert event.status == "rejected" and event.reasons == ["insufficient_run"]
    assert event.lift is None and event.p_value is None and event.cpa_incremental is None
    assert event.incremental_investment is None and event.series is None
    assert event.fit.wmape == 0.6 and event.placebo.passed is True  # the evidence of why stays


def test_an_event_rejected_by_a_gate_keeps_its_numbers(synthetic_computed):
    rejected = outcome(passed=False, selected=False, reasons=["not_significant"])
    event = results._causal(with_events(synthetic_computed, [rejected])).events[0]
    assert event.lift is not None and event.series is not None
