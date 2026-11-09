"""Run-level sufficiency (A6): do the data support publishing a lift at all? Pure over what compute() already has."""

import statistics

import numpy as np
import pandas as pd

from engine.data_preprocessor import detect_cadence
from engine.results_schema import Sufficiency

# the reasons that are about the causal analysis: they demote the run's events (pipeline.judge_sufficiency)
CAUSAL_REASONS = frozenset({"no_validated_event", "low_spend_variation", "high_oos_wmape"})


def _weekly_rate(pivot: pd.DataFrame) -> pd.DataFrame:
    """Spend per day averaged by week: the CV must not depend on the file's cadence (summing daily pacing noise into
    months divides its CV by ~√30) nor count months of different length as variation. A month stays one period."""
    period_days = detect_cadence(pivot.index) if len(pivot) > 1 else 1
    if period_days == 30:
        return pivot.div(pivot.index.days_in_month, axis=0)
    weeks = (pivot.index - pivot.index.min()).days // 7
    return (pivot / period_days).groupby(weeks).mean()


def spend_cv(investment_df: pd.DataFrame, channels: list[str]) -> dict[str, float]:
    """std/mean of each channel's weekly spend rate over the whole range; 0 for a channel that never spent."""
    pivot = investment_df.pivot_table(index="Date", columns="Product Group", values="investment").fillna(0)
    pivot = _weekly_rate(pivot)
    out = {}
    for name in channels:
        series = pivot[name] if name in pivot.columns else pd.Series(dtype=float)
        mean = float(series.mean()) if len(series) else 0.0
        out[name] = float(series.std(ddof=0)) / mean if mean > 0 else 0.0
    return out


def seasonal_naive_wmape(train, holdout, season: int) -> float | None:
    """WMAPE of repeating the train's last season over the holdout (its last value when the train is shorter than a
    season): the benchmark the model's out-of-sample WMAPE is judged against. None when the holdout sums to zero."""
    train, holdout = np.asarray(train, dtype=float), np.asarray(holdout, dtype=float)
    season = season if len(train) >= season else 1
    forecast = np.resize(train[-season:], len(holdout))
    total = float(np.abs(holdout).sum())
    return float(np.abs(holdout - forecast).sum() / total) if total else None


def _skill(event: dict) -> float | None:
    model, naive = event["oos_wmape"], event.get("naive_wmape")
    if model is None or not naive:
        return None
    return 1 - model / naive


def assess(
    validated: list[dict],
    investment_df: pd.DataFrame,
    cv_out_of_sample: bool | None,
    spend_cv_min: float,
    oos_skill_min: float,
) -> Sufficiency:
    """`validated`: {"channels", "oos_wmape", "naive_wmape"} of each event that passed every event gate.

    high_oos_wmape: the median skill over the seasonal naive (1 − WMAPE / naive WMAPE) is under `oos_skill_min`. An
    absolute WMAPE ceiling fails a low-volume KPI even with a perfect model. An event without both WMAPEs, or a run
    without a model (cv_out_of_sample None), does not fail its check.
    """
    channels = list(dict.fromkeys(c for event in validated for c in event["channels"]))
    variation = spend_cv(investment_df, channels)
    wmapes = [event["oos_wmape"] for event in validated if event["oos_wmape"] is not None]
    pre_wmape = statistics.median(wmapes) if wmapes else None
    skills = [s for s in map(_skill, validated) if s is not None]
    reasons = []
    if not validated:
        reasons.append("no_validated_event")
    if any(cv < spend_cv_min for cv in variation.values()):
        reasons.append("low_spend_variation")
    if skills and statistics.median(skills) < oos_skill_min:
        reasons.append("high_oos_wmape")
    if cv_out_of_sample is False:
        reasons.append("cv_in_sample")
    return Sufficiency(
        passed=not reasons,
        spend_variation=variation,
        validated_events=len(validated),
        pre_wmape=pre_wmape,
        reasons=reasons,
        cv_out_of_sample=cv_out_of_sample,
    )
