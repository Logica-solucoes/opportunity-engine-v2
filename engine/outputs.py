"""Files the prototype always wrote (PNG, CSV, Markdown, HTML), now rooted at `out_dir`, and the LLM reports.

Everything here only consumes a `Computed`; A1 replaces this module's role with a results.json builder.
"""

import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from engine import presentation, recommendations, reports
from engine.identifiability import hidden_channels, pool
from llm.base import LLM, LLMUnavailable

if TYPE_CHECKING:
    from engine.pipeline import Computed

log = logging.getLogger(__name__)

GLOBAL_DIR_NAME = "global_saturation_analysis"
MIX_LABELS = ("Média Histórica", "Pico de Eficiência", "Modelo de Elasticidade")


@dataclass
class Written:
    event_dirs: dict[str, Path] = field(default_factory=dict)
    image_paths: dict[str, dict[str, str]] = field(default_factory=dict)
    csv_paths: dict[str, str] = field(default_factory=dict)
    global_dir: Path | None = None
    scenarios: list[dict] = field(default_factory=list)
    kpi_projections: dict = field(default_factory=dict)
    total_monthly_investment: float = 0.0


def _kpi_name(cfg: dict) -> str:
    return cfg["performance_kpi_column"]


def _write_event(computed: "Computed", outcome, out_dir: Path, written: Written) -> None:
    cfg = computed.effective_config
    event_dir = out_dir / outcome.product_group.replace(", ", "_") / outcome.intervention_date
    event_dir.mkdir(parents=True, exist_ok=True)
    safe_group = re.sub(r"[^\w-]", "_", outcome.product_group)
    base = f"{cfg['advertiser_name']}_{safe_group}_{outcome.intervention_date}"
    kpi_name = _kpi_name(cfg)

    images = {
        "accuracy": str(event_dir / f"accuracy_plot_{base}.png"),
        "line": str(event_dir / f"line_chart_{base}.png"),
        "investment": str(event_dir / f"investment_chart_{base}.png"),
        "sessions": str(event_dir / f"sessions_chart_{base}.png"),
    }
    presentation.save_accuracy_plot(outcome.results_data, outcome.accuracy_df, images["accuracy"], kpi_name=kpi_name)
    presentation.save_line_chart_plot(outcome.line_df, images["line"], kpi_name=kpi_name)
    presentation.save_investment_bar_plot(outcome.inv_bar_df, images["investment"])
    presentation.save_sessions_bar_plot(outcome.sessions_bar_df, images["sessions"], kpi_name=kpi_name)
    presentation.save_causal_chart_data(
        event_dir,
        outcome.line_df,
        outcome.inv_bar_df,
        outcome.sessions_bar_df,
        outcome.accuracy_df,
        mae=outcome.results_data.get("mae", 0),
    )
    csv_path = event_dir / f"{base}_presentation_data.csv"
    presentation.create_presentation_dataframe(outcome.results_data, cfg).to_csv(
        csv_path, index=False, float_format="%.2f"
    )
    written.event_dirs[outcome.event_id] = event_dir
    written.image_paths[outcome.event_id] = images
    written.csv_paths[outcome.event_id] = str(csv_path)
    log.info(f"   SUCCESS! Comprehensive data saved to: {csv_path}")


def _scenario(title, description, point, factor, computed: "Computed", strategic_ratio: dict, total=None) -> dict:
    total = point["Daily_Investment"] * factor if total is None else total
    hidden = hidden_channels(computed.identifiability)  # what the data cannot support is not named to the LLM
    mixes = (computed.current_split, computed.optimized_mix, strategic_ratio)
    mixes = tuple(pool(mix, hidden) for mix in mixes)
    return {
        "title": title,
        "description": description,
        "total_investment": total,
        "splits": {label: {k: v * total for k, v in mix.items()} for label, mix in zip(MIX_LABELS, mixes, strict=True)},
        "projected_kpis": {mix: kpi * factor for mix, kpi in point.get("projected_kpis", {}).items()},
    }


