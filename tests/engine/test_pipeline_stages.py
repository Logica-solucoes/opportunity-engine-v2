import pytest

from engine import pipeline
from engine.config import EngineConfig
from tests.engine.synthetic_data import DAYS, dataset_config, make_dataset

SHORT = 364  # one year: keeps the stage tests fast while still holding the YOUTUBE spike


def _prepared(tmp_path, *, config=None, n_days=SHORT, **dataset):
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


def test_selected_is_capped_by_max_events_to_analyze(tmp_path):
    # the full-length history: with the placebo gate (A6) the one-year slice keeps a single event
    _, prepared, legacy = _prepared(tmp_path, config={"max_events_to_analyze": 1}, n_days=DAYS)
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
    assert list(frame.columns) == ["Channel", "Channel_Spend", "Projected_Total_KPIs", "Historical_Avg", "Recommended"]


# --- A4: causal controls ---------------------------------------------------------------------------------------


def _with_columns(path, columns: dict):
    import pandas as pd

    frame = pd.read_csv(path)
    for name, values in columns.items():
        frame[name] = values
    frame.to_csv(path, index=False)


def test_ad_driven_performance_columns_do_not_change_the_causal_result(tmp_path):
    import numpy as np

    from tests.fixtures.parity.generate_legacy_snapshot import jsonable

    results = []
    for name, extra in (("plain", False), ("with_clicks", True)):
        files = make_dataset(tmp_path / name, n_days=SHORT)
        if extra:
            import pandas as pd

            rng = np.random.default_rng(3)
            sessions = pd.read_csv(files["performance_file"])["Sessions"].to_numpy()
            # ad-driven and tightly tied to the KPI: the old model would have picked them
            _with_columns(
                files["performance_file"],
                {
                    col: sessions * k + rng.normal(0, 5, SHORT)
                    for col, k in (("Clicks", 3), ("Impressions", 40), ("Leads", 0.1))
                },
            )
        cfg = EngineConfig.from_input(dataset_config())
        prepared = pipeline.load_inputs(files, cfg)
        legacy = {**cfg.to_legacy_dict(), "period_days": prepared.period_days}
        events = pipeline.analyze_events(prepared, pipeline.detect_events(prepared, legacy), legacy)
        results.append([jsonable(e.results_data) for e in events])
    assert results[0] and results[0] == results[1]


def test_a_rejected_control_is_reported_and_does_not_fail_the_event(tmp_path):
    import pandas as pd

    files = make_dataset(tmp_path, n_days=SHORT)
    investment = pd.read_csv(files["investment_file"])
    youtube = investment[investment["product_group"] == "YOUTUBE"].set_index("dates")["total_revenue"]
    dates = pd.read_csv(files["generic_trends_file"])["Day"]
    _with_columns(files["generic_trends_file"], {"Like_YT": youtube.reindex(dates).to_numpy() * 1.01})
    cfg = EngineConfig.from_input({**dataset_config(), "controls": ["Like_YT"]})
    prepared = pipeline.load_inputs(files, cfg)
    legacy = {**cfg.to_legacy_dict(), "period_days": prepared.period_days}
    events = pipeline.analyze_events(prepared, pipeline.detect_events(prepared, legacy), legacy)
    youtube_events = [e for e in events if e.product_group == "YOUTUBE" and e.results_data]
    assert youtube_events
    for event in youtube_events:
        assert [c["name"] for c in event.results_data["controls_rejected"]] == ["Like_YT"]
        assert not any("control" in reason for reason in event.reasons)
    assert any(e.passed for e in youtube_events)


# --- A5: identifiability ---------------------------------------------------------------------------------------


def test_compute_assesses_every_channel_and_keeps_the_bootstrap_matrix(tmp_path):
    files = make_dataset(tmp_path, n_days=SHORT)
    computed = pipeline.compute(files, EngineConfig.from_input(dataset_config()))
    columns = computed.mmm["spend_cols"]
    assert set(computed.identifiability) == set(columns)
    assert computed.mmm["bootstrap_coefs"].shape == (200, len(columns))
    assert all({"identifiable", "reasons", "coef_ci", "point"} <= set(v) for v in computed.identifiability.values())


def _gate_results(**over):
    base = {"p_value": 0.01, "investment_change_pct": 50.0, "absolute_lift": 10.0, "model_r_squared": 0.9}
    return {**base, **over}


def _gate_cfg():
    from tests.engine.helpers import full_config

    return full_config({})


def test_a_failed_placebo_adds_placebo_failed():
    from engine.pipeline import _gate_reasons

    cfg = _gate_cfg()
    assert _gate_reasons(_gate_results(placebo_ran=True, placebo_p_value=0.01, placebo_passed=False), cfg) == [
        "placebo_failed"
    ]
    assert _gate_reasons(_gate_results(placebo_ran=True, placebo_p_value=0.6, placebo_passed=True), cfg) == []


