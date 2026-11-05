from engine import pipeline
from engine.config import EngineConfig
from tests.engine.synthetic_data import dataset_config, make_dataset

SHORT = 364  # one year: keeps the stage tests fast while still holding the YOUTUBE spike


def _prepared(tmp_path, *, config=None, **dataset):
    files = make_dataset(tmp_path, n_days=SHORT, **dataset)
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
    _, prepared, legacy = _prepared(tmp_path, config={"max_events_to_analyze": 1})
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
