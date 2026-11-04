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
        paths["generic_trends_file"] = write("trends.csv", ("Day", "Ad Opportunities"), trends)
    return paths


def clean_rows(n: int = 10, channels: tuple[str, ...] = ("SEARCH", "SOCIAL")) -> tuple[list[tuple], list[tuple]]:
    ds = days(n)
    investment = [(d, c, 100 + i * 3 + j * 50) for j, c in enumerate(channels) for i, d in enumerate(ds)]
    kpi = [(d, 1000 + i * 7) for i, d in enumerate(ds)]
    return investment, kpi
