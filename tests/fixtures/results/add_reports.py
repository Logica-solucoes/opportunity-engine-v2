"""Fill `reports` (A9) into the committed fixtures without rerunning the engine:

    uv run python tests/fixtures/results/add_reports.py

The narratives only read the document, so with no LLM this writes exactly what generate_fixtures.py would.
"""

import json
import logging
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from engine import narratives, results
from engine.config import EngineConfig
from engine.results_schema import ResultsV1
from tests.engine.real_data import GOL_RUN_CONFIG
from tests.engine.synthetic_data import dataset_config, identifiable_config

log = logging.getLogger(__name__)
CONFIGS = {
    "gol_anonimizada.json": GOL_RUN_CONFIG,
    "gol_inconclusiva.json": GOL_RUN_CONFIG,
    "identificavel.json": identifiable_config(),
    "falha.json": dataset_config(),
}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for name, config in CONFIGS.items():
        path = HERE / name
        document = json.loads(path.read_text(encoding="utf-8"))
        document["reports"] = narratives.build(document, EngineConfig.from_input(config), None)
        results.write_results(results.dump_results(ResultsV1.model_validate(document)), path)
        log.info("wrote %s", name)


if __name__ == "__main__":
    main()
