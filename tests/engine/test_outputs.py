from types import SimpleNamespace

import pandas as pd
import pytest

from engine import identifiability, outputs


def test_channel_and_advertiser_names_never_leave_out_dir(tmp_path, monkeypatch):
    for name in (
        "save_accuracy_plot",
        "save_line_chart_plot",
        "save_investment_bar_plot",
        "save_sessions_bar_plot",
        "save_causal_chart_data",
    ):
        monkeypatch.setattr(outputs.presentation, name, lambda *a, **k: None)
    monkeypatch.setattr(outputs.presentation, "create_presentation_dataframe", lambda *a: pd.DataFrame({"x": [1]}))
    computed = SimpleNamespace(effective_config={"advertiser_name": "../../adv", "performance_kpi_column": "kpi"})
    outcome = SimpleNamespace(
        event_id="e1",
        product_group="../../evil",
        intervention_date="2026-01-01",
        results_data={},
        accuracy_df=None,
        line_df=None,
        inv_bar_df=None,
        sessions_bar_df=None,
    )
    out_dir = tmp_path / "out"
    written = outputs.Written()

    outputs._write_event(computed, outcome, out_dir, written)

    assert written.event_dirs["e1"].resolve().is_relative_to(out_dir.resolve())
    assert [p.parent for p in tmp_path.rglob("*.csv")] == [written.event_dirs["e1"]]


def test_scenario_splits_fold_the_unidentified_channels():
    computed = SimpleNamespace(
        current_split={"A": 0.5, "B": 0.3, "C": 0.2},
        optimized_mix={"A": 0.6, "B": 0.2, "C": 0.2},
        identifiability={"A": {"identifiable": True}, "B": {"identifiable": False}, "C": {"identifiable": False}},
    )

    scenario = outputs._scenario("t", "d", {"Daily_Investment": 10.0}, 3.0, computed, {"A": 0.7, "B": 0.1, "C": 0.2})

    for split in scenario["splits"].values():
        assert set(split) == {"A", identifiability.UNIDENTIFIED}
        assert sum(split.values()) == pytest.approx(30.0)


def _verdicts(**identifiable):
    return {name: {"identifiable": ok} for name, ok in identifiable.items()}


def test_none_identifiable():
    assert identifiability.none_identifiable(_verdicts(A=False, B=False))
    assert not identifiability.none_identifiable(_verdicts(A=True, B=False))
    assert not identifiability.none_identifiable({})


@pytest.mark.parametrize(
    ("verdicts", "with_numbers"),
    [
        (_verdicts(A=False, B=False), ["Média Histórica"]),
        (_verdicts(A=True, B=False), ["Média Histórica", "Pico de Eficiência", "Modelo de Elasticidade"]),
    ],
)
def test_scenario_kpis_of_the_mixes_need_an_identifiable_channel(verdicts, with_numbers):
    computed = SimpleNamespace(
        current_split={"A": 0.5, "B": 0.5}, optimized_mix={"A": 0.6, "B": 0.4}, identifiability=verdicts
    )
    point = {
        "Daily_Investment": 10.0,
        "projected_kpis": {"Média Histórica": 1.0, "Pico de Eficiência": 2.0, "Modelo de Elasticidade": 3.0},
    }

    scenario = outputs._scenario("t", "d", point, 3.0, computed, {"A": 0.7, "B": 0.3})

    kpis = scenario["projected_kpis"]
    assert [k for k, v in kpis.items() if v is not None] == with_numbers
    assert set(kpis) == set(point["projected_kpis"])
