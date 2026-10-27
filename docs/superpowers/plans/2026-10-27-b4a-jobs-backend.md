# B4a · Jobs e log (backend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rodar uma simulação validada como job assíncrono: a API cria o run com snapshot, dispara o worker num subprocess, o worker roda o `engine.run` falso gravando cada linha de log, e a API serve o log por SSE com retomada.

**Architecture:** Regra de negócio em `api/runs.py` (gate, criação, run morto, visibilidade). Rotas finas em `api/routes/runs.py`, onde também mora o gerador SSE. `api/launcher.py` dispara `python -m api.worker <run_id>`, e `api/worker.py` executa e grava. `api/engine_run.py` é o fake do contrato §3 até o A0.

**Tech Stack:** Python 3.13, FastAPI 0.158 (`StreamingResponse`), SQLAlchemy 2, Alembic, Postgres 16, pytest.

Spec: `docs/superpowers/specs/2026-10-27-b4-jobs-e-log-design.md`. Antes de começar leia `CODE-STYLE.md`, `DATABASE.md` e `API-GUIDE.md`.

---

## Mapa de arquivos

| Arquivo | Papel |
|---|---|
| `api/migrations/versions/0004_runs.py` (novo) | tabelas `runs` e `run_logs` |
| `api/models.py` | `Run`, `RunLog`, `RUN_STATUSES` |
| `api/engine_run.py` (novo) | `run(inputs, config, out_dir, on_log)` falso |
| `api/launcher.py` (novo) | `launch(run_id)` por subprocess |
| `api/runs.py` (novo) | gate, `create`, `fail_stale`, `visible` |
| `api/worker.py` | `execute(db, run_id)`, `main`, log JSON |
| `api/simulations.py` | `input_key` passa a receber ids |
| `api/routes/__init__.py` | `RunId` |
| `api/routes/runs.py` (novo) | 4 rotas + gerador SSE |
| `api/main.py` | inclui o router |
| `tests/conftest.py` | fixtures `launched` (autouse) e `fast_engine` (autouse) |
| `tests/api/test_runs.py` (novo) | gate, worker, stream, isolamento |
| `tests/api/test_rbac.py` | 4 rotas na matriz |
| `mise.toml`, `.env.example` | task `worker <run_id>`, envs do fake |
| docs | `API-GUIDE.md`, `DATABASE.md`, `docs/decisoes/runs-e-jobs.md`, `docs/decisoes/README.md`, `docs/m2/README.md` |

Todas as tasks tocam `tests/conftest.py`/`api/models.py` em sequência: execute **em ordem**, sem paralelizar.

Comandos: `docker compose up -d` precisa estar no ar. Testes com `uv run pytest`.

---

### Task 1: Tabelas `runs` e `run_logs`

**Files:**
- Create: `api/migrations/versions/0004_runs.py`
- Modify: `api/models.py`
- Test: `tests/api/test_migrations.py` (existente, compara models × migrations)

- [ ] **Step 1: Escrever os models** (o teste existente `test_migrations_match_models` passa a falhar porque a migration ainda não existe)

Em `api/models.py`, ajuste os imports e acrescente no fim:

```python
from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Identity, Index, LargeBinary, Text, func, text
```

```python
RunStatus = Literal["queued", "running", "succeeded", "inconclusive", "failed"]
RUN_STATUSES = get_args(RunStatus)


class Run(Base):
    __tablename__ = "runs"
    # one active run per simulation: a double click must not become two paid jobs
    __table_args__ = (
        Index(
            "runs_one_active_per_simulation",
            "simulation_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    workspace_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True)
    simulation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("simulations.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(Enum(*RUN_STATUSES, name="run_status"))
    config: Mapped[dict] = mapped_column(JSONB)
    inputs: Mapped[dict] = mapped_column(JSONB)
    confirmed_warnings: Mapped[list] = mapped_column(JSONB)
    engine_version: Mapped[str | None] = mapped_column(Text)
    results_uri: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    error: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id"))
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    creator: Mapped[User] = relationship(foreign_keys=[created_by])
    simulation: Mapped[Simulation] = relationship()


class RunLog(Base):
    __tablename__ = "run_logs"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    run_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    level: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/api/test_migrations.py -v`
Expected: FAIL, com `compare_metadata` listando `add_table runs` e `add_table run_logs`.

- [ ] **Step 3: Escrever a migration**

`api/migrations/versions/0004_runs.py`:

