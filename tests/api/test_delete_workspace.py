import logging

import pytest
from sqlalchemy import func, select

from api import runs, simulations, storage
from api.engine_config import ParamsIn
from api.models import Membership, Run, RunLog, Simulation, User, Workspace
from tests.samples import INVESTMENT, MAPPING, PERFORMANCE


@pytest.fixture
def root(make_user):
    return make_user("root@x.com", platform=True)


@pytest.fixture
def analyst(make_user):
    return make_user("ana@x.com")


@pytest.fixture
def ws(make_workspace, analyst):
    return make_workspace("a", [(analyst, "admin")])


@pytest.fixture
def simulation(db, ws, analyst, make_simulation):
    simulation = make_simulation(ws, analyst, files={"investment": INVESTMENT, "performance": PERFORMANCE})
    simulations.save_mapping(db, simulation, MAPPING)
    simulations.save_params(db, simulation, ParamsIn().model_dump(mode="json"))
    return simulation


@pytest.fixture
def root_client(client, root, login_as):
    login_as(client, root)
    return client


def run_on(db, simulation, analyst, status):
    run = runs.create(db, simulation, set(), by=analyst)
    run.status = status
    db.add(RunLog(run_id=run.id, level="info", message="linha"))
    db.commit()
    return run


def count(db, model, *where):
    return db.scalar(select(func.count()).select_from(model).where(*where))


def delete(client, workspace, password):
    return client.request("DELETE", f"/api/admin/workspaces/{workspace.id}", json={"password": password})


def test_platform_admin_deletes_the_workspace_with_everything_in_it(
    root_client, db, ws, simulation, analyst, password, make_workspace
):
    run = run_on(db, simulation, analyst, "succeeded")
    results = storage.path(f"ws/{ws.id}/sim/{simulation.id}/runs/{run.id}/results.json")
    results.parent.mkdir(parents=True)
    results.write_text("{}")
    other = make_workspace("b", [(analyst, "analyst")])
    other_folder = storage.path(f"ws/{other.id}/sim/1")
    other_folder.mkdir(parents=True)
    wid, sid, rid = ws.id, simulation.id, run.id

    r = delete(root_client, ws, password)

    assert r.status_code == 204
    assert count(db, Workspace, Workspace.id == wid) == 0
    assert count(db, Membership, Membership.workspace_id == wid) == 0
    assert count(db, Simulation, Simulation.id == sid) == 0
    assert count(db, Run, Run.id == rid) == 0
    assert count(db, RunLog, RunLog.run_id == rid) == 0
    assert not storage.path(f"ws/{wid}").exists()
    assert other_folder.exists() and count(db, Workspace, Workspace.id == other.id) == 1
    assert count(db, User, User.id == analyst.id) == 1


def test_a_wrong_password_deletes_nothing(root_client, db, ws, simulation):
    r = delete(root_client, ws, "senha-errada")

    assert (r.status_code, r.json()["detail"]) == (400, "invalid_current_password")
    assert count(db, Workspace, Workspace.id == ws.id) == 1
    assert storage.path(f"ws/{ws.id}").exists()


def test_wrong_passwords_lock_the_account(root_client, ws):
    for _ in range(5):
        delete(root_client, ws, "senha-errada")

    r = delete(root_client, ws, "senha-errada")

    assert r.status_code == 429 and r.json()["detail"] == "locked"


@pytest.mark.parametrize("status", ["queued", "running"])
def test_a_workspace_with_an_active_run_is_not_deleted(root_client, db, ws, simulation, analyst, password, status):
    run_on(db, simulation, analyst, status)

    r = delete(root_client, ws, password)

    assert (r.status_code, r.json()["detail"]) == (409, "Há uma execução em andamento.")
    assert count(db, Workspace, Workspace.id == ws.id) == 1
    assert storage.path(f"ws/{ws.id}").exists()


def test_a_stale_run_does_not_block_the_delete(root_client, db, ws, simulation, analyst, password):
    run = run_on(db, simulation, analyst, "running")
    run.created_at = func.now() - runs.STALE_AFTER - runs.STALE_AFTER
    db.commit()

    assert delete(root_client, ws, password).status_code == 204


def test_a_workspace_admin_cannot_delete_it(client, ws, analyst, login_as, password):
    login_as(client, analyst)

    assert delete(client, ws, password).status_code == 403


def test_anonymous_cannot_delete_it(client, ws, password):
    assert delete(client, ws, password).status_code == 401


def test_unknown_workspace_is_404(root_client, ws, password):
    r = root_client.request("DELETE", "/api/admin/workspaces/999999", json={"password": password})

    assert r.status_code == 404


def test_a_missing_password_is_422(root_client, ws):
    assert root_client.delete(f"/api/admin/workspaces/{ws.id}").status_code == 422


def test_a_storage_failure_still_deletes_the_rows_and_logs_the_orphans(
    root_client, db, ws, simulation, password, monkeypatch, caplog
):
    def broken(prefix):
        raise OSError("disk")

    monkeypatch.setattr(storage, "delete_prefix", broken)
    caplog.set_level(logging.INFO)

    r = delete(root_client, ws, password)

    assert r.status_code == 204
    assert count(db, Workspace, Workspace.id == ws.id) == 0
    orphan = next(rec for rec in caplog.records if rec.getMessage().startswith("workspace.files_orphaned"))
    assert orphan.levelno == logging.ERROR and f"prefix=ws/{ws.id}" in orphan.getMessage()
