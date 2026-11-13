import numpy as np
import pandas as pd
import pytest
from threadpoolctl import threadpool_limits

import engine
from engine.config import EngineConfig
from engine.errors import EngineError
from engine.validation import MIN_COLLINEARITY_PERIODS, channel_vif, collinearity, high_vif, spend_matrix, validate
from tests.engine.csv_factory import days, write_inputs
from tests.engine.synthetic_data import collinear_inputs, dataset_config, make_dataset


def _frame(columns: dict[str, np.ndarray]) -> pd.DataFrame:
    """Long investment frame (Date, Product Group, investment), one spend array per channel."""
    n = len(next(iter(columns.values())))
    dates = pd.date_range("2024-01-02", periods=n, freq="D")
    return pd.concat(
        [pd.DataFrame({"Date": dates, "Product Group": name, "investment": values}) for name, values in columns.items()]
    )


def test_vif_matches_the_manual_regression():
    rng = np.random.default_rng(0)
    a, b = rng.normal(100, 10, 50), rng.normal(50, 5, 50)
    c = 0.5 * a + 0.5 * b + rng.normal(0, 3, 50)
    others = np.column_stack([np.ones(50), a, b])
    fitted = others @ np.linalg.lstsq(others, c, rcond=None)[0]
    r2 = 1 - ((c - fitted) ** 2).sum() / ((c - c.mean()) ** 2).sum()

    vif = channel_vif(pd.DataFrame({"A": a, "B": b, "C": c}))

    assert vif["C"] == pytest.approx(1 / (1 - r2), abs=1e-4)


def test_perfect_collinearity_is_a_none_vif_not_an_error():
    a = np.arange(40, dtype=float) % 7 + 1

    vif = channel_vif(pd.DataFrame({"A": a, "B": 2 * a, "C": np.random.default_rng(1).normal(10, 1, 40)}))

    assert vif["A"] is None and vif["B"] is None and vif["C"] is not None


def test_pairs_and_suggested_groups_come_from_the_spend_correlation(tmp_path):
    found = validate(collinear_inputs(tmp_path), dataset_config()).collinearity

    assert [(p["a"], p["b"]) for p in found.pairs] == [("PMAX", "SEARCH")]
    assert found.pairs[0]["r"] > 0.95
    assert found.suggested_groups == [["PMAX", "SEARCH"]]
    assert set(found.vif) == {"DISPLAY", "PMAX", "SEARCH", "SOCIAL", "YOUTUBE"}


def test_suggested_groups_are_the_connected_components():
    rng = np.random.default_rng(2)
    base, other = rng.normal(100, 10, 60), rng.normal(100, 10, 60)
    frame = _frame(
        {
            "A": base,
            "B": base * 1.1 + rng.normal(0, 1, 60),
            "C": base * 0.9 + rng.normal(0, 1, 60),
            "D": other,
        }
    )

    assert collinearity(spend_matrix(frame), EngineConfig()).suggested_groups == [["A", "B", "C"]]


def test_a_short_series_is_not_assessed(tmp_path):
    n = MIN_COLLINEARITY_PERIODS - 1
    channels = ("SEARCH", "SOCIAL")
    investment = [(d, c, 100 + i * 3 + j * 50) for j, c in enumerate(channels) for i, d in enumerate(days(n))]
    kpi = [(d, 1000 + i) for i, d in enumerate(days(n))]

    report = validate(write_inputs(tmp_path, investment, kpi), dataset_config())

    assert report.ok and report.collinearity.pairs == [] and report.collinearity.vif == {}
    check = next(c for c in report.checks if c.id == "collinearity_not_assessed")
    assert check.level == "info" and check.details == {"periods": n}


def test_a_collinear_pair_blocks_until_resolved(tmp_path):
    report = validate(collinear_inputs(tmp_path), dataset_config())

    check = next(c for c in report.checks if c.id == "collinearity_unresolved")
    assert not report.ok and check.level == "error"
    assert [(p["a"], p["b"]) for p in check.details["pairs"]] == [("PMAX", "SEARCH")]
    assert check.details["suggested_groups"] == [["PMAX", "SEARCH"]]
    assert "PMAX + SEARCH" in check.message


