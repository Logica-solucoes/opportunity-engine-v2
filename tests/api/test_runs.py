from datetime import timedelta

import pytest
from sqlalchemy import func

from api import engine_run, launcher, runs, simulations
from api.engine_config import ParamsIn
from api.models import Membership, Run
from tests.samples import INVESTMENT, MAPPING, PERFORMANCE

DUPLICATE = INVESTMENT + b"2024-01-01,SEARCH,30\n"
PARAMS = ParamsIn().model_dump(mode="json")


def test_fake_engine_logs_each_step_and_returns_a_result(tmp_path):
    lines = []

    result = engine_run.run({}, {}, tmp_path, lambda level, message: lines.append((level, message)))

    assert [m for _, m in lines] == engine_run.STEPS + ["Execução concluída"]
    assert {level for level, _ in lines} == {"info"}
    assert result["schema_version"] == 1 and result["engine_version"] == "fake" and result["status"] == "succeeded"


def test_fake_engine_fails_on_request(tmp_path, monkeypatch):
    monkeypatch.setenv("FAKE_ENGINE_FAIL", "1")

    with pytest.raises(RuntimeError, match="did not converge"):
        engine_run.run({}, {}, tmp_path, lambda level, message: None)


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
    def make(workspace=None, investment=INVESTMENT, params=True):
        simulation = make_simulation(
            workspace or ws, analyst, files={"investment": investment, "performance": PERFORMANCE}
        )
        simulations.save_mapping(db, simulation, MAPPING)
        if params:
            simulations.save_params(db, simulation, PARAMS)
        return simulation

    return make


def post_run(client, simulation, confirmed=(), slug="a"):
    return client.post(f"/api/w/{slug}/simulations/{simulation.id}/runs", json={"confirmed_warnings": list(confirmed)})


def test_create_run_snapshots_config_and_inputs_and_launches(logged, ready, launched, db, analyst):
    simulation = ready()

    r = post_run(logged, simulation)

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "queued" and body["simulation"] == {"id": simulation.id, "name": simulation.name}
    assert body["created_by_name"] == "ana" and body["error"] is None
    assert launched == [body["id"]]
    run = db.get(Run, body["id"])
    files = {f.kind: f for f in simulation.files}
    assert run.inputs == {
        "investment_file": {"sha256": files["investment"].sha256, "filename": "investment.csv"},
        "performance_file": {"sha256": files["performance"].sha256, "filename": "performance.csv"},
        "generic_trends_file": None,
    }
    assert run.config["column_mapping"] == MAPPING and run.workspace_id == simulation.workspace_id

    simulations.save_params(db, simulation, {**PARAMS, "investment_limit_factor": 3})
    db.refresh(run)
    assert run.config["investment_limit_factor"] == 1.5


def test_gate_refuses_a_simulation_without_validation(logged, ws, analyst, make_simulation):
    simulation = make_simulation(ws, analyst, files={"investment": INVESTMENT, "performance": PERFORMANCE})

    r = post_run(logged, simulation)

    assert (r.status_code, r.json()["detail"]) == (409, "Valide os arquivos antes de rodar.")


def test_gate_refuses_validation_errors(logged, ready):
    r = post_run(logged, ready(investment=DUPLICATE, params=False))

    assert (r.status_code, r.json()["detail"]) == (409, "Corrija os erros antes de rodar.")


def test_gate_refuses_unsaved_params(logged, ready):
    r = post_run(logged, ready(params=False))

    assert (r.status_code, r.json()["detail"]) == (409, "Salve os parâmetros antes de rodar.")


def test_gate_requires_every_warning_confirmed(logged, ready, db):
    simulation = ready()
    warnings = [
        {"id": "short_history", "level": "warning", "message": "Histórico curto"},
        {"id": "gap_days", "level": "warning", "message": "Dias sem dado"},
    ]
    simulation.validation = {**simulation.validation, "checks": warnings}
    db.commit()

    partial = post_run(logged, simulation, ["short_history"])
    full = post_run(logged, simulation, ["short_history", "gap_days"])

    assert (partial.status_code, partial.json()["detail"]) == (409, "Confirme os avisos antes de rodar.")
    assert full.status_code == 201
    assert db.get(Run, full.json()["id"]).confirmed_warnings == ["gap_days", "short_history"]


def test_one_active_run_per_simulation(logged, ready, db):
    simulation = ready()
    first = post_run(logged, simulation).json()

    second = post_run(logged, simulation)
    db.get(Run, first["id"]).status = "succeeded"
    db.commit()
    third = post_run(logged, simulation)

    assert (second.status_code, second.json()["detail"]) == (409, "Já há uma execução em andamento nesta simulação.")
    assert third.status_code == 201


def test_launch_failure_fails_the_run(logged, ready, monkeypatch):
    def broken(run_id):
        raise OSError("no python")

    monkeypatch.setattr(launcher, "launch", broken)

    r = post_run(logged, ready())

    assert r.status_code == 201
    assert (r.json()["status"], r.json()["error"]) == ("failed", "Não foi possível iniciar a execução.")


def make_stale(db, run_id):
    db.get(Run, run_id).created_at = func.now() - timedelta(minutes=21)
    db.commit()


def test_a_run_active_for_over_20_minutes_is_failed_and_frees_the_simulation(logged, ready, db):
    simulation = ready()
    run_id = post_run(logged, simulation).json()["id"]
    make_stale(db, run_id)

    got = logged.get(f"/api/w/a/runs/{run_id}").json()

    assert (got["status"], got["error"]) == ("failed", "A execução parou de responder.")
    assert post_run(logged, simulation).status_code == 201


def test_simulation_runs_newest_first(logged, ready, db):
    simulation = ready()
    old = post_run(logged, simulation).json()["id"]
    db.get(Run, old).status = "failed"
    db.commit()
    new = post_run(logged, simulation).json()["id"]

    body = logged.get(f"/api/w/a/simulations/{simulation.id}/runs").json()

    assert [r["id"] for r in body] == [new, old]


def test_viewer_does_not_see_unpublished_runs(client, ready, make_user, ws, db, login_as, analyst):
    simulation = ready()
    run = runs.create(db, simulation, set(), by=analyst)
    viewer = make_user("vi@x.com")
    db.add(Membership(user_id=viewer.id, workspace_id=ws.id, role="viewer"))
    db.commit()
    login_as(client, viewer)

    assert client.get(f"/api/w/a/runs/{run.id}").status_code == 404
    assert client.get(f"/api/w/a/simulations/{simulation.id}/runs").json() == []

    run.published_at = func.now()
    db.commit()
    assert client.get(f"/api/w/a/runs/{run.id}").status_code == 200
