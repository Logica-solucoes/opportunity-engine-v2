import json
import logging
import sys
from datetime import timedelta

import pytest
from sqlalchemy import func, select, update

from api import engine_run, launcher, runs, simulations, storage, worker
from api.engine_config import ParamsIn
from api.models import Membership, Run, RunLog
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


def messages(db, run_id):
    return db.scalars(select(RunLog.message).where(RunLog.run_id == run_id).order_by(RunLog.id)).all()


def test_worker_runs_the_engine_and_stores_the_result(db, ready, analyst):
    run = runs.create(db, ready(), set(), by=analyst)

    worker.execute(db, run.id)

    db.refresh(run)
    assert (run.status, run.engine_version, run.summary) == ("succeeded", "fake", {"status": "succeeded"})
    assert run.started_at is not None and run.finished_at is not None
    assert run.results_uri == f"ws/{run.workspace_id}/sim/{run.simulation_id}/runs/{run.id}/results.json"
    assert json.loads(storage.path(run.results_uri).read_text(encoding="utf-8"))["status"] == "succeeded"
    assert messages(db, run.id) == engine_run.STEPS + ["Execução concluída"]


def test_engine_error_shows_ptbr_and_keeps_the_traceback_out_of_the_db(db, ready, analyst, monkeypatch, caplog):
    monkeypatch.setenv("FAKE_ENGINE_FAIL", "1")
    run = runs.create(db, ready(), set(), by=analyst)

    worker.execute(db, run.id)

    db.refresh(run)
    expected = f"O motor falhou. Detalhes técnicos ficam no log do servidor (execução {run.id})."
    assert (run.status, run.error) == ("failed", expected)
    assert messages(db, run.id)[-1] == expected
    assert all("converge" not in m for m in messages(db, run.id))
    failure = next(r for r in caplog.records if r.exc_info)
    assert "did not converge" in str(failure.exc_info[1]) and failure.run_id == run.id


def test_worker_ignores_a_run_that_is_not_queued(db, ready, analyst):
    run = runs.create(db, ready(), set(), by=analyst)
    run.status = "succeeded"
    db.commit()

    worker.execute(db, run.id)

    assert messages(db, run.id) == []


def test_a_run_failed_as_stale_is_not_revived(db, ready, analyst, monkeypatch):
    run = runs.create(db, ready(), set(), by=analyst)
    real_run = engine_run.run

    def killed_midway(inputs, config, out_dir, on_log):
        db.execute(update(Run).where(Run.id == run.id).values(status="failed", error=runs.STALE_ERROR))
        db.commit()
        return real_run(inputs, config, out_dir, on_log)

    monkeypatch.setattr(engine_run, "run", killed_midway)

    worker.execute(db, run.id)

    db.refresh(run)
    assert (run.status, run.error, run.results_uri) == ("failed", runs.STALE_ERROR, None)


def test_worker_reads_the_inputs_by_sha256(db, ready, analyst, monkeypatch):
    simulation = ready()
    run = runs.create(db, simulation, set(), by=analyst)
    seen = {}
    real_run = engine_run.run

    def spy(inputs, config, out_dir, on_log):
        seen.update(inputs)
        return real_run(inputs, config, out_dir, on_log)

    monkeypatch.setattr(engine_run, "run", spy)

    worker.execute(db, run.id)

    assert seen["investment_file"].read_bytes() == INVESTMENT
    assert seen["generic_trends_file"] is None


def test_json_formatter_writes_one_cloud_logging_line_with_the_traceback():
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        record = logging.LogRecord("api.worker", logging.ERROR, __file__, 1, "worker.failed", None, sys.exc_info())
    record.run_id, record.workspace_id = 7, 3

    entry = json.loads(worker.JsonFormatter().format(record))

    assert entry["severity"] == "ERROR" and (entry["run_id"], entry["workspace_id"]) == (7, 3)
    assert entry["message"].startswith("worker.failed") and "RuntimeError: boom" in entry["message"]


def events(text):
    return [dict(line.split(": ", 1) for line in block.splitlines()) for block in text.strip().split("\n\n")]


def stream(client, run_id, slug="a", last=None):
    headers = {"Last-Event-ID": str(last)} if last is not None else {}
    return client.get(f"/api/w/{slug}/runs/{run_id}/logs/stream", headers=headers)


def finished_run_with_lines(db, simulation, analyst, n):
    run = runs.create(db, simulation, set(), by=analyst)
    db.add_all(RunLog(run_id=run.id, level="info", message=f"linha {i}") for i in range(n))
    run.status = "succeeded"
    db.commit()
    return run, db.scalars(select(RunLog.id).where(RunLog.run_id == run.id).order_by(RunLog.id)).all()


def test_stream_sends_the_last_300_lines_then_end(logged, stream_db, db, ready, analyst):
    run, ids = finished_run_with_lines(db, ready(), analyst, 350)

    r = stream(logged, run.id)

    assert r.headers["content-type"].startswith("text/event-stream")
    got = events(r.text)
    assert [int(e["id"]) for e in got[:-1]] == ids[50:]
    assert json.loads(got[0]["data"])["message"] == "linha 50"
    assert got[-1] == {"event": "end", "data": json.dumps({"status": "succeeded"})}


def test_stream_resumes_after_last_event_id(logged, stream_db, db, ready, analyst):
    run, ids = finished_run_with_lines(db, ready(), analyst, 20)

    got = events(stream(logged, run.id, last=ids[14]).text)

    assert [int(e["id"]) for e in got[:-1]] == ids[15:]
    assert got[-1]["event"] == "end"


def test_two_runs_in_two_workspaces_do_not_mix_logs_or_files(logged, stream_db, db, ready, analyst, make_workspace):
    other = make_workspace("b", [(analyst, "analyst")])
    run_a = runs.create(db, ready(), set(), by=analyst)
    run_b = runs.create(db, ready(workspace=other), set(), by=analyst)
    worker.execute(db, run_a.id)
    worker.execute(db, run_b.id)

    for run, slug in ((run_a, "a"), (run_b, "b")):
        got = events(stream(logged, run.id, slug=slug).text)
        own = db.scalars(select(RunLog.id).where(RunLog.run_id == run.id).order_by(RunLog.id)).all()
        assert [int(e["id"]) for e in got[:-1]] == own
        db.refresh(run)
        assert run.results_uri.startswith(f"ws/{run.workspace_id}/sim/{run.simulation_id}/")
    assert run_a.workspace_id != run_b.workspace_id

    assert logged.get(f"/api/w/a/runs/{run_b.id}").status_code == 404
    assert stream(logged, run_b.id, slug="a").status_code == 404
