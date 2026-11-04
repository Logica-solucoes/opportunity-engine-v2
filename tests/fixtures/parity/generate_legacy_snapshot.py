"""Generate the parity snapshot by running the FROZEN prototype's functions directly.

Run it with the prototype's own environment, never with this repo's:

    cd <legacy repo> && uv run python <this dir>/generate_legacy_snapshot.py --legacy-repo . --out snapshot.json

The prototype repo is never modified. This is a tool script, not engine code (it touches sys.path on purpose).
"""

import argparse
import json
import logging
import sys
import tempfile
import warnings
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[3]


def jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [jsonable(v) for v in obj]
    if isinstance(obj, pd.DataFrame):
        return {str(c): jsonable(obj[c].tolist()) for c in obj.columns}
    if isinstance(obj, np.ndarray):
        return jsonable(obj.tolist())
    if isinstance(obj, (np.floating, float)):
        return float(obj)
    if isinstance(obj, (np.integer, np.bool_)):
        return obj.item()
    if isinstance(obj, (pd.Timestamp,)):
        return obj.strftime("%Y-%m-%d")
    return obj


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy-repo", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()

    sys.path.insert(0, str(args.legacy_repo.resolve() / "scripts"))
    sys.path.insert(0, str(REPO_ROOT))
    warnings.filterwarnings("ignore")
    logging.disable(logging.CRITICAL)

    import analysis
    import data_preprocessor
    import elasticity_analysis as mmm
    import scipy
    import sklearn
    import statsmodels

    from tests.engine.synthetic_data import dataset_config, make_dataset

    with tempfile.TemporaryDirectory() as tmp:
        files = make_dataset(Path(tmp))
        config = {
            **dataset_config(),
            "investment_file_path": str(files["investment_file"]),
            "performance_file_path": str(files["performance_file"]),
            "generic_trends_file_path": str(files["generic_trends_file"]),
            "output_directory": tmp,
        }

        kpi_df, inv_df, trends_df, _ = data_preprocessor.load_and_prepare_data(config)
        perf_df = data_preprocessor.read_csv_robust(config["performance_file_path"], on_bad_lines="skip")
        date_col = config["column_mapping"]["performance_file"]["date_col"]
        perf_df.rename(columns={date_col: "Date"}, inplace=True)
        period_days = config.get("period_days", 1)

        increase_ratio = 1 + config["increase_threshold_percent"] / 100
        decrease_ratio = 1 - config["decrease_threshold_percent"] / 100
        span, _ = analysis.periods_to_days(config["post_event_days"], period_days, 4, label="post_event_days")
        event_map, _, _ = analysis.find_events(
            inv_df,
            config["advertiser_name"],
            increase_ratio,
            decrease_ratio,
            config["post_event_days"],
            output_dir=None,
            period_days=period_days,
        )

        events = []
        if event_map is not None and not event_map.empty:
            groups = ", ".join(event_map["ad_product"].unique())
            projection = analysis.run_opportunity_projection(kpi_df, inv_df, trends_df, groups, config)
            model_params = projection[7]
            min_date = kpi_df["Date"].min().strftime("%Y-%m-%d")
            for _, row in event_map.iterrows():
                day = pd.to_datetime(row["date"])
                event_id = f"{config['advertiser_name']}_{row['ad_product'].replace(' ', '_')}_{day.date()}"
                pre = [min_date, (day - timedelta(days=1)).strftime("%Y-%m-%d")]
                post = [day.strftime("%Y-%m-%d"), (day + timedelta(days=span)).strftime("%Y-%m-%d")]
                results, *_ = analysis.run_causal_impact_analysis(
                    kpi_df, inv_df, trends_df, perf_df, pre, post, event_id, row["ad_product"], model_params, config
                )
                reasons = []
                if not results:
                    reasons = ["analysis_failed"]
                else:
                    if config.get("require_statistical_significance", True) and not (
                        results["p_value"] < config["p_value_threshold"]
                    ):
                        reasons.append("not_significant")
                    up = results["investment_change_pct"] > 0 and results["absolute_lift"] > 0
                    down = results["investment_change_pct"] < 0 and results["absolute_lift"] < 0
                    if config.get("require_logical_direction", True) and not (up or down):
                        reasons.append("illogical_direction")
                    if config.get("require_model_fit", True) and not (
                        results.get("model_r_squared", 0) >= config["r_squared_threshold"]
                    ):
                        reasons.append("poor_fit")
                events.append(
                    {
                        "event_id": event_id,
                        "product_group": row["ad_product"],
                        "intervention_date": day.strftime("%Y-%m-%d"),
                        "results_data": jsonable(results) if results else None,
                        "passed": not reasons,
                        "reasons": reasons,
                    }
                )
        passed = sorted(
            (e for e in events if e["passed"]), key=lambda e: abs(e["results_data"]["absolute_lift"]), reverse=True
        )
        selected = {e["event_id"] for e in passed[: config["max_events_to_analyze"]]}
        for e in events:
            e["selected"] = e["event_id"] in selected

        mmm_results = mmm.run_mmm_engine(config)
        snapshot = {
            "versions": {
                "numpy": np.__version__,
                "pandas": pd.__version__,
                "scipy": scipy.__version__,
                "statsmodels": statsmodels.__version__,
                "sklearn": sklearn.__version__,
            },
            "period_days": period_days,
            "events": events,
            "mmm": None,
            "response_curve": None,
            "points": None,
        }
        if mmm_results:
            spend_cols = mmm_results["spend_cols"]
            params = mmm_results["optimal_params"]
            snapshot["mmm"] = {
                "contribution_pct": jsonable(mmm_results["contribution_pct"]),
                "r_squared": float(mmm_results["r_squared"]),
                "cv_r_squared": float(mmm_results["cv_r_squared"]),
                "marketing_contribution_of_kpi_pct": float(mmm_results["marketing_contribution_of_kpi_pct"]),
                "optimal_params": {
                    key: dict(zip(spend_cols, jsonable(params[key]), strict=True)) for key in ("alphas", "ks", "ss")
                },
            }
            optimized_mix = analysis.find_optimal_historical_mix(kpi_df, inv_df) or {}
            curve, baseline, max_eff, strategic, diminishing, saturation, realloc = (
                mmm.generate_aggregated_response_curve(
                    mmm_results, config, optimized_mix=optimized_mix, output_dir=None
                )
            )
            snapshot["response_curve"] = jsonable(curve)
            snapshot["points"] = jsonable(
                {
                    "baseline": baseline,
                    "max_efficiency": max_eff,
                    "strategic_limit": strategic,
                    "diminishing_return": diminishing,
                    "saturation": saturation,
                    "strategic_reallocation": realloc,
                }
            )
            snapshot["optimized_mix"] = jsonable(optimized_mix)

    args.out.write_text(json.dumps(snapshot, indent=1, sort_keys=True), encoding="utf-8")
    print(f"events={len(events)} selected={len(selected)} mmm={'yes' if mmm_results else 'no'}", file=sys.stderr)


if __name__ == "__main__":
    main()
