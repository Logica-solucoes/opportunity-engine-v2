"""Pins the engine's own numbers (python -m tests.fixtures.parity.make_engine_goldens), under the numeric pins, on Linux.

Since the math audit fixes (09/nov/2026) the engine departs from the frozen prototype on purpose in every block, so
test_parity.py and test_parity_real.py compare against these goldens: they catch regressions, they are not parity.
The script prints how far each block moved from the prototype (snapshot.json, real/gol.json); the reasons are in
docs/audit/diferencas-prototipo.md. Regenerate only with approval, after reading the deltas.
"""

import json
from pathlib import Path

import numpy as np
import pandas
import scipy
import sklearn
import statsmodels
from threadpoolctl import threadpool_limits

from engine.config import EngineConfig
from engine.pipeline import compute
from tests.engine.real_data import GOL_CONFIG, GOL_ENGINE, GOL_SNAPSHOT, engine_snapshot, gol_files
from tests.engine.synthetic_data import dataset_config, make_dataset

HERE = Path(__file__).resolve().parent
ENGINE_SNAPSHOT = HERE / "engine_snapshot.json"
PROTOTYPE_SNAPSHOT = HERE / "snapshot.json"


def _numbers(node, prefix=""):
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _numbers(value, f"{prefix}.{key}")
    elif isinstance(node, list):
        for i, value in enumerate(node):
            yield from _numbers(value, f"{prefix}[{i}]")
    elif isinstance(node, (int, float)) and not isinstance(node, bool):
        yield prefix, float(node)


def describe(new: dict, old: dict) -> list[str]:
    """Per block: how many numbers kept their path and the largest relative change among them."""
    lines = []
    for block in ("period_days", "events", "mmm", "response_curve", "points", "optimized_mix"):
        a, b = dict(_numbers(new.get(block))), dict(_numbers(old.get(block)))
        shared = [k for k in a if b.get(k)]
        worst = max((abs(a[k] - b[k]) / abs(b[k]) for k in shared), default=0.0)
        lines.append(f"  {block}: {len(a)} numbers, {len(shared)} comparable, max relative change {worst:.3g}")
    old_ids = {e["event_id"] for e in old.get("events") or []}
    new_ids = {e["event_id"] for e in new.get("events") or []}
    lines.append(f"  events: {len(new_ids)} now, {len(old_ids)} in the prototype, {len(new_ids & old_ids)} shared ids")
    return lines


def main() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        synthetic = engine_snapshot(compute(make_dataset(Path(tmp)), EngineConfig.from_input(dataset_config())))
    synthetic["versions"] = {
        "numpy": np.__version__,
        "pandas": pandas.__version__,
        "scipy": scipy.__version__,
        "statsmodels": statsmodels.__version__,
        "sklearn": sklearn.__version__,
    }
    ENGINE_SNAPSHOT.write_text(json.dumps(synthetic, indent=1, sort_keys=True), encoding="utf-8")
    print(f"wrote {ENGINE_SNAPSHOT}")
    print("\n".join(describe(synthetic, json.loads(PROTOTYPE_SNAPSHOT.read_text(encoding="utf-8")))))

    if not all(p.exists() for p in gol_files().values()):
        print("no exemplo_csv/Gol: skipped the Gol golden")
        return
    with threadpool_limits(limits=1):
        gol = engine_snapshot(compute(gol_files(), EngineConfig.from_input(GOL_CONFIG)))
    GOL_ENGINE.parent.mkdir(parents=True, exist_ok=True)
    GOL_ENGINE.write_text(json.dumps(gol, indent=1, sort_keys=True), encoding="utf-8")
    print(f"wrote {GOL_ENGINE}")
    if GOL_SNAPSHOT.exists():
        print("\n".join(describe(gol, json.loads(GOL_SNAPSHOT.read_text(encoding="utf-8")))))


if __name__ == "__main__":
    main()
