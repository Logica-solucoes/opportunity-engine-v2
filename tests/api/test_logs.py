import io
import json
import logging
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path

import pytest

from api import logs, runs, simulations, worker
from api.engine_config import ParamsIn
from tests.samples import INVESTMENT, MAPPING, PERFORMANCE

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def lines(caplog):
    # the same handler logs.setup() installs, over a buffer instead of stdout
    caplog.set_level(logging.INFO)
    out = io.StringIO()
    handler = logging.StreamHandler(out)
    handler.setFormatter(logs.JsonFormatter())
    handler.addFilter(logs.ContextFilter())
    logging.getLogger().addHandler(handler)
    yield lambda: [json.loads(line) for line in out.getvalue().splitlines()]
    logging.getLogger().removeHandler(handler)


def entry(lines, event):
    return next(e for e in lines() if e["message"].startswith(event))


@pytest.fixture
def finished_run(db, make_user, make_workspace, make_simulation):
    ana = make_user("ana@x.com")
    ws = make_workspace("a", [(ana, "analyst")])
    simulation = make_simulation(ws, ana, files={"investment": INVESTMENT, "performance": PERFORMANCE})
    simulations.save_mapping(db, simulation, MAPPING)
    simulations.save_params(db, simulation, ParamsIn().model_dump(mode="json"))
    run = runs.create(db, simulation, set(), by=ana)
    return ana, ws, run


def test_json_formatter_writes_one_cloud_logging_line_with_the_traceback():
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        record = logging.LogRecord("api.worker", logging.ERROR, __file__, 1, "worker.failed", None, sys.exc_info())
    record.run_id, record.workspace_id = 7, 3

    entry = json.loads(logs.JsonFormatter().format(record))

    assert (entry["severity"], entry["logger"]) == ("ERROR", "api.worker")
    assert (entry["run_id"], entry["workspace_id"]) == (7, 3) and "user_id" not in entry
    assert entry["message"].startswith("worker.failed") and "RuntimeError: boom" in entry["message"]


def test_worker_logs_carry_the_run_the_workspace_and_the_author(lines, db, finished_run, monkeypatch):
    ana, ws, run = finished_run
    monkeypatch.setattr(worker, "SessionLocal", lambda: nullcontext(db))

    worker.main([str(run.id)])

    for event in ("worker.started", "worker.finished"):
        e = entry(lines, event)
        assert (e["run_id"], e["workspace_id"], e["user_id"]) == (run.id, ws.id, ana.id), event
    assert logs.context.get() is None


def test_setup_turns_the_root_and_uvicorn_loggers_into_json():
    # a subprocess: under pytest the root already has handlers, and setup() (rightly) leaves them alone
    code = (
        "import logging; from api import logs; logs.setup();"
        "logging.getLogger('uvicorn.access').info('GET / 200');"
        "logging.getLogger('api.x').warning('oi')"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, check=True).stdout

    got = [json.loads(line) for line in out.splitlines()]
    assert [(e["logger"], e["severity"], e["message"]) for e in got] == [
        ("uvicorn.access", "INFO", "GET / 200"),
        ("api.x", "WARNING", "oi"),
    ]


def test_request_logs_carry_the_user_and_the_workspace(lines, client, make_user, make_workspace, login_as):
    ana = make_user("ana@x.com")
    ws = make_workspace("a", [(ana, "analyst")])
    login_as(client, ana)

    client.post("/api/w/a/simulations", json={"name": "Black Friday"})

    e = entry(lines, "simulation.created")
    assert (e["user_id"], e["workspace_id"], e["logger"]) == (ana.id, ws.id, "api.simulations")
    assert "run_id" not in e


def test_run_routes_add_the_run(lines, db, client, finished_run, login_as):
    ana, ws, run = finished_run
    run.status = "succeeded"
    db.commit()
    login_as(client, ana)

    client.post(f"/api/w/a/runs/{run.id}/publish")

    e = entry(lines, "run.published")
    assert (e["user_id"], e["workspace_id"], e["run_id"]) == (ana.id, ws.id, run.id)


def test_ids_do_not_leak_into_the_next_request(lines, client, make_user, make_workspace, login_as):
    ana = make_user("ana@x.com")
    make_workspace("a", [(ana, "analyst")])
    login_as(client, ana)
    client.post("/api/w/a/simulations", json={"name": "Black Friday"})

    client.post("/api/auth/login", json={"email": "ana@x.com", "password": "senha-errada-123"})

    e = entry(lines, "auth.login_failed")
    assert not {"user_id", "workspace_id", "run_id"} & e.keys()
