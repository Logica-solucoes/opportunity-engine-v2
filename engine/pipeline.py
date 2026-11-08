"""The engine pipeline as stages that return data in memory. Writers and `run` are added on top of these."""

import logging
import warnings
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import timedelta
from pathlib import Path

import pandas as pd

from engine import analysis, elasticity_analysis, identifiability, narratives, outputs, results, sufficiency
from engine.config import EngineConfig
from engine.data_preprocessor import PreparedData, load_and_prepare_data
from engine.errors import EngineError
from engine.logmessages import forward_logs
from engine.results_schema import Reports, Sufficiency, ValidationReport
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
    # not_significant, illogical_direction, poor_fit, placebo_failed, model_dependent, analysis_failed; insufficient_run (judge_sufficiency)
    reasons: list[str] = field(default_factory=list)
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
    identifiability: dict = field(default_factory=dict)  # channel -> identifiability.assess verdict; {} without a model
    sufficiency: Sufficiency | None = None  # A6: do the data support publishing a lift (set by compute)

    @property
    def low_confidence(self) -> bool:
        """The MMM's CV is under reallocation_min_cv_r2: the curve already kept the historical mix."""
        return bool(self.mmm) and not elasticity_analysis.trusts_reallocation(
            self.mmm["cv_r_squared"], self.effective_config
        )

    @property
    def reallocation_suppressed(self) -> bool:
        """No reallocation while a channel is hidden (A5) or the fit is too weak to trust a reshuffle."""
        return identifiability.reallocation_suppressed(self.identifiability) or self.low_confidence


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
        group_names = {member: " + ".join(group) for group in cfg.get("channel_groups") or [] for member in group}
        event_map = event_map[event_map["ad_product"].isin({group_names.get(p, p) for p in product_filter})]
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
    placebo = results.get("placebo_p_value")
    if placebo is not None and placebo < cfg["p_value_threshold"]:
        reasons.append("placebo_failed")  # the model finds an "effect" where nothing happened
    robust_p, threshold = results.get("robust_p_value"), cfg["p_value_threshold"]
    holds = (
        robust_p is not None and robust_p < threshold and (results["absolute_lift"] > 0) == (results["robust_lift"] > 0)
    )
    if robust_p is not None and results["p_value"] < threshold and not holds:
        reasons.append("model_dependent")  # significant only through the media features' extrapolation
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
                contested=lambda primary: not _gate_reasons(primary, cfg),  # no A6 fits for an event already out
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


def _log_contribution_split(mmm: dict, verdicts: dict) -> None:
    """Only identifiable channels: the log reaches the user live, and a share of the others is not published."""
    log.info("   --- Historical Contribution Split (Elasticity) ---")
    shares = sorted(mmm["contribution_pct"].items(), key=lambda item: item[1], reverse=True)
    shown = [(channel, pct) for channel, pct in shares if verdicts[channel]["identifiable"]]
    for channel, pct in shown:
        log.info(f"     - {channel}: {pct:.2f}%")
    if hidden := len(shares) - len(shown):
        log.info(f"     - {hidden} channel(s) not identifiable, contribution not published")


def judge_sufficiency(
    prepared: PreparedData, events: list[EventOutcome], mmm: dict | None, cfg: dict
) -> tuple[list[EventOutcome], Sufficiency]:
    """The run-level verdict (A6). A causal reason demotes every passing event to insufficient_run, as new outcomes:
    the analysed ones stay as they were."""
    validated = [
        {"channels": [c for c in e.product_group.split(", ") if c], "oos_wmape": e.results_data.get("oos_wmape")}
        for e in events
        if e.passed
    ]
    cv_out_of_sample = mmm["cv_out_of_sample"] if mmm else None
    verdict = sufficiency.assess(
        validated, prepared.spend_df, cv_out_of_sample, cfg["spend_cv_min"], cfg["oos_wmape_max"]
    )
    if verdict.passed:
        log.info(f"Dados suficientes: {verdict.validated_events} evento(s) validado(s).")
        return events, verdict
    log.warning("Dados insuficientes para publicar o resultado: " + ", ".join(verdict.reasons))
    if not sufficiency.CAUSAL_REASONS & set(verdict.reasons):
        return events, verdict
    demoted = [
        replace(e, passed=False, selected=False, reasons=[*e.reasons, "insufficient_run"]) if e.passed else e
        for e in events
    ]
    return demoted, verdict


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
    events, verdict = judge_sufficiency(prepared, events, elasticity["mmm"], cfg)
    verdicts = {}
    if elasticity["mmm"]:
        collinearity = validation.collinearity if validation else None
        verdicts = identifiability.assess(elasticity["mmm"], set(collinearity.unresolved) if collinearity else set())
        _log_contribution_split(elasticity["mmm"], verdicts)
    return Computed(
        prepared=prepared,
        effective_config=cfg,
        events=events,
        candidates=candidates,
        validation=validation,
        identifiability=verdicts,
        sufficiency=verdict,
        **elasticity,
    )


def run(
    inputs: dict[str, Path | None],
    config: "dict | EngineConfig",
    out_dir: Path,
    on_log: Callable[[str, str], None],
) -> dict:
    """The contract entry point: compute, write the legacy outputs and results.json (with the grounded reports) under `out_dir`.

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
        document = results.dump_results(results.build_results(computed, engine_version()))
        try:
            built = narratives.build(document, engine_config, llm)
            document["reports"] = Reports.model_validate(built).model_dump(mode="json", by_alias=True)
        except Exception:  # a narrative never fails the run: the screen just shows no text
            log.error("Não foi possível montar os relatórios da execução", exc_info=True)
            document["reports"] = None
        outputs.write_recommendations(written, document["reports"])
    results.write_results(document, out_dir / "results.json")
    if document["status"] == "failed":
        log.error("A análise não produziu resultados: o modelo de elasticidade falhou e nenhum evento foi aprovado.")
    return document
