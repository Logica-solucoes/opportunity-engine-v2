"""Builds, sanitizes and writes results.json from what `compute()` produced. No statistics happen here."""

import math
from typing import TYPE_CHECKING, Any

import pandas as pd

from engine.results_schema import (
    AccuracyPoint,
    Causal,
    CausalEvent,
    EventDetected,
    EventSeries,
    Fit,
    InvestmentPoint,
    KpiPoint,
    Lift,
    LinePoint,
)

if TYPE_CHECKING:
    from engine.pipeline import Computed, EventOutcome


def sanitize(obj: Any) -> Any:
    """A copy of `obj` where every NaN/inf float, at any depth, is None (JSON has no such numbers)."""
    if isinstance(obj, dict):
        return {key: sanitize(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize(value) for value in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


def _num(value: Any) -> float | None:
    """A plain float (numpy scalars included); None stays None. NaN survives here and is dropped by `sanitize`."""
    return None if value is None else float(value)


def _day(value: Any) -> str:
    return pd.Timestamp(value).strftime("%Y-%m-%d")


def _series(outcome: "EventOutcome") -> EventSeries:
    mae = outcome.results_data.get("mae")
    return EventSeries(
        line=[
            LinePoint(
                date=_day(r.Date),
                actual_kpi=_num(r.Actual_KPI),
                investment=_num(r.Investment),
                forecasted_kpi=_num(r.Forecasted_KPI),
            )
            for r in outcome.line_df.itertuples()
        ],
        accuracy=[
            AccuracyPoint(date=_day(r.Date), kpi=_num(r.kpi), predicted=_num(r.Predicted), mae=_num(mae))
            for r in outcome.accuracy_df.itertuples()
        ],
        investment=[
            InvestmentPoint(period=str(i), investment=_num(r.Investment)) for i, r in outcome.inv_bar_df.iterrows()
        ],
        kpi=[KpiPoint(category=str(i), kpi=_num(r.kpi)) for i, r in outcome.sessions_bar_df.iterrows()],
    )


def _channels(group: str) -> list[str]:
    return [name for name in group.split(", ") if name]


def _event(outcome: "EventOutcome") -> CausalEvent:
    published = outcome.passed and outcome.selected
    reasons = list(outcome.reasons) + (["not_selected"] if outcome.passed and not outcome.selected else [])
    event = CausalEvent(
        id=outcome.event_id,
        channels=_channels(outcome.product_group),
        status="published" if published else "rejected",
        reasons=reasons,
        selected=outcome.selected,
    )
    data = outcome.results_data
    if not data:
        return event
    lift = data["absolute_lift"]
    event.start, event.end = data["start_date"], data["end_date"]
    event.lift = Lift(
        abs=_num(lift),
        ci=(_num(data["absolute_lift_ci_lower"]), _num(data["absolute_lift_ci_upper"])),
        rel_pct=_num(data["relative_lift_pct"]),
    )
    event.p_value = _num(data["p_value"])
    event.investment_change_pct = _num(data["investment_change_pct"])
    event.incremental_investment = _num(data["total_investment_post_period"])
    event.cpa_incremental = None if lift == 0 else _num(data["cpa_incremental"])  # 0 was the "no lift" sentinel
    event.fit = Fit(r2=_num(data["model_r_squared"]), mae=_num(data["mae"]), mape=_num(data["mape"]))
    event.series = _series(outcome)
    return event


def _causal(computed: "Computed") -> Causal:
    cands = computed.candidates
    detected = [
        EventDetected(
            date=str(row.intervention_date),
            channels=_channels(row.product_group),
            investment_change_pct=_num(row.investment_change_pct),
            eligible=bool(row.eligible),
        )
        for row in cands.itertuples()
    ]
    events = [_event(o) for o in computed.events]
    if any(e.status == "published" for e in events):
        status, reasons = "ok", []
    elif cands.empty:
        status, reasons = "inconclusive", ["no_events_detected"]
    elif not cands["eligible"].any():
        status, reasons = "inconclusive", ["no_eligible_events"]
    else:
        status, reasons = "inconclusive", ["no_event_passed_gates"]
    return Causal(status=status, reasons=reasons, events_detected=detected, events=events)
