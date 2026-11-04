import re
from pathlib import Path

import pytest

from engine.config import EngineConfig
from engine.data_preprocessor import load_and_prepare_data
from engine.errors import EngineError
from tests.engine.helpers import full_config

ENGINE_DIR = Path(__file__).resolve().parents[2] / "engine"
INLINE_DEFAULT = re.compile(r"""\b(?:config|cfg)\.get\(\s*["'](\w+)["']\s*,""")
RUNTIME_KEYS = {"period_days"}  # detected from the data; the helpers are also called without it


def test_no_inline_defaults_remain():
    found = {}
    for path in ENGINE_DIR.glob("*.py"):
        keys = set(INLINE_DEFAULT.findall(path.read_text(encoding="utf-8"))) - RUNTIME_KEYS
        if keys:
            found[path.name] = sorted(keys)
    assert not found, f"defaults belong in EngineConfig, not inline: {found}"


def test_investment_limit_factor_has_a_single_default():
    assert EngineConfig().investment_limit_factor == 1.5
    assert EngineConfig().to_legacy_dict()["investment_limit_factor"] == 1.5


def _files(tmp_path, kpi="abc"):
    days = [f"2025-01-{d:02d}" for d in range(1, 11)]
    (tmp_path / "i.csv").write_text("dates,product_group,total_revenue\n" + "".join(f"{d},A,10\n" for d in days))
    (tmp_path / "p.csv").write_text("date,kpi\n" + "".join(f"{d},{kpi}\n" for d in days))
    return {"investment_file": tmp_path / "i.csv", "performance_file": tmp_path / "p.csv", "generic_trends_file": None}


def test_unusable_kpi_column_is_an_engine_error_in_portuguese_without_paths(tmp_path):
    paths = _files(tmp_path)
    with pytest.raises(EngineError) as raised:
        load_and_prepare_data(full_config({"performance_kpi_column": "kpi"}), paths)
    message = str(raised.value)
    assert "KPI" in message and "arquivo de performance" in message
    assert str(tmp_path) not in message


def test_missing_file_is_an_engine_error_without_the_path(tmp_path):
    paths = _files(tmp_path)
    paths["performance_file"] = tmp_path / "gone.csv"
    with pytest.raises(EngineError) as raised:
        load_and_prepare_data(full_config(), paths)
    assert isinstance(raised.value.__cause__, FileNotFoundError)
    assert str(tmp_path) not in str(raised.value)


def test_engine_error_is_not_wrapped_again(tmp_path):
    paths = _files(tmp_path)
    with pytest.raises(EngineError) as raised:
        load_and_prepare_data(full_config({"performance_kpi_column": "kpi"}), paths)
    assert "unexpected error" not in str(raised.value).lower()