def _write_global(computed: "Computed", out_dir: Path, written: Written) -> None:
    cfg = computed.effective_config
    global_dir = out_dir / GLOBAL_DIR_NAME
    global_dir.mkdir(parents=True, exist_ok=True)
    written.global_dir = global_dir
    factor = 30 / (cfg.get("period_days", 1) or 1)  # periods per month
    baseline = computed.baseline_point
    total_monthly = baseline["Daily_Investment"] * factor if baseline and "Daily_Investment" in baseline else 0

    presentation.save_opportunity_curve_plot(
        computed.response_curve_df,
        baseline,
        computed.max_efficiency_point,
        computed.diminishing_return_point,
        computed.saturation_point,
        str(global_dir / "combined_all_channels_saturation_curve.png"),
        kpi_name=_kpi_name(cfg),
        strategic_limit_point=computed.strategic_limit_point,
        strategic_reallocation_point=computed.strategic_reallocation_point,
        config=cfg,
    )
    ratio = {k: v / 100.0 for k, v in computed.mmm["contribution_pct"].items()}
    written.scenarios = [
        _scenario(
            "Cenário de Investimento Atual",
            "Mantém o volume de investimento total idêntico à média histórica atual. Serve como linha de base para "
            "avaliarmos o ganho puro de eficiência ao alterar o mix.",
            baseline or {},
            factor,
            computed,
            ratio,
            total=total_monthly,
        ),
        _scenario(
            "Cenário de Investimento Otimizado",
            "Escala o investimento total para o nível onde foi observado o maior pico de eficiência teórica antes da "
            "saturação acelerada.",
            computed.max_efficiency_point,
            factor,
            computed,
            ratio,
        ),
        _scenario(
            "Cenário de Investimento Estratégico",
            "Expande o orçamento até o limite estratégico calculado pelo modelo de elasticidade, focado em maximizar "
            "o volume de resultados.",
            computed.strategic_limit_point,
            factor,
            computed,
            ratio,
        ),
    ]
    written.total_monthly_investment = total_monthly
    written.kpi_projections = {
        "current": baseline,
        "optimized": computed.max_efficiency_point,
        "strategic": computed.strategic_limit_point,
        "reallocation": computed.strategic_reallocation_point,
    }
    presentation.create_comparative_saturation_md(
        written.scenarios,
        str(global_dir / "SATURATION_CURVE.md"),
        kpi_projections=written.kpi_projections,
        kpi_name=cfg["primary_business_metric_name"],
        period_days=cfg.get("period_days", 1),
    )


def write_legacy_outputs(computed: "Computed", out_dir: Path) -> Written:
    """PNG/CSV/Markdown for each selected event and for the global analysis. A failure in one item is logged and skipped."""
    written = Written()
    for outcome in (e for e in computed.events if e.selected):
        log.info(f"Generating Report for Event: {outcome.product_group} on {outcome.intervention_date}")
        try:
            _write_event(computed, outcome, out_dir, written)
        except Exception:
            log.error(f"Report generation failed for event {outcome.event_id}", exc_info=True)
    if computed.mmm:
        try:
            _write_global(computed, out_dir, written)
        except Exception:
            log.error("Global saturation outputs failed", exc_info=True)
    return written


def generate_reports(computed: "Computed", written: Written, llm: LLM | None) -> None:
    """LLM narrative per selected event and one global; without an LLM, or once it is unavailable, the deterministic
    recommendations file is written instead. Only LLMUnavailable stops further LLM calls."""
    cfg = computed.effective_config
    prepared = computed.prepared
    market = pd.merge(
        prepared.kpi_df.rename(columns={"Sessions": cfg["advertiser_name"]}), prepared.trends_df, on="Date", how="left"
    ).fillna(0)
    available = llm is not None

    for outcome in (e for e in computed.events if e.selected and e.event_id in written.event_dirs):
        event_dir = written.event_dirs[outcome.event_id]
        done = False
        if available:
            log.info("   - Generating Strategic Narrative with Gemini...")
            try:
                reports.generate_html_report(
                    llm,
                    outcome.results_data,
                    cfg,
                    written.image_paths[outcome.event_id],
                    os.path.join(event_dir, f"report_{event_dir.parent.name}_{event_dir.name}.html"),
                    market,
                    outcome.line_df,
                    csv_output_filename=written.csv_paths[outcome.event_id],
                    correlation_matrix=prepared.correlation_matrix,
                )
                done = True
            except LLMUnavailable as e:
                available = False
                log.warning(
                    f"AVISO: o serviço de IA está indisponível ({e.reason}); os próximos relatórios usarão o texto padrão."
                )
            except Exception:
                log.error(f"Could not generate the narrative for event {outcome.event_id}", exc_info=True)
        if not done:
            recommendations.generate_basic_recommendations_file(outcome.results_data, cfg, str(event_dir))

    if available and written.global_dir is not None:
        log.info("   - Generating Global Strategic Narrative with Gemini...")
        try:
            reports.generate_global_report(
                llm,
                cfg,
                written.scenarios,
                total_investment=written.total_monthly_investment,
                kpi_projections=written.kpi_projections,
                global_output_dir=written.global_dir,
            )
        except LLMUnavailable as e:
            log.warning(f"AVISO: o serviço de IA está indisponível ({e.reason}); a narrativa global foi pulada.")
        except Exception:
            log.error("Could not generate the global narrative", exc_info=True)