def test_a_placebo_that_did_not_run_does_not_reject():
    from engine.pipeline import _gate_reasons

    cfg = _gate_cfg()
    assert _gate_reasons(_gate_results(placebo_ran=False, placebo_p_value=None, placebo_passed=None), cfg) == []
    assert _gate_reasons(_gate_results(), cfg) == []  # results without the keys (older callers)


# --- A6: judging the run ---


def _outcome(group="A", *, passed=True, selected=True, wmape=0.1, reasons=None):
    from engine.pipeline import EventOutcome

    data = {"absolute_lift": 10.0, "oos_wmape": wmape}
    return EventOutcome(
        f"E_{group}", group, "2025-01-10", data, passed=passed, selected=selected, reasons=reasons or []
    )


def _investment(**channels):
    import numpy as np
    import pandas as pd

    days = pd.date_range("2025-01-01", periods=60)
    rows = [
        {"Date": d, "Product Group": name, "investment": v}
        for name, series in channels.items()
        for d, v in zip(days, series, strict=True)
    ]
    return pd.DataFrame(rows).assign(
        investment=lambda df: df["investment"].astype(float)
    ) if rows else pd.DataFrame(), np


def _prepared_stub(**channels):
    from types import SimpleNamespace

    import numpy as np

    series = {
        name: np.tile([50.0, 150.0], 30) if flag == "varying" else np.full(60, 100.0) for name, flag in channels.items()
    }
    return SimpleNamespace(investment_df=_investment(**series)[0])


def test_a_sound_run_keeps_its_events():
    events = [_outcome("A", wmape=0.1), _outcome("B", wmape=0.2)]
    out = pipeline.judge_sufficiency(_prepared_stub(A="varying", B="varying"), events, {"cv_out_of_sample": True}, {})
    assert out.passed is True and out.validated_events == 2
    assert all(e.passed and e.selected and e.reasons == [] for e in events)


def test_an_insufficient_run_demotes_the_events_that_passed():
    events = [_outcome("A", wmape=0.6), _outcome("B", wmape=0.7), _outcome("A", passed=False, selected=False)]
    out = pipeline.judge_sufficiency(_prepared_stub(A="varying", B="varying"), events, {"cv_out_of_sample": True}, {})
    assert out.reasons == ["high_oos_wmape"] and out.pre_wmape == pytest.approx(0.65)
    assert [(e.passed, e.selected, e.reasons) for e in events[:2]] == [(False, False, ["insufficient_run"])] * 2
    assert events[2].reasons == []  # an event that already failed a gate keeps only its own reasons


def test_an_in_sample_cv_alone_keeps_the_events():
    events = [_outcome("A")]
    out = pipeline.judge_sufficiency(_prepared_stub(A="varying"), events, {"cv_out_of_sample": False}, {})
    assert out.reasons == ["cv_in_sample"] and events[0].passed and events[0].selected


def test_without_a_model_only_the_causal_parts_count():
    out = pipeline.judge_sufficiency(_prepared_stub(A="varying"), [_outcome("A")], None, {})
    assert out.passed is True and out.cv_out_of_sample is None


def test_failed_analyses_are_not_validated_events():
    from engine.pipeline import EventOutcome

    failed = EventOutcome("E_X", "A", "2025-01-10", None, reasons=["analysis_failed"])
    out = pipeline.judge_sufficiency(_prepared_stub(A="varying"), [failed], {"cv_out_of_sample": True}, {})
    assert out.reasons == ["no_validated_event"] and out.validated_events == 0


def test_the_thresholds_come_from_the_gate_thresholds_config():
    events = [_outcome("A", wmape=0.2)]
    cfg = {"gate_thresholds": {"oos_wmape_max": 0.1}}
    out = pipeline.judge_sufficiency(_prepared_stub(A="varying"), events, {"cv_out_of_sample": True}, cfg)
    assert out.reasons == ["high_oos_wmape"]


def test_a_lift_that_needs_the_media_features_is_model_dependent():
    from engine.pipeline import _gate_reasons

    cfg = _gate_cfg()
    assert _gate_reasons(_gate_results(robust_p_value=0.6, robust_passed=False), cfg) == ["model_dependent"]
    assert _gate_reasons(_gate_results(robust_p_value=0.01, robust_passed=True), cfg) == []
    assert _gate_reasons(_gate_results(robust_p_value=None, robust_passed=None), cfg) == []


def test_analyze_events_derives_robust_passed_from_both_p_values(tmp_path):
    _, prepared, legacy = _prepared(tmp_path, config={"p_value_threshold": 0.1})
    events = pipeline.analyze_events(prepared, pipeline.detect_events(prepared, legacy), legacy)
    for e in (e for e in events if e.results_data):
        data, thr = e.results_data, 0.1
        expected = (
            None if data["robust_p_value"] is None else not (data["p_value"] < thr and data["robust_p_value"] >= thr)
        )
        assert data["robust_passed"] is expected