@pytest.mark.parametrize("resolution", [{"channel_groups": [["SEARCH", "PMAX"]]}, {"block_per_channel": True}])
def test_a_group_or_the_block_flag_resolves_the_gate(tmp_path, resolution):
    report = validate(collinear_inputs(tmp_path), {**dataset_config(), **resolution})

    assert report.ok, [c.id for c in report.checks if c.level == "error"]
    assert report.collinearity.pairs  # the report still shows the real collinearity


def test_a_group_that_misses_one_side_of_the_pair_does_not_resolve_it(tmp_path):
    config = {**dataset_config(), "channel_groups": [["YOUTUBE", "DISPLAY"]]}

    assert "collinearity_unresolved" in {c.id for c in validate(collinear_inputs(tmp_path), config).checks}


def test_a_group_naming_a_channel_not_in_the_file_is_an_error(tmp_path):
    config = {**dataset_config(), "channel_groups": [["SEARCH", "TIKTOK"]]}

    report = validate(make_dataset(tmp_path, n_days=364), config)

    check = next(c for c in report.checks if c.id == "channel_group_unknown")
    assert not report.ok and check.level == "error" and check.details == {"channels": ["TIKTOK"]}


@pytest.fixture
def no_llm(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "none")


def test_run_refuses_unresolved_collinearity_before_computing(tmp_path, no_llm):
    with pytest.raises(EngineError) as raised:
        engine.run(collinear_inputs(tmp_path / "data"), dataset_config(), tmp_path / "out", lambda level, msg: None)

    assert raised.value.check_id == "collinearity_unresolved"


def test_run_with_a_group_reports_only_the_group(tmp_path, no_llm):
    config = {**dataset_config(), "channel_groups": [["SEARCH", "PMAX"]]}

    with threadpool_limits(limits=1):
        result = engine.run(collinear_inputs(tmp_path / "data"), config, tmp_path / "out", lambda level, msg: None)

    elasticity = result["elasticity"]
    assert elasticity["status"] == "inconclusive" and elasticity["reasons"] == ["no_identifiable_channel"]
    names = {c["name"] for c in elasticity["channels"]}
    assert "SEARCH + PMAX" in names and not {"SEARCH", "PMAX"} & names
    assert elasticity["groups"] == [{"name": "SEARCH + PMAX", "members": ["SEARCH", "PMAX"]}]


def _weekly_with_partial_tail(tmp_path, weeks):
    rng = np.random.default_rng(4)
    dates = days(weeks * 7)[::7]
    a, b = rng.normal(100, 5, weeks), rng.normal(100, 5, weeks)
    investment = [(d, "A", x) for d, x in zip(dates, a)] + [(d, "B", x) for d, x in zip(dates, b)]
    partial = days(weeks * 7)[-4]
    investment += [(partial, "A", 1), (partial, "B", 1)]
    kpi = [(d, 1000 + i) for i, d in enumerate(dates)]
    return write_inputs(tmp_path, investment, kpi)


def test_a_partial_period_does_not_make_two_channels_collinear(tmp_path):
    report = validate(_weekly_with_partial_tail(tmp_path, 33), dataset_config())

    assert "partial_period_dropped" in {c.id for c in report.checks}
    assert report.ok, [c.id for c in report.checks if c.level == "error"]
    assert report.collinearity.pairs == []


def test_a_partial_period_does_not_count_toward_the_minimum(tmp_path):
    report = validate(_weekly_with_partial_tail(tmp_path, MIN_COLLINEARITY_PERIODS - 1), dataset_config())

    check = next(c for c in report.checks if c.id == "collinearity_not_assessed")
    assert check.details == {"periods": MIN_COLLINEARITY_PERIODS - 1}


def test_one_channel_has_nothing_to_assess(tmp_path):
    n = MIN_COLLINEARITY_PERIODS - 1
    investment = [(d, "SEARCH", 100 + i * 3) for i, d in enumerate(days(n))]
    kpi = [(d, 1000 + i) for i, d in enumerate(days(n))]

    report = validate(write_inputs(tmp_path, investment, kpi), dataset_config())

    assert "collinearity_not_assessed" not in {c.id for c in report.checks}


