import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

from tests.engine.synthetic_data import dataset_config, make_dataset

ROOT = Path(__file__).resolve().parents[2]


def _cli(*args, cwd=ROOT, timeout=600):
    env = {**os.environ, "LLM_PROVIDER": "none"}
    return subprocess.run(
        [sys.executable, "-m", "engine", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _write_run_json(path: Path, inputs: dict, config: dict) -> Path:
    path.write_text(json.dumps({**config, "inputs": {k: str(v) if v else None for k, v in inputs.items()}}))
    return path


def test_cli_runs_and_exits_zero_on_its_own(tmp_path):
    inputs = make_dataset(tmp_path / "data", n_days=364)
    run_json = _write_run_json(tmp_path / "run.json", inputs, dataset_config())
    done = _cli("--config", str(run_json), "--out", str(tmp_path / "out"))
    assert done.returncode == 0, done.stderr[-2000:]
    assert (tmp_path / "out" / "global_saturation_analysis" / "response_curve_data.csv").exists()
    assert "[info]" in done.stderr
    assert done.stdout == ""


def test_cli_failed_run_exits_one(tmp_path):
    days = pd.date_range("2025-01-01", periods=60, freq="D").strftime("%Y-%m-%d")
    (tmp_path / "i.csv").write_text("dates,product_group,total_revenue\n" + "".join(f"{d},A,0\n" for d in days))
    (tmp_path / "p.csv").write_text("date,Sessions\n" + "".join(f"{d},10\n" for d in days))
    config = dataset_config()
    del config["column_mapping"]["generic_trends_file"]
    inputs = {"investment_file": tmp_path / "i.csv", "performance_file": tmp_path / "p.csv"}
    run_json = _write_run_json(tmp_path / "run.json", inputs, config)
    done = _cli("--config", str(run_json), "--out", str(tmp_path / "out"))
    assert done.returncode == 1
    assert "[error]" in done.stderr


def test_cli_unknown_config_field_exits_one_with_a_portuguese_message(tmp_path):
    inputs = {"investment_file": tmp_path / "i.csv", "performance_file": tmp_path / "p.csv"}
    run_json = _write_run_json(tmp_path / "run.json", inputs, {"require_significance": True})
    done = _cli("--config", str(run_json), "--out", str(tmp_path / "out"))
    assert done.returncode == 1
    assert "Configuração inválida" in done.stderr and "require_significance" in done.stderr


def test_cli_missing_or_unreadable_config_exits_two(tmp_path):
    assert _cli("--config", str(tmp_path / "nope.json"), "--out", str(tmp_path / "out")).returncode == 2
    (tmp_path / "bad.json").write_text("{not json")
    assert _cli("--config", str(tmp_path / "bad.json"), "--out", str(tmp_path / "out")).returncode == 2
    (tmp_path / "noinputs.json").write_text("{}")
    done = _cli("--config", str(tmp_path / "noinputs.json"), "--out", str(tmp_path / "out"))
    assert done.returncode == 2 and "inputs" in done.stderr


def test_cli_passes_the_bcb_file(tmp_path):
    from engine.__main__ import _load

    run_json = tmp_path / "run.json"
    run_json.write_text('{"inputs": {"investment_file": "i.csv", "bcb_file": "bcb.csv"}}', encoding="utf-8")

    _, inputs = _load(run_json)

    assert inputs["bcb_file"] == Path("bcb.csv") and inputs["generic_trends_file"] is None
