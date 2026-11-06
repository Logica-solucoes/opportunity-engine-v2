"""Builds, sanitizes and writes results.json from what `compute()` produced. No statistics happen here."""

import json
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd

from engine.grouping import group_name
from engine.identifiability import hidden_channels, pool, reallocation_suppressed
from engine.results_schema import (
    AccuracyPoint,
    Baseline,
    Causal,
    CausalEvent,
    ChannelFit,
    CurvePoint,
    Elasticity,
    ElasticityMetrics,
    EventControls,
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
    Placebo,
    RejectedControl,
    ResponseRow,
    ResultsV1,
    Robustness,
    Scenario,
    Sufficiency,
    Unidentified,
)
from engine.sufficiency import CAUSAL_REASONS

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
    event.investment_change_pct = _num(data["investment_change_pct"])
    event.fit = Fit(
        r2=_num(data["model_r_squared"]),
        mae=_num(data["mae"]),
        mape=_num(data["mape"]),
        wmape=_num(data.get("oos_wmape")),
    )
    if "placebo_ran" in data:
        ran = data["placebo_ran"]
        event.placebo = Placebo(
            p_value=_num(data["placebo_p_value"]) if ran else None,
            passed=data["placebo_passed"] if ran else None,
        )
    if "robust_p_value" in data:
        event.robustness = Robustness(p_value=_num(data["robust_p_value"]), passed=data["robust_passed"])
    if "controls_used" in data:
        event.controls = EventControls(
            used=list(data["controls_used"]),
            rejected=[RejectedControl(name=c["name"], r=_num(c["r"])) for c in data.get("controls_rejected", [])],
        )
    if "insufficient_run" in outcome.reasons:
        return event  # the run's data do not support publishing a lift: the numbers stay out of the document
    event.lift = Lift(
        abs=_num(lift),
        ci=(_num(data["absolute_lift_ci_lower"]), _num(data["absolute_lift_ci_upper"])),
        rel_pct=_num(data["relative_lift_pct"]),
    )
    event.p_value = _num(data["p_value"])
    event.incremental_investment = _num(data["total_investment_post_period"])
    event.cpa_incremental = None if lift == 0 else _num(data["cpa_incremental"])  # 0 was the "no lift" sentinel
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
    if status != "ok" and computed.sufficiency:
        # why the run is not sufficient comes first; "no_validated_event" is what no_event_passed_gates already says
        causes = [r for r in computed.sufficiency.reasons if r in CAUSAL_REASONS and r != "no_validated_event"]
        reasons = causes + reasons
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
    hidden = hidden_channels(computed.identifiability)
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
                    variant: pool({ch: _num(record.get(f"Spend_{ch}_{suffix}")) for ch in spend_cols}, hidden)
                    for variant, suffix in MIX_VARIANTS.items()
                },
            )
        )
    return rows


def _scenarios(computed: "Computed") -> list[Scenario]:
    scenarios = []
    suppressed = reallocation_suppressed(computed.identifiability)
    for name, attribute in SCENARIO_SOURCES.items():
        point = getattr(computed, attribute)
        if not point or (suppressed and name == "strategic_reallocation"):
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
    mmm = computed.mmm
    params, frame = mmm["optimal_params"], mmm["dataframe"]
    curves = computed.individual_curves_df
    verdicts = computed.identifiability or {}
    fits = []
    for i, name in enumerate(mmm["spend_cols"]):
        verdict = verdicts.get(name)
        published = verdict is None or verdict["identifiable"]  # what the data cannot support is not published
        curve = []
        if published and curves is not None and not curves.empty:
            own = curves[curves["Channel"] == name]
            curve = [CurvePoint(x=_num(r.Channel_Spend), y=_num(r.Projected_Total_KPIs)) for r in own.itertuples()]
        fits.append(
            ChannelFit(
                name=name,
                contribution_pct=_num(mmm["contribution_pct"].get(name)) if published else None,
                identifiable=None if verdict is None else verdict["identifiable"],
                coef_ci=None if verdict is None else (_num(verdict["coef_ci"][0]), _num(verdict["coef_ci"][1])),
                hill=Hill(K=_num(params["ks"][i]), n=_num(params["ss"][i])) if published else None,
                adstock=_num(params["alphas"][i]) if published else None,
                observed_spend_range=(_num(frame[name].min()), _num(frame[name].max())),
                curve=curve,
                reasons=[] if verdict is None else list(verdict["reasons"]),
            )
        )
    return fits


def _elasticity(computed: "Computed") -> Elasticity:
    mmm = computed.mmm
    if not mmm:
        return Elasticity(status="failed", reasons=["model_failed"])
    groups = [
        Group(name=group_name(members), members=[m.strip().upper() for m in members])
        for members in computed.effective_config.get("channel_groups") or []
    ]
    hidden = [name for name in mmm["spend_cols"] if name in hidden_channels(computed.identifiability)]
    unidentified = None
    reasons = []
    if hidden:
        unidentified = Unidentified(
            channels=hidden, contribution_pct=_num(sum(mmm["contribution_pct"].get(name, 0.0) for name in hidden))
        )
    if computed.identifiability and len(hidden) == len(mmm["spend_cols"]):
        reasons = ["no_identifiable_channel"]  # informative: the total curve and scenarios are still published
    if computed.sufficiency and "cv_in_sample" in computed.sufficiency.reasons:
        reasons.append(
            "cv_in_sample"
        )  # informative: too few rows for an out-of-sample cv, the fit was scored in-sample
    return Elasticity(
        status="ok",
        reasons=reasons,
        metrics=ElasticityMetrics(
            cv_r2=_num(mmm["cv_r_squared"]),
            r2=_num(mmm["r_squared"]),
            media_contribution_pct=_num(mmm["marketing_contribution_of_kpi_pct"]),
            reallocation_suppressed=True if reallocation_suppressed(computed.identifiability) else None,
        ),
        channels=_channel_fits(computed),
        groups=groups,
        unidentified=unidentified,
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


def run_status(causal: Causal, elasticity: Elasticity | None, sufficiency: Sufficiency | None = None) -> str:
    """succeeded when both analyses produced something, failed when neither did, inconclusive otherwise.

    A run whose data are not sufficient (A6) is never `succeeded`.
    """
    ok = [causal.status == "ok", elasticity is not None and elasticity.status == "ok"]
    if all(ok):
        return "inconclusive" if sufficiency is not None and not sufficiency.passed else "succeeded"
    return "inconclusive" if any(ok) else "failed"


def build_results(computed: "Computed", engine_version: str) -> ResultsV1:
    causal, elasticity = _causal(computed), _elasticity(computed)
    return ResultsV1(
        engine_version=engine_version,
        status=run_status(causal, elasticity, computed.sufficiency),
        sufficiency=computed.sufficiency,
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