def _sum_of_a_pair_is_collinear_with_a_third(tmp_path, n=300):
    """A and B are mirror images around x (r ≈ 0.9), C is x plus noise: r(A, C) and r(B, C) < 0.85 < r(A + B, C)."""
    z = np.random.default_rng(5).normal(size=(n, 3))
    q, _ = np.linalg.qr(z - z.mean(axis=0))  # orthogonal columns: the correlations below are exact
    x, e, w = q.T * np.sqrt(n - 1) * 10
    a, b, c = 100 + x + e * np.sqrt(0.05), 100 + x - e * np.sqrt(0.05), 100 + x + w * np.sqrt(0.35)
    r = np.corrcoef([a, b, c, a + b])
    assert r[0, 1] > 0.85 and r[0, 2] < 0.85 and r[1, 2] < 0.85 and r[3, 2] > 0.85
    ds = days(n)
    investment = [(d, name, v) for name, series in (("A", a), ("B", b), ("C", c)) for d, v in zip(ds, series)]
    return write_inputs(tmp_path, investment, [(d, 1000 + i) for i, d in enumerate(ds)])


def test_a_group_that_ends_up_collinear_with_another_channel_is_still_open(tmp_path):
    paths = _sum_of_a_pair_is_collinear_with_a_third(tmp_path)
    assert [(p["a"], p["b"]) for p in validate(paths, dataset_config()).collinearity.pairs] == [("A", "B")]

    report = validate(paths, {**dataset_config(), "channel_groups": [["A", "B"]]})

    check = next(c for c in report.checks if c.id == "collinearity_unresolved")
    assert [(p["a"], p["b"]) for p in check.details["pairs"]] == [("A + B", "C")]
    assert check.details["suggested_groups"] == [["A", "B", "C"]]
    assert "A + B + C" in check.message
    assert [(p["a"], p["b"]) for p in report.collinearity.pairs] == [("A", "B")]


def _vif_only_inputs(tmp_path, n=60):
    """C = A + B: no pair is over 0.85 (r(A, C) ≈ 0.7), but C is almost an exact mix of the others (VIF in the thousands)."""
    rng = np.random.default_rng(6)
    a, b = rng.normal(1000, 200, n), rng.normal(1000, 200, n)
    c = a + b + rng.normal(0, 5, n)
    ds = days(n)
    investment = [
        (d, name, round(float(v), 2)) for name, series in (("A", a), ("B", b), ("C", c)) for d, v in zip(ds, series)
    ]
    return write_inputs(tmp_path, investment, [(d, 1000 + i) for i, d in enumerate(ds)])


def test_a_vif_over_the_limit_blocks_even_without_a_pair(tmp_path):
    report = validate(_vif_only_inputs(tmp_path), dataset_config())

    check = next(c for c in report.checks if c.id == "collinearity_unresolved")
    assert report.collinearity.pairs == [] and check.details["pairs"] == []
    assert check.details["vif_channels"] == ["A", "B", "C"]
    assert check.details["suggested_groups"] == [["A", "B", "C"]]
    assert report.collinearity.suggested_groups == [["A", "B", "C"]]
    assert "VIF acima de 10" in check.message


@pytest.mark.parametrize("resolution", [{"channel_groups": [["A", "B", "C"]]}, {"block_per_channel": True}])
def test_a_group_or_the_block_flag_resolves_the_vif_gate(tmp_path, resolution):
    report = validate(_vif_only_inputs(tmp_path), {**dataset_config(), **resolution})

    assert report.ok, [c.id for c in report.checks if c.level == "error"]


def test_the_vif_limit_comes_from_gate_thresholds(tmp_path):
    report = validate(_vif_only_inputs(tmp_path), {**dataset_config(), "gate_thresholds": {"vif_max": 1e9}})

    assert report.ok, [c.id for c in report.checks if c.level == "error"]


def test_an_undefined_vif_counts_as_over_the_limit():
    a = np.arange(40, dtype=float) % 7 + 1
    b = np.random.default_rng(1).normal(10, 1, 40)

    assert high_vif(spend_matrix(_frame({"A": a, "B": b, "C": a + b})), EngineConfig()) == ["A", "B", "C"]


