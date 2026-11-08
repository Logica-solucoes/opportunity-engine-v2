import json
import re
from pathlib import Path

import pytest

from api import csvfile, exports
from engine import ScenarioFilters, scenario
from engine.scenario import TCPA_NOTE

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
        "synthetic_STRONG_2024-09-02;STRONG;02/09/2024;16/09/2024;rejeitado;"
        "Reprovado no placebo: o modelo acha efeito numa data sem intervenção;;;;;;;;;;;;\n"
    )


def test_a_published_event_has_its_numbers():
    lines = exports.events_csv(load(GOL)).splitlines()

    assert len(lines) == 53  # the header and the Gol's 52 events
    assert (
        "default_advertiser_CANAL_06,_CANAL_08_2025-01-20;CANAL_06 + CANAL_08;20/01/2025;03/02/2025;publicado;;"
        "-514366,04;-671610,99;-357121,10;-31,11;1,44e-10;-33,57;140739,15;-0,27;0,5316;;;1,44e-10"
    ) in lines
    # analysis_failed comes without dates
    assert "default_advertiser_CANAL_02_2025-01-06;CANAL_02;;;rejeitado;A análise do evento falhou;;;;;;;;;;;;" in lines


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
        "Atual;57316,34;196855,76;196328,49;197349,42;0,29;0,00;0,00;0,00;não;",
        f"Recomendado;85974,50;197752,37;196934,36;198518,24;0,43;28658,17;896,61;31,96;não;{TCPA_NOTE}",
        f"Saturação;85974,50;197752,37;196934,36;198518,24;0,43;28658,17;896,61;31,96;não;{TCPA_NOTE}",
    ]
    steps = ramp.splitlines()
    assert steps[:2] == [
        "Cenário;Degrau;Investimento;KPI;KPI p5;KPI p95",
        "Recomendado;1;68779,60;197227,97;196580,01;197834,64",
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
    assert lines[1] == "0,00;195229,73;195229,73;195229,73;0,00;;0,00;0,00;0,00;sim;sim"
    assert len(lines) == 101
    assert {line.rsplit(";", 1)[1] for line in lines[1:]} == {"sim", "não"}
