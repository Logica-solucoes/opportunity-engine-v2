"""The refactored engine must reproduce, number for number, what the frozen prototype computed.

The snapshot comes from tests/fixtures/parity/generate_legacy_snapshot.py; see the README next to it.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pytest
import scipy
import sklearn
import statsmodels

from engine.config import EngineConfig
from engine.pipeline import compute
from tests.engine.synthetic_data import dataset_config, make_dataset
from tests.fixtures.parity.generate_legacy_snapshot import jsonable

SNAPSHOT = Path(__file__).resolve().parents[1] / "fixtures" / "parity" / "snapshot.json"
RTOL, ATOL = 1e-9, 1e-12

# The MMM optimum moves with the BLAS build: on Windows DISPLAY lands at 4.5% vs 7.0% in the Linux snapshot.
pytestmark = pytest.mark.skipif(sys.platform != "linux", reason="snapshot is Linux x86-64; see docs/decisoes/engine.md")


def assert_close(actual, expected, where="snapshot"):
    if isinstance(expected, dict):
        assert isinstance(actual, dict) and set(actual) == set(expected), f"{where}: keys differ"
        for key, value in expected.items():
            assert_close(actual[key], value, f"{where}.{key}")
    elif isinstance(expected, list):
        assert isinstance(actual, list) and len(actual) == len(expected), f"{where}: length differs"
        for i, (a, e) in enumerate(zip(actual, expected, strict=True)):
            assert_close(a, e, f"{where}[{i}]")
    elif isinstance(expected, (int, float)) and not isinstance(expected, bool):
        np.testing.assert_allclose(actual, expected, rtol=RTOL, atol=ATOL, equal_nan=True, err_msg=where)
    else:
        assert actual == expected, f"{where}: {actual!r} != {expected!r}"


@pytest.fixture(scope="module")
def snapshot():
    return json.loads(SNAPSHOT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def computed(tmp_path_factory):
    files = make_dataset(tmp_path_factory.mktemp("parity"))
    return compute(files, EngineConfig.from_input(dataset_config()))


def test_same_library_versions_as_the_snapshot(snapshot):
    here = {
        "numpy": np.__version__,
        "pandas": __import__("pandas").__version__,
        "scipy": scipy.__version__,
        "statsmodels": statsmodels.__version__,
        "sklearn": sklearn.__version__,
    }
    assert here == snapshot["versions"], "parity needs the versions the snapshot was generated with"


def test_cadence_matches(computed, snapshot):
    assert computed.prepared.period_days == snapshot["period_days"]


def test_events_and_gates_match(computed, snapshot):
    actual = [
        {
            "event_id": e.event_id,
            "product_group": e.product_group,
            "intervention_date": e.intervention_date,
            "results_data": jsonable(e.results_data) if e.results_data else None,
            "passed": e.passed,
            "reasons": e.reasons,
            "selected": e.selected,
        }
        for e in computed.events
    ]
    assert_close(actual, snapshot["events"], "events")


def test_mmm_matches(computed, snapshot):
    mmm, spend_cols = computed.mmm, computed.mmm["spend_cols"]
    actual = {
        "contribution_pct": jsonable(mmm["contribution_pct"]),
        "r_squared": float(mmm["r_squared"]),
        "cv_r_squared": float(mmm["cv_r_squared"]),
        "marketing_contribution_of_kpi_pct": float(mmm["marketing_contribution_of_kpi_pct"]),
        "optimal_params": {
            key: dict(zip(spend_cols, jsonable(mmm["optimal_params"][key]), strict=True))
            for key in ("alphas", "ks", "ss")
        },
    }
    assert_close(actual, snapshot["mmm"], "mmm")


A8_KEYS = {"KPI_Lo", "KPI_Hi", "Extrapolated"}  # added by A8; the prototype has no such columns


def without_a8(obj):
    if isinstance(obj, dict):
        return {key: without_a8(value) for key, value in obj.items() if key not in A8_KEYS}
    if isinstance(obj, list):
        return [without_a8(value) for value in obj]
    return obj


def test_response_curve_and_points_match(computed, snapshot):
    assert_close(without_a8(jsonable(computed.response_curve_df)), snapshot["response_curve"], "response_curve")
    points = {
        "baseline": computed.baseline_point,
        "max_efficiency": computed.max_efficiency_point,
        "strategic_limit": computed.strategic_limit_point,
        "diminishing_return": computed.diminishing_return_point,
        "saturation": computed.saturation_point,
        "strategic_reallocation": computed.strategic_reallocation_point,
    }
    assert_close(without_a8(jsonable(points)), snapshot["points"], "points")
    assert_close(jsonable(computed.optimized_mix), snapshot["optimized_mix"], "optimized_mix")
