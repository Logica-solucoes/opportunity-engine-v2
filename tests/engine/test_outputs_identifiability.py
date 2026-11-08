"""A5: SATURATION_CURVE.md and the scenarios speak only of the published channels."""

import dataclasses

from engine import outputs


def _hide(computed, hidden: set[str]):
    verdicts = {
        name: {
            "ci": (1.0, 2.0),
            "identifiable": name not in hidden,
            "reasons": ["coef_ci_includes_zero"] if name in hidden else [],
        }
        for name in computed.mmm["spend_cols"]
    }
    # the synthetic MMM's CV R2 is ~0: lower the reallocation bar so only the hidden channels decide
    config = {**computed.effective_config, "reallocation_min_cv_r2": -1.0}
    return dataclasses.replace(computed, identifiability=verdicts, effective_config=config)


def test_the_saturation_markdown_never_names_a_hidden_channel(synthetic_computed, tmp_path):
    spend_cols = list(synthetic_computed.mmm["spend_cols"])

    written = outputs.write_legacy_outputs(_hide(synthetic_computed, set(spend_cols[1:])), tmp_path)

    markdown = (written.global_dir / "SATURATION_CURVE.md").read_text(encoding="utf-8")
    assert spend_cols[0] in markdown
    for name in spend_cols[1:]:
        assert name not in markdown


def test_the_reallocation_is_left_out_while_a_channel_is_hidden(synthetic_computed, tmp_path):
    last = synthetic_computed.mmm["spend_cols"][-1]

    plain = outputs.write_legacy_outputs(_hide(synthetic_computed, set()), tmp_path / "plain")
    hidden = outputs.write_legacy_outputs(_hide(synthetic_computed, {last}), tmp_path / "hidden")

    assert plain.kpi_projections["reallocation"] is not None
    assert hidden.kpi_projections["reallocation"] is None
