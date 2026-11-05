import time

import numpy as np
import pytest

from engine.data_preprocessor import load_and_prepare_data
from engine.errors import EngineError
from engine.validation import validate
from tests.engine.csv_factory import clean_rows, days, legacy_config, write_inputs
from tests.engine.synthetic_data import CHANNELS, dataset_config, make_dataset


def _config():
    """What a caller hands validate: the EngineConfig shape (the loader gets its legacy form)."""
    return dataset_config()


def _by_id(report):
    return {c.id: c for c in report.checks}


def test_clean_dataset_is_ok_without_blocking_checks(tmp_path):
    report = validate(make_dataset(tmp_path, n_days=364), dataset_config())
    assert report.ok
    assert not [c for c in report.checks if c.level in ("error", "warning")]
    assert report.cadence == "diária" and report.period_days == 1
    assert report.channels == sorted(CHANNELS)
    assert report.date_range == ["2024-01-02", "2024-12-30"]
    assert report.collinearity is not None and report.collinearity.pairs == []


def test_cadence_mismatch(tmp_path):
    investment, _ = clean_rows(28)
    kpi = [(d, 100 + i) for i, d in enumerate(days(28)[::7])]
    report = validate(write_inputs(tmp_path, investment, kpi), _config())
    assert not report.ok and "cadence_mismatch" in _by_id(report)


def test_partial_period_dropped_is_info_with_counts(tmp_path):
    investment, kpi = clean_rows(28)
    weekly = days(28)[::7]
    inv = [(d, c, v) for d, c, v in investment if d in weekly] + [
        ("2024-01-04", "SEARCH", 5),
        ("2024-01-04", "SOCIAL", 5),
    ]
    perf = [(d, v) for d, v in kpi if d in weekly] + [("2024-01-04", 5)]
    # clean_rows channels are the same linear ramp, so the collinearity gate is accepted: this test is about partials
    report = validate(write_inputs(tmp_path, inv, perf), {**_config(), "block_per_channel": True})
    check = _by_id(report)["partial_period_dropped"]
    assert check.level == "info" and check.details == {"investment": 1, "performance": 1}
    assert report.ok


def test_missing_dates_lists_dates_daily_and_weekly(tmp_path):
    investment, kpi = clean_rows(20)
    gone = set(days(20)[5:8])
    kpi = [(d, v) for d, v in kpi if d not in gone]
    check = _by_id(validate(write_inputs(tmp_path / "d", investment, kpi), _config()))["missing_dates"]
    assert check.level == "warning" and check.details["count"] == 3
    assert check.details["dates"] == sorted(gone)

    weeks = days(35)[::7]
    inv = [(d, c, 100 + i) for i, d in enumerate(weeks) for c in ("SEARCH", "SOCIAL")]
    perf = [(d, 100 + i) for i, d in enumerate(weeks) if d != weeks[2]]
    check = _by_id(validate(write_inputs(tmp_path / "w", inv, perf), _config()))["missing_dates"]
    assert check.details == {"count": 1, "dates": [weeks[2]]}


def test_outliers_reports_count_and_dates(tmp_path):
    investment, kpi = clean_rows(30)
    kpi[10] = (kpi[10][0], 1_000_000)
    check = _by_id(validate(write_inputs(tmp_path, investment, kpi), _config()))["outliers"]
    assert check.level == "info" and check.details["count"] == 1 and check.details["dates"] == [kpi[10][0]]


def _two_channels(b_of_a, n=60):
    rng = np.random.default_rng(3)
    a = 100 + 50 * rng.random(n)
    investment = [(d, "A", x) for d, x in zip(days(n), a)] + [(d, "B", b_of_a(x, rng)) for d, x in zip(days(n), a)]
    return investment, [(d, 1000 + i) for i, d in enumerate(days(n))]


@pytest.mark.parametrize("names", [("A", "B"), ("DV360", "X")])
def test_channel_overlap_is_by_series_not_name(tmp_path, names):
    investment, kpi = _two_channels(lambda x, rng: x * 1.02 + rng.normal(0, 0.01))
    investment = [(d, names[0] if c == "A" else names[1], v) for d, c, v in investment]
    check = _by_id(validate(write_inputs(tmp_path, investment, kpi), _config()))["dv360_cm360_overlap"]
    assert check.level == "warning" and sorted(check.details["channels"]) == sorted(names)


def test_no_overlap_when_totals_differ_or_series_constant(tmp_path):
    investment, kpi = _two_channels(lambda x, rng: x * 3 + rng.normal(0, 0.01))
    assert "dv360_cm360_overlap" not in _by_id(validate(write_inputs(tmp_path / "a", investment, kpi), _config()))
    investment, kpi = _two_channels(lambda x, rng: 100.0)
    assert "dv360_cm360_overlap" not in _by_id(validate(write_inputs(tmp_path / "b", investment, kpi), _config()))


def test_validate_returns_error_report_instead_of_raising(tmp_path):
    investment, kpi = clean_rows()
    paths = write_inputs(tmp_path, investment, kpi)
    paths["investment_file"].write_text("")
    report = validate(paths, _config())
    assert not report.ok and [c.id for c in report.checks] == ["file_unreadable"]


