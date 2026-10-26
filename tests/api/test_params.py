from datetime import date, timedelta

import pytest

from api import simulations, suggestions
from api.engine_config import EngineConfig, ParamsIn
from tests.samples import INVESTMENT, MAPPING, PERFORMANCE


@pytest.fixture
def analyst(make_user):
    return make_user("ana@x.com")


@pytest.fixture
def ws(make_workspace, analyst):
    return make_workspace("a", [(analyst, "analyst")])


@pytest.fixture
def logged(client, analyst, ws, login_as):
    login_as(client, analyst)
    return client


def test_config_schema_lists_only_the_form_fields(logged):
    schema = logged.get("/api/engine/config-schema").json()

    props = schema["properties"]
    assert props["investment_limit_factor"]["default"] == 1.5
    assert props["optimization_target"]["enum"] == ["REVENUE", "CONVERSIONS"]
    assert {"column_mapping", "channel_groups", "controls", "gate_thresholds"}.isdisjoint(props)


def test_engine_config_is_the_form_fields_plus_the_rest():
    config = EngineConfig()

    assert config.max_budget_step == 0.2 and config.column_mapping == {}
    assert set(ParamsIn.model_fields) < set(EngineConfig.model_fields)


@pytest.fixture
def mapped(db, ws, analyst, make_simulation):
    simulation = make_simulation(ws, analyst, files={"investment": INVESTMENT, "performance": PERFORMANCE})
    simulations.save_mapping(db, simulation, MAPPING)
    return simulation


def days(n, step=1):
    return [date(2024, 1, 1) + timedelta(days=i * step) for i in range(n)]


def from_performance(tmp_path, dates, kpi="conversoes"):
    path = tmp_path / "performance.csv"
    path.write_text(f"data,{kpi}\n" + "".join(f"{d.isoformat()},10\n" for d in dates), encoding="utf-8")
    return suggestions.from_data({"performance_file": path}, {"performance_file": {"date_col": "data", "kpi_col": kpi}})


@pytest.mark.parametrize(
    "dates, value, reason",
    [
        (days(200), 50, "Um quarto dos 200 dias de histórico."),
        (days(400), 90, "Teto para série diária: um quarto dos 400 dias passaria disso."),
        (days(3), 28, "Mínimo para série diária: o histórico tem só 3 dias."),
        (days(100, step=7), 175, "Um quarto dos 700 dias de histórico."),
        (days(20, step=7), 56, "Mínimo para série semanal: o histórico tem só 140 dias."),
    ],
)
def test_pre_period_is_a_quarter_of_the_history_within_the_cadence_bounds(tmp_path, dates, value, reason):
    got = from_performance(tmp_path, dates)["min_pre_period_days"]

    assert got == {"value": value, "reason": reason, "source": "dados"}


def test_unknown_cadence_or_unreadable_dates_suggest_no_pre_period(tmp_path):
    assert "min_pre_period_days" not in from_performance(tmp_path, days(30, step=3))
    path = tmp_path / "br.csv"
    path.write_text("data,conversoes\n01/01/2024,1\n02/01/2024,2\n", encoding="utf-8")
    got = suggestions.from_data(
        {"performance_file": path}, {"performance_file": {"date_col": "data", "kpi_col": "conversoes"}}
    )
    assert "min_pre_period_days" not in got


@pytest.mark.parametrize(
    "kpi, target, monetary",
    [("Receita Líquida", "REVENUE", True), ("conversões", "CONVERSIONS", False), ("pedidos", "CONVERSIONS", False)],
)
def test_kpi_column_name_suggests_the_target(tmp_path, kpi, target, monetary):
    got = from_performance(tmp_path, days(10), kpi=kpi)

    assert got["optimization_target"]["value"] == target
    assert got["kpi_is_monetary"]["value"] is monetary
    assert f"'{kpi}'" in got["optimization_target"]["reason"]


def test_unknown_kpi_name_suggests_no_target(tmp_path):
    got = from_performance(tmp_path, days(10), kpi="kpi")

    assert "optimization_target" not in got and "kpi_is_monetary" not in got


def test_suggestions_route_reads_the_uploaded_files(logged, mapped):
    body = logged.get(f"/api/w/a/simulations/{mapped.id}/suggestions").json()

    assert body["min_pre_period_days"]["value"] == 28
    assert body["optimization_target"] == {
        "value": "CONVERSIONS",
        "reason": "A coluna de KPI se chama 'conversoes', uma contagem de conversões.",
        "source": "dados",
    }


def test_suggestions_need_a_confirmed_mapping(logged, analyst, ws, mapped, make_simulation):
    bare = make_simulation(ws, analyst, files={"investment": INVESTMENT, "performance": PERFORMANCE})
    assert logged.get(f"/api/w/a/simulations/{bare.id}/suggestions").status_code == 422

    logged.put(
        f"/api/w/a/simulations/{mapped.id}/files/investment",
        files={"file": ("investimento.csv", INVESTMENT, "text/csv")},
    )
    r = logged.get(f"/api/w/a/simulations/{mapped.id}/suggestions")
    assert (r.status_code, r.json()) == (422, {"detail": "Confirme o mapeamento de colunas antes."})


def test_suggestions_of_another_workspace_are_404(logged, analyst, make_workspace, make_simulation):
    foreign = make_simulation(make_workspace("b", [(analyst, "analyst")]), analyst)

    assert logged.get(f"/api/w/a/simulations/{foreign.id}/suggestions").status_code == 404