```python
"""runs and their log lines

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-27
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

STATUSES = ("queued", "running", "succeeded", "inconclusive", "failed")


def upgrade() -> None:
    op.create_table(
        "runs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("workspace_id", sa.BigInteger(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "simulation_id", sa.BigInteger(), sa.ForeignKey("simulations.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("status", sa.Enum(*STATUSES, name="run_status"), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False),
        sa.Column("inputs", postgresql.JSONB(), nullable=False),
        sa.Column("confirmed_warnings", postgresql.JSONB(), nullable=False),
        sa.Column("engine_version", sa.Text(), nullable=True),
        sa.Column("results_uri", sa.Text(), nullable=True),
        sa.Column("summary", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_runs_workspace_id", "runs", ["workspace_id"])
    op.create_index("ix_runs_simulation_id", "runs", ["simulation_id"])
    op.create_index(
        "runs_one_active_per_simulation",
        "runs",
        ["simulation_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.create_table(
        "run_logs",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("run_id", sa.BigInteger(), sa.ForeignKey("runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
    )
    op.create_index("ix_run_logs_run_id", "run_logs", ["run_id"])


def downgrade() -> None:
    op.drop_index("ix_run_logs_run_id", table_name="run_logs")
    op.drop_table("run_logs")
    op.drop_index("runs_one_active_per_simulation", table_name="runs")
    op.drop_index("ix_runs_simulation_id", table_name="runs")
    op.drop_index("ix_runs_workspace_id", table_name="runs")
    op.drop_table("runs")
    sa.Enum(name="run_status").drop(op.get_bind())
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/api/test_migrations.py -v && uv run alembic -c api/alembic.ini upgrade head && uv run alembic -c api/alembic.ini downgrade 0003 && uv run alembic -c api/alembic.ini upgrade head`
Expected: PASS, e o downgrade/upgrade no banco de dev sem erro.

- [ ] **Step 5: Commit**

```bash
git add api/models.py api/migrations/versions/0004_runs.py
git commit -m "feat(api): add runs and run_logs tables"
```

---

### Task 2: `engine.run` falso e launcher

**Files:**
- Create: `api/engine_run.py`, `api/launcher.py`
- Modify: `tests/conftest.py`
- Test: `tests/api/test_runs.py` (novo)

- [ ] **Step 1: Fixtures autouse e teste do fake**

Em `tests/conftest.py`, acrescente `launcher` ao import de `api` (`from api import launcher, passwords, simulations, storage`) e, depois de `no_gemini_key`:

```python
@pytest.fixture(autouse=True)
def launched(monkeypatch):
    # no test ever spawns a real worker against the test db; the ones that run it call worker.execute
    ids = []
    monkeypatch.setattr(launcher, "launch", ids.append)
    return ids


@pytest.fixture(autouse=True)
def fast_engine(monkeypatch):
    monkeypatch.setenv("FAKE_ENGINE_STEP_SECONDS", "0")
    monkeypatch.delenv("FAKE_ENGINE_FAIL", raising=False)
```

Crie `tests/api/test_runs.py`:

```python
import pytest

from api import engine_run


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
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/api/test_runs.py -v`
Expected: FAIL na coleta (`ImportError: cannot import name 'launcher'` ou `'engine_run'`).

- [ ] **Step 3: Implementar**

`api/engine_run.py`:

```python
import os
import time
from collections.abc import Callable
from pathlib import Path

STEPS = [
    "Lendo os arquivos de investimento e performance",
    "Detectando eventos de investimento",
    "Estimando o impacto causal dos eventos",
    "Ajustando as curvas de saturação",
    "Calculando os cenários de orçamento",
    "Montando o resultado",
]


def run(
    inputs: dict[str, Path | None], config: dict, out_dir: Path, on_log: Callable[[str, str], None]
) -> dict:
    # ponytail: stand-in for engine.run (A0/A1, docs/m2/README.md contract §3) that only paces log lines;
    # when engine/ exists this module becomes `from engine import run`
    pause = float(os.environ.get("FAKE_ENGINE_STEP_SECONDS", "1"))
    for i, message in enumerate(STEPS):
        if i:
            time.sleep(pause)
        on_log("info", message)
        if i == 2 and os.environ.get("FAKE_ENGINE_FAIL") == "1":
            raise RuntimeError("fake engine failure: model did not converge")
    on_log("info", "Execução concluída")
    return {
        "schema_version": 1,
        "engine_version": "fake",
        "status": "succeeded",
        "validation": None,
        "sufficiency": None,
        "causal": None,
        "elasticity": None,
        "experiment_design": None,
        "reports": None,
    }
```

`api/launcher.py`:

