"""The engine pipeline as stages that return data in memory. Writers and `run` are added on top of these."""

import logging
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

import pandas as pd

from engine import analysis, elasticity_analysis
from engine.config import EngineConfig
from engine.data_preprocessor import PreparedData, load_and_prepare_data

log = logging.getLogger(__name__)


@dataclass
class EventOutcome:
    event_id: str
    product_group: str
    intervention_date: str
    results_data: dict | None
    line_df: pd.DataFrame | None = None
    inv_bar_df: pd.DataFrame | None = None
    sessions_bar_df: pd.DataFrame | None = None
    accuracy_df: pd.DataFrame | None = None
    passed: bool = False
    reasons: list[str] = field(default_factory=list)  # not_significant, illogical_direction, poor_fit, analysis_failed
    selected: bool = False  # among the max_events_to_analyze best passing events


@dataclass
class Computed:
    prepared: PreparedData
    effective_config: dict
    events: list[EventOutcome]
    mmm: dict | None
    response_curve_df: pd.DataFrame | None = None
    baseline_point: dict | None = None
    max_efficiency_point: dict | None = None
    strategic_limit_point: dict | None = None
    diminishing_return_point: dict | None = None
    saturation_point: dict | None = None
    strategic_reallocation_point: dict | None = None
    optimized_mix: dict = field(default_factory=dict)
    current_split: dict = field(default_factory=dict)


def load_inputs(inputs: dict[str, Path | None], config: EngineConfig) -> PreparedData:
    log.info("Loading, Cleaning, and Preparing Data...")
    return load_and_prepare_data(config.to_legacy_dict(), inputs)


def detect_events(prepared: PreparedData, cfg: dict) -> pd.DataFrame:
    """Candidate events (one row each), with `eligible` False for those before min_intervention_date."""
    columns = ["event_id", "start_date", "intervention_date", "end_date", "product_group", "eligible"]
    period_days = cfg["period_days"]
    event_map, _, _ = analysis.find_events(
        prepared.investment_df,
        cfg["advertiser_name"],
        1 + cfg["increase_threshold_percent"] / 100,
        1 - cfg["decrease_threshold_percent"] / 100,
        cfg["post_event_days"],
        output_dir=None,
        period_days=period_days,
    )
    if event_map is None or event_map.empty:
        log.warning("Analysis complete: No significant events were detected.")
        return pd.DataFrame(columns=columns)
    product_filter = cfg.get("product_group_filter")
    if product_filter:
        event_map = event_map[event_map["ad_product"].isin(product_filter)]
    if event_map.empty:
        log.warning("Analysis complete: No events found for the specified products.")
        return pd.DataFrame(columns=columns)

    span, _ = analysis.periods_to_days(cfg["post_event_days"], period_days, 4, label="post_event_days")
    first_date = prepared.kpi_df["Date"].min().strftime("%Y-%m-%d")
    earliest = pd.to_datetime(cfg["min_intervention_date"]) if cfg.get("min_intervention_date") else None
    rows = []
    for _, row in event_map.iterrows():
        day = pd.to_datetime(row["date"])
        rows.append(
            {
                "event_id": f"{cfg['advertiser_name']}_{row['ad_product'].replace(' ', '_')}_{day.date()}",
                "start_date": first_date,
                "intervention_date": day.strftime("%Y-%m-%d"),
                "end_date": (day + timedelta(days=span)).strftime("%Y-%m-%d"),
                "product_group": row["ad_product"],
                "eligible": earliest is None or day >= earliest,
            }
        )
    return pd.DataFrame(rows, columns=columns)


def _gate_reasons(results: dict, cfg: dict) -> list[str]:
    reasons = []
    if cfg["require_statistical_significance"] and not results["p_value"] < cfg["p_value_threshold"]:
        reasons.append("not_significant")
    pct, lift = results["investment_change_pct"], results["absolute_lift"]
    if cfg["require_logical_direction"] and not ((pct > 0 and lift > 0) or (pct < 0 and lift < 0)):
        reasons.append("illogical_direction")
    if cfg["require_model_fit"] and not results.get("model_r_squared", 0) >= cfg["r_squared_threshold"]:
        reasons.append("poor_fit")
    return reasons