def test_a_vif_only_channel_is_suggested_with_its_most_correlated_channel():
    rng = np.random.default_rng(1)
    a, b = rng.normal(100, 20, 300), rng.normal(100, 20, 300)
    frame = _frame({"A": a, "B": b, "C": a + b + rng.normal(0, 0.5, 300)})

    found = collinearity(spend_matrix(frame), EngineConfig(gate_thresholds={"collinearity_r": 0.95}))

    assert found.pairs == [] and any("C" in group for group in found.suggested_groups)


def test_an_overlap_pair_does_not_block_through_its_vif(tmp_path):
    rng = np.random.default_rng(8)
    x = rng.normal(1000, 200, 60)
    series = {"X": x, "Y": x * (1 + rng.normal(0, 0.01, 60)), "Z": rng.normal(500, 80, 60)}
    ds = days(60)
    investment = [(d, name, round(float(v), 2)) for name, s in series.items() for d, v in zip(ds, s)]

    report = validate(write_inputs(tmp_path, investment, [(d, 1000 + i) for i, d in enumerate(ds)]), dataset_config())

    ids = {c.id for c in report.checks}
    assert "dv360_cm360_overlap" in ids and "collinearity_unresolved" not in ids


def test_a_vif_only_channel_is_never_suggested_with_an_overlap_twin():
    rng = np.random.default_rng(2)
    c, d = rng.normal(100, 20, 300), rng.normal(100, 20, 300)
    a = c + d + rng.normal(0, 0.5, 300)
    frame = _frame({"A": a, "B": a * (1 + rng.normal(0, 0.001, 300)), "C": c, "D": d})

    found = collinearity(spend_matrix(frame), EngineConfig(), {frozenset({"A", "B"})})

    assert found.suggested_groups and not any({"A", "B"} <= set(group) for group in found.suggested_groups)


def test_unresolved_lists_the_channels_still_collinear_as_modelled(tmp_path):
    blocked = validate(collinear_inputs(tmp_path / "a"), {**dataset_config(), "block_per_channel": True})
    grouped = validate(collinear_inputs(tmp_path / "b"), {**dataset_config(), "channel_groups": [["SEARCH", "PMAX"]]})

    assert blocked.ok and blocked.collinearity.unresolved == ["PMAX", "SEARCH"]
    assert grouped.ok and grouped.collinearity.unresolved == []


def test_the_gate_works_on_weekly_data(tmp_path):
    paths = collinear_inputs(tmp_path, n_days=728, cadence_days=7)

    report = validate(paths, dataset_config())

    assert report.period_days == 7 and "collinearity_unresolved" in {c.id for c in report.checks}
    assert validate(paths, {**dataset_config(), "channel_groups": [["SEARCH", "PMAX"]]}).ok


def test_a_group_named_like_a_channel_already_in_the_file_is_an_error(tmp_path):
    ds = days(10)
    investment = [(d, name, 100 + i) for name in ("A", "B", "A + B") for i, d in enumerate(ds)]
    paths = write_inputs(tmp_path, investment, [(d, 1000 + i) for i, d in enumerate(ds)])

    report = validate(paths, {**dataset_config(), "channel_groups": [["A", "B"]]})

    check = next(c for c in report.checks if c.id == "channel_group_name_taken")
    assert not report.ok and check.level == "error" and check.details == {"channels": ["A + B"]}


def test_vif_of_many_channels_matches_statsmodels_and_is_fast():
    import time

    from statsmodels.stats.outliers_influence import variance_inflation_factor

    rng = np.random.default_rng(3)
    base = rng.normal(0, 1, (1000, 1))
    wide = pd.DataFrame(base + rng.normal(0, 1, (1000, 80)), columns=[f"C{i}" for i in range(80)])
    x = np.column_stack([np.ones(1000), wide.to_numpy()])
    expected = [variance_inflation_factor(x, i) for i in range(1, 81)]

    start = time.perf_counter()
    vif = channel_vif(wide)
    elapsed = time.perf_counter() - start

    assert [vif[c] for c in wide.columns] == pytest.approx(expected, abs=1e-4)
    assert elapsed < 0.2
