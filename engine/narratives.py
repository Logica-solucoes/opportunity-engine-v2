"""LLM narratives of a run (A9): one per published event and one global, built only from the results.json the engine
already published, checked by `grounding`, regenerated once, and replaced by a deterministic text when they fail."""

import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from engine import grounding
from engine.config import EngineConfig
from engine.errors import EngineError
from engine.scenario import ScenarioFilters, scenario
from llm.base import LLM, LLMBadOutput, LLMError, LLMRefused, LLMUnavailable

log = logging.getLogger(__name__)

# per call: a provider retrying a 503 for minutes would freeze the log; the first call of a run pays it in full before
# LLMUnavailable stops the others
TIMEOUT_S = 60
# the whole narrative step must fit well inside the 20 min worker watchdog (api/runs.py)
LLM_BUDGET_S = 300
DEADLINE_RESERVE_S = 2 * TIMEOUT_S + 60  # a job's worst case (2 tries) plus writing results.json, before RUN_DEADLINE
CI_LEVEL_PCT = 95
SEVERITY = {"passed": 0, "regenerated": 1, "blocked": 2}
ELASTICITY_REASONS = {
    "no_identifiable_channel": "nenhum canal tem efeito identificável",
    "model_failed": "o modelo de elasticidade falhou",
    "cv_in_sample": "o histórico é curto e o modelo não foi validado fora da amostra",
}
SCENARIO_LABELS = {"current": "Atual", "recommended": "Recomendado", "saturation": "Saturação"}
FEEDBACK = {
    "number": "número que não está nos dados",
    "channel": "canal que não pode ser citado",
    "output": "resposta fora do formato pedido",
}


class EventNarrative(BaseModel):
    title: str
    verdict: str
    analysis: str
    next_steps: list[str] = Field(max_length=3)


class ScenarioNote(BaseModel):
    name: str
    analysis: str


class GlobalNarrative(BaseModel):
    title: str
    summary: str
    scenarios: list[ScenarioNote] = Field(max_length=4)
    recommendations: list[str] = Field(max_length=3)


RULES = """Regras:
- Escreva em português do Brasil, em tom executivo e direto.
- Use só números que estão nos dados abaixo. Pode arredondar, mas não calcule nenhum número novo.
- Cite só estes canais: {channels}. Não cite nenhum outro.
- O KPI se chama "{kpi}".
- Escreva datas como DD/MM/AAAA.
- Escreva números no formato brasileiro (vírgula decimal, ponto de milhar), com no máximo 2 casas decimais; valores em reais com R$.
- Escreva p-valores abaixo de 0,0001 como "p < 0,0001".
"""
EVENT_PROMPT = (
    "Escreva um relatório curto sobre um evento de investimento em mídia. O efeito no KPI foi estimado por um modelo "
    "causal e passou nos critérios de publicação.\n\n" + RULES + "\nDados (JSON):\n{data}\n"
)
GLOBAL_PROMPT = (
    "Escreva um resumo da análise de elasticidade do investimento em mídia (curva de resposta e cenários mensais)."
    "\n{status_rule}\n\n" + RULES + "\nDados (JSON):\n{data}\n"
)
NOT_OK_RULE = (
    "A análise não é conclusiva (veja status e reasons). Explique só por que ela não é conclusiva e não sugira "
    "valores de investimento."
)
CAVEAT_RULE = "A análise tem ressalvas (veja reasons): apresente os valores, sempre junto dessas ressalvas."
P_FLOOR = 0.0001


