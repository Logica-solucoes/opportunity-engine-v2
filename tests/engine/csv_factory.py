"""Minimal input CSVs for the validation tests."""

from pathlib import Path

import pandas as pd

from engine.config import EngineConfig
from tests.engine.synthetic_data import dataset_config


def legacy_config() -> dict:
    """What the engine reads from a config: the prototype's keys, defaults included."""
    return EngineConfig.from_input(dataset_config()).to_legacy_dict()


def days(n: int, start: str = "2024-01-02") -> list[str]:
    return [d.strftime("%Y-%m-%d") for d in pd.date_range(start, periods=n, freq="D")]


def write_inputs(
    tmp_path: Path,
    investment: list[tuple],
    kpi: list[tuple],
    *,
    trends: list[tuple] | None = None,
    sep: str = ",",
    inv_header: tuple = ("dates", "product_group", "total_revenue"),
    kpi_header: tuple = ("date", "Sessions"),
    trends_columns: dict[str, list] | None = None,
) -> dict[str, Path | None]:
    """Rows are written verbatim: `investment` as (date, channel, value), `kpi` as (date, value, *extra columns).

    Extra columns need a matching `kpi_header`.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)

    def write(name: str, header: tuple, rows: list[tuple]) -> Path:
        path = tmp_path / name
        lines = [sep.join(header)] + [sep.join(str(v) for v in row) for row in rows]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    paths: dict[str, Path | None] = {
        "investment_file": write("investment.csv", inv_header, investment),
        "performance_file": write("performance.csv", kpi_header, kpi),
        "generic_trends_file": None,
    }
    if trends is not None:
        extra = trends_columns or {}
        rows = [(*row, *(values[i] for values in extra.values())) for i, row in enumerate(trends)]
        paths["generic_trends_file"] = write("trends.csv", ("Day", "Ad Opportunities", *extra), rows)
    return paths


def clean_rows(n: int = 10, channels: tuple[str, ...] = ("SEARCH", "SOCIAL")) -> tuple[list[tuple], list[tuple]]:
    ds = days(n)
    investment = [(d, c, 100 + i * 3 + j * 50) for j, c in enumerate(channels) for i, d in enumerate(ds)]
    kpi = [(d, 1000 + i * 7) for i, d in enumerate(ds)]
    return investment, kpi


def correlated_rows(n: int = 60, noise: float = 0.02) -> tuple[list[tuple], list[tuple]]:
    """Channels A and B move together (r above 0.95), C is independent. Rows for `write_inputs`."""
    import numpy as np

    rng = np.random.default_rng(3)
    ds = days(n)
    a = rng.normal(1000, 200, n).clip(min=100)
    b = a * (1 + rng.normal(0, noise, n))
    c = rng.normal(500, 80, n).clip(min=50)
    investment = [
        (d, name, round(float(v), 2)) for name, series in (("A", a), ("B", b), ("C", c)) for d, v in zip(ds, series)
    ]
    kpi = [(d, round(float(5000 + 3 * x + 2 * y + rng.normal(0, 50)), 2)) for d, x, y in zip(ds, a, c)]
    return investment, kpi


def with_twin(paths: dict, source: str = "SEARCH", twin: str = "SEARCH2", noise: float = 0.002) -> dict:
    """Adds a channel that follows `source` to the investment file written by make_dataset."""
    import numpy as np

    path = paths["investment_file"]
    frame = pd.read_csv(path)
    rng = np.random.default_rng(5)
    copy = frame[frame["product_group"] == source].copy()
    copy["product_group"] = twin
    copy["total_revenue"] = copy["total_revenue"] * (1 + rng.normal(0, noise, len(copy)))
    pd.concat([frame, copy]).sort_values(["dates", "product_group"]).to_csv(path, index=False)
    return paths
