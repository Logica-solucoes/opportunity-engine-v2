import dataclasses

from engine import pipeline
from engine.config import EngineConfig
from tests.engine.synthetic_data import dataset_config, make_dataset

SHORT = 364  # one year: keeps the stage tests fast while still holding the YOUTUBE spike


def _prepared(tmp_path, *, config=None, n_days: int = SHORT, **dataset):
    files = make_dataset(tmp_path, n_days=n_days, **dataset)
    cfg = EngineConfig.from_input({**dataset_config(), **(config or {})})
    prepared = pipeline.load_inputs(files, cfg)
    return cfg, prepared, {**cfg.to_legacy_dict(), "period_days": prepared.period_days}


def test_no_events_when_spend_is_flat(tmp_path):
    _, prepared, legacy = _prepared(tmp_path, flat_spend=True)
    candidates = pipeline.detect_events(prepared, legacy)
    assert candidates.empty
    assert pipeline.analyze_events(prepared, candidates, legacy) == []
    mmm = pipeline.run_elasticity(prepared, legacy)
    assert mmm["mmm"] is not None


def test_runs_without_a_trends_file(tmp_path):
    _, prepared, legacy = _prepared(tmp_path, with_trends=False)
    assert prepared.trends_df.empty
    candidates = pipeline.detect_events(prepared, legacy)
    events = pipeline.analyze_events(prepared, candidates, legacy)
    assert events and all(e.event_id for e in events)


def test_gates_record_their_reasons(tmp_path):
    _, prepared, legacy = _prepared(tmp_path, config={"p_value_threshold": 1e-12})
    events = pipeline.analyze_events(prepared, pipeline.detect_events(prepared, legacy), legacy)
    assert events and not any(e.passed for e in events)
    assert any("not_significant" in e.reasons for e in events)
    assert not any(e.selected for e in events)
    assert not any("placebo_p_value" in e.results_data for e in events if e.results_data)  # no A6 fits once out


def test_selected_is_capped_by_max_events_to_analyze(tmp_path):
    _, prepared, legacy = _prepared(tmp_path, config={"max_events_to_analyze": 1}, n_days=728)
    events = pipeline.analyze_events(prepared, pipeline.detect_events(prepared, legacy), legacy)
    passed = [e for e in events if e.passed]
    assert len(passed) >= 2, "the synthetic spike should yield several passing events"
    assert sum(e.selected for e in events) == 1
    best = max(passed, key=lambda e: abs(e.results_data["absolute_lift"]))
    assert best.selected


def test_min_intervention_date_skips_earlier_events(tmp_path):
    _, prepared, legacy = _prepared(tmp_path, config={"min_intervention_date": "2099-01-01"})
    candidates = pipeline.detect_events(prepared, legacy)
    assert not candidates["eligible"].any()
    assert pipeline.analyze_events(prepared, candidates, legacy) == []


def test_stages_do_not_mutate_the_config(tmp_path):
    cfg, prepared, legacy = _prepared(tmp_path)
    before = (cfg.model_dump(), dict(legacy))
    pipeline.detect_events(prepared, legacy)
    assert (cfg.model_dump(), legacy) == before


def test_detect_events_keeps_the_investment_change(tmp_path):
    _, prepared, legacy = _prepared(tmp_path)
    candidates = pipeline.detect_events(prepared, legacy)
    assert "investment_change_pct" in candidates.columns
    assert candidates["investment_change_pct"].dtype.kind == "f"
    assert (candidates["investment_change_pct"].abs() > 0).all()
    _, flat, flat_legacy = _prepared(tmp_path / "flat", flat_spend=True)
    assert "investment_change_pct" in pipeline.detect_events(flat, flat_legacy).columns


def test_compute_keeps_the_candidates(synthetic_computed, synthetic_prepared):
    candidates = synthetic_computed.candidates
    assert len(candidates) >= len(synthetic_computed.events) > 0
    assert "eligible" in candidates.columns


def test_compute_keeps_the_individual_curves(synthetic_computed):
    curves = synthetic_computed.individual_curves_df
    spend_cols = synthetic_computed.mmm["spend_cols"]
    assert set(curves["Channel"]) == set(spend_cols)
    assert (curves.groupby("Channel").size() == 100).all()


def test_individual_curves_function_returns_the_frame(synthetic_computed):
    from engine import elasticity_analysis

    frame = elasticity_analysis.generate_individual_response_curves(
        synthetic_computed.mmm, synthetic_computed.effective_config, output_dir=None
    )
    assert list(frame.columns) == [
        "Channel",
        "Channel_Spend",
        "Projected_Total_KPIs",
        "Historical_Avg",
        "Recommended",
        "KPI_Lo",
        "KPI_Hi",
        "Extrapolated",
    ]


def test_product_filter_naming_a_member_keeps_the_grouped_events(tmp_path):
    config = {"channel_groups": [["YOUTUBE", "DISPLAY"]], "product_group_filter": ["YOUTUBE"]}
    _, prepared, legacy = _prepared(tmp_path, config=config)
    candidates = pipeline.detect_events(prepared, legacy)
    assert not candidates.empty
    assert set(candidates["product_group"]) == {"YOUTUBE + DISPLAY"}


