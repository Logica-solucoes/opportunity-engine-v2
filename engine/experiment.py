"""Experiment designer (A7): how long a test must run to see the target lift, and the budget it puts at risk.

Provisional formula until Data Science signs it off: MDE of the KPI summed over T periods at 95% confidence and 80%
power, 2.8 * sigma * sqrt(f * T), with sigma the residual noise of the KPI around trend (+ day of week on daily data)
and f the AR(1) variance factor of those residuals.
"""

import math

import numpy as np
import pandas as pd

from engine.results_schema import ExperimentCell, ExperimentDesign

Z = 1.96 + 0.84
MIN_PERIODS = 30
WINDOW_DAYS = 90
MAX_RHO = 0.95  # rho -> 1 would blow f up; a negative rho would shrink the MDE, so it is floored at 0


def _noise(window: pd.DataFrame, daily: bool) -> tuple[float, float]:
    y = window["kpi"].to_numpy(dtype=float)
    t = np.arange(len(y), dtype=float)
    columns = [np.ones_like(t), t]
    if daily:
        dow = window["Date"].dt.dayofweek.to_numpy()
        columns += [(dow == d).astype(float) for d in range(1, 7)]
    x = np.column_stack(columns)
    beta, *_ = np.linalg.lstsq(x, y, rcond=None)
    e = y - x @ beta
    sigma = math.sqrt(float(e @ e) / (len(y) - x.shape[1]))
    rho = float(np.corrcoef(e[1:], e[:-1])[0, 1]) if sigma > 0 else 0.0
    return sigma, min(max(rho if math.isfinite(rho) else 0.0, 0.0), MAX_RHO)


def _assumptions(target_lift: float) -> list[str]:
    pct = f"{target_lift * 100:g}".replace(".", ",")
    return [
        "O efeito mínimo detectável vem do ruído do KPI em torno da tendência e do dia da semana; a mídia fica "
        "dentro desse ruído, então a estimativa é conservadora.",
        f"A duração é a mesma para todos os canais: o efeito-alvo é {pct}% do KPI total, e desligar um canal "
        "pequeno dificilmente move tanto.",
        "Fórmula provisória (95% de confiança, 80% de poder, correção de autocorrelação AR(1)) até a validação "
        "da Data Science.",
    ]


def design(
    kpi_df: pd.DataFrame,
    spend_df: pd.DataFrame,
    period_days: int,
    target_lift: float,
    max_days: int,
    budget_step: float,
) -> ExperimentDesign:
    base = {"period_days": period_days, "target_lift": target_lift, "assumptions": _assumptions(target_lift)}
    kpi = kpi_df.sort_values("Date")
    if len(kpi) < MIN_PERIODS:
        return ExperimentDesign(status="insufficient_history", reasons=["short_history"], **base)

    window = kpi.tail(max(MIN_PERIODS, math.ceil(WINDOW_DAYS / period_days)))
    mean = float(window["kpi"].mean())
    if not math.isfinite(mean) or mean <= 0:
        return ExperimentDesign(status="insufficient_history", reasons=["degenerate_kpi"], **base)
    sigma, rho = _noise(window, daily=period_days == 1)
    if not math.isfinite(sigma) or sigma <= 1e-9 * mean:
        return ExperimentDesign(status="insufficient_history", reasons=["degenerate_kpi"], **base)

    f = (1 + rho) / (1 - rho)
    periods = max(1, math.ceil((Z * sigma * math.sqrt(f) / (target_lift * mean)) ** 2))
    max_periods = max_days // period_days
    if max_periods < 1:
        return ExperimentDesign(status="insufficient_history", reasons=["duration_capped"], **base)
    feasible = periods <= max_periods
    periods = min(periods, max_periods)
    mde_abs = Z * sigma * math.sqrt(f * periods)

    in_window = spend_df[spend_df["Date"].isin(window["Date"])]
    per_period = (in_window.groupby("Product Group")["investment"].sum() / len(window)).sort_values(kind="stable")
    cells = []
    for channel, spend in per_period[per_period > 0].items():
        risk = float(spend) * periods
        cells += [
            ExperimentCell(
                channel=str(channel), test_type="on_off", step=None, spend_per_period=float(spend), budget_at_risk=risk
            ),
            ExperimentCell(
                channel=str(channel),
                test_type="step_up",
                step=budget_step,
                spend_per_period=float(spend),
                budget_at_risk=budget_step * risk,
            ),
        ]

    return ExperimentDesign(
        status="ok",
        reasons=[] if feasible else ["duration_capped"],
        sigma=sigma,
        rho=rho,
        kpi_per_period=mean,
        duration_periods=periods,
        duration_days=periods * period_days,
        feasible=feasible,
        mde_abs=mde_abs,
        mde_rel=mde_abs / (mean * periods),
        designs=cells,
        **base,
    )
