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
from engine.inputs import RawInputs, apply_channel_groups, cadence_check, read_inputs, sufficiency_check
from engine.results_schema import Check, Collinearity, ValidationReport

log = logging.getLogger(__name__)

MAX_LISTED_DATES = 50
OVERLAP_CORRELATION = 0.95
OVERLAP_RATIO_MIN = 0.9  # the smaller total over the larger: 0.9-1.1 either way round
MIN_COLLINEARITY_PERIODS = 30  # with fewer dates two channels correlate near ±1 by chance; A6/A10 calibrate
MAX_FINITE_VIF = 1e6  # above this (or negative, R² rounded past 1): perfect collinearity, reported as None
MIN_WEEKS_FOR_WEEKDAY = 5
MIN_OUTLIER_SHARE = 0.01  # an outlier also departs from its local level by more than 1% of the KPI's median
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
                    f"{dropped_inv + dropped_kpi} data(s) de período parcial saem da série "
                    f"({dropped_inv} no investimento, {dropped_kpi} na performance): nas pontas, o período é "
                    "descartado; no meio (ex.: semana partida na virada do ano), os valores são somados ao período."
                ),
                details={"investment": int(dropped_inv), "performance": int(dropped_kpi)},
            )
        )
    insufficient = sufficiency_check(kept_inv, kept_kpi)
    if insufficient:
        checks.append(insufficient)
    return checks, kept_inv, kept_kpi


ALIGNED_MIN = 0.8


def check_aligned(investment_df: pd.DataFrame, kpi_df: pd.DataFrame) -> list[Check]:
    """Every join downstream is on the exact date: weekly spend dated on Mondays and a KPI dated on Sundays share no
    row, and the MMM would read a KPI of zeros. Only KPI dates inside the investment's range count."""
    start, end = investment_df["Date"].min(), investment_df["Date"].max()
    kpi_dates = set(kpi_df.loc[kpi_df["Date"].between(start, end), "Date"])
    if not kpi_dates:
        shared = 0.0
    else:
        shared = len(kpi_dates & set(investment_df["Date"])) / len(kpi_dates)
    if shared >= ALIGNED_MIN:
        return []
    return [
        Check(
            id="dates_not_aligned",
            level="error",
            message=(
                f"Só {shared:.0%} das datas do arquivo de performance aparecem no arquivo de investimento. Os dois "
                "precisam usar as mesmas datas (no semanal, o mesmo dia da semana para cada semana)."
            ),
            details={"shared_ratio": round(shared, 4)},
        )
    ]


def _gaps(dates: pd.Series, period_days: int) -> list[pd.Timestamp]:
    unique = pd.Series(pd.to_datetime(dates).unique()).sort_values().reset_index(drop=True)
    missing = []
    for before, after in itertools.pairwise(unique):
        if period_days == 30:  # calendar months, not 30-day steps
            steps = (after.year - before.year) * 12 + after.month - before.month
            missing.extend(before + pd.DateOffset(months=k) for k in range(1, steps))
            continue
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


def _kpi_residual(kpi_df: pd.DataFrame, period_days: int) -> pd.Series:
    """The KPI minus its local level and, daily, minus each weekday's median: fences on the raw series miss a spike on
    a trend and flag the ends of a strong one. The level is the mean of the medians of the `window` periods just
    before and just after, never the point itself (a median that includes it piles residuals at zero and narrows the
    IQR). The first and last `window` points have no level: a one-sided median lags the trend and, daily, the weekday."""
    kpi = kpi_df.sort_values("Date").set_index("Date")["kpi"]
    window = 7 if period_days == 1 else 3
    before = kpi.shift(1).rolling(window).median()
    after = kpi[::-1].shift(1).rolling(window).median()[::-1]
    residual = kpi - (before + after) / 2
    if period_days == 1:
        weekday = residual.groupby(residual.index.dayofweek)
        # with few weeks the weekday's median is the spike itself
        residual -= weekday.transform("median").where(weekday.transform("count") >= MIN_WEEKS_FOR_WEEKDAY, 0)
    return residual


def check_outliers(kpi_df: pd.DataFrame, period_days: int) -> list[Check]:
    if kpi_df.empty:
        return []
    residual = _kpi_residual(kpi_df, period_days)
    lower, upper = iqr_bounds(residual)
    # on an almost noiseless KPI the IQR is ~0 and the small shift a spike leaves on its neighbours' level would count
    tolerance = MIN_OUTLIER_SHARE * float(kpi_df["kpi"].abs().median())
    hit = residual[((residual > upper) | (residual < lower)) & (residual.abs() > tolerance)].reset_index()
    if hit.empty:
        return []
    return [
        Check(
            id="outliers",
            level="info",
            message=(
                f"{len(hit)} ponto(s) do KPI fora da faixa esperada (1,5 × IQR, descontadas tendência e sazonalidade)."
            ),
            details={"count": int(len(hit)), "dates": _iso(hit["Date"].head(MAX_LISTED_DATES))},
        )
    ]


