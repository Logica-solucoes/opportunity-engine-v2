from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from api import runs, simulations, storage
from api.engine_config import ParamsIn
from api.models import Membership, RunLog, Simulation
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


def test_delete_moves_the_workspace_to_the_trash_and_keeps_everything(root_client, db, ws, simulation, root, password):
    r = delete(root_client, ws, password)

    assert r.status_code == 204
    db.refresh(ws)
    assert ws.deleted_at is not None and ws.deleted_by == root.id
    assert count(db, Simulation, Simulation.workspace_id == ws.id) == 1
    assert count(db, Membership, Membership.workspace_id == ws.id) == 1
    assert storage.path(f"ws/{ws.id}").exists()


def test_a_trashed_workspace_is_gone_for_its_members(make_client, db, ws, analyst, root, login_as, password):
    member = make_client()
    login_as(member, analyst)
    root_c = make_client()
    login_as(root_c, root)

    delete(root_c, ws, password)

    assert member.get("/api/w/a/simulations").status_code == 404
    assert member.get("/api/me").json()["workspaces"] == []
    assert root_c.get("/api/me").json()["workspaces"] == []


def test_a_trashed_workspace_cannot_be_deleted_again(root_client, ws, password):
    delete(root_client, ws, password)

    assert delete(root_client, ws, password).status_code == 404


def test_the_google_connector_of_a_trashed_workspace_is_404(root_client, ws, password):
    delete(root_client, ws, password)

    assert root_client.delete(f"/api/admin/workspaces/{ws.id}/google").status_code == 404


def test_a_wrong_password_trashes_nothing(root_client, db, ws):
    r = delete(root_client, ws, "senha-errada")

    assert (r.status_code, r.json()["detail"]) == (400, "invalid_current_password")
    db.refresh(ws)
    assert ws.deleted_at is None


def test_wrong_passwords_lock_the_account(root_client, ws):
    for _ in range(5):
        delete(root_client, ws, "senha-errada")

    r = delete(root_client, ws, "senha-errada")

    assert r.status_code == 429 and r.json()["detail"] == "locked"


@pytest.mark.parametrize("status", ["queued", "running"])
def test_a_workspace_with_an_active_run_is_not_trashed(root_client, db, ws, simulation, analyst, password, status):
    run_on(db, simulation, analyst, status)

    r = delete(root_client, ws, password)

    assert (r.status_code, r.json()["detail"]) == (409, "Há uma execução em andamento.")
    db.refresh(ws)
    assert ws.deleted_at is None


def test_a_stale_run_does_not_block_the_trash(root_client, db, ws, simulation, analyst, password):
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


def test_the_list_shows_the_trash_with_the_purge_date(root_client, ws, password):
    delete(root_client, ws, password)

    [item] = root_client.get("/api/admin/workspaces").json()

    deleted = datetime.fromisoformat(item["deleted_at"])
    assert datetime.fromisoformat(item["purge_at"]) - deleted == timedelta(days=7)


def test_an_active_workspace_has_no_trash_dates(root_client, ws):
    [item] = root_client.get("/api/admin/workspaces").json()

    assert item["deleted_at"] is None and item["purge_at"] is None


def test_restore_brings_back_access_and_data(make_client, db, ws, simulation, analyst, root, login_as, password):
    member = make_client()
    login_as(member, analyst)
    root_c = make_client()
    login_as(root_c, root)
    delete(root_c, ws, password)

    r = root_c.post(f"/api/admin/workspaces/{ws.id}/restore")

    assert r.status_code == 200 and r.json()["deleted_at"] is None
    assert member.get("/api/w/a/simulations").status_code == 200
    db.refresh(ws)
    assert ws.deleted_by is None


def test_restoring_an_active_workspace_is_404(root_client, ws):
    assert root_client.post(f"/api/admin/workspaces/{ws.id}/restore").status_code == 404


def test_the_slug_of_a_trashed_workspace_stays_reserved(root_client, make_workspace, password):
    trashed = make_workspace("lixo", [])
    delete(root_client, trashed, password)

    r = root_client.post("/api/admin/workspaces", json={"name": "Outra", "slug": "lixo"})

    assert r.status_code == 409
    assert r.json()["detail"] == (
        "Esse slug é de um workspace na lixeira. Restaure-o ou aguarde a exclusão definitiva."
    )
