import numpy as np
import pandas as pd
import pytest

from engine.config import EngineConfig
from engine.validation import MIN_COLLINEARITY_PERIODS, channel_vif, collinearity, validate
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

    assert collinearity(frame, EngineConfig()).suggested_groups == [["A", "B", "C"]]


def test_a_short_series_is_not_assessed(tmp_path):
    n = MIN_COLLINEARITY_PERIODS - 1
    channels = ("SEARCH", "SOCIAL")
    investment = [(d, c, 100 + i * 3 + j * 50) for j, c in enumerate(channels) for i, d in enumerate(days(n))]
    kpi = [(d, 1000 + i) for i, d in enumerate(days(n))]

    report = validate(write_inputs(tmp_path, investment, kpi), dataset_config())

    assert report.ok and report.collinearity.pairs == [] and report.collinearity.vif == {}
    check = next(c for c in report.checks if c.id == "collinearity_not_assessed")
    assert check.level == "info" and check.details == {"periods": n}
