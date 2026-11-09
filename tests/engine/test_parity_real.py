"""Regression on real client data (Gol): skipped unless exemplo_csv/ and the engine golden exist locally.

Both are confidential and git-ignored. The golden is the engine's own output (mise run parity-golden); since the math
audit fixes (09/nov/2026) the Gol departs from the prototype (real/gol.json) on purpose, see
docs/audit/diferencas-prototipo.md.
"""

import json

import pytest
from threadpoolctl import threadpool_limits

from engine.config import EngineConfig
from engine.pipeline import compute
from tests.engine.real_data import GOL_CONFIG, GOL_ENGINE, engine_snapshot, gol_files
from tests.engine.test_parity import assert_close

pytestmark = pytest.mark.skipif(
    not (GOL_ENGINE.exists() and all(p.exists() for p in gol_files().values())),
    reason="needs exemplo_csv/Gol and tests/fixtures/parity/real/gol_engine.json (mise run parity-golden)",
)

BLOCKS = ("period_days", "events", "mmm", "response_curve", "points", "optimized_mix")


@pytest.fixture(scope="module")
def golden():
    return json.loads(GOL_ENGINE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def actual():
    # multi-threaded BLAS moves the curve and its points by up to ~7e-4 (relative) on this data; the golden comes
    # from a single-threaded run, so compare like with like
    with threadpool_limits(limits=1):
        return engine_snapshot(compute(gol_files(), EngineConfig.from_input(GOL_CONFIG)))


@pytest.mark.parametrize("block", BLOCKS)
def test_gol_block_matches_the_engine_golden(block, actual, golden):
    assert_close(actual[block], golden[block], block)
