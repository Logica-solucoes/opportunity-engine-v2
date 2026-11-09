"""Per-channel identifiability (A5): the bootstrap spread of a channel's contribution decides whether it is published."""

import numpy as np

UNIDENTIFIED = "Não identificados"  # no channel collides: names are upper-cased on load (data_preprocessor)


def assess(mmm: dict, collinear: set[str] = frozenset()) -> dict[str, dict]:
    """{channel: {"ci": (p2.5, p97.5), "identifiable": bool, "reasons": [...]}}, the CI in KPI units over the period.

    The Ridge is positive, so a contribution is never negative: "the CI crosses zero" is p2.5 == 0. A channel the
    collinearity gate left open (block_per_channel) is never identifiable, whatever its CI, and neither is one whose
    floor under the observed spend the Hill bound set (mmm["unmeasured_floor"]): the bootstrap holds Hill fixed, so its
    CI misses that the level at zero spend is not in the data.

    hi - lo <= point is a precision rule: the 95% half-width at most half the contribution, about point/se >= 3.92
    against the 1.96 of "clear of zero", so every channel that fails coef_ci_includes_zero also fails it (G5). It stays
    on purpose: the bootstrap holds the adstock/Hill fitted on the same rows, and with only the zero test a no-effect
    channel came out identifiable at point/se ~2.5 in 2 of the 3 acceptance seeds.
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
        if name in collinear:
            reasons.append("collinearity")
        if name in mmm.get("unmeasured_floor", ()):
            reasons.append("hill_at_bound")
        verdicts[name] = {"ci": (float(lo[i]), float(hi[i])), "identifiable": not reasons, "reasons": reasons}
    return verdicts


def unidentified(verdicts: dict[str, dict]) -> set[str]:
    return {name for name, verdict in verdicts.items() if not verdict["identifiable"]}


def none_identifiable(verdicts: dict[str, dict]) -> bool:
    return bool(verdicts) and not any(v["identifiable"] for v in verdicts.values())


def reallocation_suppressed(verdicts: dict[str, dict]) -> bool:
    """Moving the same budget between channels rests on every channel's own effect: no reallocation while any is hidden."""
    return bool(unidentified(verdicts))


def fold_mix(mix: dict[str, float | None], hidden: set[str]) -> dict[str, float | None]:
    """The mix without the hidden channels, their spend summed under UNIDENTIFIED (None when one of them is missing)."""
    if not hidden & mix.keys():
        return mix
    kept = {name: value for name, value in mix.items() if name not in hidden}
    pooled = [value for name, value in mix.items() if name in hidden]
    kept[UNIDENTIFIED] = None if any(value is None for value in pooled) else sum(pooled)
    return kept
