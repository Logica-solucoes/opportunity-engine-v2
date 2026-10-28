# B9a · Uso, logs e retenção — backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Logs da API e do worker em JSON com `user_id`/`workspace_id`/`run_id`; view `usage` com rotas de uso (JSON e CSV) para o platform admin; `DELETE` de simulação para o admin do workspace, apagando linhas e arquivos.

**Architecture:** `api/logs.py` (novo) tem o formatter JSON, um filtro que lê os IDs de um `ContextVar` com um `dict` por request, e o middleware que cria esse `dict`; a auth, o `find_run` e o worker preenchem o `dict` com `logs.tag(...)`. A view `usage` (migration `0005`) agrega `runs` por workspace × usuário × mês; `api/usage.py` (novo) lê a view e monta o CSV. `simulations.delete` apaga a linha (o banco cascateia o resto) e depois o prefixo no storage.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2, Alembic, pytest contra Postgres (`docker compose up -d`), `uv`.

Spec: `docs/superpowers/specs/2026-10-28-b9-uso-logs-retencao-design.md` (seção B9a). Leia antes `CODE-STYLE.md`, `API-GUIDE.md`, `DATABASE.md` e `SECURITY.md`.

---

## Arquivos

| Arquivo | Mudança |
|---|---|
| `api/logs.py` | **novo**: `context`, `scope`, `tag`, `ContextFilter`, `JsonFormatter`, `setup`, `request_context` |
| `api/main.py` | middleware `logs.request_context`; `logs.setup()` antes de `app = create_app()` |
| `api/auth.py` | `logs.tag` em `current_user` e `require_role` |
| `api/routes/runs.py` | `logs.tag(run_id=…)` em `find_run` |
| `api/worker.py` | sai o `JsonFormatter`; `logs.scope` no `main`, `logs.tag` no `execute`, sem `extra=ids`; `__main__` chama `logs.setup()` |
| `api/migrations/versions/0005_usage_view.py` | **novo**: `CREATE VIEW usage` |
| `api/usage.py` | **novo**: `rows`, `to_csv` |
| `api/routes/admin.py` | `GET /usage`, `GET /usage.csv` |
| `api/models.py` | `ACTIVE_RUN_STATUSES` |
| `api/runs.py` | `ACTIVE` passa a vir de `ACTIVE_RUN_STATUSES` |
| `api/storage.py` | `delete_prefix` |
| `api/simulations.py` | `Blocked`, `ACTIVE_RUN_ERROR`, `delete` |
| `api/routes/simulations.py` | `DELETE /{simulation_id}` |
| `tests/api/test_logs.py` | **novo** |
| `tests/api/test_usage.py` | **novo** |
| `tests/api/test_delete_simulation.py` | **novo** |
| `tests/api/test_runs.py` | o teste do formatter sai daqui; uma asserção do teste de erro do motor muda |
| `tests/api/test_rbac.py` | três linhas novas na matriz |
| docs | fechamento (Task 6) |

Antes de começar: `docker compose up -d` e `uv run pytest -q` verde.

---

### Task 1: `api/logs.py`, formatter compartilhado e o worker

**Files:**
- Create: `api/logs.py`
- Modify: `api/worker.py`
- Create: `tests/api/test_logs.py`
- Modify: `tests/api/test_runs.py` (remover `test_json_formatter_writes_one_cloud_logging_line_with_the_traceback`; ajustar `test_engine_error_shows_ptbr_and_keeps_the_traceback_out_of_the_db`)

- [ ] **Step 1: Write the failing tests**

Crie `tests/api/test_logs.py`:

```python
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
```

Em `tests/api/test_runs.py`:
- apague a função `test_json_formatter_writes_one_cloud_logging_line_with_the_traceback` inteira (ela passa a morar em `test_logs.py`);
- em `test_engine_error_shows_ptbr_and_keeps_the_traceback_out_of_the_db`, troque a última linha

```python
    assert "did not converge" in str(failure.exc_info[1]) and failure.run_id == run.id
```

por

```python
    assert "did not converge" in str(failure.exc_info[1])
```

