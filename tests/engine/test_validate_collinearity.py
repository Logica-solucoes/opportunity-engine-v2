import time

import numpy as np
import pytest

from engine.data_preprocessor import load_and_prepare_data
from engine.errors import EngineError
from engine.validation import validate
from tests.engine.csv_factory import correlated_rows, days, legacy_config, with_twin, write_inputs
from tests.engine.synthetic_data import dataset_config, make_dataset


def _config(**extra) -> dict:
    return {**dataset_config(), **extra}


def _by_id(report):
    return {c.id: c for c in report.checks}


def _correlated(tmp_path):
    return write_inputs(tmp_path, *correlated_rows())


def test_flagged_pair_blocks_with_suggestion(tmp_path):
    report = validate(_correlated(tmp_path), _config())
    check = _by_id(report)["collinearity_unresolved"]
    assert not report.ok and check.level == "error"
    assert check.details["suggested_groups"] == [["A", "B"]]
    assert report.collinearity.pairs[0]["a"] == "A" and report.collinearity.suggested_groups == [["A", "B"]]


def test_group_resolves_and_becomes_one_channel(tmp_path):
    report = validate(_correlated(tmp_path), _config(channel_groups=[["A", "B"]]))
    assert report.ok, report.checks
    assert report.channels == ["A + B", "C"] and report.collinearity.pairs == []


def test_block_per_channel_turns_error_into_warning(tmp_path):
    report = validate(_correlated(tmp_path), _config(block_per_channel=True))
    ids = _by_id(report)
    assert report.ok and ids["collinearity_blocked"].level == "warning" and "collinearity_unresolved" not in ids


def test_group_still_colliding_with_another_channel_stays_unresolved(tmp_path):
    investment, kpi = correlated_rows()
    rng = np.random.default_rng(9)
    a = {d: v for d, name, v in investment if name == "A"}
    investment += [(d, "D", round(v * (1 + rng.normal(0, 0.02)), 2)) for d, v in a.items()]
    report = validate(write_inputs(tmp_path, investment, kpi), _config(channel_groups=[["A", "B"]]))
    assert "collinearity_unresolved" in _by_id(report)


@pytest.mark.parametrize(
    ("groups", "check_id"),
    [
        ([["A", "X"]], "group_unknown_channel"),
        ([["A", "B"], ["B", "C"]], "group_overlap"),
        ([["A"]], "group_too_small"),
    ],
)
def test_group_errors_skip_the_gate_and_the_loader_agrees(tmp_path, groups, check_id):
    paths = _correlated(tmp_path)
    report = validate(paths, _config(channel_groups=groups))
    assert not report.ok and check_id in _by_id(report) and "collinearity_unresolved" not in _by_id(report)
    with pytest.raises(EngineError) as raised:
        load_and_prepare_data({**legacy_config(), "channel_groups": groups}, paths)
    assert raised.value.check_id == check_id


def test_group_names_are_matched_case_and_space_insensitively(tmp_path):
    assert validate(_correlated(tmp_path), _config(channel_groups=[[" a ", "b"]])).ok


def test_all_channels_in_one_group_leaves_a_single_channel(tmp_path):
    report = validate(_correlated(tmp_path), _config(channel_groups=[["A", "B", "C"]]))
    assert report.ok and report.channels == ["A + B + C"]


def test_thresholds_come_from_gate_thresholds(tmp_path):
    paths = _correlated(tmp_path)
    lenient = validate(paths, _config(gate_thresholds={"collinearity_r": 0.9999, "vif_max": 100000}))
    assert lenient.ok and "collinearity_unresolved" not in _by_id(lenient)


def test_weekly_cadence_groups_and_gates(tmp_path):
    paths = with_twin(make_dataset(tmp_path, cadence_days=7, n_days=728))
    assert "collinearity_unresolved" in _by_id(validate(paths, dataset_config()))
    assert validate(paths, _config(channel_groups=[["SEARCH", "SEARCH2"]])).ok


def test_loader_returns_grouped_investment(tmp_path):
    prepared = load_and_prepare_data({**legacy_config(), "channel_groups": [["A", "B"]]}, _correlated(tmp_path))
    assert set(prepared.investment_df["Product Group"]) == {"A + B", "C"}


def test_clean_dataset_has_no_collinearity_checks(tmp_path):
    report = validate(make_dataset(tmp_path, n_days=364), dataset_config())
    assert report.ok and not [c for c in report.checks if c.id.startswith(("collinearity", "group"))]
    assert report.collinearity.pairs == [] and report.collinearity.suggested_groups == []


def test_validate_stays_fast_with_collinearity(tmp_path):
    ds = days(730)
    rng = np.random.default_rng(2)
    investment = [(d, f"CH{j:02d}", round(float(rng.normal(500 + 10 * j, 60)), 2)) for j in range(15) for d in ds]
    kpi = [(d, round(float(1000 + rng.normal(0, 30)), 2)) for d in ds]
    paths = write_inputs(tmp_path, investment, kpi)
    start = time.perf_counter()
    validate(paths, _config(block_per_channel=True))
    assert time.perf_counter() - start < 10
