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


def _ids(raw):
    return [c.id for c in raw.checks]


def test_duplicate_date_channel_flags_error(tmp_path):
    investment, kpi = clean_rows()
    investment.append(investment[0])
    raw = read_inputs(_config(), write_inputs(tmp_path, investment, kpi))
    [check] = raw.checks
    assert check.id == "duplicate_date_channel" and check.level == "error"
    assert check.details["count"] == 1
    assert check.details["examples"] == [{"date": investment[0][0], "channel": "SEARCH"}]


def test_kpi_duplicate_dates_without_channel_column(tmp_path):
    investment, kpi = clean_rows()
    kpi.append(kpi[0])
    raw = read_inputs(_config(), write_inputs(tmp_path, investment, kpi))
    assert _ids(raw) == ["kpi_duplicate_dates"]
    assert raw.checks[0].details["count"] == 1


def test_kpi_not_single_source_with_channel_column(tmp_path):
    investment, kpi = clean_rows()
    kpi = [(d, v, "A") for d, v in kpi] + [(d, v, "B") for d, v in kpi]
    paths = write_inputs(tmp_path, investment, kpi, kpi_header=("date", "Sessions", "Canal"))
    raw = read_inputs(_config(), paths)
    assert _ids(raw) == ["kpi_not_single_source"]  # and not also kpi_duplicate_dates
    assert raw.checks[0].details["columns"] == ["Canal"]


def test_single_kpi_with_numeric_extra_column_is_ok(tmp_path):
    investment, kpi = clean_rows()
    kpi = [(d, v, v // 2) for d, v in kpi]
    paths = write_inputs(tmp_path, investment, kpi, kpi_header=("date", "Sessions", "Clicks"))
    assert read_inputs(_config(), paths).checks == []


def test_semicolon_decimal_comma_performance_is_ok(tmp_path):
    investment, kpi = clean_rows()
    kpi = [(d, f"{v},50") for d, v in kpi]
    paths = write_inputs(tmp_path, investment, kpi, sep=";")
    assert read_inputs(_config(), paths).checks == []


def test_load_and_prepare_data_raises_with_check_id(tmp_path):
    from engine.data_preprocessor import load_and_prepare_data

    investment, kpi = clean_rows()
    cases = {
        "duplicate_date_channel": (investment + [investment[0]], kpi, ("date", "Sessions"), kpi),
        "kpi_duplicate_dates": (investment, kpi + [kpi[0]], ("date", "Sessions"), None),
        "kpi_not_single_source": (
            investment,
            [(d, v, "A") for d, v in kpi] + [(d, v, "B") for d, v in kpi],
            ("date", "Sessions", "Canal"),
            None,
        ),
    }
    for check_id, (inv, perf, header, _) in cases.items():
        paths = write_inputs(tmp_path / check_id, inv, perf, kpi_header=header)
        with pytest.raises(EngineError) as exc:
            load_and_prepare_data(_config(), paths)
        assert exc.value.check_id == check_id


def test_a_missing_path_is_file_unreadable(tmp_path):
    investment, kpi = clean_rows()
    paths = write_inputs(tmp_path, investment, kpi)
    paths["investment_file"] = None
    with pytest.raises(EngineError) as exc:
        read_inputs(_config(), paths)
    assert exc.value.check_id == "file_unreadable"
