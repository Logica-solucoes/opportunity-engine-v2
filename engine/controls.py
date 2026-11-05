"""Screening of causal controls: a control that moves with the treated channel's spend is an effect of it, not a control."""

import numpy as np
import pandas as pd


def screen_controls(
    pre_data: pd.DataFrame, candidates: list[str], treated_channels: list[str], threshold: float
) -> tuple[list[str], list[dict]]:
    """Returns (accepted names, rejected as {"name", "r"}) for one event's pre-period.

    A candidate is rejected when `abs(r) > threshold` against the summed raw spend of the treated channels. An
    undefined correlation (constant series) does not reject. Candidates that are not columns are ignored.
    """
    missing = [c for c in treated_channels if c not in pre_data.columns]
    if missing:
        raise ValueError(f"canais tratados ausentes do pré-período: {missing}")
    spend = pre_data[treated_channels].sum(axis=1)
    accepted: list[str] = []
    rejected: list[dict] = []
    for name in dict.fromkeys(c for c in candidates if c in pre_data.columns):
        with np.errstate(divide="ignore", invalid="ignore"):
            r = pre_data[name].corr(spend)
        if pd.notna(r) and abs(r) > threshold:
            rejected.append({"name": name, "r": round(float(r), 4)})
        else:
            accepted.append(name)
    rejected.sort(key=lambda item: (-abs(item["r"]), item["name"]))
    return sorted(accepted), rejected
