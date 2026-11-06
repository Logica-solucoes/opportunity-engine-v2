"""Per-channel identifiability (A5): the bootstrap spread of a channel's contribution decides whether it is published."""

import numpy as np

UNIDENTIFIED = "Não identificados"  # no channel collides: names are upper-cased on load (data_preprocessor)


def assess(mmm: dict) -> dict[str, dict]:
    """{channel: {"ci": (p2.5, p97.5), "identifiable": bool, "reasons": [...]}}, the CI in KPI units over the period.

    The Ridge is positive, so a contribution is never negative: "the CI crosses zero" is p2.5 == 0.
    """
    totals = np.asarray(mmm["channel_totals"])
    contributions = np.asarray(mmm["coef_samples"]) * totals
    points = np.asarray(mmm["model"].coef_) * totals
    lo, hi = np.percentile(contributions, [2.5, 97.5], axis=0)
    verdicts = {}
    for i, name in enumerate(mmm["spend_cols"]):
        reasons = []
        if lo[i] <= 0:
            reasons.append("coef_ci_includes_zero")
        if hi[i] - lo[i] > points[i]:
            reasons.append("coef_ci_too_wide")
        verdicts[name] = {"ci": (float(lo[i]), float(hi[i])), "identifiable": not reasons, "reasons": reasons}
    return verdicts


def unidentified(verdicts: dict[str, dict]) -> set[str]:
    return {name for name, verdict in verdicts.items() if not verdict["identifiable"]}


def fold_mix(mix: dict[str, float | None], hidden: set[str]) -> dict[str, float | None]:
    """The mix without the hidden channels, their spend summed under UNIDENTIFIED (a missing value counts as 0)."""
    if not hidden & mix.keys():
        return mix
    kept = {name: value for name, value in mix.items() if name not in hidden}
    kept[UNIDENTIFIED] = sum(value or 0.0 for name, value in mix.items() if name in hidden)
    return kept
