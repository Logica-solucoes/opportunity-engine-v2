import pytest
from sqlalchemy import func

from api import runs, simulations, storage
from api.engine_config import ParamsIn
from api.models import Membership
from tests.samples import GOL_RESULTS, INVESTMENT, MAPPING, PERFORMANCE


@pytest.fixture
def analyst(make_user):
    return make_user("ana@x.com")


@pytest.fixture
def ws(make_workspace, analyst):
    return make_workspace("a", [(analyst, "analyst")])


@pytest.fixture
def logged(client, analyst, ws, login_as):
    login_as(client, analyst)
    return client


@pytest.fixture
def finished(db, ws, analyst, make_simulation):
    def make(workspace=None, status="succeeded", results=True):
        simulation = make_simulation(
            workspace or ws, analyst, files={"investment": INVESTMENT, "performance": PERFORMANCE}
        )
        simulations.save_mapping(db, simulation, MAPPING)
        simulations.save_params(db, simulation, ParamsIn().model_dump(mode="json"))
        run = runs.create(db, simulation, set(), by=analyst)
        run.status = status
        if results:
            run.results_uri = f"ws/{run.workspace_id}/sim/{run.simulation_id}/runs/{run.id}/results.json"
            storage.put(run.results_uri, GOL_RESULTS)
        db.commit()
        return run

    return make


def test_analyst_gets_the_stored_results(logged, finished):
    run = finished()

    r = logged.get(f"/api/w/a/runs/{run.id}/results")

    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/json")
    assert r.content == GOL_RESULTS.read_bytes()


def test_viewer_gets_results_only_once_published(client, finished, make_user, ws, db, login_as):
    run = finished()
    viewer = make_user("vi@x.com")
    db.add(Membership(user_id=viewer.id, workspace_id=ws.id, role="viewer"))
    db.commit()
    login_as(client, viewer)

    assert client.get(f"/api/w/a/runs/{run.id}/results").status_code == 404

    run.published_at = func.now()
    db.commit()
    assert client.get(f"/api/w/a/runs/{run.id}/results").status_code == 200


def test_run_of_another_workspace_looks_missing(logged, finished, make_workspace, make_user):
    other = make_workspace("b", [(make_user("bo@x.com"), "analyst")])
    run = finished(workspace=other)

    assert logged.get(f"/api/w/a/runs/{run.id}/results").status_code == 404


@pytest.mark.parametrize("status", ["queued", "running", "failed"])
def test_run_without_results_is_404_with_a_message(logged, finished, status):
    run = finished(status=status, results=False)

    r = logged.get(f"/api/w/a/runs/{run.id}/results")

    assert r.status_code == 404
    assert r.json()["detail"] == "Esta execução não tem resultado."


def test_results_file_gone_from_disk_is_404(logged, finished):
    run = finished()
    storage.path(run.results_uri).unlink()

    r = logged.get(f"/api/w/a/runs/{run.id}/results")

    assert r.status_code == 404
    assert r.json()["detail"] == "Esta execução não tem resultado."