def _sig(obj: Any) -> Any:
    """Floats to 4 significant digits, recursively: the model copies what it is given."""
    if isinstance(obj, float):
        return float(f"{obj:.4g}")
    if isinstance(obj, dict):
        return {k: _sig(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_sig(v) for v in obj]
    return obj


def _br(value: float, decimals: int) -> str:
    return f"{value:,.{decimals}f}".translate(str.maketrans(",.", ".,"))


def _money(value: float) -> str:
    return f"R$ {_br(value, 2)}"


def _day(iso: str) -> str:
    year, month, day = iso[:10].split("-")
    return f"{day}/{month}/{year}"


def _p(value: float) -> str:
    return f"< {_br(P_FLOOR, 4)}" if value < P_FLOOR else _br(value, 4)


def _days_between(start: str | None, end: str | None) -> int | None:
    if not start or not end:
        return None
    return (date.fromisoformat(end[:10]) - date.fromisoformat(start[:10])).days


def text_of(obj: Any) -> str:
    if isinstance(obj, str):
        return obj
    if isinstance(obj, dict):
        return " ".join(text_of(v) for v in obj.values())
    if isinstance(obj, list):
        return " ".join(text_of(v) for v in obj)
    return ""


def event_payload(
    event: dict, kpi: str, p_value_threshold: float, sufficiency_reasons: list[str], period_days: int = 1
) -> dict:
    fit = event.get("fit") or {}
    days = _days_between(event.get("start"), event.get("end"))
    return _sig(
        {
            "kpi_name": kpi,
            "p_value_threshold": p_value_threshold,
            "ci_level_pct": CI_LEVEL_PCT,
            "channels": event["channels"],
            "start": event.get("start"),
            "end": event.get("end"),
            "post_period_days": None if days is None else days + period_days,  # `end` is the last period's start
            "investment_change_pct": event.get("investment_change_pct"),
            "lift": event.get("lift"),
            "p_value": event.get("p_value"),
            "incremental_investment": event.get("incremental_investment"),  # post-period spend minus the baseline
            "cpa_incremental": event.get("cpa_incremental"),
            "fit": {"r2": fit.get("r2"), "wmape": fit.get("wmape")},
            "placebo_p_value": (event.get("placebo") or {}).get("p_value"),
            "robustness_p_value": (event.get("robustness") or {}).get("p_value"),
            "sufficiency_reasons": sufficiency_reasons,
        }
    )


def global_payload(document: dict, config: EngineConfig, kpi: str, revenue: bool) -> dict | None:
    payload = _global_payload(document, config, kpi, revenue)
    return None if payload is None else _sig(payload)


def _global_payload(document: dict, config: EngineConfig, kpi: str, revenue: bool) -> dict | None:
    elasticity = document.get("elasticity")
    if not elasticity:
        return None
    channels = elasticity.get("channels") or []
    payload = {
        "kpi_name": kpi,
        "revenue_mode": revenue,
        "status": elasticity["status"],
        "reasons": [ELASTICITY_REASONS.get(r, r) for r in elasticity.get("reasons") or []],
        "channels_without_identifiable_effect": sum(1 for c in channels if not c.get("identifiable")),
    }
    # the narrative follows the Elasticity tab: whatever `scenario` serves (a short history included) gets described
    try:
        answer = scenario(document, ScenarioFilters(), config.max_budget_step)
    except EngineError:
        answer = None
    if answer is None and elasticity["status"] != "ok":
        return payload
    metrics = elasticity.get("metrics") or {}
    keys = ("cv_r2", "r2", "media_contribution_pct", "low_confidence", "reallocation_suppressed")
    payload["metrics"] = {k: metrics.get(k) for k in keys}
    payload["channels"] = [
        {"name": c["name"], "contribution_pct": c.get("contribution_pct"), "K": (c.get("hill") or {}).get("K")}
        for c in channels
        if c.get("identifiable")
    ]
    if answer is None:
        return payload
    revenue = answer.get("revenue_mode", revenue)
    payload["revenue_mode"] = revenue
    fields = ("investment", "kpi", "kpi_lo", "kpi_hi", "extrapolated", "icpa") + (("roas", "iroas") if revenue else ())
    payload["scenarios_monthly"] = {
        name: {k: answer[name].get(k) for k in fields} for name in SCENARIO_LABELS if answer.get(name)
    }
    return payload


def universe(document: dict) -> set[str]:
    """Every channel name the run knows: the check rejects any of them outside the published set."""
    names = set((document.get("validation") or {}).get("channels") or [])
    elasticity = document.get("elasticity") or {}
    names |= {c["name"] for c in elasticity.get("channels") or []}
    names |= {g["name"] for g in elasticity.get("groups") or []}
    for event in (document.get("causal") or {}).get("events") or []:
        names |= set(event["channels"])
    return names


def deterministic_event(p: dict) -> dict:
    lift = p.get("lift") or {}
    period = f"{_day(p['start'])} a {_day(p['end'])}" if p.get("start") and p.get("end") else ""
    title = " · ".join(part for part in (", ".join(p["channels"]), period) if part)
    if lift.get("abs") is None:
        verdict = "Evento publicado sem estimativa de lift."
    else:
        verdict = f"{'Aumento' if lift['abs'] >= 0 else 'Queda'} de {_br(abs(lift['abs']), 0)} em {p['kpi_name']}"
        if lift.get("rel_pct") is not None:
            verdict += f" ({_br(abs(lift['rel_pct']), 1)}%)"
        ci = lift.get("ci") or [None, None]
        if None not in ci:
            verdict += f", IC {CI_LEVEL_PCT}% [{_br(ci[0], 0)}; {_br(ci[1], 0)}]"
        if p.get("p_value") is not None:
            verdict += f", p-valor {_p(p['p_value'])}"
        verdict += "."
    fit = p.get("fit") or {}
    facts = []
    if p.get("incremental_investment") is not None:
        facts.append(f"investimento incremental de {_money(p['incremental_investment'])}")
    if p.get("cpa_incremental") is not None:
        facts.append(f"CPA incremental de {_money(p['cpa_incremental'])}")
    if fit.get("r2") is not None:
        facts.append(f"R² de {_br(fit['r2'], 2)} no pré-período")
    if fit.get("wmape") is not None:
        facts.append(f"WMAPE fora da amostra de {_br(fit['wmape'] * 100, 1)}%")
    analysis = "; ".join(facts)
    analysis = analysis[:1].upper() + analysis[1:] + "." if analysis else ""
    return {"title": title, "verdict": verdict, "analysis": analysis, "next_steps": []}


def deterministic_global(p: dict) -> dict:
    scenarios = p.get("scenarios_monthly") or {}
    if not scenarios:
        reasons = [ELASTICITY_REASONS.get(r, r) for r in p["reasons"]] or ["não há curva de resposta para simular"]
        summary = "A análise de elasticidade não é conclusiva: " + "; ".join(reasons) + "."
        if p["channels_without_identifiable_effect"]:
            summary += f" Canais sem efeito identificável: {p['channels_without_identifiable_effect']}."
        return {"title": "Elasticidade não conclusiva", "summary": summary, "scenarios": [], "recommendations": []}
    rows = []
    for name, s in scenarios.items():
        if s.get("investment") is None:
            continue
        text = f"Investimento mensal de {_money(s['investment'])}"
        if s.get("kpi") is not None:
            text += f" e {p['kpi_name']} de {_br(s['kpi'], 0)}"
        if s.get("kpi_lo") is not None and s.get("kpi_hi") is not None:
            text += f" (faixa de {_br(s['kpi_lo'], 0)} a {_br(s['kpi_hi'], 0)})"
        rows.append({"name": SCENARIO_LABELS[name], "analysis": text + "."})
    summary = "Valores mensais da curva de resposta, sem filtros de meta."
    if p["reasons"]:
        summary += " Ressalva: " + "; ".join(p["reasons"]) + "."
    return {
        "title": "Elasticidade do investimento",
        "summary": summary,
        "scenarios": rows,
        "recommendations": [],
    }


@dataclass(frozen=True)
class Kind:
    prompt: str
    model: type[BaseModel]
    fallback: Callable[[dict], dict]


EVENT = Kind(EVENT_PROMPT, EventNarrative, deterministic_event)
GLOBAL = Kind(GLOBAL_PROMPT, GlobalNarrative, deterministic_global)


def _feedback(issues: list[dict]) -> str:
    lines = "\n".join(f"- {FEEDBACK[i['kind']]}: {i['value']}" for i in issues)
    return f"\n\nSua resposta anterior foi recusada. Corrija:\n{lines}"


def _status_rule(payload: dict) -> str:
    if payload.get("status", "ok") == "ok":
        return ""
    return CAVEAT_RULE if payload.get("scenarios_monthly") else NOT_OK_RULE


def _ask(llm: LLM, kind: Kind, payload: dict, published: set[str], names: set[str]) -> tuple[dict | None, dict]:
    prompt = kind.prompt.format(
        channels=", ".join(sorted(published)) or "nenhum",
        kpi=payload["kpi_name"],
        status_rule=_status_rule(payload),
        data=json.dumps(payload, ensure_ascii=False, indent=2),
    )
    first: list[dict] = []
    issues: list[dict] = []
    for _ in range(2):
        try:
            answer = llm.generate_json(
                prompt + (_feedback(issues) if issues else ""), kind.model.model_json_schema(), timeout_s=TIMEOUT_S
            )
            narrative = kind.model.model_validate(answer).model_dump()
            issues = grounding.check(text_of(narrative), payload, published, names)
        except (LLMBadOutput, LLMRefused) as e:
            issues = [{"kind": "output", "value": str(e) or type(e).__name__}]
        except ValidationError:
            issues = [{"kind": "output", "value": "bad_shape"}]
        if not issues:
            return narrative, {"status": "regenerated" if first else "passed", "issues": first}
        first = first or issues
    return None, {"status": "blocked", "issues": issues}


def _summary(reports: dict) -> dict | None:
    judged = [
        (key, report["grounding"])
        for key, report in [*reports["events"].items(), ("global", reports["global"])]
        if report and report["grounding"]
    ]
    if not judged:
        return None
    return {
        "status": max((g["status"] for _, g in judged), key=SEVERITY.__getitem__),
        "issues": [{"report": key, **issue} for key, g in judged for issue in g["issues"]],
    }


def _published_by_elasticity(document: dict, payload: dict) -> set[str]:
    """Identifiable channels and, for a published group, its members: the group is a channel the run names itself."""
    published = {c["name"] for c in payload.get("channels", [])}
    members = {g["name"]: g.get("members") or [] for g in (document.get("elasticity") or {}).get("groups") or []}
    return published.union(*(members.get(name, []) for name in published))


def jobs(document: dict, config: EngineConfig) -> list[tuple[str, Kind, dict, set[str]]]:
    """What `build` asks the LLM about: (key, kind, payload, channels it may cite) per published event, then the global."""
    kpi = config.column_mapping.get("performance_file", {}).get("kpi_col") or "KPI"
    revenue = config.kpi_is_monetary or config.optimization_target == "REVENUE"
    sufficiency = (document.get("sufficiency") or {}).get("reasons") or []
    period_days = (document.get("validation") or {}).get("period_days") or 1
    found = [
        (
            event["id"],
            EVENT,
            event_payload(event, kpi, config.p_value_threshold, sufficiency, period_days),
            set(event["channels"]),
        )
        for event in (document.get("causal") or {}).get("events") or []
        if event["status"] == "published"
    ]
    payload = global_payload(document, config, kpi, revenue)
    if payload is not None:
        found.append(("global", GLOBAL, payload, _published_by_elasticity(document, payload)))
    return found


def build(document: dict, config: EngineConfig, llm: LLM | None) -> dict:
    """The `reports` section: a narrative per published event and a global one, each from the LLM when it passes the
    grounding check (at most two tries) or the deterministic text otherwise."""
    names = universe(document)
    jobs_ = jobs(document, config)
    if llm is not None and jobs_:
        log.info("Gerando as narrativas com a IA e conferindo os números (grounding)...")

    started = time.monotonic()
    budget = min(LLM_BUDGET_S, float(os.environ.get("RUN_DEADLINE", "inf")) - time.time() - DEADLINE_RESERVE_S)
    reports: dict = {"events": {}, "global": None, "grounding": None}
    for key, kind, payload, published in jobs_:
        narrative, judged = None, None
        if llm is not None and time.monotonic() - started > budget:
            log.warning("AVISO: o tempo reservado para a IA acabou; os próximos relatórios usarão o texto padrão.")
            llm = None
        if llm is not None and payload.get("status") != "failed":
            try:
                narrative, judged = _ask(llm, kind, payload, published, names)
            except LLMError as e:  # unavailable, bad key or any failure that is not about the output: stop asking
                reason = e.reason if isinstance(e, LLMUnavailable) else str(e) or type(e).__name__
                log.warning(f"AVISO: o serviço de IA falhou ({reason}); os próximos relatórios usarão o texto padrão.")
                llm = None
            except Exception:
                log.error(f"Não foi possível gerar a narrativa {key}", exc_info=True)
        if judged and judged["status"] == "blocked":
            log.warning(f"   - A narrativa {key} citou números ou canais fora do resultado; vale o texto padrão.")
        report = {"source": "llm", **narrative} if narrative else {"source": "deterministic", **kind.fallback(payload)}
        report["grounding"] = judged
        if key == "global":
            reports["global"] = report
        else:
            reports["events"][key] = report
    reports["grounding"] = _summary(reports)
    return reports
