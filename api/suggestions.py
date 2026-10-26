import statistics
from collections.abc import Iterator
from datetime import date
from itertools import pairwise
from pathlib import Path

from api import csvfile

# history step in days -> (label, lowest, highest pre-period in days)
PRE_PERIOD = {1: ("diária", 28, 90), 7: ("semanal", 56, 182)}
# stems of the normalized KPI column name
MONETARY = ("receita", "revenue", "faturamento", "gmv", "valor")
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
