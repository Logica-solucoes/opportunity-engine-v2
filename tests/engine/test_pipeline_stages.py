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
