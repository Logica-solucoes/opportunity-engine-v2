"""Planner guardrails and the interactive scenario (A8). Pure over the results.json dict: no model, no I/O."""

import math
from typing import Self

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from engine.errors import EngineError

DAYS_PER_MONTH = 30
NO_CURVE = "Esta execução não tem curva de resposta para simular cenários."

TCPA_NOTE = (
    "Campanhas com CPA desejado (tCPA): mudar a verba pode pedir ajuste do CPA desejado. Espere o período de "
    "aprendizado do lance automático antes de ler o resultado ou dar o próximo degrau."
)
TROAS_NOTE = (
    "Campanhas com ROAS desejado (tROAS): mudar a verba pode pedir ajuste do ROAS desejado. Espere o período de "
    "aprendizado do lance automático antes de ler o resultado ou dar o próximo degrau."
)
_TOLERANCE = 1e-9


def bid_note(revenue_mode: bool) -> str:
    return TROAS_NOTE if revenue_mode else TCPA_NOTE


def _at(investment: float, curve: list[dict], key: str) -> float | None:
    values = [row[key] for row in curve]
    if not curve or any(v is None for v in values):
        return None
    return float(np.interp(investment, [row["investment"] for row in curve], values))


def ramp(current: float | None, target: float, max_step: float, curve: list[dict]) -> list[dict] | None:
    """Compounding steps of at most `max_step` from `current` to `target` (the last one lands on it), with KPI and
    band interpolated on `curve` (ascending investment). None when a single move is within the step."""
    # cutting to 0 is a pause, not a bid change: nothing to ramp (and compounding cuts never reach 0)
    if not current or not (0 < current < math.inf and 0 < target < math.inf):
        return None
    if abs(target / current - 1) <= max_step + _TOLERANCE:
        return None
    up = target > current
    factor = 1 + max_step if up else 1 - max_step
    tolerance = _TOLERANCE * current
    levels, level = [], current
    while True:
        level *= factor
        if (level >= target - tolerance) if up else (level <= target + tolerance):
            levels.append(target)
            break
        levels.append(level)
    return [
        {
            "step": i,
            "investment": investment,
            "kpi": _at(investment, curve, "kpi"),
            "kpi_lo": _at(investment, curve, "kpi_lo"),
            "kpi_hi": _at(investment, curve, "kpi_hi"),
        }
        for i, investment in enumerate(levels, 1)
    ]


