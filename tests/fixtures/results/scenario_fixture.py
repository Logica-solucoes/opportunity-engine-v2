"""Write identificavel_scenario.json, the unfiltered scenario of identificavel.json, for the E2E of the elasticity tab:
uv run python tests/fixtures/results/scenario_fixture.py (seconds; rerun after regenerating identificavel.json)."""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from engine import EngineConfig, ScenarioFilters, scenario

SOURCE, TARGET = HERE / "identificavel.json", HERE / "identificavel_scenario.json"


def build() -> dict:
    doc = json.loads(SOURCE.read_text(encoding="utf-8"))
    return scenario(doc, ScenarioFilters(), EngineConfig().max_budget_step)


if __name__ == "__main__":
    TARGET.write_text(json.dumps(build(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {TARGET.name}", file=sys.stderr)
