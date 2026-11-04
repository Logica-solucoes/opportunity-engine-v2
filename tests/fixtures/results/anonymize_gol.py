"""Anonymize the Gol example data before it becomes a versioned fixture.

Channels become CANAL_01..NN (alphabetical order of the real names, worked out at run time: no real name lives in
this file), investment and KPI are multiplied by two different private factors, dates and trends stay as they are.
The factors live in a git-ignored file; whoever regenerates the fixtures needs the same file.
"""

import json
import random
import shutil
from pathlib import Path

import pandas as pd

FACTORS_FILE = Path(__file__).resolve().parent / ".private" / "factors.json"


def load_factors(path: Path = FACTORS_FILE) -> dict[str, float]:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        rng = random.SystemRandom()
        path.write_text(
            json.dumps({"investment": round(rng.uniform(0.3, 3.0), 6), "kpi": round(rng.uniform(0.3, 3.0), 6)}),
            encoding="utf-8",
        )
    return json.loads(path.read_text(encoding="utf-8"))


def _read(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, encoding="utf-8-sig", keep_default_na=False)


def anonymize(files: dict[str, Path], mapping: dict, out_dir: Path, factors: dict[str, float]) -> tuple[dict, dict]:
    """Write anonymized copies of `files` into `out_dir`. Returns (new files, real->anonymous channel names)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    investment = _read(files["investment_file"])
    cols = mapping["investment_file"]
    names = sorted(investment[cols["channel_col"]].str.strip().unique())
    renamed = {name: f"CANAL_{i:02d}" for i, name in enumerate(names, start=1)}
    investment[cols["channel_col"]] = investment[cols["channel_col"]].str.strip().map(renamed)
    values = pd.to_numeric(investment[cols["investment_col"]]) * factors["investment"]
    investment[cols["investment_col"]] = values.round(2)

    performance = _read(files["performance_file"])
    kpi_col = mapping["performance_file"]["kpi_col"]
    performance[kpi_col] = (pd.to_numeric(performance[kpi_col]) * factors["kpi"]).round(2)

    new_files = {"investment_file": out_dir / "investment.csv", "performance_file": out_dir / "performance.csv"}
    investment.to_csv(new_files["investment_file"], index=False)
    performance.to_csv(new_files["performance_file"], index=False)
    trends = files.get("generic_trends_file")
    new_files["generic_trends_file"] = None
    if trends:
        new_files["generic_trends_file"] = out_dir / "trends.csv"
        shutil.copyfile(trends, new_files["generic_trends_file"])
    return new_files, renamed