```python
import subprocess
import sys


def launch(run_id: int) -> None:
    # ponytail: local subprocess only; the Cloud Run Jobs launcher (RUN_ID env override) comes in B11
    subprocess.Popen([sys.executable, "-m", "api.worker", str(run_id)])
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/api/test_runs.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add api/engine_run.py api/launcher.py tests/conftest.py tests/api/test_runs.py
git commit -m "feat(api): add a fake engine run and a subprocess launcher"
```

---

### Task 3: Criar e ler runs (gate, snapshot, run morto)

**Files:**
- Create: `api/runs.py`, `api/routes/runs.py`
- Modify: `api/routes/__init__.py`, `api/main.py`
- Test: `tests/api/test_runs.py`

- [ ] **Step 1: Escrever os testes**

Acrescente em `tests/api/test_runs.py` (os imports vão para o topo do arquivo):

```python
from datetime import timedelta

from sqlalchemy import func

from api import launcher, runs, simulations
from api.engine_config import ParamsIn
from api.models import Run
from tests.samples import INVESTMENT, MAPPING, PERFORMANCE

DUPLICATE = INVESTMENT + b"2024-01-01,SEARCH,30\n"
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
    return client.post(
        f"/api/w/{slug}/simulations/{simulation.id}/runs", json={"confirmed_warnings": list(confirmed)}
    )


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
```

O import de models no topo fica `from api.models import Membership, Run`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/api/test_runs.py -v`
Expected: FAIL (`ImportError: cannot import name 'runs'`).

- [ ] **Step 3: Implementar `api/runs.py`**

```python
import logging
from datetime import timedelta

from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from api import launcher, simulations
from api.auth import Ctx
from api.models import Run, Simulation, User

log = logging.getLogger(__name__)

# the Cloud Run Job times out at 15 min: a run still active after 20 is dead
STALE_AFTER = timedelta(minutes=20)
ACTIVE = ("queued", "running")
STALE_ERROR = "A execução parou de responder."
LAUNCH_ERROR = "Não foi possível iniciar a execução."


class Blocked(Exception):
    pass


def fail_stale(db: Session, *where) -> None:
    db.execute(
        update(Run)
        .where(Run.status.in_(ACTIVE), Run.created_at < func.now() - STALE_AFTER, *where)
        .values(status="failed", error=STALE_ERROR, finished_at=func.now())
    )
    db.commit()


def visible(ctx: Ctx) -> list:
    where = [Run.workspace_id == ctx.workspace.id]
    # viewers see only what an analyst published (B6)
    if ctx.role == "viewer":
        where.append(Run.published_at.is_not(None))
    return where


def block_reason(simulation: Simulation, confirmed: set[str]) -> str | None:
    # same sentences as runBlockReason in web/src/lib/simulations.ts
    report = simulation.validation
    if report is None:
        return "Valide os arquivos antes de rodar."
    if not report["ok"]:
        return "Corrija os erros antes de rodar."
    if any(c["level"] == "warning" and c["id"] not in confirmed for c in report["checks"]):
        return "Confirme os avisos antes de rodar."
    if "optimization_target" not in simulation.config:
        return "Salve os parâmetros antes de rodar."
    return None


def create(db: Session, simulation: Simulation, confirmed: set[str], by: User) -> Run:
    fail_stale(db, Run.simulation_id == simulation.id)
    simulations.lock(db, simulation)
    reason = block_reason(simulation, confirmed)
    if reason:
        raise Blocked(reason)

    files = {f.kind: f for f in simulation.files}
    run = Run(
        workspace_id=simulation.workspace_id,
        simulation_id=simulation.id,
        status="queued",
        config=simulation.config,
        inputs={
            key: {"sha256": files[kind].sha256, "filename": files[kind].filename} if kind in files else None
            for key, kind in simulations.MAPPING_FILES.items()
        },
        confirmed_warnings=sorted(confirmed),
        created_by=by.id,
    )
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise Blocked("Já há uma execução em andamento nesta simulação.")
    log.info("run.created run_id=%s simulation_id=%s workspace_id=%s by=%s", run.id, run.simulation_id, run.workspace_id, by.id)

    try:
        launcher.launch(run.id)
    except OSError:
        log.exception("run.launch_failed run_id=%s", run.id)
        run.status, run.error, run.finished_at = "failed", LAUNCH_ERROR, func.now()
        db.commit()
    return run
```

O `IntegrityError` só pode vir do índice parcial: as FKs já foram checadas pela trava da simulação.

- [ ] **Step 4: Implementar as rotas**

Em `api/routes/__init__.py`, depois de `SimulationId`:

```python
RunId = Annotated[int, Path(ge=1, le=2**63 - 1)]
```

`api/routes/runs.py`:

```python
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from api import runs
from api.auth import Ctx, require_role
from api.db import get_db
from api.models import Run
from api.routes import RunId, SimulationId
from api.routes.simulations import find_simulation

