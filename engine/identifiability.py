"""Per-channel identifiability: can the data tell this channel's effect from zero, and pin it down?"""

import numpy as np

from engine.results_schema import ValidationReport

UNIDENTIFIED_KEY = "nao_identificavel"  # where the channels that fail are pooled in every published mix


def assess(coefs: np.ndarray, columns: list[str], width_ratio: float, collinear_channels: set[str]) -> dict[str, dict]:
    """`coefs` is the bootstrap matrix (resamples x channels). A channel is identifiable when the 95% interval of its
    coefficient stays above zero and is no wider than `width_ratio` times the coefficient itself (the bootstrap mean,
    which is the one the model uses). A channel the collinearity gate flagged is never identifiable."""
    lo, hi = np.percentile(coefs, [2.5, 97.5], axis=0)
    point = coefs.mean(axis=0)
    out: dict[str, dict] = {}
    for i, name in enumerate(columns):
        reasons = []
        if not lo[i] > 0 or point[i] == 0:
            reasons.append("ci_crosses_zero")
        elif (hi[i] - lo[i]) > width_ratio * abs(point[i]):
            reasons.append("ci_too_wide")
        if name in collinear_channels:
            reasons.append("collinearity")
        out[name] = {
            "identifiable": not reasons,
            "reasons": reasons,
            "coef_ci": (float(lo[i]), float(hi[i])),
            "point": float(point[i]),
        }
    return out


def collinear_channels(validation: ValidationReport | None, vif_max: float) -> set[str]:
    """Channels the A3 gate flagged: in a pair above the correlation limit, or with a VIF above the limit (or undefined)."""
    collinearity = None if validation is None else validation.collinearity
    if collinearity is None:
        return set()
    flagged = {name for pair in collinearity.pairs for name in (pair["a"], pair["b"])}
    flagged |= {name for name, value in collinearity.vif.items() if value is None or value > vif_max}
    return flagged


def hidden_channels(identifiability: dict[str, dict] | None) -> set[str]:
    """Channels that must not be published on their own; empty when nothing was assessed."""
    if not identifiability:
        return set()
    return {name for name, verdict in identifiability.items() if not verdict["identifiable"]}


def pool(values: dict[str, float | None], hidden: set[str]) -> dict[str, float | None]:
    """`values` with the hidden channels summed under UNIDENTIFIED_KEY (the key exists only if one was pooled)."""
    kept = {name: value for name, value in values.items() if name not in hidden}
    pooled = [value for name, value in values.items() if name in hidden]
    if pooled:
        kept[UNIDENTIFIED_KEY] = None if any(v is None for v in pooled) else sum(pooled)
    return kept


def reallocation_suppressed(identifiability: dict[str, dict] | None) -> bool:
    """The gain of moving budget between channels rests on every channel's coefficient: it is not published (nor
    narrated by the LLM) while any channel is not identifiable."""
    return bool(hidden_channels(identifiability))
