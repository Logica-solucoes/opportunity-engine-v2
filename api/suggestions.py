import json
import logging
import math
import statistics
from collections import defaultdict
from collections.abc import Iterator
from datetime import date
from itertools import pairwise
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ValidationError

from api import csvfile, gemini
from api.engine_config import ParamsIn

log = logging.getLogger(__name__)

# history step in days -> (label, lowest, highest pre-period in days)
PRE_PERIOD = {1: ("diária", 28, 90), 7: ("semanal", 56, 182)}
# stems of the normalized KPI column name
# "value" before "convers": "Conversion value" is revenue, not a count
MONETARY = ("receita", "revenue", "faturamento", "gmv", "valor", "value")
CONVERSIONS = ("convers", "venda", "pedido", "lead")


def suggestion(value, reason: str) -> dict:
    return {"value": value, "reason": reason, "source": "dados"}


def columns(path: Path, *names: str) -> Iterator[list[str]]:
    rows = csvfile.rows(path)
    header = [c.strip() for c in next(rows)]
    at = [header.index(n) for n in names]
    for row in rows:
        if len(row) > max(at):
            yield [row[i].strip() for i in at]


def parse_date(text: str) -> date | None:
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def history(path: Path, date_col: str) -> tuple[int | None, list[date]]:
    """(step in days if daily or weekly, sorted distinct dates); unreadable dates are skipped."""
    dates = sorted({d for (text,) in columns(path, date_col) if (d := parse_date(text))})
    gaps = [(b - a).days for a, b in pairwise(dates)]
    step = statistics.median(gaps) if gaps else None
    return (int(step) if step in PRE_PERIOD else None), dates


def pre_period(step: int, dates: list[date]) -> dict:
    label, lowest, highest = PRE_PERIOD[step]
    span = (dates[-1] - dates[0]).days + step
    quarter = span // 4
    if quarter < lowest:
        return suggestion(lowest, f"Mínimo para série {label}: o histórico tem só {span} dias.")
    if quarter > highest:
        return suggestion(highest, f"Teto para série {label}: um quarto dos {span} dias passaria disso.")
    return suggestion(quarter, f"Um quarto dos {span} dias de histórico.")


def from_data(paths: dict[str, Path | None], mapping: dict) -> dict[str, dict]:
    performance = mapping["performance_file"]
    found = {}
    step, dates = history(paths["performance_file"], performance["date_col"])
    if step:
        found["min_pre_period_days"] = pre_period(step, dates)

    kpi = csvfile.normalize(performance["kpi_col"])
    name = performance["kpi_col"]
    if any(stem in kpi for stem in MONETARY):
        reason = f"A coluna de KPI se chama '{name}', um valor em dinheiro."
        found["optimization_target"] = suggestion("REVENUE", reason)
        found["kpi_is_monetary"] = suggestion(True, reason)
    elif any(stem in kpi for stem in CONVERSIONS):
        reason = f"A coluna de KPI se chama '{name}', uma contagem de conversões."
        found["optimization_target"] = suggestion("CONVERSIONS", reason)
        found["kpi_is_monetary"] = suggestion(False, reason)
    return found


def field_paths(model: type[BaseModel] = ParamsIn, prefix: str = "") -> list[str]:
    paths = []
    for name, field in model.model_fields.items():
        if isinstance(field.annotation, type) and issubclass(field.annotation, BaseModel):
            paths += field_paths(field.annotation, f"{prefix}{name}.")
        else:
            paths.append(prefix + name)
    return paths


PARAM_PATHS = tuple(field_paths())


class GeminiSuggestion(BaseModel):
    field: Literal[PARAM_PATHS]
    # a string so the schema stays simple; ParamsIn coerces "2" or "true" to the field's type
    value: str
    reason: str


class GeminiAnswer(BaseModel):
    suggestions: list[GeminiSuggestion]


