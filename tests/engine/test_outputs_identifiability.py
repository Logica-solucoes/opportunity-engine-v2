"""A5: SATURATION_CURVE.md and the global LLM prompt speak only of the published channels."""

import dataclasses
import json

from engine import outputs
from tests.fakes.llm import GLOBAL_NARRATIVE, FakeLLM


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


def _global_prompt(computed, out_dir):
    written = outputs.write_legacy_outputs(computed, out_dir)
    llm = FakeLLM([json.dumps(GLOBAL_NARRATIVE)])
    outputs.generate_reports(computed, dataclasses.replace(written, event_dirs={}), llm)  # only the global narrative
    assert len(llm.calls) == 1
    return written, llm.calls[0]


def test_the_saturation_markdown_and_the_global_prompt_never_name_a_hidden_channel(synthetic_computed, tmp_path):
    spend_cols = list(synthetic_computed.mmm["spend_cols"])

    written, prompt = _global_prompt(_hide(synthetic_computed, set(spend_cols[1:])), tmp_path)

    markdown = (written.global_dir / "SATURATION_CURVE.md").read_text(encoding="utf-8")
    assert spend_cols[0] in markdown
    for name in spend_cols[1:]:
        assert name not in markdown and name not in prompt


def test_the_reallocation_is_not_offered_to_the_llm_while_a_channel_is_hidden(synthetic_computed, tmp_path):
    last = synthetic_computed.mmm["spend_cols"][-1]

    plain, plain_prompt = _global_prompt(_hide(synthetic_computed, set()), tmp_path / "plain")
    hidden, hidden_prompt = _global_prompt(_hide(synthetic_computed, {last}), tmp_path / "hidden")

    assert plain.kpi_projections["reallocation"] is not None and "Realocação Estratégica" in plain_prompt
    assert hidden.kpi_projections["reallocation"] is None and "Realocação" not in hidden_prompt
