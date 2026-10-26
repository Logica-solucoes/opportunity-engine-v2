import json
from datetime import date, timedelta

import pytest

from api import gemini, simulations, suggestions
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


def answer(*items):
    return lambda prompt, schema: json.dumps(
        {"suggestions": [dict(zip(("field", "value", "reason"), i)) for i in items]}
    )


def test_gemini_suggestions_come_validated_with_their_reason(logged, mapped, monkeypatch):
    monkeypatch.setattr(
        gemini,
        "ask",
        answer(
            ("investment_limit_factor", "2", "Os canais ainda têm folga."),
            ("financial_targets.target_cpa", "35.5", "CPA médio do período."),
            ("max_budget_step", "7", "Fora do limite."),
            ("column_mapping", "{}", "Campo que não é do formulário."),
        ),
    )

    r = logged.post(f"/api/w/a/simulations/{mapped.id}/suggestions/gemini")

    assert r.status_code == 200
    assert r.json() == {
        "available": True,
        "suggestions": {
            "investment_limit_factor": {"value": 2.0, "reason": "Os canais ainda têm folga.", "source": "gemini"},
            "financial_targets.target_cpa": {"value": 35.5, "reason": "CPA médio do período.", "source": "gemini"},
        },
    }


def test_gemini_prompt_carries_a_summary_and_no_rows(logged, mapped, monkeypatch):
    prompts = []

    def ask(prompt, schema):
        prompts.append(prompt)
        return json.dumps({"suggestions": []})

    monkeypatch.setattr(gemini, "ask", ask)
    logged.post(f"/api/w/a/simulations/{mapped.id}/suggestions/gemini")

    assert "SEARCH" in prompts[0] and "conversoes" in prompts[0]
    for line in (INVESTMENT + PERFORMANCE).decode().splitlines():
        if line[:1].isdigit():
            assert line not in prompts[0]


def sdk_error(prompt, schema):
    raise gemini.Unavailable("Timeout")


@pytest.mark.parametrize(
    "ask",
    [None, sdk_error, lambda prompt, schema: "isto não é json"],
    ids=["no key", "sdk error", "bad answer"],
)
def test_gemini_unavailable_answers_200_and_nothing(logged, mapped, monkeypatch, ask):
    if ask:
        monkeypatch.setattr(gemini, "ask", ask)

    r = logged.post(f"/api/w/a/simulations/{mapped.id}/suggestions/gemini")

    assert (r.status_code, r.json()) == (200, {"available": False, "suggestions": {}})


def test_gemini_needs_a_confirmed_mapping(logged, analyst, ws, make_simulation):
    bare = make_simulation(ws, analyst, files={"investment": INVESTMENT, "performance": PERFORMANCE})

    assert logged.post(f"/api/w/a/simulations/{bare.id}/suggestions/gemini").status_code == 422


def test_params_are_saved_with_defaults_and_keep_the_mapping(logged, mapped):
    url = f"/api/w/a/simulations/{mapped.id}"

    r = logged.put(f"{url}/params", json={"investment_limit_factor": 2, "financial_targets": {"target_cpa": 30}})

    assert r.status_code == 200
    config = r.json()["config"]
    assert config["column_mapping"] == MAPPING
    assert config["investment_limit_factor"] == 2.0 and config["max_budget_step"] == 0.2
    assert config["financial_targets"] == {
        "target_cpa": 30.0,
        "target_icpa": None,
        "target_roas": None,
        "target_iroas": None,
    }
    assert r.json()["validation"] is not None

    remapped = logged.put(f"{url}/mapping", json=MAPPING).json()
    assert remapped["config"]["investment_limit_factor"] == 2.0


@pytest.mark.parametrize(
    "body, loc, kind",
    [
        ({"investment_limit_factor": 1}, ["body", "investment_limit_factor"], "greater_than"),
        ({"financial_targets": {"target_cpa": -1}}, ["body", "financial_targets", "target_cpa"], "greater_than"),
        ({"optimization_target": "CLICKS"}, ["body", "optimization_target"], "literal_error"),
        ({"column_mapping": {}}, ["body", "column_mapping"], "extra_forbidden"),
    ],
)
def test_invalid_params_are_422_with_the_field(logged, mapped, body, loc, kind):
    r = logged.put(f"/api/w/a/simulations/{mapped.id}/params", json=body)

    assert r.status_code == 422
    assert [(e["loc"], e["type"]) for e in r.json()["detail"]] == [(loc, kind)]


def test_params_need_a_confirmed_mapping(logged, analyst, ws, make_simulation):
    bare = make_simulation(ws, analyst, files={"investment": INVESTMENT, "performance": PERFORMANCE})

    r = logged.put(f"/api/w/a/simulations/{bare.id}/params", json={})

    assert (r.status_code, r.json()) == (422, {"detail": "Confirme o mapeamento de colunas antes."})