GATES = {
    "require_statistical_significance": True,
    "p_value_threshold": 0.05,
    "require_logical_direction": True,
    "require_model_fit": False,
    "r_squared_threshold": 0.3,
}
SIGNIFICANT = {"p_value": 0.01, "investment_change_pct": 50.0, "absolute_lift": 10.0, "model_r_squared": 0.5}


def test_a_failed_placebo_is_a_gate_reason_and_a_skipped_one_is_not():
    assert pipeline._gate_reasons({**SIGNIFICANT, "placebo_p_value": 0.01}, GATES) == ["placebo_failed"]
    assert pipeline._gate_reasons({**SIGNIFICANT, "placebo_p_value": 0.5}, GATES) == []
    assert pipeline._gate_reasons({**SIGNIFICANT, "placebo_p_value": None}, GATES) == []


def _passing(event_id, group="YOUTUBE"):
    return pipeline.EventOutcome(event_id, group, "2024-10-28", {"oos_wmape": 0.1}, passed=True, selected=True)


def test_an_insufficient_run_demotes_the_passing_events_as_new_outcomes(synthetic_prepared):
    good = _passing("e1")
    bad = pipeline.EventOutcome("e2", "YOUTUBE", "2024-10-28", {"oos_wmape": 0.1}, reasons=["not_significant"])
    limits = {
        "spend_cv_min": 0.99,
        "oos_wmape_max": 0.3,
        "oos_skill_min": 0.1,
    }  # YOUTUBE varies ~0.3 on the short synthetic

    events, verdict = pipeline.judge_sufficiency(synthetic_prepared, [good, bad], {"cv_out_of_sample": True}, limits)

    assert verdict.passed is False and verdict.reasons == ["low_spend_variation"]
    assert events[0].reasons == ["insufficient_run"] and not events[0].passed and not events[0].selected
    assert events[1] is bad
    assert good.passed and good.selected and good.reasons == []  # the analysed outcome is untouched


def test_an_in_sample_cv_fails_the_run_but_keeps_the_events(synthetic_prepared):
    good = _passing("e1")
    limits = {"spend_cv_min": 0.1, "oos_wmape_max": 0.3, "oos_skill_min": 0.1}

    events, verdict = pipeline.judge_sufficiency(synthetic_prepared, [good], {"cv_out_of_sample": False}, limits)

    assert verdict.reasons == ["cv_in_sample"] and events == [good]


def test_compute_judges_the_sufficiency(synthetic_computed):
    verdict = synthetic_computed.sufficiency
    assert verdict is not None and verdict.validated_events == sum(e.passed for e in synthetic_computed.events)


def test_a_lift_significant_only_with_the_media_features_is_model_dependent():
    robust = {"robust_p_value": 0.01, "robust_lift": 8.0}
    assert pipeline._gate_reasons({**SIGNIFICANT, **robust}, GATES) == []
    assert pipeline._gate_reasons({**SIGNIFICANT, **robust, "robust_p_value": 0.4}, GATES) == ["model_dependent"]
    assert pipeline._gate_reasons({**SIGNIFICANT, **robust, "robust_lift": -8.0}, GATES) == ["model_dependent"]
    not_significant = {**SIGNIFICANT, "p_value": 0.4, "robust_p_value": 0.4, "robust_lift": 1.0}
    assert "model_dependent" not in pipeline._gate_reasons(not_significant, GATES)


def test_the_spend_variation_is_measured_before_the_adstock(synthetic_prepared):
    smoothed = synthetic_prepared.investment_df.assign(investment=1.0)  # what the adstock can flatten a channel to
    prepared = dataclasses.replace(synthetic_prepared, investment_df=smoothed)
    limits = {"spend_cv_min": 0.1, "oos_wmape_max": 0.3, "oos_skill_min": 0.1}

    _, verdict = pipeline.judge_sufficiency(prepared, [_passing("e1")], {"cv_out_of_sample": True}, limits)

    assert verdict.spend_variation["YOUTUBE"] > 0.1 and verdict.reasons == []


def test_the_extra_a6_fits_run_only_for_events_the_primary_gates_kept(synthetic_computed):
    later = {"placebo_failed", "model_dependent", "insufficient_run"}  # reasons decided by or after those fits
    analysed = [e for e in synthetic_computed.events if e.results_data]
    kept = [e for e in analysed if not set(e.reasons) - later]

    assert kept  # the rejected side (no extra fits) is checked in test_gates_record_their_reasons
    for event in analysed:
        diagnosed = {"placebo_p_value", "oos_wmape", "robust_p_value"} <= event.results_data.keys()
        assert diagnosed == (event in kept), event.event_id


def test_the_pre_period_looks_back_at_most_a_year_of_rows(tmp_path):
    _, prepared, legacy = _prepared(tmp_path, n_days=730)
    candidates = pipeline.detect_events(prepared, legacy)
    dates = prepared.kpi_df["Date"].sort_values().reset_index(drop=True)

    rows_before = [
        int(((dates >= row.start_date) & (dates < row.intervention_date)).sum()) for row in candidates.itertuples()
    ]

    assert max(rows_before) == pipeline.PRE_PERIOD_MAX_ROWS
    assert min(rows_before) < pipeline.PRE_PERIOD_MAX_ROWS  # early events still start at the first date
