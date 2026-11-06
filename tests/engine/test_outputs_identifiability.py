"""A5: the scenarios, SATURATION_CURVE.md and the global LLM prompt speak only of the published channels."""

import dataclasses
import json

from engine import outputs
from engine.identifiability import UNIDENTIFIED_KEY
from tests.fakes.llm import GLOBAL_NARRATIVE, FakeLLM


def _assessed(computed, identifiable: set[str]):
    verdicts = {
        name: {
            "identifiable": name in identifiable,
            "reasons": [] if name in identifiable else ["ci_crosses_zero"],
            "coef_ci": (0.0, 1.0),
            "point": 1.0,
        }
        for name in computed.mmm["spend_cols"]
    }
    return dataclasses.replace(computed, identifiability=verdicts)


def _only_global(written):
    return dataclasses.replace(written, event_dirs={})


def test_scenario_splits_pool_the_hidden_channels_and_keep_their_totals(synthetic_computed, tmp_path):
    spend_cols = list(synthetic_computed.mmm["spend_cols"])
    keep, hidden = spend_cols[0], spend_cols[1:]
    plain = outputs.write_legacy_outputs(dataclasses.replace(synthetic_computed, identifiability=None), tmp_path / "a")
    filtered = outputs.write_legacy_outputs(_assessed(synthetic_computed, {keep}), tmp_path / "b")
    assert plain.scenarios and len(plain.scenarios) == len(filtered.scenarios)
    for before, after in zip(plain.scenarios, filtered.scenarios, strict=True):
        for label, split in after["splits"].items():
            assert set(split) == {keep, UNIDENTIFIED_KEY} and not set(hidden) & set(split)
            assert sum(split.values()) == __import__("pytest").approx(sum(before["splits"][label].values()))


def test_saturation_markdown_and_global_prompt_never_name_a_hidden_channel(synthetic_computed, tmp_path):
    spend_cols = list(synthetic_computed.mmm["spend_cols"])
    computed = _assessed(synthetic_computed, {spend_cols[0]})
    written = outputs.write_legacy_outputs(computed, tmp_path)
    markdown = (written.global_dir / "SATURATION_CURVE.md").read_text(encoding="utf-8")
    llm = FakeLLM([json.dumps(GLOBAL_NARRATIVE)])
    outputs.generate_reports(computed, _only_global(written), llm)
    assert len(llm.calls) == 1
    for name in spend_cols[1:]:
        assert name not in markdown and name not in llm.calls[0]
    assert spend_cols[0] in markdown


def test_without_identifiability_the_payload_is_unchanged(synthetic_computed, tmp_path):
    computed = dataclasses.replace(synthetic_computed, identifiability=None)
    written = outputs.write_legacy_outputs(computed, tmp_path)
    markdown = (written.global_dir / "SATURATION_CURVE.md").read_text(encoding="utf-8")
    assert all(name in markdown for name in computed.mmm["spend_cols"]) and UNIDENTIFIED_KEY not in markdown
