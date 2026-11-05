"""engine.validate: what is wrong with the three uploaded files, before any model runs (docs/m2/README.md §2)."""

import itertools
import logging
from pathlib import Path

import numpy as np
import pandas as pd
from statsmodels.stats.outliers_influence import variance_inflation_factor

from engine.config import EngineConfig
from engine.data_preprocessor import detect_cadence, drop_partial_periods, iqr_bounds
from engine.errors import EngineError
from engine.inputs import RawInputs, cadence_check, read_inputs, sufficiency_check
from engine.results_schema import Check, Collinearity, ValidationReport

log = logging.getLogger(__name__)

MAX_LISTED_DATES = 50
OVERLAP_CORRELATION = 0.95
OVERLAP_RATIO_MIN = 0.9  # the smaller total over the larger: 0.9-1.1 either way round
MIN_COLLINEARITY_PERIODS = 30  # with fewer dates two channels correlate near ±1 by chance; A6/A10 calibrate
MAX_FINITE_VIF = 1e6  # above this R² rounded to 1: perfect collinearity, reported as None
CADENCE_LABEL = {1: "diária", 7: "semanal", 30: "mensal"}


def _iso(dates) -> list[str]:
    return [pd.Timestamp(d).strftime("%Y-%m-%d") for d in dates]


def check_partial(investment_df: pd.DataFrame, kpi_df: pd.DataFrame, inv_cadence: int, kpi_cadence: int):
    """Returns (checks, investment after the drop, performance after the drop)."""
    kept_inv = drop_partial_periods(investment_df, "Date", inv_cadence)
    kept_kpi = drop_partial_periods(kpi_df, "Date", kpi_cadence)
    dropped_inv = investment_df["Date"].nunique() - kept_inv["Date"].nunique()
    dropped_kpi = kpi_df["Date"].nunique() - kept_kpi["Date"].nunique()
    checks = []
    if dropped_inv or dropped_kpi:
        checks.append(
            Check(
                id="partial_period_dropped",
                level="info",
                message=(
                    f"{dropped_inv + dropped_kpi} período(s) parcial(is) serão descartados "
                    f"({dropped_inv} no investimento, {dropped_kpi} na performance)."
                ),
                details={"investment": int(dropped_inv), "performance": int(dropped_kpi)},
            )
        )
    insufficient = sufficiency_check(kept_inv, kept_kpi)
    if insufficient:
        checks.append(insufficient)
    return checks, kept_inv, kept_kpi


def _gaps(dates: pd.Series, period_days: int) -> list[pd.Timestamp]:
    unique = pd.Series(pd.to_datetime(dates).unique()).sort_values().reset_index(drop=True)
    missing = []
    for before, after in itertools.pairwise(unique):
        steps = round((after - before).days / period_days)
        missing.extend(before + pd.Timedelta(days=period_days * k) for k in range(1, steps))
    return missing


def check_missing_dates(investment_df: pd.DataFrame, kpi_df: pd.DataFrame, period_days: int) -> list[Check]:
    missing = sorted(set(_gaps(investment_df["Date"], period_days)) | set(_gaps(kpi_df["Date"], period_days)))
    if not missing:
        return []
    return [
        Check(
            id="missing_dates",
            level="warning",
            message=(
                f"Faltam {len(missing)} data(s) na série entre o início e o fim dos arquivos. "
                "O motor trata lacunas como ausência de dado, não como zero."
            ),
            details={"count": len(missing), "dates": _iso(missing[:MAX_LISTED_DATES])},
        )
    ]


def check_outliers(kpi_df: pd.DataFrame) -> list[Check]:
    if kpi_df.empty:
        return []
    lower, upper = iqr_bounds(kpi_df["kpi"])
    hit = kpi_df[(kpi_df["kpi"] > upper) | (kpi_df["kpi"] < lower)].sort_values("Date")
    if hit.empty:
        return []
    return [
        Check(
            id="outliers",
            level="info",
            message=f"{len(hit)} ponto(s) do KPI fora da faixa esperada (1,5 × IQR).",
            details={"count": int(len(hit)), "dates": _iso(hit["Date"].head(MAX_LISTED_DATES))},
        )
    ]


def spend_matrix(investment_df: pd.DataFrame) -> pd.DataFrame:
    """Date × channel spend, without constant channels (no correlation or VIF for them)."""
    wide = investment_df.pivot_table(index="Date", columns="Product Group", values="investment").fillna(0)
    return wide.loc[:, wide.std() > 0]


def channel_vif(wide: pd.DataFrame) -> dict[str, float | None]:
    """VIF of each channel's spend on the others; None when one channel is an exact mix of the others."""
    x = np.column_stack([np.ones(len(wide)), wide.to_numpy(dtype=float)])
    out = {}
    with np.errstate(divide="ignore", invalid="ignore"):
        for i, name in enumerate(wide.columns, start=1):
            value = float(variance_inflation_factor(x, i))
            out[name] = round(value, 4) if np.isfinite(value) and value <= MAX_FINITE_VIF else None
    return out


def _connected(pairs: list[dict]) -> list[list[str]]:
    groups: list[set[str]] = []
    for pair in pairs:
        linked = [g for g in groups if pair["a"] in g or pair["b"] in g]
        groups = [g for g in groups if g not in linked] + [{pair["a"], pair["b"]}.union(*linked)]
    return sorted(sorted(g) for g in groups)


