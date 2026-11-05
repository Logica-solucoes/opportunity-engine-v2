import json

import pytest
from threadpoolctl import threadpool_limits

from api import runs, simulations, storage, worker
from api.engine_config import ParamsIn
from tests.engine.synthetic_data import make_dataset

MAPPING = {
    "investment_file": {"date_col": "dates", "channel_col": "product_group", "investment_col": "total_revenue"},
    "performance_file": {"date_col": "date", "kpi_col": "Sessions"},
}


@pytest.fixture(autouse=True)
def real_engine(monkeypatch):
    monkeypatch.delenv("ENGINE_FAKE")
    monkeypatch.setenv("LLM_PROVIDER", "none")


@pytest.fixture
def analyst(make_user):
    return make_user("ana@x.com")


@pytest.fixture
def synthetic(db, make_workspace, analyst, make_simulation, tmp_path):
    ws = make_workspace("a", [(analyst, "analyst")])
    paths = make_dataset(tmp_path / "data", n_days=364, with_trends=False)
    files = {
        "investment": paths["investment_file"].read_bytes(),
        "performance": paths["performance_file"].read_bytes(),
    }
    simulation = make_simulation(ws, analyst, files=files)
    simulations.save_mapping(db, simulation, MAPPING)
    return simulation


def test_the_upload_gets_the_engine_report(synthetic):
    report = synthetic.validation

    assert report["ok"] is True
    assert (report["cadence"], report["period_days"]) == ("diária", 1)
    assert report["channels"] == ["DISPLAY", "PMAX", "SEARCH", "SOCIAL", "YOUTUBE"]


def test_a_run_stores_the_engine_results_json(db, synthetic, analyst):
    simulations.save_params(db, synthetic, ParamsIn().model_dump(mode="json"))
    warnings = {c["id"] for c in synthetic.validation["checks"] if c["level"] == "warning"}
    run = runs.create(db, synthetic, warnings, by=analyst)

    with threadpool_limits(limits=1):
        worker.execute(db, run.id)

    db.refresh(run)
    assert run.status in ("succeeded", "inconclusive"), run.error
    results = json.loads(storage.path(run.results_uri).read_text(encoding="utf-8"))
    assert results["schema_version"] == 1 and results["status"] == run.status
    assert results["validation"]["ok"] is True
    assert run.engine_version == results["engine_version"]
