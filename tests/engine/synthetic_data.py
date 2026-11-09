"""Deterministic synthetic media dataset used by the parity snapshot and the engine tests.

KPI = level + weekly seasonality + saturating, carried-over response to each channel's spend + noise.
"""

from pathlib import Path

import numpy as np
import pandas as pd

CHANNELS = {  # name -> (daily spend level, response weight)
    "SEARCH": (1000.0, 2500.0),
    "PMAX": (800.0, 1800.0),
    "YOUTUBE": (500.0, 1200.0),
    "DISPLAY": (300.0, 400.0),
    "SOCIAL": (400.0, 700.0),
}
START = "2024-01-02"  # a Tuesday: weeks run Monday to Sunday, so the first (partial) detection week is dropped
DAYS = 728  # whole weeks
SPIKES = {
    "YOUTUBE": (300, 21, 2.5),
    "PMAX": (520, 21, 0.35),
}  # channel -> (first day, length in days, spend multiplier)


def make_dataset(
    out_dir: Path,
    *,
    seed: int = 7,
    cadence_days: int = 1,
    with_trends: bool = True,
    flat_spend: bool = False,
    n_days: int = DAYS,
) -> dict[str, Path | None]:
    rng = np.random.default_rng(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    days = pd.date_range(START, periods=n_days, freq="D")

    spend = {}
    for name, (level, _) in CHANNELS.items():
        series = level * rng.lognormal(0.0, 0.03, n_days)
        if not flat_spend and name in SPIKES:
            first, length, mult = SPIKES[name]
            series[first : first + length] *= mult
        spend[name] = series

    weekday = days.dayofweek.to_numpy()
    kpi = 5000.0 * np.where(weekday >= 5, 0.85, 1.0)
    for name, (_, weight) in CHANNELS.items():
        carried = np.zeros(n_days)
        for t in range(n_days):
            carried[t] = spend[name][t] + (0.5 * carried[t - 1] if t else 0.0)
        kpi += weight * carried / (carried + 2.0 * CHANNELS[name][0])
    kpi *= rng.lognormal(0.0, 0.03, n_days)
    trends = 50 + 10 * np.sin(np.arange(n_days) / 30.0) + rng.normal(0, 2, n_days)

    frame = pd.DataFrame({"date": days, "Sessions": kpi, "Ad Opportunities": trends})
    investment = pd.DataFrame(
        {"dates": np.tile(days, len(CHANNELS)), "product_group": np.repeat(list(CHANNELS), n_days)}
    )
    investment["total_revenue"] = np.concatenate([spend[name] for name in CHANNELS])

    if cadence_days == 7:
        block = (np.arange(n_days) // 7) * 7
        label = pd.Series(pd.Timestamp(START) + pd.to_timedelta(block, unit="D"), name="date")
        frame = frame.groupby(label.to_numpy()).agg({"Sessions": "sum", "Ad Opportunities": "mean"})
        frame = frame.rename_axis("date").reset_index()
        inv_label = np.tile(label.to_numpy(), len(CHANNELS))
        investment = investment.assign(dates=inv_label)
        investment = investment.groupby(["dates", "product_group"], as_index=False)["total_revenue"].sum()
    elif cadence_days != 1:
        raise ValueError("cadence_days must be 1 or 7")

    paths: dict[str, Path | None] = {
        "investment_file": out_dir / "investment.csv",
        "performance_file": out_dir / "performance.csv",
        "generic_trends_file": None,
    }
    investment.sort_values(["dates", "product_group"]).to_csv(
        paths["investment_file"], index=False, date_format="%Y-%m-%d"
    )
    frame[["date", "Sessions"]].to_csv(paths["performance_file"], index=False, date_format="%Y-%m-%d")
    if with_trends:
        paths["generic_trends_file"] = out_dir / "trends.csv"
        frame[["date", "Ad Opportunities"]].rename(columns={"date": "Day"}).to_csv(
            paths["generic_trends_file"], index=False, date_format="%Y-%m-%d"
        )
    return paths


def dataset_config() -> dict:
    """Engine config (prototype key names) matching the columns written by make_dataset."""
    return {
        "advertiser_name": "synthetic",
        "optimization_target": "CONVERSIONS",
        "kpi_is_monetary": False,
        "average_ticket": 100,
        "conversion_rate_from_kpi_to_bo": 0.05,
        "financial_targets": {"target_cpa": 25.0, "target_icpa": 30.0, "target_roas": 4.0, "target_iroas": 2.0},
        "investment_limit_factor": 1.5,
        "p_value_threshold": 0.1,
        "r_squared_threshold": 0.3,
        "min_pre_period_days": 14,
        "require_statistical_significance": True,
        "require_logical_direction": True,
        "require_model_fit": False,  # the local-level model's in-sample R2 is negative on this data; keep events passing
        "increase_threshold_percent": 50,
        "decrease_threshold_percent": 30,
        "post_event_days": 14,
        "max_events_to_analyze": 5,
        "treat_outliers": False,
        "column_mapping": {
            "investment_file": {"date_col": "dates", "channel_col": "product_group", "investment_col": "total_revenue"},
            "performance_file": {"date_col": "date", "kpi_col": "Sessions"},
            "generic_trends_file": {"date_col": "Day", "trends_col": "Ad Opportunities"},
        },
    }


def make_identifiable_dataset(out_dir: Path, n_days: int = 364, seed: int = 7) -> dict[str, Path | None]:
    """Two channels with widely varying spend: STRONG drives the KPI, NOEFFECT does not (A5 acceptance).

    Not "NULL" as a name: pandas reads it as a missing value.
    """
    rng = np.random.default_rng(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    days = pd.date_range(START, periods=n_days, freq="D")
    strong = 1000 * rng.lognormal(0, 0.5, n_days)
    noeffect = 800 * rng.lognormal(0, 0.5, n_days)
    carried = np.zeros(n_days)
    for t in range(n_days):
        carried[t] = strong[t] + (0.5 * carried[t - 1] if t else 0.0)
    kpi = (5000 + 3000 * carried / (carried + 2000)) * rng.lognormal(0, 0.03, n_days)

    paths: dict[str, Path | None] = {
        "investment_file": out_dir / "investment.csv",
        "performance_file": out_dir / "performance.csv",
        "generic_trends_file": None,
    }
    investment = pd.DataFrame(
        {
            "dates": np.tile(days, 2),
            "product_group": np.repeat(["STRONG", "NOEFFECT"], n_days),
            "total_revenue": np.concatenate([strong, noeffect]),
        }
    )
    investment.to_csv(paths["investment_file"], index=False, date_format="%Y-%m-%d")
    pd.DataFrame({"date": days, "Sessions": kpi}).to_csv(paths["performance_file"], index=False, date_format="%Y-%m-%d")
    return paths


def identifiable_config() -> dict:
    """dataset_config without the trends file, which make_identifiable_dataset does not write."""
    config = dataset_config()
    config["column_mapping"] = {k: v for k, v in config["column_mapping"].items() if k != "generic_trends_file"}
    return config


def collinear_inputs(out_dir: Path, *, n_days: int = 364, cadence_days: int = 1) -> dict[str, Path | None]:
    """make_dataset with PMAX spend = 0.8 × SEARCH (r ≈ 0.99): one pair over the 0.85 gate.

    0.8 keeps the totals apart, so dv360_cm360_overlap (same total) does not fire.
    """
    paths = make_dataset(out_dir, n_days=n_days, cadence_days=cadence_days)
    inv = pd.read_csv(paths["investment_file"])
    search = inv.loc[inv["product_group"] == "SEARCH", "total_revenue"].to_numpy()
    noise = np.random.default_rng(3).lognormal(0.0, 0.005, len(search))
    inv.loc[inv["product_group"] == "PMAX", "total_revenue"] = 0.8 * search * noise
    inv.to_csv(paths["investment_file"], index=False)
    return paths
