"""Real client data (exemplo_csv/, never versioned) for the real-data parity check.

The legacy numbers come from `mise run parity-real` into tests/fixtures/parity/real/ (also never versioned).
"""

from pathlib import Path

from engine.config import EngineConfig
from tests.fixtures.parity.generate_legacy_snapshot import jsonable

REPO_ROOT = Path(__file__).resolve().parents[2]
GOL_DIR = REPO_ROOT / "exemplo_csv" / "Gol"
GOL_SNAPSHOT = REPO_ROOT / "tests" / "fixtures" / "parity" / "real" / "gol.json"

GOL_CONFIG = {
    "column_mapping": {
        "investment_file": {"date_col": "date", "channel_col": "channel", "investment_col": "investment"},
        "performance_file": {"date_col": "date", "kpi_col": "kpi"},
        "generic_trends_file": {"date_col": "date", "trends_col": "Generic Searches"},
    },
    "date_formats": {
        "investment_file": "%d/%m/%Y",
        "performance_file": "%d/%m/%Y",
        "generic_trends_file": "%d/%m/%Y",
    },
}


def gol_files() -> dict[str, Path]:
    return {
        "investment_file": GOL_DIR / "investment.csv",
        "performance_file": GOL_DIR / "performance.csv",
        "generic_trends_file": GOL_DIR / "trends.csv",
    }


def gol_spec() -> dict:
    """What the prototype's generator needs (--dataset-json): the same config the engine gets, in its legacy shape."""
    legacy = EngineConfig.from_input(GOL_CONFIG).to_legacy_dict()
    return {"legacy": legacy, "files": {key: str(path) for key, path in gol_files().items()}}


def engine_snapshot(computed) -> dict:
    """The engine's numbers in the exact shape generate_legacy_snapshot.py writes."""
    snapshot = {
        "period_days": computed.prepared.period_days,
        "events": [
            {
                "event_id": e.event_id,
                "product_group": e.product_group,
                "intervention_date": e.intervention_date,
                "results_data": jsonable(e.results_data) if e.results_data else None,
                "passed": e.passed,
                "reasons": e.reasons,
                "selected": e.selected,
            }
            for e in computed.events
        ],
        "mmm": None,
        "response_curve": None,
        "points": None,
    }
    mmm = computed.mmm
    if mmm:
        spend_cols = mmm["spend_cols"]
        snapshot["mmm"] = {
            "contribution_pct": jsonable(mmm["contribution_pct"]),
            "r_squared": float(mmm["r_squared"]),
            "cv_r_squared": float(mmm["cv_r_squared"]),
            "marketing_contribution_of_kpi_pct": float(mmm["marketing_contribution_of_kpi_pct"]),
            "optimal_params": {
                key: dict(zip(spend_cols, jsonable(mmm["optimal_params"][key]), strict=True))
                for key in ("alphas", "ks", "ss")
            },
        }
        snapshot["response_curve"] = jsonable(computed.response_curve_df)
        snapshot["points"] = jsonable(
            {
                "baseline": computed.baseline_point,
                "max_efficiency": computed.max_efficiency_point,
                "strategic_limit": computed.strategic_limit_point,
                "diminishing_return": computed.diminishing_return_point,
                "saturation": computed.saturation_point,
                "strategic_reallocation": computed.strategic_reallocation_point,
            }
        )
        snapshot["optimized_mix"] = jsonable(computed.optimized_mix)
    return snapshot
