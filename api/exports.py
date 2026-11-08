"""The CSV exports of a run (B7): pure functions from the results.json, or the engine.scenario answer, to text."""

from api.csvfile import decimal, safe, to_csv

# labelled as REASON_LABELS in web/src/lib/results.ts; tests/api/test_exports.py keeps the two in step
EVENT_REASONS = {
    "not_significant": "Não significativo",
    "illogical_direction": "Direção ilógica (KPI contra o investimento)",
    "poor_fit": "Ajuste ruim no pré-período",
    "analysis_failed": "A análise do evento falhou",
    "not_selected": "Superado por outro evento do mesmo período",
    "placebo_failed": "Reprovado no placebo: o modelo acha efeito numa data sem intervenção",
    "insufficient_run": "Os dados desta execução não sustentam publicar lift",
    "model_dependent": "O efeito só aparece com as variáveis de mídia do modelo",
    "control_rejected": "Um controle foi descartado por acompanhar o investimento do canal",
}

EVENTS_HEADER = [
    "Evento",
    "Canais",
    "Início",
    "Fim",
    "Veredito",
    "Motivos",
    "Lift",
    "Lift IC inferior",
    "Lift IC superior",
    "Lift %",
    "p-valor",
    "Variação do investimento %",
    "Investimento incremental",
    "CPA incremental",
    "R²",
    "WMAPE",
    "Placebo p-valor",
    "Robustez p-valor",
]

# (label, key, decimals, revenue mode only)
TABLE_COLUMNS = [
    ("Investimento", "investment", 2, False),
    ("KPI", "kpi", 2, False),
    ("KPI p5", "kpi_lo", 2, False),
    ("KPI p95", "kpi_hi", 2, False),
    ("Receita", "revenue", 2, True),
    ("CPA", "cpa", 2, False),
    ("ROAS", "roas", 4, True),
    ("Investimento incremental", "incremental_investment", 2, False),
    ("KPI incremental", "incremental_kpi", 2, False),
    ("iCPA", "icpa", 2, False),
    ("iROAS", "iroas", 4, True),
]
CURVE_COLUMNS = [
    ("Investimento", "investment", 2, False),
    ("KPI", "kpi", 2, False),
    ("KPI p5", "kpi_lo", 2, False),
    ("KPI p95", "kpi_hi", 2, False),
    ("Receita", "revenue", 2, True),
    ("CPA", "cpa", 2, False),
    ("iCPA", "icpa", 2, False),
    ("ROAS", "roas", 4, True),
    ("iROAS", "iroas", 4, True),
    ("Investimento incremental", "incremental_investment", 2, False),
    ("KPI incremental", "incremental_kpi", 2, False),
    ("% incrementalidade", "pct_incrementality", 2, False),
]
RAMP_HEADER = ["Cenário", "Degrau", "Investimento", "KPI", "KPI p5", "KPI p95"]
SCENARIOS = [("current", "Atual"), ("recommended", "Recomendado"), ("saturation", "Saturação")]


def _day(iso: str | None) -> str:
    return f"{iso[8:10]}/{iso[5:7]}/{iso[:4]}" if iso else ""


def _p_value(value: float | None) -> str:
    # p-values reach 1e-40: three significant digits, not a fixed number of decimals
    return "" if value is None else f"{value:.3g}".replace(".", ",")


def _yes_no(value: bool | None) -> str:
    return "" if value is None else "sim" if value else "não"


def _event_row(event: dict) -> list[str]:
    row = [
        safe(event["id"]),
        safe(" + ".join(event["channels"])),
        _day(event.get("start")),
        _day(event.get("end")),
        "publicado" if event["status"] == "published" else "rejeitado",
        " · ".join(EVENT_REASONS.get(r, r) for r in event.get("reasons") or []),
    ]
    # a rejected event's numbers stay out of every export, as on the screen (docs/decisoes/dashboards.md)
    if event["status"] != "published":
        return row + [""] * (len(EVENTS_HEADER) - len(row))
    lift = event.get("lift") or {}
    lo, hi = lift.get("ci") or (None, None)
    fit = event.get("fit") or {}
    return row + [
        decimal(lift.get("abs")),
        decimal(lo),
        decimal(hi),
        decimal(lift.get("rel_pct")),
        _p_value(event.get("p_value")),
        decimal(event.get("investment_change_pct")),
        decimal(event.get("incremental_investment")),
        decimal(event.get("cpa_incremental")),
        decimal(fit.get("r2"), 4),
        decimal(fit.get("wmape"), 4),
        _p_value((event.get("placebo") or {}).get("p_value")),
        _p_value((event.get("robustness") or {}).get("p_value")),
    ]


def events_csv(results: dict) -> str:
    return to_csv(EVENTS_HEADER, [_event_row(e) for e in results["causal"]["events"]])


def _shown(columns: list[tuple], revenue_mode: bool) -> list[tuple]:
    return [c for c in columns if revenue_mode or not c[3]]


def scenario_csv(answer: dict) -> str:
    columns = _shown(TABLE_COLUMNS, answer["revenue_mode"])
    scenarios = [(label, answer[key]) for key, label in SCENARIOS if answer[key]]
    lines = [
        [
            label,
            *(decimal(row[key], digits) for _, key, digits, _ in columns),
            _yes_no(row["extrapolated"]),
            " · ".join(row["notes"]),
        ]
        for label, row in scenarios
    ]
    ramp = [
        [label, step["step"], *(decimal(step[k]) for k in ("investment", "kpi", "kpi_lo", "kpi_hi"))]
        for label, row in scenarios
        for step in row["ramp"] or []
    ]
    if ramp:
        lines += [[], RAMP_HEADER, *ramp]
    return to_csv(["Cenário", *(c[0] for c in columns), "Extrapolado", "Notas"], lines)


def curve_csv(answer: dict) -> str:
    columns = _shown(CURVE_COLUMNS, answer["revenue_mode"])
    lines = [
        [
            *(decimal(point[key], digits) for _, key, digits, _ in columns),
            _yes_no(point["extrapolated"]),
            _yes_no(point["in_filter"]),
        ]
        for point in answer["curve"]
    ]
    return to_csv([*(c[0] for c in columns), "Extrapolado", "No filtro"], lines)
