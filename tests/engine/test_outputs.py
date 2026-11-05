from types import SimpleNamespace

import pandas as pd

from engine import outputs


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
