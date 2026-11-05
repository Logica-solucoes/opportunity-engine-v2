import numpy as np
import pandas as pd
import pytest
from threadpoolctl import threadpool_limits

import engine
from engine.config import EngineConfig
from engine.errors import EngineError
from engine.validation import MIN_COLLINEARITY_PERIODS, channel_vif, collinearity, spend_matrix, validate
from tests.engine.csv_factory import days, write_inputs
from tests.engine.synthetic_data import dataset_config, make_dataset


def collinear_inputs(tmp_path, n_days=364):
    """The synthetic dataset with PMAX spend = 0.8 × SEARCH (r ≈ 0.99): one pair over the 0.85 gate.

    0.8 keeps the totals apart, so dv360_cm360_overlap (same total) does not fire.
    """
    paths = make_dataset(tmp_path, n_days=n_days)
    inv = pd.read_csv(paths["investment_file"])
    search = inv.loc[inv["product_group"] == "SEARCH", "total_revenue"].to_numpy()
    noise = np.random.default_rng(3).lognormal(0.0, 0.005, len(search))
    inv.loc[inv["product_group"] == "PMAX", "total_revenue"] = 0.8 * search * noise
    inv.to_csv(paths["investment_file"], index=False)
    return paths


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
    config = {**dataset_config(), "channel_groups": [["SEARCH", "YOUTUBE"]]}

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
    assert elasticity["status"] == "ok", elasticity["reasons"]
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