def spend_matrix(investment_df: pd.DataFrame) -> pd.DataFrame:
    """Date × channel spend, without constant channels (no correlation or VIF for them)."""
    if investment_df.empty:
        return pd.DataFrame()
    wide = investment_df.pivot_table(index="Date", columns="Product Group", values="investment").fillna(0)
    return wide.loc[:, wide.std() > 0]


def channel_vif(wide: pd.DataFrame) -> dict[str, float | None]:
    """VIF of each channel's spend on the others; None when one channel is an exact mix of the others."""
    x = np.column_stack([np.ones(len(wide)), wide.to_numpy(dtype=float)])
    out = {}
    with np.errstate(divide="ignore", invalid="ignore"):
        for i, name in enumerate(wide.columns, start=1):
            value = float(variance_inflation_factor(x, i))
            out[name] = round(value, 4) if np.isfinite(value) and 0 < value <= MAX_FINITE_VIF else None
    return out


def _connected(edges: list[tuple[str, str]]) -> list[list[str]]:
    groups: list[set[str]] = []
    for a, b in edges:
        linked = [g for g in groups if a in g or b in g]
        groups = [g for g in groups if g not in linked] + [{a, b}.union(*linked)]
    return sorted(sorted(g) for g in groups)


def _assessable(wide: pd.DataFrame) -> bool:
    return wide.shape[1] >= 2 and len(wide) >= MIN_COLLINEARITY_PERIODS


def _pairs_over(wide: pd.DataFrame, config: EngineConfig) -> list[dict]:
    if not _assessable(wide):
        return []
    limit = config.gate_threshold("collinearity_r")
    corr = wide.corr()
    return [
        {"a": a, "b": b, "r": round(float(corr.loc[a, b]), 4)}
        for a, b in itertools.combinations(wide.columns, 2)
        if abs(corr.loc[a, b]) > limit
    ]


def _not_overlap(pairs: list[dict], overlapping: set[frozenset]) -> list[dict]:
    return [p for p in pairs if frozenset((p["a"], p["b"])) not in overlapping]


def _without_twins(wide: pd.DataFrame, overlapping: set[frozenset]) -> pd.DataFrame:
    """One channel of each overlap pair: the twin's VIF only says it duplicates the other, as the overlap check does."""
    twins = {max(pair) for pair in overlapping}
    return wide.drop(columns=[c for c in wide.columns if c in twins])


def high_vif(wide: pd.DataFrame, config: EngineConfig, overlapping: set[frozenset] = frozenset()) -> list[str]:
    """Channels whose VIF is over `vif_max`, or undefined (an exact mix of the others); empty on a short series."""
    if not _assessable(wide):
        return []
    limit = config.gate_threshold("vif_max")
    vif = channel_vif(_without_twins(wide, overlapping))
    return sorted(name for name, value in vif.items() if value is None or value > limit)


def _suggested(
    wide: pd.DataFrame, pairs: list[dict], vif_channels: list[str], overlapping: set[frozenset]
) -> list[list[str]]:
    """Connected components of the pairs; a channel flagged only by its VIF joins the one it correlates with most,
    never an overlap twin (summing one source reported twice doubles it)."""
    edges = [(p["a"], p["b"]) for p in pairs]
    paired = {name for edge in edges for name in edge}
    corr = _without_twins(wide, overlapping).corr().abs()
    edges += [(name, str(corr[name].drop(name).idxmax())) for name in vif_channels if name not in paired]
    return _connected(edges)


def collinearity(wide: pd.DataFrame, config: EngineConfig, overlapping: set[frozenset] = frozenset()) -> Collinearity:
    """Pairs over the |r| gate, every channel's VIF and the groups the pairs and the VIFs suggest; empty on a short
    series. An overlap pair stays in `pairs` but is not suggested for grouping: summing one source reported twice
    doubles it. `unresolved` is filled by `validate`, on the grouped spend."""
    if not _assessable(wide):
        return Collinearity()
    pairs = _pairs_over(wide, config)
    vif_channels = high_vif(wide, config, overlapping)
    return Collinearity(
        pairs=pairs,
        vif=channel_vif(wide),
        suggested_groups=_suggested(wide, _not_overlap(pairs, overlapping), vif_channels, overlapping),
    )


