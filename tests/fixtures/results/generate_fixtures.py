"""Regenerate the results.json fixtures: uv run python tests/fixtures/results/generate_fixtures.py

Needs exemplo_csv/Gol (confidential, not versioned) and tests/fixtures/results/.private/factors.json (created on the
first run; keep it, a different factors file produces different fixtures). ~3 minutes, single-threaded BLAS.
"""

import logging
import os
import shutil
import sys
import tempfile
import warnings
from pathlib import Path

import pandas as pd
from threadpoolctl import threadpool_limits

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))
os.environ["LLM_PROVIDER"] = "none"

import engine
from engine import results
from engine.config import EngineConfig
from engine.pipeline import Computed, load_inputs
from tests.engine.real_data import GOL_CONFIG, gol_files
from tests.engine.synthetic_data import dataset_config, make_dataset
from tests.fixtures.results.anonymize_gol import anonymize, load_factors


def failed_document() -> dict:
    """A run where nothing worked: no events and no model."""
    with tempfile.TemporaryDirectory() as tmp:
        config = EngineConfig.from_input(dataset_config())
        files = make_dataset(Path(tmp), n_days=120)
        prepared = load_inputs(files, config)
        report = engine.validate(files, config)
    computed = Computed(
        prepared=prepared, effective_config=config.to_legacy_dict(), events=[], mmm=None, validation=report
    )
    return results.dump_results(results.build_results(computed, "fixture"))


def main() -> None:
    warnings.filterwarnings("ignore")
    logging.disable(logging.CRITICAL)
    gol = gol_files()
    last_day = pd.to_datetime(pd.read_csv(gol["performance_file"], encoding="utf-8-sig")["date"], dayfirst=True).max()
    with tempfile.TemporaryDirectory() as tmp, threadpool_limits(limits=1):
        files, _ = anonymize(gol, GOL_CONFIG["column_mapping"], Path(tmp) / "data", load_factors())
        runs = {
            "gol_anonimizada.json": GOL_CONFIG,
            "gol_inconclusiva.json": {
                **GOL_CONFIG,
                "min_intervention_date": (last_day + pd.Timedelta(days=1)).strftime("%Y-%m-%d"),
            },
        }
        for name, config in runs.items():
            out = Path(tmp) / name.removesuffix(".json")
            engine.run(files, config, out, lambda level, message: None)
            shutil.copyfile(out / "results.json", HERE / name)
            print(f"wrote {name}", file=sys.stderr)
    results.write_results(failed_document(), HERE / "falha.json")
    print("wrote falha.json", file=sys.stderr)


if __name__ == "__main__":
    main()