router = APIRouter(prefix="/api/w/{slug}")
analyst = require_role("analyst")
viewer = require_role("viewer")


class RunIn(BaseModel):
    confirmed_warnings: list[str] = Field(default=[], max_length=100)


class SimulationRef(BaseModel):
    id: int
    name: str


class RunOut(BaseModel):
    id: int
    status: str
    simulation: SimulationRef
    created_by_name: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    error: str | None
    summary: dict | None
    engine_version: str | None


def run_out(r: Run) -> RunOut:
    return RunOut(
        id=r.id,
        status=r.status,
        simulation=SimulationRef(id=r.simulation.id, name=r.simulation.name),
        created_by_name=r.creator.name,
        created_at=r.created_at,
        started_at=r.started_at,
        finished_at=r.finished_at,
        error=r.error,
        summary=r.summary,
        engine_version=r.engine_version,
    )


def find_run(db: Session, ctx: Ctx, run_id: int) -> Run:
    runs.fail_stale(db, Run.id == run_id, Run.workspace_id == ctx.workspace.id)
    run = db.scalar(select(Run).where(Run.id == run_id, *runs.visible(ctx)))
    if run is None:
        raise HTTPException(404)
    return run


@router.post("/simulations/{simulation_id}/runs", status_code=201, response_model=RunOut)
def create_run(simulation_id: SimulationId, body: RunIn, ctx: Ctx = Depends(analyst), db: Session = Depends(get_db)):
    simulation = find_simulation(db, ctx, simulation_id)
    try:
        run = runs.create(db, simulation, set(body.confirmed_warnings), by=ctx.user)
    except runs.Blocked as e:
        raise HTTPException(409, str(e))
    return run_out(run)


@router.get("/simulations/{simulation_id}/runs", response_model=list[RunOut])
def list_runs(simulation_id: SimulationId, ctx: Ctx = Depends(viewer), db: Session = Depends(get_db)):
    find_simulation(db, ctx, simulation_id)
    runs.fail_stale(db, Run.simulation_id == simulation_id)
    rows = db.scalars(
        select(Run)
        .options(joinedload(Run.creator), joinedload(Run.simulation))
        .where(Run.simulation_id == simulation_id, *runs.visible(ctx))
        .order_by(Run.id.desc())
        .limit(20)
    )
    return [run_out(r) for r in rows]


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: RunId, ctx: Ctx = Depends(viewer), db: Session = Depends(get_db)):
    return run_out(find_run(db, ctx, run_id))
```

Em `api/main.py`: `from api.routes import admin, engine, members, runs, simulations` e `app.include_router(runs.router)` depois do `simulations.router`.

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest tests/api/test_runs.py -v`
Expected: todos passam. O `test_matrix_covers_every_api_route` vai falhar até a Task 6; não rode o `test_rbac.py` agora.

- [ ] **Step 6: Commit**

```bash
git add api/runs.py api/routes/runs.py api/routes/__init__.py api/main.py tests/api/test_runs.py
git commit -m "feat(api): create runs behind the validation gate and read them per workspace"
```

---

### Task 4: Worker

**Files:**
- Modify: `api/worker.py`, `api/simulations.py`
- Test: `tests/api/test_runs.py`

- [ ] **Step 1: Escrever os testes**

Acrescente em `tests/api/test_runs.py` (imports no topo: `import json, logging, sys`, `from sqlalchemy import select, update`, `from api import engine_run, storage, worker`, `from api.models import RunLog`):

```python
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
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/api/test_runs.py -v -k "worker or engine_error or stale_is_not or json_formatter"`
Expected: FAIL (`AttributeError: module 'api.worker' has no attribute 'execute'`).

- [ ] **Step 3: `input_key` por ids**

Em `api/simulations.py`, troque `input_key` e os dois usos:

```python
def input_key(workspace_id: int, simulation_id: int, sha256: str) -> str:
    return f"ws/{workspace_id}/sim/{simulation_id}/inputs/{sha256}.csv"
```

- em `input_paths`: `storage.path(input_key(simulation.workspace_id, simulation.id, files[kind].sha256))`
- em `save_file`: `storage.put(input_key(simulation.workspace_id, simulation.id, sha256), local)`

- [ ] **Step 4: Implementar o worker**

`api/worker.py` inteiro:

