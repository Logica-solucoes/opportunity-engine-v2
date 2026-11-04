import pytest

from engine.errors import EngineError
from engine.inputs import read_inputs
from tests.engine.csv_factory import clean_rows, legacy_config, write_inputs


def _config(**mapping_overrides):
    config = legacy_config()
    for key, value in mapping_overrides.items():
        config["column_mapping"][key].update(value)
    config["date_formats"] = {}
    return config


def test_read_inputs_clean_returns_normalized_tables(tmp_path):
    investment, kpi = clean_rows()
    raw = read_inputs(_config(), write_inputs(tmp_path, investment, kpi))
    assert list(raw.kpi_df.columns) == ["Date", "kpi"]
    assert {"Date", "Product Group", "investment"} <= set(raw.investment_df.columns)
    assert raw.checks == []


def test_missing_file_is_file_unreadable(tmp_path):
    investment, kpi = clean_rows()
    paths = write_inputs(tmp_path, investment, kpi)
    paths["investment_file"].write_text("")
    with pytest.raises(EngineError) as exc:
        read_inputs(_config(), paths)
    assert exc.value.check_id == "file_unreadable"
    assert str(tmp_path) not in str(exc.value)


def test_missing_column_is_column_missing(tmp_path):
    investment, kpi = clean_rows()
    paths = write_inputs(tmp_path, investment, kpi, inv_header=("dates", "product_group", "foo"))
    config = _config(investment_file={"investment_col": "inexistente"})
    with pytest.raises(EngineError) as exc:
        read_inputs(config, paths)
    assert exc.value.check_id == "column_missing"


def test_unparseable_dates(tmp_path):
    investment, kpi = clean_rows()
    kpi = [("abc", v) for _, v in kpi]
    with pytest.raises(EngineError) as exc:
        read_inputs(_config(), write_inputs(tmp_path, investment, kpi))
    assert exc.value.check_id == "date_unparseable"


def test_mostly_non_numeric_kpi_is_value_not_numeric(tmp_path):
    investment, kpi = clean_rows()
    kpi = [(d, "x" if i < 6 else v) for i, (d, v) in enumerate(kpi)]
    raw = read_inputs(_config(), write_inputs(tmp_path, investment, kpi))
    [check] = [c for c in raw.checks if c.id == "value_not_numeric"]
    assert check.level == "error"


def test_engine_error_keeps_check_id():
    assert EngineError("m", "c").check_id == "c"
    assert EngineError("m").check_id is None
