import json
import re
from pathlib import Path

import pytest

from api import csvfile, exports, runs, simulations, storage
from api.engine_config import ParamsIn
from api.models import Membership
from engine import ScenarioFilters, scenario
from engine.scenario import TCPA_NOTE
from tests.samples import INVESTMENT, MAPPING, PERFORMANCE

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "results"
GOL, IDENTIFIABLE = FIXTURES / "gol_anonimizada.json", FIXTURES / "identificavel.json"
WEB_RESULTS = Path(__file__).resolve().parents[2] / "web" / "src" / "lib" / "results.ts"
BOM = "﻿"
EVENTS_HEADER = (
    "Evento;Canais;Início;Fim;Veredito;Motivos;Lift;Lift IC inferior;Lift IC superior;Lift %;p-valor;"
    "Variação do investimento %;Investimento incremental;CPA incremental;R²;WMAPE;Placebo p-valor;Robustez p-valor"
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def answer(**filters) -> dict:
    return scenario(load(IDENTIFIABLE), ScenarioFilters(**filters), 0.2)


# --- csvfile ---


def test_the_writer_is_what_excel_in_ptbr_opens():
    assert csvfile.to_csv(["a", "b"], [["1,5", "x;y"], [], [2, ""]]) == f'{BOM}a;b\n1,5;"x;y"\n\n2;\n'


@pytest.mark.parametrize(
    ("value", "digits", "text"), [(None, 2, ""), (-1234.567, 2, "-1234,57"), (2.5, 4, "2,5000"), (0.0, 1, "0,0")]
)
def test_decimal_has_a_comma_and_no_thousands_separator(value, digits, text):
    assert csvfile.decimal(value, digits) == text


def test_safe_quotes_what_excel_would_run():
    assert [csvfile.safe(c) for c in ["=1+1", "+x", "-x", "@x", "ok"]] == ["'=1+1", "'+x", "'-x", "'@x", "ok"]


# --- events ---


def test_a_rejected_event_has_its_verdict_and_reasons_but_no_numbers():
    assert exports.events_csv(load(IDENTIFIABLE)) == (
        f"{BOM}{EVENTS_HEADER}\n"
        "synthetic_NOEFFECT,_STRONG_2024-01-15;NOEFFECT + STRONG;;;rejeitado;A análise do evento falhou;;;;;;;;;;;;\n"
        "synthetic_STRONG_2024-08-05;STRONG;05/08/2024;18/08/2024;rejeitado;"
        "O efeito só aparece com as variáveis de mídia do modelo;;;;;;;;;;;;\n"
    )


PUBLISHED = {
    "id": "adv_A_2025-01-20",
    "channels": ["A", "B"],
    "status": "published",
    "reasons": [],
    "start": "2025-01-20",
    "end": "2025-02-03",
    "lift": {"abs": -514366.04, "ci": [-671610.99, -357121.10], "rel_pct": -31.11},
    "p_value": 1.44e-10,
    "investment_change_pct": -33.57,
    "incremental_investment": -140739.15,
    "cpa_incremental": 0.27,
    "fit": {"r2": 0.5316, "wmape": None},
    "placebo": None,
    "robustness": {"p_value": 1.44e-10},
}


def test_a_published_event_has_its_numbers():
    # since the audit fixes no fixture has a published event (the Gol's are all demoted), so the row is hand-built
    line = exports.events_csv({"causal": {"events": [PUBLISHED]}}).splitlines()[1]

    assert line == (
        "adv_A_2025-01-20;A + B;20/01/2025;03/02/2025;publicado;;"
        "-514366,04;-671610,99;-357121,10;-31,11;1,44e-10;-33,57;-140739,15;0,27;0,5316;;;1,44e-10"
    )


def test_the_gol_events_export_with_the_failed_ones_undated():
    lines = exports.events_csv(load(GOL)).splitlines()

    assert len(lines) == 32  # the header and the Gol's 31 events
    assert "default_advertiser_CANAL_01_2025-01-13;CANAL_01;;;rejeitado;A análise do evento falhou;;;;;;;;;;;;" in lines


def test_channel_names_cannot_run_as_a_formula():
    event = {"id": "=HYPERLINK(1)_x", "channels": ["=HYPERLINK(1)", "B"], "status": "rejected", "reasons": []}

    line = exports.events_csv({"causal": {"events": [event]}}).splitlines()[1]

    assert line.startswith("'=HYPERLINK(1)_x;'=HYPERLINK(1) + B;;;rejeitado;;")


def test_an_unknown_reason_shows_its_code():
    event = {"id": "x", "channels": ["A"], "status": "rejected", "reasons": ["new_gate", "not_significant"]}

    assert ";rejeitado;new_gate · Não significativo;" in exports.events_csv({"causal": {"events": [event]}})


def test_event_reason_labels_are_the_screens():
    # the engine sets event reasons as literals in engine/pipeline.py and engine/results.py, with no list to import;
    # REASON_LABELS in the front is where a new one gets its label, so the CSV must say the same thing
    block = WEB_RESULTS.read_text(encoding="utf-8").split("const REASON_LABELS", 1)[1].split("}", 1)[0]
    web = dict(re.findall(r"^\s+(\w+): '([^']*)',$", block, re.MULTILINE))

    assert {code: web.get(code) for code in exports.EVENT_REASONS} == exports.EVENT_REASONS


@pytest.mark.parametrize("path", [GOL, IDENTIFIABLE], ids=lambda p: p.name)
def test_every_event_reason_of_a_real_run_has_a_label(path):
    reasons = {r for e in load(path)["causal"]["events"] for r in e["reasons"]}

    assert reasons <= exports.EVENT_REASONS.keys()


# --- scenario and curve ---


def test_scenario_csv_has_the_table_then_the_ramp():
    head, ramp = exports.scenario_csv(answer()).split("\n\n")

    assert head.splitlines() == [
        f"{BOM}Cenário;Investimento;KPI;KPI p5;KPI p95;CPA;Investimento incremental;KPI incremental;iCPA;Extrapolado;Notas",
        "Atual;58152,20;198731,29;198124,38;199343,39;0,29;0,00;0,00;0,00;não;",
        f"Recomendado;87228,30;204995,97;203986,04;206045,37;0,43;29076,10;6264,68;4,64;não;{TCPA_NOTE}",
        f"Saturação;87228,30;204995,97;203986,04;206045,37;0,43;29076,10;6264,68;4,64;não;{TCPA_NOTE}",
    ]
    steps = ramp.splitlines()
    assert steps[:2] == [
        "Cenário;Degrau;Investimento;KPI;KPI p5;KPI p95",
        "Recomendado;1;69782,64;201540,05;200853,23;202258,64",
    ]
    assert len(steps) == 7  # the header and 3 steps to each of recommended and saturation


def test_no_recommended_row_when_nothing_passes_the_filters():
    lines = exports.scenario_csv(answer(target_cpa=1e-9, min_budget=1)).splitlines()

    assert [line.split(";")[0] for line in lines[1:3]] == ["Atual", "Saturação"]
    assert not any(line.startswith("Recomendado;") for line in lines)


def test_revenue_columns_only_in_revenue_mode():
    revenue = {**answer(), "revenue_mode": True}

    assert exports.scenario_csv(revenue).splitlines()[0] == (
        f"{BOM}Cenário;Investimento;KPI;KPI p5;KPI p95;Receita;CPA;ROAS;Investimento incremental;KPI incremental;"
        "iCPA;iROAS;Extrapolado;Notas"
    )
    assert exports.curve_csv(revenue).splitlines()[0] == (
        f"{BOM}Investimento;KPI;KPI p5;KPI p95;Receita;CPA;iCPA;ROAS;iROAS;Investimento incremental;"
        "KPI incremental;% incrementalidade;Extrapolado;No filtro"
    )


def test_curve_csv_has_a_point_per_line_with_its_filter_flag():
    lines = exports.curve_csv(answer(target_cpa=0.3)).splitlines()

    assert lines[0] == (
        f"{BOM}Investimento;KPI;KPI p5;KPI p95;CPA;iCPA;Investimento incremental;KPI incremental;"
        "% incrementalidade;Extrapolado;No filtro"
    )
    assert (
        lines[1] == "0,00;92200,24;78537,67;106020,87;0,00;;0,00;0,00;0,00;sim;sim"
    )  # the zero-media KPI and its band
    assert len(lines) == 101
    assert {line.rsplit(";", 1)[1] for line in lines[1:]} == {"sim", "não"}


# --- routes ---

FILES = ["events.csv", "scenario.csv", "curve.csv"]


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


@pytest.fixture
def finished(db, ws, analyst, make_simulation):
    def make(workspace=None, document=IDENTIFIABLE, results=True):
        simulation = make_simulation(
            workspace or ws, analyst, files={"investment": INVESTMENT, "performance": PERFORMANCE}
        )
        simulations.save_mapping(db, simulation, MAPPING)
        simulations.save_params(db, simulation, ParamsIn().model_dump(mode="json"))
        run = runs.create(db, simulation, set(), by=analyst)
        run.status = "succeeded"
        if results:
            run.results_uri = f"ws/{run.workspace_id}/sim/{run.simulation_id}/runs/{run.id}/results.json"
            storage.put(run.results_uri, document)
        db.commit()
        return run

    return make


def url(run, file, slug="a", query=""):
    return f"/api/w/{slug}/runs/{run.id}/{file}{query}"


@pytest.mark.parametrize(
    ("file", "name"), [("events.csv", "eventos"), ("scenario.csv", "cenarios"), ("curve.csv", "curva")]
)
def test_each_csv_is_an_attachment_named_after_the_run(logged, finished, file, name):
    run = finished()

    r = logged.get(url(run, file))

    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "text/csv; charset=utf-8"
    assert r.headers["content-disposition"] == f'attachment; filename="execucao-{run.id}-{name}.csv"'
    assert r.content.startswith(b"\xef\xbb\xbf")


def test_the_events_csv_is_the_documents_events(logged, finished):
    assert logged.get(url(finished(), "events.csv")).text == exports.events_csv(load(IDENTIFIABLE))


def test_the_gol_still_exports_its_events(logged, finished):
    r = logged.get(url(finished(document=GOL), "events.csv"))

    assert r.status_code == 200 and len(r.text.splitlines()) == 32


def test_filters_reach_the_scenario_csv(logged, finished):
    run = finished()

    every = logged.get(url(run, "scenario.csv")).text
    capped = logged.get(url(run, "scenario.csv", query="?target_cpa=0.3")).text
    nothing = logged.get(url(run, "scenario.csv", query="?target_cpa=0.000000001&min_budget=1")).text

    assert "\nRecomendado;87228,30;" in every
    assert "\nRecomendado;59033,29;" in capped
    assert "\nRecomendado;" not in nothing and "\nSaturação;" in nothing


def test_filters_reach_the_curve_csv(logged, finished):
    lines = logged.get(url(finished(), "curve.csv", query="?target_cpa=0.000000001&min_budget=1")).text.splitlines()

    assert len(lines) == 101 and all(line.endswith(";não") for line in lines[1:])


@pytest.mark.parametrize("file", FILES)
def test_a_run_without_results_is_not_found(logged, finished, file):
    r = logged.get(url(finished(results=False), file))

    assert r.status_code == 404 and r.json()["detail"] == "Esta execução não tem resultado."


@pytest.mark.parametrize("file", FILES)
def test_a_run_of_another_workspace_is_not_found(logged, finished, make_workspace, analyst, file):
    run = finished(workspace=make_workspace("b", [(analyst, "analyst")]))

    assert logged.get(url(run, file, slug="a")).status_code == 404


@pytest.mark.parametrize("file", FILES)
def test_viewer_exports_only_a_published_run(make_client, login_as, make_user, db, ws, finished, analyst, file):
    run = finished()
    viewer = make_user("vi@x.com")
    db.add(Membership(user_id=viewer.id, workspace_id=ws.id, role="viewer"))
    db.commit()
    client = make_client()
    login_as(client, viewer)

    assert client.get(url(run, file)).status_code == 404
    runs.publish(db, run, by=analyst)
    assert client.get(url(run, file)).status_code == 200


def test_events_csv_without_a_causal_section_is_not_found(logged, finished, tmp_path):
    document = tmp_path / "results.json"
    document.write_text(json.dumps({**load(IDENTIFIABLE), "causal": None}), encoding="utf-8")

    r = logged.get(url(finished(document=document), "events.csv"))

    assert r.status_code == 404 and r.json()["detail"] == "Esta execução não tem análise causal."


@pytest.mark.parametrize("file", ["scenario.csv", "curve.csv"])
def test_a_refused_elasticity_is_a_conflict(logged, finished, file):
    r = logged.get(url(finished(document=GOL), file))

    assert r.status_code == 409 and "não é conclusiva" in r.json()["detail"]


@pytest.mark.parametrize("file", ["scenario.csv", "curve.csv"])
@pytest.mark.parametrize("query", ["?min_budget=-1", "?min_budget=10&max_budget=5", "?foo=1"])
def test_bad_filters_are_rejected(logged, finished, file, query):
    assert logged.get(url(finished(), file, query=query)).status_code == 422
