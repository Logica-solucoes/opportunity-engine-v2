"""Parity on real client data (Gol): skipped unless exemplo_csv/ and the legacy numbers exist locally.

Both are confidential and git-ignored. Create the numbers with `mise run parity-real`.
"""

import json

import pytest
from threadpoolctl import threadpool_limits

from engine.config import EngineConfig
from engine.pipeline import compute
from tests.engine.real_data import GOL_CONFIG, GOL_SNAPSHOT, engine_snapshot, gol_files
from tests.engine.test_parity import assert_close

pytestmark = pytest.mark.skipif(
    not (GOL_SNAPSHOT.exists() and all(p.exists() for p in gol_files().values())),
    reason="needs exemplo_csv/Gol and tests/fixtures/parity/real/gol.json (mise run parity-real)",
)

BLOCKS = ("period_days", "events", "mmm", "response_curve", "points", "optimized_mix")


@pytest.fixture(scope="module")
def legacy():
    return json.loads(GOL_SNAPSHOT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def actual():
    # multi-threaded BLAS moves the curve and its points by up to ~7e-4 (relative) on this data; the legacy numbers
    # come from a single-threaded run (mise run parity-real), so compare like with like
    with threadpool_limits(limits=1):
        return engine_snapshot(compute(gol_files(), EngineConfig.from_input(GOL_CONFIG)))


@pytest.mark.parametrize("block", BLOCKS)
def test_gol_block_matches_the_prototype(block, actual, legacy):
    assert_close(actual[block], legacy[block], block)