def check_short_series(wide: pd.DataFrame) -> list[Check]:
    periods = len(wide)
    if wide.shape[1] < 2 or periods >= MIN_COLLINEARITY_PERIODS:
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


def check_channel_overlap(wide: pd.DataFrame) -> list[Check]:
    """Two channels that move together and add up to the same total are probably one source reported twice."""
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


def check_groups(
    kept_inv: pd.DataFrame, channels: set[str], config: EngineConfig, overlapping: set[frozenset]
) -> tuple[list[Check], list[str]]:
    """The analyst's answer to the gate, judged on the spend as modelled (groups summed): no pair over the |r| limit
    and no VIF over vif_max, or block_per_channel. Also returns the channels still over a limit (A5 hides them)."""
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
    grouped_members = {member for group in config.channel_groups for member in group}
    taken = sorted({" + ".join(group) for group in config.channel_groups} & (channels - grouped_members))
    if taken:
        checks.append(
            Check(
                id="channel_group_name_taken",
                level="error",
                message=(
                    "O nome do grupo coincide com um canal que já está no arquivo de investimento: "
                    f"{', '.join(taken)}. Renomeie esse canal no arquivo."
                ),
                details={"channels": taken},
            )
        )
    grouped = spend_matrix(apply_channel_groups(kept_inv, config.channel_groups))
    pairs = _pairs_over(grouped, config)
    open_pairs = _not_overlap(pairs, overlapping)
    vif_channels = high_vif(grouped, config, overlapping)
    # overlap twins only warn (the analyst picks one), but they stay unresolved: A5 must not publish either one alone
    unresolved = sorted({name for p in pairs for name in (p["a"], p["b"])} | set(vif_channels))
    if config.block_per_channel or not (open_pairs or vif_channels):
        return checks, unresolved
    members = {" + ".join(group): group for group in config.channel_groups}
    suggested_groups = sorted(
        sorted({m for name in group for m in members.get(name, [name])})
        for group in _suggested(grouped, open_pairs, vif_channels, overlapping)
    )
    suggested = "; ".join(" + ".join(group) for group in suggested_groups)
    vif_note = f" VIF acima de {config.gate_threshold('vif_max'):g}: {', '.join(vif_channels)}." if vif_channels else ""
    checks.append(
        Check(
            id="collinearity_unresolved",
            level="error",
            message=(
                "Há canais que gastam juntos, e o modelo não consegue separar o efeito de cada um "
                f"(sugestão: {suggested}).{vif_note} Agrupe-os ou aceite resultados só no nível agregado."
            ),
            details={"pairs": open_pairs, "vif_channels": vif_channels, "suggested_groups": suggested_groups},
        )
    )
    return checks, unresolved


def _series_checks(raw: RawInputs) -> tuple[list[Check], int | None, pd.DataFrame]:
    """The checks on the series, the cadence and the investment without its partial periods."""
    inv, kpi = raw.investment_df, raw.kpi_df
    if inv.empty or kpi.empty:
        return [], None, inv
    inv_cadence, kpi_cadence = detect_cadence(inv["Date"]), detect_cadence(kpi["Date"])
    mismatch = cadence_check(inv_cadence, kpi_cadence)
    checks = [mismatch] if mismatch else []
    partial, kept_inv, kept_kpi = check_partial(inv, kpi, inv_cadence, kpi_cadence)
    checks += partial
    if not mismatch and not kept_inv.empty and not kept_kpi.empty:
        checks += check_aligned(kept_inv, kept_kpi)
    checks += check_missing_dates(inv, kpi, inv_cadence)
    checks += check_outliers(kept_kpi, kpi_cadence)
    return checks, inv_cadence, kept_inv


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
    series, period_days, kept_inv = _series_checks(raw)
    checks = [*raw.checks, *series]
    investment = raw.investment_df
    found = Collinearity()
    if not investment.empty:
        wide = spend_matrix(kept_inv)
        overlap = check_channel_overlap(wide)
        overlapping = {frozenset(c.details["channels"]) for c in overlap}
        found = collinearity(wide, engine_config, overlapping)
        checks += [*overlap, *check_short_series(wide)]
        group_checks, found.unresolved = check_groups(
            kept_inv, set(investment["Product Group"]), engine_config, overlapping
        )
        checks += group_checks
    return ValidationReport(
        ok=not any(c.level == "error" for c in checks),
        cadence=None if period_days is None else CADENCE_LABEL.get(period_days, f"{period_days} dias"),
        period_days=period_days,
        date_range=None if investment.empty else _iso([investment["Date"].min(), investment["Date"].max()]),
        channels=sorted(investment["Product Group"].unique()),
        checks=checks,
        collinearity=found,
    )