PROMPT = """Você ajuda um analista de mídia a configurar uma análise de investimento em mídia.
Com base no resumo dos dados abaixo, sugira valores para os parâmetros do schema que dá para justificar com esses dados.
Para cada sugestão, explique em uma frase curta, em português do Brasil, por que o valor faz sentido.
Não sugira o que o resumo não justifica.

Resumo dos dados:
{summary}

Schema dos parâmetros:
{schema}
"""


def number(text: str) -> float | None:
    # exports come as "R$ 1.234,56" (pt-BR) or "1,234.56": the rightmost separator is the decimal one,
    # unless it repeats ("1.234.567"), then it only groups thousands
    for noise in ("R$", "$", " ", "\xa0"):
        text = text.replace(noise, "")
    decimal, thousands = (",", ".") if text.rfind(",") > text.rfind(".") else (".", ",")
    text = text.replace(thousands, "")
    if text.count(decimal) > 1:
        text = text.replace(decimal, "")
    text = text.replace(decimal, ".")
    try:
        n = float(text)
    except ValueError:
        return None
    return n if math.isfinite(n) else None


def summary(paths: dict[str, Path | None], mapping: dict) -> dict:
    """Aggregates only: no row of the client's files leaves the platform."""
    investment, performance = mapping["investment_file"], mapping["performance_file"]
    spend = defaultdict(float)
    for channel, value in columns(paths["investment_file"], investment["channel_col"], investment["investment_col"]):
        if (n := number(value)) is not None:
            spend[channel] += n
    kpi = [
        n for (value,) in columns(paths["performance_file"], performance["kpi_col"]) if (n := number(value)) is not None
    ]
    step, dates = history(paths["performance_file"], performance["date_col"])
    total = sum(spend.values())
    return {
        "kpi_column": performance["kpi_col"],
        "mapped_columns": mapping,
        "cadence": {1: "daily", 7: "weekly"}.get(step),
        "period": [dates[0].isoformat(), dates[-1].isoformat()] if dates else None,
        "total_investment": round(total, 2),
        "channels": [
            {"name": channel, "investment_share_pct": round(100 * s / total, 1) if total else 0}
            for channel, s in sorted(spend.items())
        ],
        "kpi": {"min": min(kpi), "mean": round(statistics.fmean(kpi), 2), "max": max(kpi)} if kpi else None,
    }


def checked(path: str, value: str):
    """The value coerced by ParamsIn; raises ValidationError when the field rejects it."""
    params = ParamsIn().model_dump()
    *parents, leaf = path.split(".")
    node = params
    for key in parents:
        node = node[key]
    node[leaf] = value
    valid = ParamsIn.model_validate(params).model_dump(mode="json")
    for key in parents:
        valid = valid[key]
    return valid[leaf]


def from_gemini(paths: dict[str, Path | None], mapping: dict) -> dict[str, dict] | None:
    """None when Gemini can't answer; the form keeps the data suggestions."""
    prompt = PROMPT.format(
        summary=json.dumps(summary(paths, mapping), ensure_ascii=False),
        schema=json.dumps(ParamsIn.model_json_schema(), ensure_ascii=False),
    )
    try:
        items = json.loads(gemini.ask(prompt, GeminiAnswer.model_json_schema()))["suggestions"]
    except gemini.Unavailable as e:
        log.warning("simulation.gemini_unavailable reason=%s", e)
        return None
    except (ValueError, KeyError, TypeError):
        items = None
    if not isinstance(items, list):
        log.warning("simulation.gemini_unavailable reason=bad_answer")
        return None

    found = {}
    # one by one: a bad item drops only itself, not the whole answer
    for item in items:
        try:
            s = GeminiSuggestion.model_validate(item)
            value = checked(s.field, s.value)
        except ValidationError:
            # model output: cap it before it reaches the log
            log.info(
                "simulation.gemini_dropped field=%r", str(item.get("field"))[:60] if isinstance(item, dict) else None
            )
            continue
        found[s.field] = {"value": value, "reason": s.reason[:300], "source": "gemini"}
    return found