```python
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

from sqlalchemy import func, update
from sqlalchemy.orm import Session

from api import engine_run, simulations, storage
from api.db import SessionLocal
from api.models import Run, RunLog

log = logging.getLogger("api.worker")

ENGINE_ERROR = "O motor falhou. Detalhes técnicos ficam no log do servidor (execução {id})."


class JsonFormatter(logging.Formatter):
    # Cloud Logging reads one JSON object per stdout line; the traceback rides inside `message`
    def format(self, record: logging.LogRecord) -> str:
        entry = {"severity": record.levelname, "message": super().format(record)}
        entry.update({k: getattr(record, k) for k in ("run_id", "workspace_id") if hasattr(record, k)})
        return json.dumps(entry, ensure_ascii=False)


def execute(db: Session, run_id: int) -> None:
    run = db.scalar(
        update(Run)
        .where(Run.id == run_id, Run.status == "queued")
        .values(status="running", started_at=func.now())
        .returning(Run)
    )
    if run is None:
        log.info("worker.skipped run_id=%s", run_id)
        return
    rid, wid, sid, config, files = run.id, run.workspace_id, run.simulation_id, run.config, run.inputs
    db.commit()
    ids = {"run_id": rid, "workspace_id": wid}
    log.info("worker.started run_id=%s", rid, extra=ids)

    def on_log(level: str, message: str) -> None:
        db.add(RunLog(run_id=rid, level=level, message=message))
        # ponytail: one insert per line keeps the "running for N s" honest; batch if the engine gets chatty
        db.commit()

    inputs = {
        key: storage.path(simulations.input_key(wid, sid, f["sha256"])) if f else None for key, f in files.items()
    }
    try:
        with tempfile.TemporaryDirectory() as tmp:
            results = engine_run.run(inputs, config, Path(tmp), on_log)
            out = Path(tmp) / "results.json"
            out.write_text(json.dumps(results, ensure_ascii=False), encoding="utf-8")
            key = f"ws/{wid}/sim/{sid}/runs/{rid}/results.json"
            storage.put(key, out)
        values = {
            "status": results["status"],
            "engine_version": results["engine_version"],
            "results_uri": key,
            "summary": {"status": results["status"]},
        }
    except Exception:  # noqa: BLE001 - any engine failure fails the run; the raw message may be English or carry data
        log.exception("worker.engine_failed run_id=%s", rid, extra=ids)
        db.rollback()
        message = ENGINE_ERROR.format(id=rid)
        db.add(RunLog(run_id=rid, level="error", message=message))
        values = {"status": "failed", "error": message}

    # a run the API already failed as stale stays failed
    applied = db.execute(
        update(Run).where(Run.id == rid, Run.status == "running").values(**values, finished_at=func.now())
    ).rowcount
    db.commit()
    log.info("worker.finished run_id=%s status=%s applied=%s", rid, values["status"], bool(applied), extra=ids)


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    # the Cloud Run Job (B11) passes RUN_ID as an env override; locally the launcher passes it as an argument
    run_id = int(args[0] if args else os.environ["RUN_ID"])
    with SessionLocal() as db:
        execute(db, run_id)


if __name__ == "__main__":
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    main()
```

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest tests/api/test_runs.py tests/api/test_simulations.py tests/api/test_params.py -v`
Expected: todos passam (a troca do `input_key` não quebra B2/B3).

- [ ] **Step 6: Rodar o worker de verdade uma vez**

Contra o banco de dev já migrado (Task 1), rode `uv run python -m api.worker 999999`.
Expected: uma linha JSON `{"severity": "INFO", "message": "worker.skipped run_id=999999"}` no stdout.

- [ ] **Step 7: Commit**

```bash
git add api/worker.py api/simulations.py tests/api/test_runs.py
git commit -m "feat(api): run the engine in the worker and log each line for the screen"
```

---

### Task 5: Stream SSE do log

**Files:**
- Modify: `api/routes/runs.py`
- Test: `tests/api/test_runs.py`

- [ ] **Step 1: Escrever os testes**

Em `tests/conftest.py`, acrescente `from contextlib import nullcontext` aos imports do topo, `from api.routes import runs as runs_routes` logo depois de `from api.main import create_app`, e a fixture perto de `make_simulation` (o test_rbac usa a mesma na Task 6):

```python
@pytest.fixture
def stream_db(db, monkeypatch):
    # the log stream opens short sessions of its own; in tests they must see the test transaction
    monkeypatch.setattr(runs_routes, "SessionLocal", lambda: nullcontext(db))
    monkeypatch.setattr(runs_routes, "POLL_SECONDS", 0)
```

Acrescente em `tests/api/test_runs.py`:

```python
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