def analyze_events(prepared: PreparedData, candidates: pd.DataFrame, cfg: dict) -> list[EventOutcome]:
    eligible = candidates[candidates["eligible"]] if not candidates.empty else candidates
    if eligible.empty:
        return []
    log.info(f"Analyzing {len(eligible)} candidates...")

    # the response model is pre-trained once, on the whole history and every channel that had an event
    groups = ", ".join(candidates["product_group"].unique())
    projection = analysis.run_opportunity_projection(
        prepared.kpi_df, prepared.investment_df, prepared.trends_df, groups, cfg
    )
    model_params = projection[7]

    outcomes = []
    for _, event in eligible.iterrows():
        pre = [
            event["start_date"],
            (pd.to_datetime(event["intervention_date"]) - timedelta(days=1)).strftime("%Y-%m-%d"),
        ]
        post = [event["intervention_date"], event["end_date"]]
        outcome = EventOutcome(event["event_id"], event["product_group"], event["intervention_date"], None)
        try:
            results, line_df, inv_bar_df, sessions_bar_df, accuracy_df = analysis.run_causal_impact_analysis(
                prepared.kpi_df,
                prepared.investment_df,
                prepared.trends_df,
                prepared.performance_df,
                pre,
                post,
                event["event_id"],
                event["product_group"],
                model_params,
                cfg,
            )
        except Exception:
            log.exception("Causal impact analysis failed for %s", event["event_id"])
            results = None
        if not results:
            outcome.reasons = ["analysis_failed"]
            log.warning("   - FAILED: Causal impact analysis could not be completed.")
        else:
            outcome.results_data = results
            outcome.line_df, outcome.inv_bar_df = line_df, inv_bar_df
            outcome.sessions_bar_df, outcome.accuracy_df = sessions_bar_df, accuracy_df
            outcome.reasons = _gate_reasons(results, cfg)
            outcome.passed = not outcome.reasons
            if not outcome.passed:
                log.warning("   - SKIPPED: Event did not meet validation criteria.")
        outcomes.append(outcome)

    passed = sorted((o for o in outcomes if o.passed), key=lambda o: abs(o.results_data["absolute_lift"]), reverse=True)
    for outcome in passed[: cfg["max_events_to_analyze"]]:
        outcome.selected = True
    return outcomes


def run_elasticity(prepared: PreparedData, cfg: dict, *, global_dir: Path | None = None) -> dict:
    """MMM, aggregated response curve and, when `global_dir` is given, the curve functions' own exports there."""
    log.info("Starting Global Elasticity Analysis...")
    mmm = elasticity_analysis.run_mmm_engine(cfg, prepared)
    result = {"mmm": mmm}
    if not mmm:
        return result

    pivot = prepared.investment_df.pivot_table(index="Date", columns="Product Group", values="investment").fillna(0)
    totals = pivot.sum()
    result["current_split"] = (totals / totals.sum()).to_dict()
    result["optimized_mix"] = analysis.find_optimal_historical_mix(prepared.kpi_df, prepared.investment_df) or {}
    (
        result["response_curve_df"],
        result["baseline_point"],
        result["max_efficiency_point"],
        result["strategic_limit_point"],
        result["diminishing_return_point"],
        result["saturation_point"],
        result["strategic_reallocation_point"],
    ) = elasticity_analysis.generate_aggregated_response_curve(
        mmm, cfg, optimized_mix=result["optimized_mix"], output_dir=global_dir
    )
    if global_dir is not None:
        elasticity_analysis.generate_individual_response_curves(
            mmm, cfg, output_dir=global_dir, strategic_limit_point=result["strategic_limit_point"]
        )
    return result


def compute(inputs: dict[str, Path | None], config: EngineConfig, *, global_dir: Path | None = None) -> Computed:
    """Everything the engine calculates, in memory. Writes files only inside `global_dir` (the curve exports)."""
    prepared = load_inputs(inputs, config)
    cfg = {**config.to_legacy_dict(), "period_days": prepared.period_days}
    candidates = detect_events(prepared, cfg)
    events = analyze_events(prepared, candidates, cfg)
    elasticity = run_elasticity(prepared, cfg, global_dir=global_dir)
    return Computed(prepared=prepared, effective_config=cfg, events=events, **elasticity)
