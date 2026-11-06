"""A5 on the client files in exemplo_csv/ (confidential): skipped without them."""

import pytest
from threadpoolctl import threadpool_limits

from engine.config import EngineConfig
from engine.pipeline import compute
from engine.results import build_results
from tests.engine.real_data import GOL_CONFIG, REPO_ROOT, gol_files

pytestmark = pytest.mark.skipif(not (REPO_ROOT / "exemplo_csv").exists(), reason="needs exemplo_csv/")


@pytest.fixture(scope="module")
def gol():
    with threadpool_limits(limits=1):
        computed = compute(gol_files(), EngineConfig.from_input(GOL_CONFIG))
    return computed, build_results(computed, "test").elasticity


def test_gol_publishes_the_total_but_no_channel_on_its_own(gol):
    """Measured on 05/nov/2026: 0 of 12 Gol channels pass the bootstrap rule (META is the only one with a real
    effect, but its 95% interval is wider than its coefficient). A10 calibrates this on the Core data; when it
    changes, update this test together with docs/decisoes/engine.md."""
    computed, elasticity = gol
    assert len(elasticity.channels) == 12
    assert not any(channel.identifiable for channel in elasticity.channels)
    assert elasticity.unidentified.channels == [c.name for c in elasticity.channels]
    assert elasticity.reasons == ["no_identifiable_channel"]
    assert elasticity.response_curve and elasticity.scenarios and elasticity.metrics is not None
    assert all(set(row.mix["historical"]) == {"nao_identificavel"} for row in elasticity.response_curve)
    assert all(c.hill is None and c.curve == [] and c.contribution_pct is None for c in elasticity.channels)