class ScenarioFilters(BaseModel):
    """The planner filters, all monthly and optional (streamlit_app.py:2208-2232)."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    min_budget: float | None = Field(default=None, ge=0)
    max_budget: float | None = Field(default=None, ge=0)
    target_cpa: float | None = Field(default=None, gt=0)
    target_icpa: float | None = Field(default=None, gt=0)
    min_roas: float | None = Field(default=None, ge=0)
    min_iroas: float | None = Field(default=None, ge=0)
    min_kpi: float | None = Field(default=None, ge=0)
    min_incrementality_pct: float | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def _budget_range(self) -> Self:
        if self.min_budget is not None and self.max_budget is not None and self.min_budget > self.max_budget:
            raise ValueError("o orçamento mínimo passa do máximo")
        return self


def _scaled(value: float | None, factor: float) -> float | None:
    return None if value is None else value * factor


def _ratio(a: float | None, b: float | None) -> float | None:
    return a / b if a is not None and b else None


def _icpa(incremental_investment: float | None, incremental_kpi: float | None) -> float | None:
    # compute_incremental_cpa of the prototype: no KPI gained means no meaningful cost, not a cost of 0
    if incremental_investment is None or incremental_kpi is None or incremental_kpi <= 0:
        return None
    return incremental_investment / incremental_kpi


def _curve_row(row: dict, factor: float) -> dict:
    investment, kpi = row["investment"] * factor, _scaled(row["kpi"], factor)
    revenue = _scaled(row["revenue"], factor)
    incremental_kpi = row["incremental_kpi"]
    return {
        "investment": investment,
        "kpi": kpi,
        "kpi_lo": _scaled(row["kpi_lo"], factor),
        "kpi_hi": _scaled(row["kpi_hi"], factor),
        "revenue": revenue,
        "cpa": _ratio(investment, kpi),
        "icpa": _icpa(row["incremental_investment"], incremental_kpi),
        "roas": _ratio(revenue, investment),
        "iroas": row["iroas"],
        "incremental_investment": _scaled(row["incremental_investment"], factor),
        "incremental_kpi": _scaled(incremental_kpi, factor),
        "pct_incrementality": incremental_kpi / row["kpi"] * 100
        if row["kpi"] and row["kpi"] > 0 and incremental_kpi is not None
        else 0.0,
        "extrapolated": row["extrapolated"],
    }


def _keeps(row: dict, f: ScenarioFilters, revenue_mode: bool) -> bool:
    """Same tests, same order as the Streamlit sidebar; ROAS filters only exist in revenue mode there."""
    return all(
        (
            f.min_budget is None or row["investment"] >= f.min_budget,
            f.max_budget is None or row["investment"] <= f.max_budget,
            f.target_cpa is None or (row["cpa"] is not None and row["cpa"] <= f.target_cpa),
            f.target_icpa is None or (row["icpa"] is not None and row["icpa"] <= f.target_icpa),
            not revenue_mode or f.min_roas is None or (row["roas"] is not None and row["roas"] >= f.min_roas),
            not revenue_mode or f.min_iroas is None or (row["iroas"] or 0.0) >= f.min_iroas,
            f.min_kpi is None or (row["kpi"] is not None and row["kpi"] >= f.min_kpi),
            f.min_incrementality_pct is None or row["pct_incrementality"] >= f.min_incrementality_pct,
        )
    )


def _saturation_index(curve: list[dict], start_investment: float) -> int | None:
    """find_saturation_point (prototype dashboard_charts.py:15): the row right after the last one whose marginal gain
    is above 10% of the peak, searching from `start_investment` up. None means "fall back"."""
    idx = [i for i, row in enumerate(curve) if row["investment"] >= start_investment]
    if len(idx) <= 1:
        return None
    xs = np.array([curve[i]["investment"] for i in idx])
    ys = np.array([curve[i]["kpi"] for i in idx])
    derivative = np.concatenate([[0.0], np.diff(ys) / np.diff(xs)])
    peak = derivative.max()
    if peak <= 0:
        return None
    above = np.where(derivative > peak * 0.1)[0]
    position = above[-1] + 1
    return idx[position] if position < len(idx) else None


def _table_row(point: dict, base: dict, max_step: float, curve: list[dict], note: str) -> dict:
    incremental_investment = point["investment"] - base["investment"]
    incremental_kpi = point["kpi"] - base["kpi"]
    incremental_revenue = (
        point["revenue"] - base["revenue"] if point["revenue"] is not None and base["revenue"] is not None else None
    )
    changes = not math.isclose(point["investment"], base["investment"])
    return {
        "investment": point["investment"],
        "kpi": point["kpi"],
        "kpi_lo": point["kpi_lo"],
        "kpi_hi": point["kpi_hi"],
        "revenue": point["revenue"],
        "cpa": _ratio(point["investment"], point["kpi"]),
        "roas": _ratio(point["revenue"], point["investment"]),
        "incremental_investment": incremental_investment,
        "incremental_kpi": incremental_kpi,
        "icpa": _icpa(incremental_investment, incremental_kpi),
        "iroas": _ratio(incremental_revenue, incremental_investment) if incremental_kpi > 0 else None,
        "extrapolated": point["extrapolated"],
        "ramp": ramp(base["investment"], point["investment"], max_step, curve) if changes else None,
        "notes": [note] if changes else [],
    }


def scenario(results: dict, filters: ScenarioFilters, max_budget_step: float) -> dict:
    """Recommended point, saturation point and the filtered curve for the planner, in monthly values.

    Pure over the results.json dict: the curve is the one the run simulated; filters only pick points of it.
    """
    elasticity = results.get("elasticity") or {}
    rows = elasticity.get("response_curve") or []
    current = next((s for s in elasticity.get("scenarios") or [] if s["name"] == "current"), None)
    period_days = (results.get("validation") or {}).get("period_days")
    usable = rows and all(row["investment"] is not None and row["kpi"] is not None for row in rows)
    if not usable or current is None or current.get("kpi") is None or not period_days:
        raise EngineError(NO_CURVE)

    factor = DAYS_PER_MONTH / period_days
    revenue_mode = any(row["revenue"] is not None for row in rows)
    curve = [_curve_row(row, factor) for row in rows]
    for row in curve:
        row["in_filter"] = _keeps(row, filters, revenue_mode)
    kept = [row for row in curve if row["in_filter"]]
    recommended = max(kept, key=lambda row: row["investment"]) if kept else None

    revenue_per_kpi = next(
        (row["revenue"] / row["kpi"] for row in curve if row["revenue"] is not None and row["kpi"]), None
    )
    base = {
        "investment": current["investment"] * factor,
        "kpi": current["kpi"] * factor,
        "kpi_lo": _scaled(current.get("kpi_lo"), factor),
        "kpi_hi": _scaled(current.get("kpi_hi"), factor),
        "extrapolated": current.get("extrapolated"),
    }
    base["revenue"] = base["kpi"] * revenue_per_kpi if revenue_per_kpi is not None else None

    index = _saturation_index(curve, base["investment"])
    saturation = curve[index] if index is not None else (recommended or curve[-1])

    note = bid_note(revenue_mode)
    current_row = _table_row(base, base, max_budget_step, curve, note)
    current_row["icpa"] = 0.0
    current_row["iroas"] = 0.0 if revenue_mode else None
    return {
        "unit": "month",
        "revenue_mode": revenue_mode,
        "current": current_row,
        "recommended": _table_row(recommended, base, max_budget_step, curve, note) if recommended else None,
        "saturation": _table_row(saturation, base, max_budget_step, curve, note),
        "curve": curve,
    }
