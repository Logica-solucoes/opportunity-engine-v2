from pathlib import Path

import pytest

from api import runs, simulations, storage
from api.engine_config import ParamsIn
from api.models import Membership
from tests.samples import INVESTMENT, MAPPING, PERFORMANCE

GOL = Path(__file__).resolve().parents[1] / "fixtures" / "results" / "gol_anonimizada.json"
PARAMS = ParamsIn().model_dump(mode="json")


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
def ready(db, ws, analyst, make_simulation):
    def make(workspace=None):
        simulation = make_simulation(
            workspace or ws, analyst, files={"investment": INVESTMENT, "performance": PERFORMANCE}
        )
        simulations.save_mapping(db, simulation, MAPPING)
        simulations.save_params(db, simulation, PARAMS)
        return simulation

    return make


def finished(db, simulation, analyst, with_results=True):
    run = runs.create(db, simulation, set(), by=analyst)
    run.status = "succeeded"
    if with_results:
        key = f"ws/{run.workspace_id}/sim/{run.simulation_id}/runs/{run.id}/results.json"
        storage.put(key, GOL)
        run.results_uri = key
    db.commit()
    return run


def url(run, slug="a", query=""):
    return f"/api/w/{slug}/runs/{run.id}/scenario{query}"


def test_analyst_reads_the_monthly_scenario(logged, db, ready, analyst):
    run = finished(db, ready(), analyst)

    r = logged.get(url(run))

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["unit"] == "month" and body["recommended"] is not None and len(body["curve"]) == 100


def test_filters_go_through_the_query(logged, db, ready, analyst):
    run = finished(db, ready(), analyst)

    r = logged.get(url(run, query="?target_cpa=0.000000001&min_budget=1"))

    assert r.status_code == 200 and r.json()["recommended"] is None


def test_viewer_sees_only_a_published_run(make_client, login_as, make_user, db, ws, ready, analyst):
    run = finished(db, ready(), analyst)
    viewer = make_user("vi@x.com")
    db.add(Membership(user_id=viewer.id, workspace_id=ws.id, role="viewer"))
    db.commit()
    client = make_client()
    login_as(client, viewer)

    assert client.get(url(run)).status_code == 404
    runs.publish(db, run, by=analyst)
    assert client.get(url(run)).status_code == 200


def test_a_run_of_another_workspace_is_not_found(logged, db, ready, analyst, make_workspace):
    other = make_workspace("b", [(analyst, "analyst")])
    run = finished(db, ready(workspace=other), analyst)

    assert logged.get(url(run, slug="a")).status_code == 404


def test_a_run_without_results_is_a_conflict(logged, db, ready, analyst):
    run = finished(db, ready(), analyst, with_results=False)

    r = logged.get(url(run))

    assert r.status_code == 409 and "cenários" in r.json()["detail"]


@pytest.mark.parametrize("query", ["?min_budget=-1", "?min_budget=10&max_budget=5", "?foo=1"])
def test_bad_filters_are_rejected(logged, db, ready, analyst, query):
    run = finished(db, ready(), analyst)

    assert logged.get(url(run, query=query)).status_code == 422
