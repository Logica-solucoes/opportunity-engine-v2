import logging

import pytest
from sqlalchemy import func, select

from api import runs, simulations, storage
from api.engine_config import ParamsIn
from api.models import Run, RunLog, Simulation, SimulationFile
from tests.samples import INVESTMENT, MAPPING, PERFORMANCE


@pytest.fixture
def analyst(make_user):
    return make_user("ana@x.com")


@pytest.fixture
def boss(make_user):
    return make_user("chefe@x.com")


@pytest.fixture
def ws(make_workspace, analyst, boss):
    return make_workspace("a", [(analyst, "analyst"), (boss, "admin")])


@pytest.fixture
def admin_client(client, boss, ws, login_as):
    login_as(client, boss)
    return client


@pytest.fixture
def simulation(db, ws, analyst, make_simulation):
    simulation = make_simulation(ws, analyst, files={"investment": INVESTMENT, "performance": PERFORMANCE})
    simulations.save_mapping(db, simulation, MAPPING)
    simulations.save_params(db, simulation, ParamsIn().model_dump(mode="json"))
    return simulation


def run_on(db, simulation, analyst, status):
    run = runs.create(db, simulation, set(), by=analyst)
    run.status = status
    db.add(RunLog(run_id=run.id, level="info", message="linha"))
    db.commit()
    return run


def count(db, model, *where):
    return db.scalar(select(func.count()).select_from(model).where(*where))


def test_admin_deletes_the_simulation_with_its_runs_logs_and_files(admin_client, db, simulation, analyst):
    run = run_on(db, simulation, analyst, "succeeded")
    results = storage.path(f"ws/{simulation.workspace_id}/sim/{simulation.id}/runs/{run.id}/results.json")
    results.parent.mkdir(parents=True)
    results.write_text("{}")
    folder = storage.path(f"ws/{simulation.workspace_id}/sim/{simulation.id}")
    sid, rid = simulation.id, run.id

    r = admin_client.delete(f"/api/w/a/simulations/{sid}")

    assert r.status_code == 204
    assert count(db, Simulation, Simulation.id == sid) == 0
    assert count(db, SimulationFile, SimulationFile.simulation_id == sid) == 0
    assert count(db, Run, Run.simulation_id == sid) == 0
    assert count(db, RunLog, RunLog.run_id == rid) == 0
    assert not folder.exists()


@pytest.mark.parametrize("status", ["queued", "running"])
def test_a_simulation_with_an_active_run_is_not_deleted(admin_client, db, simulation, analyst, status):
    run_on(db, simulation, analyst, status)

    r = admin_client.delete(f"/api/w/a/simulations/{simulation.id}")

    assert (r.status_code, r.json()["detail"]) == (409, "Há uma execução em andamento.")
    assert count(db, Simulation, Simulation.id == simulation.id) == 1
    assert storage.path(f"ws/{simulation.workspace_id}/sim/{simulation.id}").exists()


def test_a_stale_run_does_not_block_the_delete(admin_client, db, simulation, analyst):
    run = run_on(db, simulation, analyst, "running")
    run.created_at = func.now() - runs.STALE_AFTER - runs.STALE_AFTER
    db.commit()

    assert admin_client.delete(f"/api/w/a/simulations/{simulation.id}").status_code == 204


def test_simulation_of_another_workspace_is_404(admin_client, db, analyst, make_workspace, make_simulation):
    foreign = make_simulation(make_workspace("b", [(analyst, "analyst")]), analyst)

    assert admin_client.delete(f"/api/w/a/simulations/{foreign.id}").status_code == 404
    assert admin_client.delete(f"/api/w/b/simulations/{foreign.id}").status_code == 404
    assert count(db, Simulation, Simulation.id == foreign.id) == 1


def test_a_storage_failure_still_deletes_the_rows_and_logs_the_orphans(
    admin_client, db, simulation, monkeypatch, caplog
):
    def broken(prefix):
        raise OSError("disk")

    monkeypatch.setattr(storage, "delete_prefix", broken)
    caplog.set_level(logging.INFO)

    r = admin_client.delete(f"/api/w/a/simulations/{simulation.id}")

    assert r.status_code == 204
    assert count(db, Simulation, Simulation.id == simulation.id) == 0
    orphan = next(rec for rec in caplog.records if rec.getMessage().startswith("simulation.files_orphaned"))
    assert orphan.levelno == logging.ERROR
    assert f"prefix=ws/{simulation.workspace_id}/sim/{simulation.id}" in orphan.getMessage()


def test_delete_prefix_ignores_a_missing_folder():
    storage.delete_prefix("ws/999/sim/999")