(o `run_id` deixa de ser um atributo do record: ele vem do contexto e só aparece na linha JSON, coberto por `test_logs.py`);
- se `import sys` ficar sem uso no arquivo, remova-o (o `ruff check` acusa).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_logs.py -q`
Expected: FAIL com `ImportError: cannot import name 'logs' from 'api'`

- [ ] **Step 3: Write minimal implementation**

Crie `api/logs.py`:

```python
import json
import logging
import sys
from contextlib import contextmanager
from contextvars import ContextVar

from fastapi import Request

IDS = ("user_id", "workspace_id", "run_id")

# one dict per request (or worker run). FastAPI runs sync dependencies in a copy of the context,
# so a .set() there would never reach the route: they mutate this dict through tag() instead
context: ContextVar[dict | None] = ContextVar("log_context", default=None)


@contextmanager
def scope(**ids):
    token = context.set(ids)
    try:
        yield
    finally:
        context.reset(token)


def tag(**ids) -> None:
    current = context.get()
    if current is not None:
        current.update(ids)


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in (context.get() or {}).items():
            if not hasattr(record, key):
                setattr(record, key, value)
        return True


class JsonFormatter(logging.Formatter):
    # Cloud Logging reads one JSON object per stdout line; the traceback rides inside `message`
    def format(self, record: logging.LogRecord) -> str:
        entry = {"severity": record.levelname, "logger": record.name, "message": super().format(record)}
        entry.update({k: getattr(record, k) for k in IDS if hasattr(record, k)})
        return json.dumps(entry, ensure_ascii=False)


def setup() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(ContextFilter())
    # no force=: under pytest the root already holds the capture handlers, and basicConfig leaves them alone
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    # uvicorn's loggers bring their own text handlers and don't propagate; uvicorn.error goes through "uvicorn"
    for name in ("uvicorn", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = [handler]
        logger.propagate = False


async def request_context(request: Request, call_next):
    with scope():
        return await call_next(request)
```

Em `api/worker.py`:

1. Imports: troque `from api import engine_run, simulations, storage` por `from api import engine_run, logs, simulations, storage`.
2. Apague a classe `JsonFormatter` inteira (o `import json` fica: o worker ainda grava o `results.json`).
3. Em `execute`, troque

```python
    rid, wid, sid, config, files = run.id, run.workspace_id, run.simulation_id, run.config, run.inputs
    db.commit()
    ids = {"run_id": rid, "workspace_id": wid}
    log.info("worker.started run_id=%s", rid, extra=ids)
```

por (o `created_by` é lido antes do commit, que expira o objeto)

```python
    rid, wid, sid, uid = run.id, run.workspace_id, run.simulation_id, run.created_by
    config, files = run.config, run.inputs
    db.commit()
    logs.tag(workspace_id=wid, user_id=uid)
    log.info("worker.started run_id=%s", rid)
```

4. Remova `, extra=ids` das duas chamadas que restam (`log.exception("worker.engine_failed …")` e `log.info("worker.finished …")`).
5. Em `main`, troque

```python
    with SessionLocal() as db:
        execute(db, run_id)
```

por

```python
    with SessionLocal() as db, logs.scope(run_id=run_id):
        execute(db, run_id)
```

6. No bloco `if __name__ == "__main__":`, troque as três linhas

```python
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])
```

por

```python
    logs.setup()
```

Se `sys` continuar em uso (`sys.argv` no `main`), o import fica.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_logs.py tests/api/test_runs.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/logs.py api/worker.py tests/api/test_logs.py tests/api/test_runs.py
git commit -m "feat(api): shared json log formatter with ids from the context, used by the worker"
```

---

### Task 2: IDs da request nos logs da API

**Files:**
- Modify: `api/main.py`
- Modify: `api/auth.py` (`current_user`, `require_role`)
- Modify: `api/routes/runs.py` (`find_run`)
- Test: `tests/api/test_logs.py`

- [ ] **Step 1: Write the failing tests**

Acrescente ao fim de `tests/api/test_logs.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_logs.py -q`
Expected: FAIL com `KeyError: 'user_id'` nos dois primeiros

- [ ] **Step 3: Write minimal implementation**

`api/main.py`:

```python
from api import auth, db, logs, passwords
```

(substitui `from api import auth, db, passwords`). Em `create_app`, como primeira linha depois de `app = FastAPI(...)`:

