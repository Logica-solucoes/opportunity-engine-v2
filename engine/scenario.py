"""Planner guardrails and the interactive scenario (A8). Pure over the results.json dict: no model, no I/O."""

import numpy as np

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
    if not current or current <= 0 or abs(target / current - 1) <= max_step + _TOLERANCE:
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