def test_two_runs_in_two_workspaces_do_not_mix_logs_or_files(
    logged, stream_db, db, ready, analyst, make_workspace
):
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
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/api/test_runs.py -v -k "stream_ or two_runs"`
Expected: FAIL (`AttributeError: ... has no attribute 'SessionLocal'` na fixture `stream_db`).

- [ ] **Step 3: Implementar**

Em `api/routes/runs.py`, imports novos:

```python
import json
import time
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import StreamingResponse

from api.db import SessionLocal, get_db
from api.models import Run, RunLog
```

Constantes, depois do `viewer = …`:

```python
POLL_SECONDS = 0.5
BACKLOG = 300
BATCH = 500
```

Gerador e rota, no fim do arquivo:

```python
def log_events(run_id: int, after: int | None):
    while True:
        # a short session per poll: the stream lasts the whole run and must not pin a pooled connection
        with SessionLocal() as db:
            runs.fail_stale(db, Run.id == run_id)
            # status before lines: the worker writes every line before the final status
            status = db.scalar(select(Run.status).where(Run.id == run_id))
            query = select(RunLog).where(RunLog.run_id == run_id)
            if after is None:
                rows = db.scalars(query.order_by(RunLog.id.desc()).limit(BACKLOG)).all()[::-1]
            else:
                rows = db.scalars(query.where(RunLog.id > after).order_by(RunLog.id).limit(BATCH)).all()
            chunk = "".join(
                f"id: {r.id}\ndata: {json.dumps({'ts': r.ts.isoformat(), 'level': r.level, 'message': r.message}, ensure_ascii=False)}\n\n"
                for r in rows
            )
        if chunk:
            yield chunk
            after = rows[-1].id
            continue
        # a deleted run (status None) ends the stream too
        if status not in runs.ACTIVE:
            yield f"event: end\ndata: {json.dumps({'status': status})}\n\n"
            return
        after = after or 0
        time.sleep(POLL_SECONDS)


