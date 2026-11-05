"""Parity on real client data (Gol): skipped unless exemplo_csv/ and the legacy numbers exist locally.

Both are confidential and git-ignored. Create the numbers with `mise run parity-real`.
"""

import json

import pytest
from threadpoolctl import threadpool_limits

from engine.config import EngineConfig
from engine.pipeline import compute
from tests.engine.real_data import GOL_A4_EVENTS, GOL_CONFIG, GOL_SNAPSHOT, engine_snapshot, gol_files
from tests.engine.test_parity import assert_close

pytestmark = pytest.mark.skipif(
    not (GOL_SNAPSHOT.exists() and all(p.exists() for p in gol_files().values())),
    reason="needs exemplo_csv/Gol and tests/fixtures/parity/real/gol.json (mise run parity-real)",
)

BLOCKS = ("period_days", "mmm", "response_curve", "points", "optimized_mix")  # events: see below


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


def test_gol_detected_events_match_the_prototype(actual, legacy):
    """Event detection is untouched by A4."""
    identity = ("event_id", "product_group", "intervention_date")
    assert [{k: e[k] for k in identity} for e in actual["events"]] == [
        {k: e[k] for k in identity} for e in legacy["events"]
    ]


@pytest.mark.skipif(not GOL_A4_EVENTS.exists(), reason="needs mise run parity-a4-golden")
def test_gol_causal_numbers_match_the_a4_golden(actual):
    """Since A4 the causal numbers are pinned to the engine's own golden (make_a4_golden.py --real)."""
    assert_close(actual["events"], json.loads(GOL_A4_EVENTS.read_text(encoding="utf-8")), "events")
