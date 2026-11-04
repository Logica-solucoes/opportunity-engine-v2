import pandas as pd

from tests.engine.synthetic_data import dataset_config, make_dataset


def _event_weeks(investment_file) -> int:
    """Weeks where a channel's spend leaves the 12-week-average band the engine uses (>1.5x or <0.7x)."""
    df = pd.read_csv(investment_file, parse_dates=["dates"])
    flagged = 0
    for _, g in df.groupby("product_group"):
        weekly = g.groupby(g["dates"].dt.to_period("W-MON").dt.start_time)["total_revenue"].sum()
        ratio = weekly / weekly.rolling(12, min_periods=1).mean().shift(1)
        flagged += int(((ratio > 1.5) | (ratio < 0.7)).sum())
    return flagged


def test_dataset_is_deterministic(tmp_path):
    a = make_dataset(tmp_path / "a")
    b = make_dataset(tmp_path / "b")
    for key in ("investment_file", "performance_file", "generic_trends_file"):
        assert a[key].read_bytes() == b[key].read_bytes()


def test_dataset_has_detectable_events(tmp_path):
    files = make_dataset(tmp_path)
    df = pd.read_csv(files["investment_file"])
    assert df["product_group"].nunique() >= 5
    assert df["dates"].nunique() == 728
    assert _event_weeks(files["investment_file"]) >= 2


def test_flat_spend_has_no_events(tmp_path):
    files = make_dataset(tmp_path, flat_spend=True)
    assert _event_weeks(files["investment_file"]) == 0


def test_weekly_cadence(tmp_path):
    files = make_dataset(tmp_path, cadence_days=7)
    for key, col in (("investment_file", "dates"), ("performance_file", "date"), ("generic_trends_file", "Day")):
        dates = pd.to_datetime(pd.read_csv(files[key])[col]).drop_duplicates().sort_values()
        assert set(dates.diff().dropna().dt.days) == {7}


def test_without_trends(tmp_path):
    files = make_dataset(tmp_path, with_trends=False)
    assert files["generic_trends_file"] is None


def test_config_uses_the_dataset_columns():
    cfg = dataset_config()
    assert cfg["column_mapping"]["investment_file"] == {
        "date_col": "dates",
        "channel_col": "product_group",
        "investment_col": "total_revenue",
    }
    assert cfg["column_mapping"]["performance_file"] == {"date_col": "date", "kpi_col": "Sessions"}
    assert cfg["investment_limit_factor"] == 1.5