def _bad_cases(tmp_path):
    investment, kpi = clean_rows(14)
    yield "duplicate_date_channel", write_inputs(tmp_path / "1", investment + [investment[0]], kpi)
    yield "kpi_duplicate_dates", write_inputs(tmp_path / "2", investment, kpi + [kpi[0]])
    two = [(d, v, "A") for d, v in kpi] + [(d, v, "B") for d, v in kpi]
    yield (
        "kpi_not_single_source",
        write_inputs(tmp_path / "3", investment, two, kpi_header=("date", "Sessions", "Canal")),
    )
    weekly = [(d, 100 + i) for i, d in enumerate(days(14)[::7])]
    yield "cadence_mismatch", write_inputs(tmp_path / "4", investment, weekly)
    yield "column_missing", write_inputs(tmp_path / "5", investment, kpi, kpi_header=("date", "zzz"))
    yield "date_unparseable", write_inputs(tmp_path / "6", investment, [("abc", v) for _, v in kpi])
    yield "value_not_numeric", write_inputs(tmp_path / "7", investment, [(d, "x") for d, _ in kpi])


def test_validate_agrees_with_load_and_prepare_data(tmp_path):
    for expected, paths in _bad_cases(tmp_path):
        report = validate(paths, _config())
        assert not report.ok
        first_error = next(c for c in report.checks if c.level == "error")
        with pytest.raises(EngineError) as exc:
            load_and_prepare_data(legacy_config(), paths)
        assert exc.value.check_id == first_error.id == expected


def test_validate_under_10s_730_days_15_channels(tmp_path):
    n = 730
    rng = np.random.default_rng(1)
    investment = [(d, f"CH{j:02d}", 100 + 30 * rng.random()) for j in range(15) for d in days(n)]
    kpi = [(d, 1000 + 10 * rng.random()) for d in days(n)]
    paths = write_inputs(tmp_path, investment, kpi)
    start = time.perf_counter()
    report = validate(paths, _config())
    assert time.perf_counter() - start < 10
    assert report.ok


def test_validate_reports_columns_it_cannot_interpret_instead_of_raising(tmp_path):
    investment, kpi = clean_rows()
    numeric_codes = [(d, 1 if c == "SEARCH" else 2, v) for d, c, v in investment]
    report = validate(write_inputs(tmp_path / "a", numeric_codes, kpi), _config())
    assert not report.ok and [c.id for c in report.checks] == ["column_unusable"]
    twin_headers = write_inputs(tmp_path / "b", investment, kpi, kpi_header=("date", "Sessions", "Sessions "))
    assert not validate(twin_headers, _config()).ok


def test_run_turns_columns_it_cannot_interpret_into_an_engine_error(monkeypatch, tmp_path):
    import engine

    monkeypatch.setenv("LLM_PROVIDER", "none")
    investment, kpi = clean_rows()
    numeric_codes = [(d, 1 if c == "SEARCH" else 2, v) for d, c, v in investment]
    paths = write_inputs(tmp_path / "in", numeric_codes, kpi)
    with pytest.raises(EngineError) as exc:
        engine.run(paths, _config(), tmp_path / "out", lambda level, message: None)
    assert exc.value.check_id == "column_unusable"


def test_channel_overlap_does_not_depend_on_channel_order(tmp_path):
    for first, second in (("A", "B"), ("B", "A")):
        investment, kpi = _two_channels(lambda x, rng: x * 1.105)
        investment = [(d, first if c == "A" else second, v) for d, c, v in investment]
        report = validate(write_inputs(tmp_path / first, investment, kpi), _config())
        assert "dv360_cm360_overlap" in _by_id(report), (first, second)


def _controls_case(tmp_path, controls, columns):
    investment, kpi = clean_rows(30)
    trends = [(d, 50 + i) for i, (d, _) in enumerate(kpi)]
    extra = {name: [10.0 + (i % 5) for i in range(30)] for name in columns}
    paths = write_inputs(tmp_path, investment, kpi, trends=trends, trends_columns=extra)
    mapping = {"generic_trends_file": {"date_col": "Day", "trends_col": "Ad Opportunities"}}
    config = {**_config(), "controls": controls, "column_mapping": {**_config()["column_mapping"], **mapping}}
    legacy = legacy_config()
    legacy["column_mapping"]["generic_trends_file"] = mapping["generic_trends_file"]
    legacy["controls"] = controls
    return paths, config, legacy


def test_controls_present_and_numeric_are_ok(tmp_path):
    paths, config, _ = _controls_case(tmp_path, ["Selic"], ["Selic"])
    report = validate(paths, {**config, "block_per_channel": True})
    assert report.ok, report.checks


@pytest.mark.parametrize(
    ("controls", "columns", "check_id"),
    [(["Nope"], ["Selic"], "control_missing"), (["SEARCH"], ["SEARCH"], "control_name_clash")],
)
def test_control_errors_agree_between_validate_and_loader(tmp_path, controls, columns, check_id):
    paths, config, legacy = _controls_case(tmp_path, controls, columns)
    report = validate(paths, {**config, "block_per_channel": True})
    assert not report.ok and _by_id(report)[check_id].level == "error"
    with pytest.raises(EngineError) as raised:
        load_and_prepare_data(legacy, paths)
    assert raised.value.check_id == check_id