```python
    app.middleware("http")(logs.request_context)
```

E no fim do arquivo troque `app = create_app()` por:

```python
# at import, so uvicorn (which configures its loggers before importing the app) ends up with JSON
logs.setup()
app = create_app()
```

`api/auth.py`: acrescente `from api import logs` aos imports (`api.passwords` e `api.db` já vêm de `api`; mantenha a ordem do ruff). Troque `current_user` por:

```python
def current_user(session: UserSession = Depends(current_session)) -> User:
    logs.tag(user_id=session.user_id)
    return session.user
```

Em `require_role`, logo depois do `if workspace is None: raise HTTPException(404)`:

```python
        logs.tag(workspace_id=workspace.id)
```

`api/routes/runs.py`, em `find_run`, antes do `return run`:

```python
    logs.tag(run_id=run.id)
```

com `from api import logs, runs, simulations, storage` no lugar de `from api import runs, simulations, storage`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_logs.py tests/api/test_logging.py -q`
Expected: PASS (o `test_logging.py` existente continua verde: nenhum segredo entra no log)

- [ ] **Step 5: Commit**

```bash
git add api/main.py api/auth.py api/routes/runs.py tests/api/test_logs.py
git commit -m "feat(api): tag api logs with the user, workspace and run of the request"
```

---

### Task 3: view `usage`

**Files:**
- Create: `api/migrations/versions/0005_usage_view.py`
- Create: `api/usage.py`
- Create: `tests/api/test_usage.py`

- [ ] **Step 1: Write the failing tests**

Crie `tests/api/test_usage.py`:

```python
from datetime import UTC, datetime, timedelta

import pytest

from api import usage
from api.models import Run

OCT = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)


@pytest.fixture
def ana(make_user):
    return make_user("ana@x.com")


@pytest.fixture
def ws(make_workspace, ana):
    return make_workspace("a", [(ana, "analyst")])


@pytest.fixture
def add_run(db, make_simulation):
    # one simulation per run: the schema allows a single active run per simulation
    def add(ws, user, status, created_at=OCT, seconds=None):
        simulation = make_simulation(ws, user)
        started = created_at + timedelta(seconds=5) if seconds is not None else None
        db.add(
            Run(
                workspace_id=ws.id,
                simulation_id=simulation.id,
                created_by=user.id,
                status=status,
                config={},
                inputs={},
                confirmed_warnings=[],
                created_at=created_at,
                started_at=started,
                finished_at=started + timedelta(seconds=seconds) if started else None,
            )
        )
        db.commit()

    return add


def test_usage_counts_runs_by_status_and_sums_the_run_time(db, ws, ana, add_run):
    add_run(ws, ana, "succeeded", seconds=90)
    add_run(ws, ana, "succeeded", seconds=30)
    add_run(ws, ana, "inconclusive", seconds=60)
    add_run(ws, ana, "failed")
    add_run(ws, ana, "queued")
    add_run(ws, ana, "running")

    [row] = usage.rows(db, None)

    assert row == {
        "month": "2026-10",
        "workspace_id": ws.id,
        "workspace_name": "A",
        "user_id": ana.id,
        "user_name": "ana",
        "user_email": "ana@x.com",
        "succeeded": 2,
        "inconclusive": 1,
        "failed": 1,
        "active": 2,
        "total": 6,
        "run_seconds": 180,
    }


def test_the_month_is_the_business_month_in_sao_paulo(db, ws, ana, add_run):
    # 01:00 UTC on Oct 1 is still Sep 30 in São Paulo
    add_run(ws, ana, "succeeded", created_at=datetime(2026, 10, 1, 1, 0, tzinfo=UTC))
    add_run(ws, ana, "succeeded", created_at=datetime(2026, 10, 1, 4, 0, tzinfo=UTC))

    assert [(r["month"], r["total"]) for r in usage.rows(db, None)] == [("2026-10", 1), ("2026-09", 1)]
    assert [r["total"] for r in usage.rows(db, "2026-09")] == [1]


