"""Builds, sanitizes and writes results.json from what `compute()` produced. No statistics happen here."""

import json
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

from engine import identifiability
from engine.results_schema import (
    AccuracyPoint,
    Baseline,
    Causal,
    CausalEvent,
    ChannelFit,
    CurvePoint,
    Elasticity,
    ElasticityMetrics,
    EventDetected,
    EventSeries,
    Fit,
    Group,
    Hill,
    InvestmentPoint,
    KpiPoint,
    Lift,
    LinePoint,
    MonthlyBaseline,
    ResponseRow,
    ResultsV1,
    Scenario,
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


# --- elasticity ---

# scenario name -> attribute of Computed holding that notable point
SCENARIO_SOURCES = {
    "current": "baseline_point",
    "max_efficiency": "max_efficiency_point",
    "strategic_limit": "strategic_limit_point",
    "diminishing_return": "diminishing_return_point",
    "saturation": "saturation_point",
    "strategic_reallocation": "strategic_reallocation_point",
}
MIX_VARIANTS = {"historical": "Historical", "optimized": "Optimized", "strategic": "Strategic"}


def _icpa(point: dict) -> float | None:
    """The engine fills iCPA with 0 where it is undefined (nothing invested, or no KPI gained): that is null here."""
    if not point.get("Incremental_Investment") or not point.get("Incremental_KPI", 1):
        return None
    return _num(point.get("iCPA"))


def _revenue_mode(cfg: dict) -> bool:
    return bool(cfg.get("kpi_is_monetary")) or cfg.get("optimization_target") == "REVENUE"


def _response_rows(computed: "Computed") -> list[ResponseRow]:
    frame = computed.response_curve_df
    if frame is None or frame.empty:
        return []
    spend_cols = computed.mmm["spend_cols"]
    hidden = identifiability.unidentified(computed.identifiability)
    revenue_mode = _revenue_mode(computed.effective_config)  # outside it revenue and ROAS are 0 by construction
    rows = []
    for record in frame.to_dict("records"):
        rows.append(
            ResponseRow(
                investment=_num(record.get("Daily_Investment")),
                kpi=_num(record.get("Projected_Total_KPIs")),
                revenue=_num(record.get("Projected_Revenue")) if revenue_mode else None,
                icpa=_icpa(record),
                # incremental revenue / incremental investment; the engine writes 0 for 0/0
                iroas=_num(record.get("Incremental_ROI"))
                if revenue_mode and record.get("Incremental_Investment")
                else None,
                incremental_investment=_num(record.get("Incremental_Investment")),
                incremental_kpi=_num(record.get("Incremental_KPI")),
                mix={
                    variant: identifiability.fold_mix(
                        {ch: _num(record.get(f"Spend_{ch}_{suffix}")) for ch in spend_cols}, hidden
                    )
                    for variant, suffix in MIX_VARIANTS.items()
                },
            )
        )
    return rows


def _scenarios(computed: "Computed") -> list[Scenario]:
    scenarios = []
    for name, attribute in SCENARIO_SOURCES.items():
        point = getattr(computed, attribute)
        if not point or (
            name == "strategic_reallocation" and identifiability.none_identifiable(computed.identifiability)
        ):
            continue
        scenarios.append(
            Scenario(
                name=name,
                investment=_num(point.get("Daily_Investment")),
                kpi=_num(point.get("Projected_Total_KPIs")),
                icpa=_icpa(point),
                incremental_investment=_num(point.get("Incremental_Investment")),
                incremental_kpi=_num(point.get("Incremental_KPI")),
            )
        )
    return scenarios


def _channel_fits(computed: "Computed") -> list[ChannelFit]:
    """A channel that is not identifiable keeps only its verdict and observed spend: no share, Hill, adstock or curve."""
    mmm = computed.mmm
    if not computed.identifiability:
        raise ValueError(
            "Computed has an MMM but no identifiability verdicts: run_elasticity runs identifiability.assess"
        )
    params, frame = mmm["optimal_params"], mmm["dataframe"]
    curves = computed.individual_curves_df
    fits = []
    for i, name in enumerate(mmm["spend_cols"]):
        verdict = computed.identifiability[name]
        fit = ChannelFit(
            name=name,
            identifiable=verdict["identifiable"],
            coef_ci=tuple(_num(v) for v in verdict["ci"]),
            reasons=verdict["reasons"],
            observed_spend_range=(_num(frame[name].min()), _num(frame[name].max())),
        )
        if verdict["identifiable"]:
            fit.contribution_pct = _num(mmm["contribution_pct"].get(name))
            fit.hill = Hill(K=_num(params["ks"][i]), n=_num(params["ss"][i]))
            fit.adstock = _num(params["alphas"][i])
            if curves is not None and not curves.empty:
                own = curves[curves["Channel"] == name]
                fit.curve = [
                    CurvePoint(x=_num(r.Channel_Spend), y=_num(r.Projected_Total_KPIs)) for r in own.itertuples()
                ]
        fits.append(fit)
    return fits


def _elasticity(computed: "Computed") -> Elasticity:
    mmm = computed.mmm
    if not mmm:
        return Elasticity(status="failed", reasons=["model_failed"])
    groups = [
        Group(name=" + ".join(members), members=list(members))
        for members in computed.effective_config.get("channel_groups") or []
    ]
    none_identifiable = identifiability.none_identifiable(computed.identifiability)
    return Elasticity(
        status="inconclusive" if none_identifiable else "ok",
        reasons=["no_identifiable_channel"] if none_identifiable else [],
        metrics=ElasticityMetrics(
            cv_r2=_num(mmm["cv_r_squared"]),
            r2=_num(mmm["r_squared"]),
            media_contribution_pct=_num(mmm["marketing_contribution_of_kpi_pct"]),
        ),
        channels=_channel_fits(computed),
        groups=groups,
        response_curve=_response_rows(computed),
        scenarios=_scenarios(computed),
    )


def _baseline(computed: "Computed") -> Baseline:
    prepared = computed.prepared
    kpi = prepared.kpi_df.assign(month=prepared.kpi_df["Date"].dt.strftime("%Y-%m")).groupby("month")["kpi"].sum()
    inv = prepared.investment_df.assign(month=prepared.investment_df["Date"].dt.strftime("%Y-%m"))
    by_channel = inv.groupby(["month", "Product Group"])["investment"].sum()
    monthly = []
    for month in sorted(set(kpi.index) | set(inv["month"])):
        channels = {str(ch): _num(v) for (m, ch), v in by_channel.items() if m == month}
        monthly.append(
            MonthlyBaseline(
                month=month,
                kpi=_num(kpi.get(month, 0.0)),
                investment=_num(sum(v for v in channels.values() if v is not None)),
                by_channel=channels,
            )
        )
    return Baseline(monthly=monthly)


def run_status(causal: Causal, elasticity: Elasticity | None) -> str:
    """succeeded when both analyses are ok, failed when neither published anything, inconclusive otherwise.

    An inconclusive elasticity still publishes the total curve and the scenarios (A5), so it counts as something.
    """
    ok = [causal.status == "ok", elasticity is not None and elasticity.status == "ok"]
    if all(ok):
        return "succeeded"
    if any(ok) or (elasticity is not None and elasticity.status == "inconclusive"):
        return "inconclusive"
    return "failed"


def build_results(computed: "Computed", engine_version: str) -> ResultsV1:
    causal, elasticity = _causal(computed), _elasticity(computed)
    return ResultsV1(
        engine_version=engine_version,
        status=run_status(causal, elasticity),
        causal=causal,
        elasticity=elasticity,
        baseline=_baseline(computed),
        validation=computed.validation,
    )


def dump_results(results: ResultsV1) -> dict:
    """The JSON-safe dict: non-finite numbers become None, and the cleaned document is validated again."""
    data = sanitize(results.model_dump(mode="json", by_alias=True))
    return ResultsV1.model_validate(data).model_dump(mode="json", by_alias=True)


def write_results(data: dict, path: Path) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, allow_nan=False), encoding="utf-8")
