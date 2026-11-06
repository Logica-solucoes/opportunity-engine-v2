"""Run-level sufficiency (A6): do the data support publishing a lift at all? Pure over what compute() already has."""

import statistics

import pandas as pd

from engine.results_schema import Sufficiency

# the reasons that are about the causal analysis: they demote the run's events (pipeline.judge_sufficiency)
CAUSAL_REASONS = frozenset({"no_validated_event", "low_spend_variation", "high_oos_wmape"})


def spend_cv(investment_df: pd.DataFrame, channels: list[str]) -> dict[str, float]:
    """std/mean of each channel's spend per period over the whole range; 0 for a channel that never spent."""
    pivot = investment_df.pivot_table(index="Date", columns="Product Group", values="investment").fillna(0)
    out = {}
    for name in channels:
        series = pivot[name] if name in pivot.columns else pd.Series(dtype=float)
        mean = float(series.mean()) if len(series) else 0.0
        out[name] = float(series.std(ddof=0)) / mean if mean > 0 else 0.0
    return out


def assess(
    validated: list[dict],
    investment_df: pd.DataFrame,
    cv_out_of_sample: bool | None,
    spend_cv_min: float,
    oos_wmape_max: float,
) -> Sufficiency:
    """`validated`: {"channels", "oos_wmape"} of each event that passed every event gate. A WMAPE that could not be
    computed for any event, or a run without a model (cv_out_of_sample None), does not fail its check."""
    channels = list(dict.fromkeys(c for event in validated for c in event["channels"]))
    variation = spend_cv(investment_df, channels)
    wmapes = [event["oos_wmape"] for event in validated if event["oos_wmape"] is not None]
    pre_wmape = statistics.median(wmapes) if wmapes else None
    reasons = []
    if not validated:
        reasons.append("no_validated_event")
    if any(cv < spend_cv_min for cv in variation.values()):
        reasons.append("low_spend_variation")
    if pre_wmape is not None and pre_wmape > oos_wmape_max:
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
