"""Pairwise correlation and VIF of the spend per channel: do two channels move together too much to be told apart?"""

import itertools

import numpy as np
import pandas as pd
import statsmodels.api as sm
from statsmodels.stats.outliers_influence import variance_inflation_factor

from engine.results_schema import Collinearity


def _vif(wide: pd.DataFrame) -> dict[str, float | None]:
    n_rows, n_channels = wide.shape
    if n_channels < 2 or n_rows <= n_channels + 1:
        return {}
    matrix = sm.add_constant(wide.to_numpy(dtype=float), has_constant="add")
    out: dict[str, float | None] = {}
    with np.errstate(divide="ignore", invalid="ignore"):
        for i, name in enumerate(wide.columns, start=1):
            value = float(variance_inflation_factor(matrix, i))
            out[name] = round(value, 4) if np.isfinite(value) else None
    return out


def flagged(result: Collinearity, vif_max: float) -> tuple[list[dict], list[str]]:
    """(pairs, channels whose VIF is above the limit or undefined)."""
    high = sorted(name for name, value in result.vif.items() if value is None or value > vif_max)
    return result.pairs, high


def _components(edges: list[tuple[str, str]]) -> list[list[str]]:
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in edges:
        parent[find(a)] = find(b)
    groups: dict[str, list[str]] = {}
    for node in list(parent):
        groups.setdefault(find(node), []).append(node)
    return sorted(sorted(members) for members in groups.values() if len(members) > 1)


def analyze(wide: pd.DataFrame, r_max: float, vif_max: float) -> Collinearity:
    """`wide` is Date x channel with 0 where a channel has no spend; constant and all-zero channels are left out."""
    wide = wide.loc[:, (wide.std() > 0) & (wide.sum() > 0)].sort_index(axis=1)
    if wide.shape[1] < 2:
        return Collinearity()
    corr = wide.corr()
    pairs = [
        {"a": a, "b": b, "r": round(float(corr.loc[a, b]), 4)}
        for a, b in itertools.combinations(wide.columns, 2)
        if abs(corr.loc[a, b]) > r_max
    ]
    pairs.sort(key=lambda p: (-abs(p["r"]), p["a"], p["b"]))
    result = Collinearity(pairs=pairs, vif=_vif(wide))

    edges = [(p["a"], p["b"]) for p in pairs]
    paired = {name for edge in edges for name in edge}
    for name in flagged(result, vif_max)[1]:
        if name in paired:
            continue
        others = corr[name].drop(name).abs()
        edges.append((name, str(others.idxmax())))
    result.suggested_groups = _components(edges)
    return result