@router.get("/runs/{run_id}/logs/stream")
def stream_logs(
    run_id: RunId,
    ctx: Ctx = Depends(viewer),
    db: Session = Depends(get_db),
    last_event_id: Annotated[int | None, Header(ge=0)] = None,
):
    find_run(db, ctx, run_id)
    # hand the request's connection back to the pool: the stream polls with sessions of its own
    db.commit()
    return StreamingResponse(
        log_events(run_id, last_event_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
```

O `after = after or 0` cobre o primeiro poll vazio sem `Last-Event-ID`: depois dele só entram linhas novas.

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/api/test_runs.py -v`
Expected: todos passam.

- [ ] **Step 5: Commit**

```bash
git add api/routes/runs.py tests/api/test_runs.py tests/conftest.py
git commit -m "feat(api): stream run logs over sse with last-event-id resume"
```

---

### Task 6: Matriz de RBAC

**Files:**
- Modify: `tests/api/test_rbac.py`

- [ ] **Step 1: Acrescentar as rotas e o run no `env`**

Em `ROUTES`, depois de `…/params`:

```python
    ("POST", "/api/w/{slug}/simulations/{simulation_id}/runs"): ("analyst", 201, lambda e: {"confirmed_warnings": []}),
    ("GET", "/api/w/{slug}/simulations/{simulation_id}/runs"): ("viewer", 200, None),
    ("GET", "/api/w/{slug}/runs/{run_id}"): ("viewer", 200, None),
    ("GET", "/api/w/{slug}/runs/{run_id}/logs/stream"): ("viewer", 200, None),
```

Imports: `from sqlalchemy import func`, `from api import runs, simulations`, `from api.engine_config import ParamsIn`.

No fixture `env`, peça `stream_db` (o stream precisa enxergar a transação do teste) e monte um run publicado e terminado: o viewer só vê publicado, e o POST da matriz precisa da simulação sem run ativo.

```python
@pytest.fixture
def env(db, stream_db, make_user, make_workspace, make_simulation, password):
    users = {role: make_user(f"{role}@x.com") for role in ("viewer", "analyst", "admin")}
    users["platform"] = make_user("platform@x.com", platform=True)
    target = make_user("target@x.com")
    make_user("fora@x.com")
    ws = make_workspace("a", [(users[r], r) for r in ("viewer", "analyst", "admin")] + [(target, "viewer")])
    simulation = make_simulation(ws, users["analyst"], files={"investment": INVESTMENT, "performance": PERFORMANCE})
    simulations.save_mapping(db, simulation, MAPPING)
    simulations.save_params(db, simulation, ParamsIn().model_dump(mode="json"))
    run = runs.create(db, simulation, set(), by=users["analyst"])
    run.status, run.published_at = "succeeded", func.now()
    db.commit()
    return {"users": users, "target": target, "password": password, "simulation": simulation, "run": run}
```

No `test_role_matrix`, o `format` ganha `run_id=env["run"].id`.

- [ ] **Step 2: Rodar**

Run: `uv run pytest tests/api/test_rbac.py -v`
Expected: todos passam, inclusive `test_matrix_covers_every_api_route`.

- [ ] **Step 3: Suite inteira e lint**

Run: `uv run pytest && uv run ruff check . && uv run ruff format --check .`
Expected: tudo verde. Se o `ruff format --check` acusar arquivo, rode `uv run ruff format <arquivo>` e confira o diff.

- [ ] **Step 4: Commit**

```bash
git add tests/api/test_rbac.py
git commit -m "test(api): cover the run routes in the role matrix"
```

---

### Task 7: Tasks, env e docs

**Files:**
- Modify: `mise.toml`, `.env.example`, `API-GUIDE.md`, `DATABASE.md`, `docs/decisoes/README.md`, `docs/m2/README.md`
- Create: `docs/decisoes/runs-e-jobs.md`

- [ ] **Step 1: `mise.toml` e `.env.example`**

Task `worker`:

```toml
[tasks.worker]
description = "Run one queued run: mise run worker <run_id>"
run = "uv run python -m api.worker"
```

No fim do `.env.example`:

```
# engine.run falso até o A0: pausa entre as etapas do log (s) e falha forçada (1) para ver o caminho de erro
# FAKE_ENGINE_STEP_SECONDS=1
# FAKE_ENGINE_FAIL=
```

- [ ] **Step 2: `API-GUIDE.md`**

Na tabela de endpoints, depois de `…/params`:

```markdown
| POST | `/api/w/{slug}/simulations/{simulation_id}/runs` | Analyst+. `{confirmed_warnings: [check_id]}` → 201 `RunOut` (`queued`, ou `failed` se o worker não subiu); snapshot de `config` e do sha256 dos inputs. 409 com a frase pt-BR: sem validação, erro na validação, aviso não confirmado, parâmetros não salvos, ou já há run ativo na simulação |
| GET | `/api/w/{slug}/simulations/{simulation_id}/runs` | Viewer+ (viewer só vê publicados). Até 20 `RunOut`, mais recente primeiro |
| GET | `/api/w/{slug}/runs/{run_id}` | Viewer+ (viewer só vê publicado; senão 404). `RunOut`: `{id, status, simulation: {id, name}, created_by_name, created_at, started_at, finished_at, error, summary, engine_version}` |
| GET | `/api/w/{slug}/runs/{run_id}/logs/stream` | Viewer+, mesma visibilidade. SSE: `id: <log id>` + `data: {ts, level, message}`; sem `Last-Event-ID` manda as 300 últimas, com ele as de id maior; `event: end` + `data: {status}` quando o run termina |
```

Em **Status de erro**, acrescente "409 conflito com o estado do recurso (run bloqueado pelo gate ou já ativo)".

- [ ] **Step 3: `DATABASE.md`**

Na tabela, depois de `simulation_files`:

```markdown
| `runs` | `workspace_id` (index, desnormalizado para escopo direto), `simulation_id` (index), `status` enum `run_status` (queued\|running\|succeeded\|inconclusive\|failed), `config jsonb` e `inputs jsonb` (snapshot: o run nunca relê a simulação), `confirmed_warnings jsonb`, `engine_version`, `results_uri`, `summary jsonb`, `error` (pt-BR para a tela), `published_at/by` (B6), `created_by`, `created_at`, `started_at`, `finished_at`. Índice único parcial `runs_one_active_per_simulation` em `simulation_id` com status ativo | `0004` |
| `run_logs` | `id` identity (ordem e cursor do SSE), `run_id` (index), `ts`, `level`, `message` (pt-BR) | `0004` |
```

- [ ] **Step 4: `docs/decisoes/runs-e-jobs.md`**

```markdown
# Runs e jobs

Decisões do B4, 27/out/2026. Spec: `docs/superpowers/specs/2026-10-27-b4-jobs-e-log-design.md`.

## `engine.run` falso em `api/`

O A0 ainda não entregou o `engine/`. `api/engine_run.py` segue a assinatura do contrato §3 (`run(inputs, config, out_dir, on_log) -> dict`, `on_log(level, message)`), emite seis etapas em pt-BR com pausa de `FAKE_ENGINE_STEP_SECONDS` e falha com `FAKE_ENGINE_FAIL=1`. Quando o motor existir, o módulo vira `from engine import run`. Mesmo caminho do `validate` (B2) e do `EngineConfig` (B3).

## Só o launcher local

`api/launcher.py` dispara `python -m api.worker <run_id>` por subprocess e não espera. O launcher do Cloud Run Jobs (override de env `RUN_ID`, que o worker já lê) entra no B11: sem projeto GCP, uma implementação só com mock seria aparência. Os testes trocam o `launch` por uma lista (fixture `launched`, autouse) e rodam `worker.execute` no processo.

## Gate no servidor

O `POST …/runs` refaz a conta do `runBlockReason` da tela, com as mesmas frases: sem validação, erro, aviso não confirmado (por `check.id`, guardado no run), parâmetros não salvos (`optimization_target` no `config`). Quem passa o gate ganha snapshot de `config` e do sha256 dos inputs: editar a simulação depois não muda o run, e o storage por conteúdo garante que o arquivo ainda existe.

## Um run ativo por simulação

Índice único parcial em `runs(simulation_id)` com status `queued`/`running`. O `IntegrityError` vira 409. Duplo clique ou duas abas não viram dois jobs pagos; editar arquivos ou parâmetros durante o run continua livre.

## Run morto sem heartbeat

O trilha-b pedia heartbeat. O Job tem timeout de 15 min, então run ativo com `created_at` há mais de 20 min está morto por definição, sem coluna nova. A API marca esses runs como `failed` ("A execução parou de responder.") ao criar run, ao ler run e lista, e a cada volta do stream. O worker grava o resultado com `WHERE status = 'running'`: um run já dado como morto não ressuscita. Localmente nada mata um worker pendurado; ele só deixa de importar depois dos 20 min.

## Uma linha de log por insert

O trilha-b pedia lote de 0,5 s. O motor emite centenas de linhas por run, não milhares, e o lote atrasaria a última linha antes de uma etapa longa, que é a que a tela usa para o "em andamento há N s". O worker faz insert e commit por linha na própria sessão. Se o motor ficar verboso, agrupar (marcado com `ponytail:` no `on_log`).

## Erro do motor nunca chega cru à tela

Exceção do motor vira `failed` com "O motor falhou. Detalhes técnicos ficam no log do servidor (execução N)." em `runs.error` e numa linha `error` do log. O traceback e a mensagem crua vão só para o stdout JSON (`severity`, `message`, `run_id`, `workspace_id`), que o Cloud Logging lê. A mensagem crua pode estar em inglês ou carregar dado do cliente. Pergunta ao dev A no contrato §3: uma exceção do motor com mensagem pt-BR própria para a tela.

## SSE com sessões curtas

`GET …/logs/stream` é um gerador síncrono no `StreamingResponse`. A rota checa auth e escopo com a sessão da requisição e a devolve ao pool antes de abrir o stream; cada volta do laço (0,5 s) abre uma sessão curta, lê o status e depois as linhas novas (nessa ordem: o worker grava todas as linhas antes do status final). Sem `Last-Event-ID` vão as 300 últimas linhas; com ele, as de id maior, e o `EventSource` reconecta sozinho mandando o último id. Cada aba assistindo segura uma thread do threadpool durante o run.

## Viewer e publicação

As rotas de leitura aceitam viewer, mas ele só enxerga run com `published_at`, que só o B6 preenche. Até lá, run não publicado é 404 para o viewer, como recurso de outro workspace.
```

Em `docs/decisoes/README.md`, linha nova na tabela:

```markdown
| [runs-e-jobs.md](runs-e-jobs.md) | `engine.run` falso, launcher local, gate no servidor, um run ativo, run morto sem heartbeat, log por linha, erro do motor, SSE |
```

- [ ] **Step 5: Contrato §3 no `docs/m2/README.md`**

Depois do parágrafo que começa com "O formato exato de cada seção é fechado no spec do item dono", acrescente:

```markdown
`on_log` (proposto pelo B4, a confirmar no spec do A0): `on_log(level: str, message: str)`, com `level` em `info|warning|error` e `message` já em pt-BR, pronta para a tela; o worker grava cada chamada em `run_logs`. `inputs` tem as mesmas chaves do `validate`. Em aberto para o A0: o motor levanta uma exceção própria com mensagem pt-BR para a tela? Até lá, toda exceção vira uma mensagem genérica e o traceback fica só no Cloud Logging.
```

- [ ] **Step 6: Commit**

```bash
git add mise.toml .env.example API-GUIDE.md DATABASE.md docs/decisoes/runs-e-jobs.md docs/decisoes/README.md docs/m2/README.md
git commit -m "docs: record b4a runs routes, tables and decisions"
```

O `Status` do B4 no trilha-b e o "Estado atual" do `CLAUDE.md` ficam para o fim do B4b, quando o item fecha.
