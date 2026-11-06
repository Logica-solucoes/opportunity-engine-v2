"""Run-level sufficiency (A6): do the data support publishing a lift at all?"""

import statistics

import pandas as pd

from engine.config import GateThresholds
from engine.results_schema import Sufficiency

CAUSAL_REASONS = ("no_validated_event", "low_spend_variation", "high_oos_wmape")


def spend_cv(investment_df: pd.DataFrame, channels: list[str]) -> dict[str, float]:
    """std/mean of each channel's raw spend per native period over the whole range (0 when the mean is 0)."""
    pivot = investment_df.pivot_table(index="Date", columns="Product Group", values="investment").fillna(0)
    out = {}
    for name in channels:
        series = pivot[name] if name in pivot.columns else pd.Series(dtype=float)
        mean = float(series.mean()) if len(series) else 0.0
        out[name] = float(series.std(ddof=0)) / mean if mean > 0 else 0.0
    return out


def assess(
    validated: list[dict], investment_df: pd.DataFrame, cv_out_of_sample: bool | None, thresholds: GateThresholds
) -> Sufficiency:
    """`validated`: {"product_group", "oos_wmape"} of every event that passed all the gates."""
    channels = list(dict.fromkeys(c for e in validated for c in e["product_group"].split(", ") if c))
    variation = spend_cv(investment_df, channels)
    wmapes = [e["oos_wmape"] for e in validated if e.get("oos_wmape") is not None]
    pre_wmape = statistics.median(wmapes) if wmapes else None

    reasons = []
    if not validated:
        reasons.append("no_validated_event")
    if any(cv < thresholds.spend_cv_min for cv in variation.values()):
        reasons.append("low_spend_variation")
    if pre_wmape is not None and pre_wmape > thresholds.oos_wmape_max:
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