def test_usage_splits_by_workspace_and_user_and_orders_newest_month_first(
    db, ws, ana, add_run, make_user, make_workspace
):
    bia = make_user("bia@x.com")
    other = make_workspace("b", [(ana, "analyst")])
    add_run(ws, ana, "succeeded")
    add_run(ws, bia, "succeeded")
    add_run(other, ana, "succeeded")
    add_run(ws, ana, "succeeded", created_at=OCT + timedelta(days=31))

    got = [(r["month"], r["workspace_name"], r["user_name"]) for r in usage.rows(db, None)]

    assert got == [("2026-11", "A", "ana"), ("2026-10", "A", "ana"), ("2026-10", "A", "bia"), ("2026-10", "B", "ana")]


def test_csv_is_ready_for_a_ptbr_spreadsheet(db, ws, ana, add_run):
    add_run(ws, ana, "succeeded", seconds=90)

    text = usage.to_csv(usage.rows(db, None))

    assert text.startswith("﻿")
    header, line = text.lstrip("﻿").splitlines()
    assert header == (
        "Mês;Workspace;Usuário;E-mail;Concluídas;Inconclusivas;Falharam;Em andamento;Total;Minutos de execução"
    )
    assert line == "2026-10;A;ana;ana@x.com;1;0;0;0;1;1,5"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_usage.py -q`
Expected: FAIL com `ImportError: cannot import name 'usage' from 'api'`

- [ ] **Step 3: Write minimal implementation**

Crie `api/migrations/versions/0005_usage_view.py`:

```python
"""usage view: runs per workspace, user and month

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-28
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # the business month is São Paulo's: a run at 22:00 on the 31st belongs to that month, not the next
    op.execute(
        """
        CREATE VIEW usage AS
        SELECT
            workspace_id,
            created_by AS user_id,
            to_char(created_at AT TIME ZONE 'America/Sao_Paulo', 'YYYY-MM') AS month,
            count(*) FILTER (WHERE status = 'succeeded') AS succeeded,
            count(*) FILTER (WHERE status = 'inconclusive') AS inconclusive,
            count(*) FILTER (WHERE status = 'failed') AS failed,
            count(*) FILTER (WHERE status IN ('queued', 'running')) AS active,
            count(*) AS total,
            coalesce(sum(extract(epoch FROM finished_at - started_at)), 0)::bigint AS run_seconds
        FROM runs
        GROUP BY workspace_id, created_by, month
        """
    )


def downgrade() -> None:
    op.execute("DROP VIEW usage")
```

(`sum` ignora os runs sem `started_at` ou sem `finished_at`: a diferença é `NULL`.)

Crie `api/usage.py`:

```python
import csv
import io

from sqlalchemy import column, select, table
from sqlalchemy.orm import Session

from api.models import User, Workspace

COUNTS = ("succeeded", "inconclusive", "failed", "active", "total")

usage = table("usage", column("workspace_id"), column("user_id"), column("month"), *map(column, COUNTS), column("run_seconds"))

CSV_HEADER = [
    "Mês",
    "Workspace",
    "Usuário",
    "E-mail",
    "Concluídas",
    "Inconclusivas",
    "Falharam",
    "Em andamento",
    "Total",
    "Minutos de execução",
]


def rows(db: Session, month: str | None) -> list[dict]:
    query = (
        select(
            usage,
            Workspace.name.label("workspace_name"),
            User.name.label("user_name"),
            User.email.label("user_email"),
        )
        .join(Workspace, Workspace.id == usage.c.workspace_id)
        .join(User, User.id == usage.c.user_id)
        .order_by(usage.c.month.desc(), Workspace.name, User.name)
    )
    if month:
        query = query.where(usage.c.month == month)
    return [dict(r._mapping) for r in db.execute(query)]


def to_csv(rows: list[dict]) -> str:
    # ";" and a decimal comma, with a BOM: what Excel in pt-BR opens without the import wizard
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\n")
    writer.writerow(CSV_HEADER)
    for r in rows:
        minutes = f"{r['run_seconds'] / 60:.1f}".replace(".", ",")
        writer.writerow([r["month"], r["workspace_name"], r["user_name"], r["user_email"], *(r[c] for c in COUNTS), minutes])
    return "﻿" + out.getvalue()
```

(rode `uv run ruff format api/usage.py` depois: as duas linhas longas viram várias.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_usage.py tests/api/test_migrations.py -q`
Expected: PASS (a fixture `schema` roda o `alembic upgrade head`, que cria a view; o `compare_metadata` ignora views)

- [ ] **Step 5: Commit**

```bash
git add api/migrations/versions/0005_usage_view.py api/usage.py tests/api/test_usage.py
git commit -m "feat(api): usage view of runs per workspace, user and month"
```

---

### Task 4: rotas de uso do platform admin

**Files:**
- Modify: `api/routes/admin.py`
- Test: `tests/api/test_usage.py`, `tests/api/test_rbac.py`

- [ ] **Step 1: Write the failing tests**

Acrescente ao fim de `tests/api/test_usage.py`:

```python
@pytest.fixture
def root_client(client, make_user, login_as):
    login_as(client, make_user("root@x.com", platform=True))
    return client


def test_usage_route_filters_by_month(root_client, ws, ana, add_run):
    add_run(ws, ana, "succeeded")
    add_run(ws, ana, "succeeded", created_at=OCT + timedelta(days=31))

    every = root_client.get("/api/admin/usage")
    october = root_client.get("/api/admin/usage", params={"month": "2026-10"})

    assert [r["month"] for r in every.json()] == ["2026-11", "2026-10"]
    assert [(r["month"], r["user_email"], r["succeeded"]) for r in october.json()] == [("2026-10", "ana@x.com", 1)]


@pytest.mark.parametrize("month", ["2026-13", "2026-1", "out/2026", "2026-10-01"])
def test_usage_rejects_a_malformed_month(root_client, month):
    assert root_client.get("/api/admin/usage", params={"month": month}).status_code == 422
    assert root_client.get("/api/admin/usage.csv", params={"month": month}).status_code == 422


def test_usage_csv_is_an_attachment_named_after_the_month(root_client, ws, ana, add_run):
    add_run(ws, ana, "succeeded", seconds=90)

    month = root_client.get("/api/admin/usage.csv", params={"month": "2026-10"})
    every = root_client.get("/api/admin/usage.csv")

    assert month.headers["content-type"] == "text/csv; charset=utf-8"
    assert month.headers["content-disposition"] == 'attachment; filename="uso-2026-10.csv"'
    assert month.text.endswith("2026-10;A;ana;ana@x.com;1;0;0;0;1;1,5\n")
    assert every.headers["content-disposition"] == 'attachment; filename="uso.csv"'
```

Em `tests/api/test_rbac.py`, em `ROUTES`, depois da linha de `PATCH /api/admin/users/{user_id}`:

```python
    ("GET", "/api/admin/usage"): (PLATFORM, 200, None),
    ("GET", "/api/admin/usage.csv"): (PLATFORM, 200, None),
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_usage.py tests/api/test_rbac.py -q`
Expected: FAIL (404 nas rotas novas; a matriz acusa rota faltando)

- [ ] **Step 3: Write minimal implementation**

`api/routes/admin.py`, imports:

```python
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from api import accounts, usage
```

(substituem as linhas atuais de `fastapi` e de `from api import accounts`; mantenha os demais imports.)

Depois de `TempPasswordOut`:

```python
Month = Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")]


class UsageRow(BaseModel):
    month: str
    workspace_id: int
    workspace_name: str
    user_id: int
    user_name: str
    user_email: str
    succeeded: int
    inconclusive: int
    failed: int
    active: int
    total: int
    run_seconds: int
```

E no fim do arquivo:

```python
@router.get("/usage", response_model=list[UsageRow])
def list_usage(month: Month = None, _: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    return usage.rows(db, month)


@router.get("/usage.csv")
def export_usage(month: Month = None, _: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    name = f"uso-{month}.csv" if month else "uso.csv"
    return Response(
        usage.to_csv(usage.rows(db, month)),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
```

(`name` só tem dígitos e hífen: o `pattern` do `Month` garante, então o header não precisa de escape.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_usage.py tests/api/test_rbac.py -q`
Expected: PASS. Se o `content-type` vier sem o `; charset=utf-8` ou duplicado, ajuste o `media_type` para `"text/csv"` (o Starlette acrescenta o charset em `text/*`) e mantenha a asserção do teste.

- [ ] **Step 5: Commit**

```bash
git add api/routes/admin.py tests/api/test_usage.py tests/api/test_rbac.py
git commit -m "feat(api): usage list and csv export for the platform admin"
```

---

### Task 5: apagar simulação

**Files:**
- Modify: `api/models.py` (constante perto de `RUN_STATUSES`)
- Modify: `api/runs.py` (`ACTIVE`)
- Modify: `api/storage.py`
- Modify: `api/simulations.py`
- Modify: `api/routes/simulations.py`
- Create: `tests/api/test_delete_simulation.py`
- Modify: `tests/api/test_rbac.py`

- [ ] **Step 1: Write the failing tests**

Crie `tests/api/test_delete_simulation.py`:

```python
import logging

import pytest
from sqlalchemy import func, select

from api import runs, simulations, storage
from api.engine_config import ParamsIn
from api.models import Membership, Run, RunLog, Simulation, SimulationFile
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
```

Em `tests/api/test_rbac.py`, em `ROUTES`, depois da linha de `GET /api/w/{slug}/simulations/{simulation_id}`:

```python
    ("DELETE", "/api/w/{slug}/simulations/{simulation_id}"): ("admin", 204, None),
```

(o run do fixture `env` é `succeeded`, então o delete não bate no 409.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_delete_simulation.py tests/api/test_rbac.py -q`
Expected: FAIL (405 na rota; `AttributeError: module 'api.storage' has no attribute 'delete_prefix'`)

- [ ] **Step 3: Write minimal implementation**

`api/models.py`, logo depois de `RUN_STATUSES = get_args(RunStatus)`:

```python
ACTIVE_RUN_STATUSES = ("queued", "running")
```

`api/runs.py`: troque `from api.models import Run, Simulation, User` por `from api.models import ACTIVE_RUN_STATUSES, Run, Simulation, User` e `ACTIVE = ("queued", "running")` por `ACTIVE = ACTIVE_RUN_STATUSES`.

`api/storage.py`, no fim:

```python
def delete_prefix(prefix: str) -> None:
    target = path(prefix)
    if target.exists():
        shutil.rmtree(target)
```

e troque o comentário `ponytail:` do topo por:

```python
# ponytail: local dir only; GCS comes in B11, chosen by env here, with path() downloading to a temp file
# and delete_prefix() listing and deleting the blobs under the prefix
```

`api/simulations.py`:
- imports: `from sqlalchemy import delete as sql_delete, func, select` (no lugar de `from sqlalchemy import func`) e `from api.models import ACTIVE_RUN_STATUSES, Run, Simulation, SimulationFile, User, Workspace`;
- depois de `class InvalidInput(Exception)`:

```python
class Blocked(Exception):
    pass


ACTIVE_RUN_ERROR = "Há uma execução em andamento."
```

- no fim do arquivo:

```python
def delete(db: Session, simulation: Simulation, by: User) -> None:
    # FOR UPDATE: a run being created waits for this commit, then finds the simulation gone
    db.refresh(simulation, with_for_update=True)
    active = select(Run.id).where(Run.simulation_id == simulation.id, Run.status.in_(ACTIVE_RUN_STATUSES))
    if db.scalar(active.limit(1)) is not None:
        raise Blocked(ACTIVE_RUN_ERROR)
    sid, wid = simulation.id, simulation.workspace_id
    prefix = f"ws/{wid}/sim/{sid}"
    # files, runs and run logs go with it through ON DELETE CASCADE
    db.execute(sql_delete(Simulation).where(Simulation.id == sid))
    db.commit()
    log.info("simulation.deleted simulation_id=%s workspace_id=%s by=%s", sid, wid, by.id)
    # rows first: files gone with rows still standing would leave runs pointing at nothing
    try:
        storage.delete_prefix(prefix)
    except OSError:
        log.exception("simulation.files_orphaned prefix=%s", prefix)
```

Se o ruff reclamar do `delete as sql_delete` no meio do import, use duas linhas: `from sqlalchemy import func, select` e `from sqlalchemy import delete as sql_delete`.

`api/routes/simulations.py`:
- imports: `from api import runs, simulations` (no lugar de `from api import simulations`) e `from api.models import FILE_KINDS, FileKind, Run, Simulation, SimulationFile`;
- depois de `analyst = require_role("analyst")`: `workspace_admin = require_role("admin")`;
- a rota, logo depois de `get_simulation`:

```python
@router.delete("/{simulation_id}", status_code=204)
def delete_simulation(
    simulation_id: SimulationId, ctx: Ctx = Depends(workspace_admin), db: Session = Depends(get_db)
):
    simulation = find_simulation(db, ctx, simulation_id)
    runs.fail_stale(db, Run.simulation_id == simulation.id)
    try:
        simulations.delete(db, simulation, by=ctx.user)
    except simulations.Blocked as e:
        raise HTTPException(409, str(e))
```

Confira que não há import circular: `api.runs` importa `api.simulations`, e `api.routes.simulations` importa os dois, o que já acontece em `api/routes/runs.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: PASS (suíte inteira)

- [ ] **Step 5: Lint**

Run: `uv run ruff format --check . && uv run ruff check .`
Expected: sem erros (rode `uv run ruff format .` se o format acusar)

- [ ] **Step 6: Commit**

```bash
git add api/models.py api/runs.py api/storage.py api/simulations.py api/routes/simulations.py tests/api/test_delete_simulation.py tests/api/test_rbac.py
git commit -m "feat(api): workspace admins delete a simulation with its runs and files"
```

---

### Task 6: fechamento (docs)

**Files:**
- Modify: `API-GUIDE.md`, `DATABASE.md`, `docs/decisoes/infra-e-operacao.md`, `docs/decisoes/upload-e-storage.md`, `docs/m2/trilha-b-plataforma.md`, `CLAUDE.md`

Os arquivos usam CRLF: edite com a ferramenta `Edit` (ela preserva), não com `sed`.

- [ ] **Step 1: `API-GUIDE.md`**

Depois da linha de `GET /api/w/{slug}/simulations/{simulation_id}`:

```markdown
| DELETE | `/api/w/{slug}/simulations/{simulation_id}` | Admin do workspace. → 204; apaga a simulação, os arquivos, os runs e os logs (cascade) e depois a pasta `ws/{wid}/sim/{sid}/` no storage. 409 "Há uma execução em andamento." com run `queued`/`running` (depois do `fail_stale`) |
```

Depois da linha de `PATCH /api/admin/users/{user_id}`:

```markdown
| GET | `/api/admin/usage` | Platform admin. `?month=YYYY-MM` opcional (fora do formato → 422). `[{month, workspace_id, workspace_name, user_id, user_name, user_email, succeeded, inconclusive, failed, active, total, run_seconds}]`, mês mais recente primeiro; mês no fuso de São Paulo |
| GET | `/api/admin/usage.csv` | Platform admin. Mesmo filtro. CSV como anexo `uso-YYYY-MM.csv` (ou `uso.csv`), `;` e vírgula decimal, com BOM, minutos com uma casa |
```

- [ ] **Step 2: `DATABASE.md`**

Na tabela de `## Tabelas`, depois da linha de `run_logs`:

```markdown
| `usage` (view) | uma linha por `workspace_id` × `user_id` (`runs.created_by`) × `month` (`YYYY-MM` em `America/Sao_Paulo`); `succeeded`, `inconclusive`, `failed`, `active` (queued + running), `total`, `run_seconds` (soma de `finished_at − started_at`). Lida com `sqlalchemy.table()` em `api/usage.py`, sem model | `0005` |
```

- [ ] **Step 3: `docs/decisoes/infra-e-operacao.md`**

No fim do arquivo:

```markdown
## Logs em JSON com os IDs da request (B9)

Uma linha JSON por evento no stdout (`severity`, `logger`, `message` e, quando existem, `user_id`, `workspace_id`, `run_id`), na API e no worker, inclusive no dev: o Cloud Logging lê assim, e o dev vê o mesmo que a produção. `api/logs.py` concentra o formatter, o filtro e o `setup()`, que também troca os handlers do uvicorn (o access log incluso). O `setup()` roda no import de `api/main.py` porque o uvicorn configura os loggers dele antes de importar a app. O `cli.py` continua em texto: a saída dele é para quem está no terminal.

**Sintoma que guiou o desenho:** dependência síncrona do FastAPI roda numa cópia do contexto, então um `ContextVar.set()` feito no `require_role` não chega à rota. O middleware cria um `dict` por request no `ContextVar`, e `current_user`/`require_role`/`find_run` **mutam** esse objeto (`logs.tag`), que é o mesmo nas cópias. O worker abre o seu no `main` (`logs.scope(run_id=…)`) e completa com workspace e autor no `execute`. Nenhuma chamada `log.info` precisa passar `extra=`.

## Uso derivado de `runs` (B9)

A view `usage` agrega `runs` por workspace × usuário × mês, com status em colunas e o tempo de execução somado: sem tabela nova, sem job de consolidação, e um BI pode ler a view direto. O mês é o de São Paulo, não o de UTC (um run às 22h do dia 31 é daquele mês). O CSV sai com `;`, vírgula decimal e BOM, o que o Excel em pt-BR abre sem assistente. A cópia no BigQuery do trilha-b ficou para o B11, quando houver projeto GCP; é o 6º da ordem de corte.
```

- [ ] **Step 4: `docs/decisoes/upload-e-storage.md`**

Logo antes de `## Telas (B2b)`:

```markdown
## Apagar simulação (B9)

Só o admin do workspace (e o platform admin, que o `require_role` trata como admin) apaga. Com run `queued`/`running` é 409: o worker gravaria o resultado numa pasta e numa linha que já não existem. A linha da simulação é travada `FOR UPDATE` antes da checagem, para um run criado ao mesmo tempo esperar e achar a simulação apagada.

A ordem é banco, depois storage. Apagar a linha leva `simulation_files`, `runs` e `run_logs` pelo `ON DELETE CASCADE`; depois sai a pasta `ws/{wid}/sim/{sid}/` inteira (entradas e `results.json`). Se o storage falhar, a resposta continua 204 e o log registra `simulation.files_orphaned` com o prefixo, para limpeza manual. O contrário (arquivos apagados e linhas de pé) deixaria runs apontando para arquivos que não existem. Retenção automática espera o prazo de LGPD do Data Tech.
```

- [ ] **Step 5: `docs/m2/trilha-b-plataforma.md`**

Em `## B9 · Uso, logs e retenção — semana 3`, logo abaixo do título (antes de `- **BRD:**`):

```markdown
- **Status:** 🟡 em andamento. B9a (backend) em 28/out/2026, verificado por `tests/api/test_logs.py` (linhas JSON com `user_id`/`workspace_id`/`run_id` na API e no worker, sem vazar entre requests), `tests/api/test_usage.py` (view, mês de São Paulo, CSV) e `tests/api/test_delete_simulation.py` (cascade, pasta no storage, 409 com run ativo, falha de storage) e `tests/api/test_rbac.py`. Falta o B9b (telas). Fora: cópia no BigQuery (B11) e retenção automática (prazo de LGPD em aberto). Desvios em `docs/decisoes/infra-e-operacao.md` e `docs/decisoes/upload-e-storage.md`.
```

- [ ] **Step 6: `CLAUDE.md`**

Na seção Estrutura, depois da linha de `auth.py`:

```
  logs.py         logs JSON (Cloud Logging) com user_id/workspace_id/run_id do contexto da request
```

e depois da linha de `runs.py`:

```
  usage.py        uso por workspace × usuário × mês (view `usage`) e o CSV
```

No parágrafo "Estado atual", depois da frase do B6b, acrescente:

```markdown
**B9a (uso, logs e retenção backend) concluído em 28/out/2026**: logs JSON com `user_id`/`workspace_id`/`run_id` na API e no worker, view `usage` (migration `0005`) com `GET /api/admin/usage` e o CSV, `DELETE` de simulação para o admin do workspace.
```

e troque "Faltam: B7–B9 (B7 depende do B5, então o próximo livre é B8 ou B9)," por "Faltam: B9b, B7 (depende do B5), B8,".

- [ ] **Step 7: Commit**

```bash
git add API-GUIDE.md DATABASE.md docs/decisoes/infra-e-operacao.md docs/decisoes/upload-e-storage.md docs/m2/trilha-b-plataforma.md CLAUDE.md
git commit -m "docs: record the b9a usage, logs and delete backend"
```
