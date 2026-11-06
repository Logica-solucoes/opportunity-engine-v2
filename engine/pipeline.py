"""The engine pipeline as stages that return data in memory. Writers and `run` are added on top of these."""

import logging
import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

import pandas as pd

from engine import analysis, elasticity_analysis, outputs, results
from engine.config import EngineConfig, GateThresholds
from engine.data_preprocessor import PreparedData, load_and_prepare_data
from engine.errors import EngineError
from engine.identifiability import UNIDENTIFIED_KEY, assess, collinear_channels, hidden_channels, pool
from engine.logmessages import forward_logs
from engine.results_schema import ValidationReport
from engine.validation import validate
from engine.version import engine_version
from llm import get_llm

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
    candidates: pd.DataFrame = field(default_factory=pd.DataFrame)  # every detected event, `eligible` or not
    individual_curves_df: pd.DataFrame | None = None  # per-channel curves (Channel, Channel_Spend, ...)
    validation: ValidationReport | None = None  # what validate reported for these inputs (set by run)
    identifiability: dict[str, dict] | None = None  # per MMM channel: identifiable, reasons, coef_ci, point (A5)


def load_inputs(inputs: dict[str, Path | None], config: EngineConfig) -> PreparedData:
    log.info("Loading, Cleaning, and Preparing Data...")
    return load_and_prepare_data(config.to_legacy_dict(), inputs)


def detect_events(prepared: PreparedData, cfg: dict) -> pd.DataFrame:
    """Candidate events (one row each), with `eligible` False for those before min_intervention_date."""
    columns = [
        "event_id",
        "start_date",
        "intervention_date",
        "end_date",
        "product_group",
        "eligible",
        "investment_change_pct",
    ]
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
                "investment_change_pct": float(row["percentage_change"]),
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
                prepared.controls_df,
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
    result["individual_curves_df"] = elasticity_analysis.generate_individual_response_curves(
        mmm, cfg, output_dir=global_dir, strategic_limit_point=result["strategic_limit_point"]
    )
    return result


def _log_published_split(mmm: dict, identifiability: dict[str, dict]) -> None:
    """The contribution split the run log shows: identifiable channels on their own, the rest together."""
    channels = list(mmm["spend_cols"])
    hidden = hidden_channels(identifiability)
    shown = len(channels) - len(hidden)
    log.info(
        f"   - Identificabilidade: {shown} de {len(channels)} canais têm efeito separável de zero; "
        "os demais aparecem juntos como não identificáveis."
    )
    split = pool({name: mmm["contribution_pct"].get(name, 0.0) for name in channels}, hidden)
    for name, pct in sorted(split.items(), key=lambda item: item[1] or 0.0, reverse=True):
        label = "não identificáveis (juntos)" if name == UNIDENTIFIED_KEY else name
        log.info(f"     - {label}: {pct:.2f}%")


def compute(
    inputs: dict[str, Path | None],
    config: EngineConfig,
    *,
    global_dir: Path | None = None,
    validation: ValidationReport | None = None,
) -> Computed:
    """Everything the engine calculates, in memory. Writes files only inside `global_dir` (the curve exports)."""
    prepared = load_inputs(inputs, config)
    cfg = {**config.to_legacy_dict(), "period_days": prepared.period_days}
    candidates = detect_events(prepared, cfg)
    events = analyze_events(prepared, candidates, cfg)
    elasticity = run_elasticity(prepared, cfg, global_dir=global_dir)
    identifiability = None
    if elasticity.get("mmm"):
        gate = GateThresholds.model_validate(cfg.get("gate_thresholds") or {})
        flagged = collinear_channels(validation, gate.vif_max)
        mmm = elasticity["mmm"]
        identifiability = assess(mmm["bootstrap_coefs"], mmm["spend_cols"], gate.identifiability_width_ratio, flagged)
        _log_published_split(mmm, identifiability)
    return Computed(
        prepared=prepared,
        effective_config=cfg,
        events=events,
        candidates=candidates,
        validation=validation,
        identifiability=identifiability,
        **elasticity,
    )


def run(
    inputs: dict[str, Path | None],
    config: "dict | EngineConfig",
    out_dir: Path,
    on_log: Callable[[str, str], None],
) -> dict:
    """The contract entry point: compute, write the legacy outputs and the LLM reports under `out_dir`.

    Never mutates `config`, never changes the working directory, never leaves warning filters changed.
    """
    engine_config = EngineConfig.from_input(config)
    try:
        llm = get_llm()  # resolved before the analysis: a broken deployment setting must not waste a full run
    except ValueError as e:
        raise EngineError(
            "Provedor de IA desconhecido na variável LLM_PROVIDER. Corrija a configuração do servidor."
        ) from e
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    with forward_logs(on_log), warnings.catch_warnings():
        warnings.simplefilter("ignore")
        global_dir = out_dir / outputs.GLOBAL_DIR_NAME
        global_dir.mkdir(parents=True, exist_ok=True)
        try:
            report = validate(inputs, engine_config)
            for check in report.checks:
                log.log(logging.WARNING if check.level != "info" else logging.INFO, "   - %s", check.message)
            failure = next((c for c in report.checks if c.level == "error"), None)
            if failure:
                raise EngineError(failure.message, failure.id)
            computed = compute(inputs, engine_config, global_dir=global_dir, validation=report)
        except EngineError:
            raise
        except Exception as e:  # the detail (English, maybe with paths) stays in the chain and the server log
            log.exception("Erro inesperado durante a análise")
            raise EngineError(
                "Erro inesperado durante a análise. Os detalhes técnicos ficam no log do servidor."
            ) from e
        written = outputs.write_legacy_outputs(computed, out_dir)
        outputs.generate_reports(computed, written, llm)
    document = results.dump_results(results.build_results(computed, engine_version()))
    results.write_results(document, out_dir / "results.json")
    if document["status"] == "failed":
        log.error("A análise não produziu resultados: o modelo de elasticidade falhou e nenhum evento foi aprovado.")
    return document
