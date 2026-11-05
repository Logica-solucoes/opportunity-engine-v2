"""Channel groups: the analyst's answer to collinearity. Members' spend is summed before any modelling."""

import pandas as pd

from engine.results_schema import Check

DEFAULT_COLLINEARITY_R = 0.85
DEFAULT_VIF_MAX = 10.0


def _normalize(name: str) -> str:
    return str(name).strip().upper()


def group_name(members: list[str]) -> str:
    return " + ".join(_normalize(m) for m in members)


def thresholds(config: dict) -> tuple[float, float]:
    """(collinearity_r, vif_max) from `gate_thresholds`, with the defaults for what is not set."""
    gate = config.get("gate_thresholds") or {}
    return (
        float(gate.get("collinearity_r", DEFAULT_COLLINEARITY_R)),
        float(gate.get("vif_max", DEFAULT_VIF_MAX)),
    )


def _error(check_id: str, message: str, channels: list[str]) -> Check:
    return Check(id=check_id, level="error", message=message, details={"channels": channels})


def apply_groups(investment_df: pd.DataFrame, groups: list[list[str]]) -> tuple[pd.DataFrame, list[Check]]:
    """Returns the investment with each group as one channel, or the input untouched plus the errors found."""
    if not groups:
        return investment_df, []
    normalized = [[_normalize(m) for m in members] for members in groups]
    known = set(investment_df["Product Group"].unique())

    checks: list[Check] = []
    unknown = sorted({m for members in normalized for m in members} - known)
    if unknown:
        checks.append(
            _error(
                "group_unknown_channel",
                f"Os grupos citam canais que não existem no arquivo de investimento: {', '.join(unknown)}.",
                unknown,
            )
        )
    seen: set[str] = set()
    repeated: set[str] = set()
    for members in normalized:
        for m in set(members):
            (repeated if m in seen else seen).add(m)
    if repeated:
        checks.append(
            _error(
                "group_overlap",
                f"Um canal só pode estar em um grupo; repetidos: {', '.join(sorted(repeated))}.",
                sorted(repeated),
            )
        )
    small = [group_name(members) for members in normalized if len(set(members)) < 2]
    if small:
        checks.append(
            _error("group_too_small", f"Cada grupo precisa de pelo menos 2 canais: {', '.join(small)}.", small)
        )
    if checks:
        return investment_df, checks

    renames = {m: group_name(members) for members in normalized for m in members}
    df = investment_df.assign(**{"Product Group": investment_df["Product Group"].replace(renames)})
    grouped = df.groupby(["Date", "Product Group"], as_index=False)["investment"].sum()
    return grouped[["Date", "Product Group", "investment"]], []