def collinearity(investment_df: pd.DataFrame, config: EngineConfig) -> Collinearity:
    """Pairs over the |r| gate, every channel's VIF and the groups the pairs suggest; empty on a short series."""
    wide = spend_matrix(investment_df)
    if wide.shape[1] < 2 or len(wide) < MIN_COLLINEARITY_PERIODS:
        return Collinearity()
    limit = config.gate_threshold("collinearity_r")
    corr = wide.corr()
    pairs = [
        {"a": a, "b": b, "r": round(float(corr.loc[a, b]), 4)}
        for a, b in itertools.combinations(wide.columns, 2)
        if abs(corr.loc[a, b]) > limit
    ]
    return Collinearity(pairs=pairs, vif=channel_vif(wide), suggested_groups=_connected(pairs))


def check_short_series(investment_df: pd.DataFrame) -> list[Check]:
    periods = int(investment_df["Date"].nunique())
    if periods >= MIN_COLLINEARITY_PERIODS:
        return []
    return [
        Check(
            id="collinearity_not_assessed",
            level="info",
            message=(
                f"A colinearidade entre canais não foi avaliada: o histórico tem {periods} período(s), "
                f"e o mínimo é {MIN_COLLINEARITY_PERIODS}."
            ),
            details={"periods": periods},
        )
    ]


def check_channel_overlap(investment_df: pd.DataFrame) -> list[Check]:
    """Two channels that move together and add up to the same total are probably one source reported twice."""
    if investment_df.empty:
        return []
    wide = spend_matrix(investment_df)
    checks = []
    for a, b in itertools.combinations(wide.columns, 2):
        total_a, total_b = wide[a].sum(), wide[b].sum()
        if min(total_a, total_b) <= 0:
            continue
        correlation = float(np.corrcoef(wide[a], wide[b])[0, 1])
        ratio = float(min(total_a, total_b) / max(total_a, total_b))  # symmetric: the order of the names is irrelevant
        if correlation > OVERLAP_CORRELATION and ratio >= OVERLAP_RATIO_MIN:
            checks.append(
                Check(
                    id="dv360_cm360_overlap",
                    level="warning",
                    message=(
                        f"Os canais '{a}' e '{b}' têm séries quase idênticas (correlação {correlation:.2f}, mesmo "
                        "total). Podem ser a mesma mídia reportada duas vezes; escolha qual manter."
                    ),
                    details={"channels": [a, b], "correlation": round(correlation, 4), "sum_ratio": round(ratio, 4)},
                )
            )
    return checks


def check_groups(found: Collinearity, channels: set[str], config: EngineConfig) -> list[Check]:
    """The analyst's answer to the gate: every flagged pair inside one group, or block_per_channel."""
    checks = []
    unknown = sorted({member for group in config.channel_groups for member in group} - channels)
    if unknown:
        checks.append(
            Check(
                id="channel_group_unknown",
                level="error",
                message=f"O agrupamento cita canais que não estão no arquivo de investimento: {', '.join(unknown)}.",
                details={"channels": unknown},
            )
        )
    if config.block_per_channel:
        return checks
    open_pairs = [
        p for p in found.pairs if not any(p["a"] in group and p["b"] in group for group in config.channel_groups)
    ]
    if open_pairs:
        suggested = "; ".join(" + ".join(group) for group in found.suggested_groups)
        checks.append(
            Check(
                id="collinearity_unresolved",
                level="error",
                message=(
                    "Há canais que gastam juntos, e o modelo não consegue separar o efeito de cada um "
                    f"(sugestão: {suggested}). Agrupe-os ou aceite resultados só no nível agregado."
                ),
                details={"pairs": open_pairs, "suggested_groups": found.suggested_groups},
            )
        )
    return checks


def _series_checks(raw: RawInputs) -> tuple[list[Check], int | None]:
    inv, kpi = raw.investment_df, raw.kpi_df
    if inv.empty or kpi.empty:
        return [], None
    inv_cadence, kpi_cadence = detect_cadence(inv["Date"]), detect_cadence(kpi["Date"])
    mismatch = cadence_check(inv_cadence, kpi_cadence)
    checks = [mismatch] if mismatch else []
    partial, kept_inv, kept_kpi = check_partial(inv, kpi, inv_cadence, kpi_cadence)
    checks += partial
    checks += check_missing_dates(inv, kpi, inv_cadence)
    checks += check_outliers(kept_kpi)
    checks += check_channel_overlap(kept_inv)
    return checks, inv_cadence


def validate(inputs: dict[str, Path | None], config: "dict | EngineConfig") -> ValidationReport:
    """Reads the files and reports every problem found. A problem in the data never raises: it is a check."""
    engine_config = EngineConfig.from_input(config)
    legacy = engine_config.to_legacy_dict()
    try:
        raw = read_inputs(legacy, inputs)
    except EngineError as e:
        return ValidationReport(
            ok=False,
            checks=[Check(id=e.check_id or "file_unreadable", level="error", message=str(e))],
            collinearity=Collinearity(),
        )
    series, period_days = _series_checks(raw)
    checks = [*raw.checks, *series]
    investment = raw.investment_df
    found = Collinearity()
    if not investment.empty:
        found = collinearity(investment, engine_config)
        checks += check_short_series(investment)
        checks += check_groups(found, set(investment["Product Group"]), engine_config)
    return ValidationReport(
        ok=not any(c.level == "error" for c in checks),
        cadence=None if period_days is None else CADENCE_LABEL.get(period_days, f"{period_days} dias"),
        period_days=period_days,
        date_range=None if investment.empty else _iso([investment["Date"].min(), investment["Date"].max()]),
        channels=sorted(investment["Product Group"].unique()),
        checks=checks,
        collinearity=found,
    )
