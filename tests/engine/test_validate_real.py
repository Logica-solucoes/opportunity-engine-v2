"""validate on the client files in exemplo_csv/ (confidential, never versioned): skipped without them."""

import pytest

from engine.validation import validate
from tests.engine.real_data import GOL_CONFIG, REPO_ROOT, gol_files, gol_original_files

EXEMPLOS = REPO_ROOT / "exemplo_csv"
pytestmark = pytest.mark.skipif(not EXEMPLOS.exists(), reason="needs exemplo_csv/")


def _mapping(date, channel, investment, perf_date, kpi):
    return {
        "column_mapping": {
            "investment_file": {"date_col": date, "channel_col": channel, "investment_col": investment},
            "performance_file": {"date_col": perf_date, "kpi_col": kpi},
        },
    }


def _ids(report):
    return {c.id: c.level for c in report.checks}


def test_gol_as_sent_is_rejected_for_its_repeated_google_rows():
    report = validate(gol_original_files(), GOL_CONFIG)
    assert not report.ok
    assert _ids(report)["duplicate_date_channel"] == "error"


def test_gol_with_the_google_rows_averaged_is_accepted():
    report = validate(gol_files(), GOL_CONFIG)
    assert report.ok, report.checks


def test_tcross_leads_by_channel_is_not_a_single_source():
    config = {
        **_mapping("Data", "Canal", "Investimento", "Data", "Leads"),
        "date_formats": {"investment_file": "%d/%m/%Y", "performance_file": "%d/%m/%Y"},
    }
    files = {
        "investment_file": EXEMPLOS / "Tcross" / "Investimento_Tcross_2026_v2.csv",
        "performance_file": EXEMPLOS / "Tcross" / "Leads_tcross_2026_v2.csv",
        "generic_trends_file": None,
    }
    report = validate(files, config)
    assert not report.ok
    assert _ids(report)["kpi_not_single_source"] == "error"


def test_pmax_weekly_has_one_channel_so_it_is_a_single_source():
    config = {
        **_mapping("Data", "Canal", "Investimento", "Data", "Leads"),
        "date_formats": {"investment_file": "%d/%m/%Y", "performance_file": "%d/%m/%Y"},
    }
    files = {
        "investment_file": EXEMPLOS / "PMAX" / "investimento_pmax_semanal.csv",
        "performance_file": EXEMPLOS / "PMAX" / "performance_pmax_semanal.csv",
        "generic_trends_file": None,
    }
    report = validate(files, config)
    assert "kpi_not_single_source" not in _ids(report)
    assert report.period_days == 7


def test_vw_total_revenue_has_only_warnings_and_infos():
    config = _mapping("Data", "canal", "Investimento", "Data", "Faturamento Total")
    files = {
        "investment_file": EXEMPLOS / "VW" / "investimento.csv",
        "performance_file": EXEMPLOS / "VW" / "performance_vendas totais.csv",
        "generic_trends_file": None,
    }
    report = validate(files, config)
    assert report.ok, report.checks
    assert set(_ids(report)) <= {"missing_dates", "outliers"}


def test_gol_sits_just_above_the_collinearity_limit():
    """GOOGLE DISPLAY/VIDEO x KAYAK at |r| 0.8501 (limit 0.85): the gate asks for a decision, the group is suggested."""
    report = validate(gol_files(), {**GOL_CONFIG, "block_per_channel": False})
    assert not report.ok and _ids(report)["collinearity_unresolved"] == "error"
    assert [(p["a"], p["b"]) for p in report.collinearity.pairs] == [("GOOGLE DISPLAY/VIDEO", "KAYAK")]
    assert report.collinearity.suggested_groups == [["GOOGLE DISPLAY/VIDEO", "KAYAK"]]
    assert max(v for v in report.collinearity.vif.values() if v is not None) < 10

    accepted = validate(gol_files(), {**GOL_CONFIG, "block_per_channel": True})
    assert accepted.ok and _ids(accepted)["collinearity_blocked"] == "warning"

    grouped = validate(
        gol_files(), {**GOL_CONFIG, "block_per_channel": False, "channel_groups": [["GOOGLE DISPLAY/VIDEO", "KAYAK"]]}
    )
    assert grouped.ok and "GOOGLE DISPLAY/VIDEO + KAYAK" in grouped.channels


def test_gol_controls_are_checked_against_its_trends_file():
    """The Gol trends file has only Generic Searches: a declared extra control is reported, not ignored."""
    missing = validate(gol_files(), {**GOL_CONFIG, "controls": ["Selic"]})
    assert not missing.ok and _ids(missing)["control_missing"] == "error"
    assert validate(gol_files(), GOL_CONFIG).ok
