"""A6 on the client files in exemplo_csv/ (confidential): skipped without them."""

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
    return computed, build_results(computed, "test")


def test_gol_sufficiency_and_placebo_as_measured(gol):
    """Measured on 06/nov/2026: of 52 events, 50 were analyzed and the placebo ran in 48; 11 events carry
    `placebo_failed` (a rate above the nominal level: the model's forecast error is understated), none is
    `model_dependent`, 11 pass every gate, and the run is sufficient (median out-of-sample WMAPE 0.197 <= 0.30).
    A10 calibrates the limits on the Core data; when this changes, update docs/decisoes/engine.md with it."""
    computed, results = gol
    data = [o.results_data for o in computed.events if o.results_data]
    assert len(computed.events) == 52 and len(data) == 50
    assert sum(d["placebo_ran"] for d in data) == 48
    assert sum("placebo_failed" in o.reasons for o in computed.events) == 11
    assert not any("model_dependent" in o.reasons for o in computed.events)
    assert sum(o.passed for o in computed.events) == 11
    assert results.sufficiency.passed is True and results.sufficiency.validated_events == 11
    assert results.sufficiency.pre_wmape == pytest.approx(0.197, abs=0.005)
    assert results.status == "succeeded"
