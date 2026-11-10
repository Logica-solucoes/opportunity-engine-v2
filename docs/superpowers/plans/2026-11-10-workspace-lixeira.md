# Lixeira de workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Excluir workspace passa a movê-lo para uma lixeira restaurável; a CLI apaga de vez os vencidos (7 dias) e apaga um workspace na hora quando preciso.

**Architecture:** Duas colunas novas em `workspaces` (`deleted_at`, `deleted_by`). Toda consulta de workspace "ativo" filtra `deleted_at IS NULL` (`require_role`, `me_out`, rotas de admin). O hard delete atual (`accounts.delete_workspace`) vira `accounts.purge_workspace`, chamado só pela CLI (`purge-workspaces` no cron e `delete-workspace` sob demanda). A tela de admin separa ativos e lixeira e ganha "Restaurar".

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2, Alembic, pytest (uv); React 19 + TanStack Query, shadcn (bun).

**Spec:** `docs/superpowers/specs/2026-11-10-workspace-lixeira-design.md`. Regras do repo: `CODE-STYLE.md`, `DATABASE.md`, `API-GUIDE.md`, `SECURITY.md` (skill `project-conventions`).

**Base:** branch `worktree-cookie-secure-flag`, que já tem o hard delete com senha (commits `c9988a3`, `93408f9`). Este plano reescreve aquele comportamento.

**Comandos:**
- testes: `uv run pytest tests/api/<arquivo> -q` (Postgres do `docker compose up -d` precisa estar no ar)
- lint Python: `uv run ruff check api tests && uv run ruff format api tests`
- web: `cd web && bun run build && bun run lint`

**Paralelismo:** Task 1 primeiro. Depois Task 2, depois Task 3 (mesmos arquivos). Task 4 (CLI) depende só da Task 2. Task 5 (web) depende só do contrato da Task 3 e pode rodar junto com a Task 4. Task 6 (docs) por último.

---

## Mapa de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `api/migrations/versions/0007_workspace_trash.py` (novo) | colunas `deleted_at`, `deleted_by` |
| `api/models.py` | `Workspace.deleted_at`, `Workspace.deleted_by` |
| `api/accounts.py` | `TRASH_DAYS`, `SlugInTrash`, `active_workspaces`, `trash_workspace`, `restore_workspace`, `purge_workspace` (renomeado de `delete_workspace`), `purge_trash`, `create_workspace` com slug na lixeira |
| `api/auth.py` | `require_role` ignora workspace na lixeira |
| `api/routes/auth.py` | `me_out` ignora workspace na lixeira |
| `api/routes/admin.py` | DELETE vira lixeira, POST restore, `WorkspaceOut` com `deleted_at`/`purge_at`, `find_workspace(trashed=)`, 409 do slug na lixeira |
| `api/cli.py` | comandos `purge-workspaces` e `delete-workspace` |
| `tests/api/test_delete_workspace.py` | reescrito para lixeira e restauração |
| `tests/api/test_cli.py` | purga e delete-workspace |
| `tests/api/test_rbac.py` | linha da rota de restore |
| `web/src/components/GoogleConnectorDialog.tsx` | tipo `AdminWorkspace` com `deleted_at`/`purge_at` |
| `web/src/components/DeleteWorkspace.tsx` | texto e toast de lixeira |
| `web/src/components/TrashedWorkspaces.tsx` (novo) | seção Lixeira com Restaurar |
| `web/src/routes/_auth/admin/workspaces.tsx` | separa ativos e lixeira |
| `API-GUIDE.md`, `DATABASE.md`, `docs/decisoes/auth.md`, `docs/deploy.md` | docs no mesmo commit da Task 6 |

---

### Task 1: Colunas da lixeira

**Files:**
- Create: `api/migrations/versions/0007_workspace_trash.py`
- Modify: `api/models.py` (classe `Workspace`)
- Test: `tests/api/test_migrations.py` (já existe `test_migrations_match_models`)

- [ ] **Step 1: Adicionar as colunas no model (o teste de migration fica vermelho)**

Em `api/models.py`, na classe `Workspace`, depois de `created_at`:

```python
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"))
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/api/test_migrations.py::test_migrations_match_models -q`
Expected: FAIL, o `compare_metadata` lista `add_column` de `deleted_at` e `deleted_by`.

- [ ] **Step 3: Escrever a migration**

`api/migrations/versions/0007_workspace_trash.py`:

```python
"""workspace trash: deleted_at and deleted_by

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-10
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("workspaces", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "workspaces",
        sa.Column("deleted_by", sa.BigInteger(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("workspaces", "deleted_by")
    op.drop_column("workspaces", "deleted_at")
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/api/test_migrations.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/models.py api/migrations/versions/0007_workspace_trash.py
git commit -m "feat(api): colunas deleted_at e deleted_by em workspaces"
```

---

### Task 2: Excluir move para a lixeira e o workspace some

**Files:**
- Modify: `api/accounts.py`, `api/auth.py:208`, `api/routes/auth.py:41-50`, `api/routes/admin.py`
- Test: `tests/api/test_delete_workspace.py` (reescrever)

- [ ] **Step 1: Reescrever os testes**

Substituir o conteúdo de `tests/api/test_delete_workspace.py` por:

```python
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
```

Confira o nome do fixture que cria um segundo client em `tests/conftest.py` (`make_client`, linha ~112). Se ele tiver outra assinatura, ajuste `test_a_trashed_workspace_is_gone_for_its_members` para dois clients independentes com sessões separadas.

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/api/test_delete_workspace.py -q`
Expected: FAIL em `test_delete_moves_the_workspace_to_the_trash_and_keeps_everything` (o workspace é apagado de vez), `test_a_trashed_workspace_is_gone_for_its_members`, `test_a_trashed_workspace_cannot_be_deleted_again`, `test_the_google_connector_of_a_trashed_workspace_is_404`.

- [ ] **Step 3: `accounts`: lixeira, purga e consulta de ativos**

Em `api/accounts.py`:

1. Imports: trocar `from sqlalchemy import select` por `from sqlalchemy import func, select` e adicionar `from datetime import timedelta` no topo.
2. Depois das exceções, adicionar:

```python
TRASH_DAYS = 7


def active_workspaces():
    return select(Workspace).where(Workspace.deleted_at.is_(None))
```

3. Extrair a checagem de run ativo (usada pela lixeira e pela purga):

```python
def ensure_no_active_run(db: Session, workspace: Workspace) -> None:
    # FOR UPDATE: a run being created waits for this commit
    db.refresh(workspace, with_for_update=True)
    active = select(Run.id).where(Run.workspace_id == workspace.id, Run.status.in_(ACTIVE_RUN_STATUSES))
    if db.scalar(active.limit(1)) is not None:
        raise ActiveRun
```

4. Substituir a função `delete_workspace` inteira por:

```python
def trash_workspace(db: Session, workspace: Workspace, by: User) -> None:
    ensure_no_active_run(db, workspace)
    workspace.deleted_at = func.now()
    workspace.deleted_by = by.id
    db.commit()
    log.info("auth.workspace_trashed workspace_id=%s slug=%s by=%s", workspace.id, workspace.slug, by.id)


def purge_workspace(db: Session, workspace: Workspace, by: str) -> None:
    ensure_no_active_run(db, workspace)
    wid, slug = workspace.id, workspace.slug
    # memberships, simulations, files, runs and run logs go with it through ON DELETE CASCADE; users stay
    db.execute(sql_delete(Workspace).where(Workspace.id == wid))
    db.commit()
    log.info("auth.workspace_purged workspace_id=%s slug=%s by=%s", wid, slug, by)
    # rows first: files gone with rows still standing would leave runs pointing at nothing
    prefix = f"ws/{wid}"
    try:
        storage.delete_prefix(prefix)
    except OSError:
        log.exception("workspace.files_orphaned prefix=%s", prefix)
```

`by` em `purge_workspace` é texto (`"cli"`): só a CLI purga.

- [ ] **Step 4: `require_role` e `me_out` ignoram a lixeira**

Em `api/auth.py`, no `require_role` (linha ~208), trocar a busca por:

```python
        workspace = db.scalar(select(Workspace).where(Workspace.slug == slug, Workspace.deleted_at.is_(None)))
```

(`api/auth.py` não pode importar `api/accounts.py`: `accounts` já importa `auth`.)

Em `api/routes/auth.py`, `me_out`:

```python
def me_out(db: Session, user: User) -> MeOut:
    if user.is_platform_admin:
        rows = [(w, "admin") for w in db.scalars(accounts.active_workspaces().order_by(Workspace.name))]
    else:
        rows = db.execute(
            select(Workspace, Membership.role)
            .join(Membership, Membership.workspace_id == Workspace.id)
            .where(Membership.user_id == user.id, Workspace.deleted_at.is_(None))
            .order_by(Workspace.name)
        ).all()
```

(mantenha o resto da função como está; `accounts` já é importado em `api/routes/auth.py`, confira.)

- [ ] **Step 5: Rotas de admin**

Em `api/routes/admin.py`:

```python
def find_workspace(db: Session, workspace_id: int, trashed: bool = False) -> Workspace:
    workspace = db.get(Workspace, workspace_id)
    if workspace is None or (workspace.deleted_at is not None) != trashed:
        raise HTTPException(404)
    return workspace
```

e na rota `delete_workspace` trocar `accounts.delete_workspace(db, workspace, by=admin)` por `accounts.trash_workspace(db, workspace, by=admin)`.

- [ ] **Step 6: Rodar e ver passar**

Run: `uv run pytest tests/api/test_delete_workspace.py tests/api/test_admin.py tests/api/test_auth.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add api/accounts.py api/auth.py api/routes/auth.py api/routes/admin.py tests/api/test_delete_workspace.py
git commit -m "feat(api): excluir workspace move para a lixeira em vez de apagar"
```

---

### Task 3: Restaurar, lista com a lixeira e slug reservado

**Files:**
- Modify: `api/accounts.py`, `api/routes/admin.py`, `tests/api/test_rbac.py`
- Test: `tests/api/test_delete_workspace.py` (acrescentar)

- [ ] **Step 1: Acrescentar os testes**

No fim de `tests/api/test_delete_workspace.py`:

```python
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


def test_the_slug_of_a_trashed_workspace_stays_reserved(root_client, ws, password):
    delete(root_client, ws, password)

    r = root_client.post("/api/admin/workspaces", json={"name": "Outra", "slug": "a"})

    assert r.status_code == 409
    assert r.json()["detail"] == (
        "Esse slug é de um workspace na lixeira. Restaure-o ou aguarde a exclusão definitiva."
    )
```

e no topo do arquivo: `from datetime import datetime, timedelta`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/api/test_delete_workspace.py -q`
Expected: FAIL nos 5 testes novos (`KeyError: 'deleted_at'`, 405 no restore, 409 com a mensagem antiga).

- [ ] **Step 3: `accounts`: restaurar e slug na lixeira**

Em `api/accounts.py`, nova exceção junto das outras:

```python
class SlugInTrash(Exception):
    pass
```

`create_workspace` passa a ser:

```python
def create_workspace(db: Session, name: str, slug: str) -> Workspace:
    existing = db.scalar(select(Workspace).where(Workspace.slug == slug))
    if existing is not None:
        raise SlugInTrash if existing.deleted_at is not None else Conflict
    workspace = Workspace(name=name, slug=slug)
    db.add(workspace)
    commit_or_conflict(db)
    log.info("auth.workspace_created workspace_id=%s slug=%s", workspace.id, slug)
    return workspace
```

e, depois de `trash_workspace`:

```python
def restore_workspace(db: Session, workspace: Workspace, by: User) -> None:
    workspace.deleted_at = None
    workspace.deleted_by = None
    db.commit()
    log.info("auth.workspace_restored workspace_id=%s slug=%s by=%s", workspace.id, workspace.slug, by.id)
```

- [ ] **Step 4: Rotas**

Em `api/routes/admin.py`:

1. Import: `from datetime import datetime, timedelta`.
2. `WorkspaceOut` ganha dois campos e `workspace_out` os calcula:

```python
class WorkspaceOut(BaseModel):
    id: int
    name: str
    slug: str
    created_at: datetime
    google: google_import.GoogleConfig | None
    deleted_at: datetime | None
    purge_at: datetime | None


def workspace_out(w: Workspace) -> WorkspaceOut:
    purge_at = w.deleted_at + timedelta(days=accounts.TRASH_DAYS) if w.deleted_at else None
    return WorkspaceOut(
        id=w.id,
        name=w.name,
        slug=w.slug,
        created_at=w.created_at,
        google=google_import.config_of(w),
        deleted_at=w.deleted_at,
        purge_at=purge_at,
    )
```

3. Em `create_workspace`, antes do `except accounts.Conflict`:

```python
    except accounts.SlugInTrash:
        raise HTTPException(409, "Esse slug é de um workspace na lixeira. Restaure-o ou aguarde a exclusão definitiva.")
```

4. Rota nova, logo depois de `delete_workspace`:

```python
@router.post("/workspaces/{workspace_id}/restore", response_model=WorkspaceOut)
def restore_workspace(
    workspace_id: WorkspaceId, admin: User = Depends(require_platform_admin), db: Session = Depends(get_db)
):
    workspace = find_workspace(db, workspace_id, trashed=True)
    accounts.restore_workspace(db, workspace, by=admin)
    return workspace_out(workspace)
```

`GET /workspaces` continua listando todos (ativos e lixeira); a tela separa.

- [ ] **Step 5: Matriz do RBAC**

Em `tests/api/test_rbac.py`, no dicionário `ROUTES`, depois da linha do `DELETE /api/admin/workspaces/{workspace_id}`:

```python
    # the env's workspace is active, so the platform admin gets past the guard and finds nothing to restore
    ("POST", "/api/admin/workspaces/{workspace_id}/restore"): (PLATFORM, 404, None),
```

- [ ] **Step 6: Rodar e ver passar**

Run: `uv run pytest tests/api/test_delete_workspace.py tests/api/test_admin.py tests/api/test_rbac.py -q`
Expected: PASS (o `test_rbac.py` leva alguns minutos).

- [ ] **Step 7: Commit**

```bash
git add api/accounts.py api/routes/admin.py tests/api/test_delete_workspace.py tests/api/test_rbac.py
git commit -m "feat(api): restaurar workspace da lixeira e slug reservado até a purga"
```

---

### Task 4: CLI `purge-workspaces` e `delete-workspace`

**Files:**
- Modify: `api/accounts.py`, `api/cli.py`
- Test: `tests/api/test_cli.py` (acrescentar)

- [ ] **Step 1: Acrescentar os testes**

No fim de `tests/api/test_cli.py`:

```python
import logging
from datetime import timedelta

import pytest
from sqlalchemy import func

from api import storage
from api.models import Run, Simulation, Workspace


@pytest.fixture
def cli_db(db, monkeypatch):
    monkeypatch.setattr(cli, "SessionLocal", lambda: nullcontext(db))
    return db


def trashed(db, make_workspace, slug, age):
    workspace = make_workspace(slug)
    workspace.deleted_at = func.now() - age
    db.commit()
    storage.path(f"ws/{workspace.id}/sim/1").mkdir(parents=True)
    return workspace


def exists(db, workspace_id):
    return db.get(Workspace, workspace_id) is not None


def test_purge_deletes_only_what_is_in_the_trash_for_more_than_7_days(cli_db, make_workspace, capsys):
    old = trashed(cli_db, make_workspace, "velho", timedelta(days=7, seconds=1))
    recent = trashed(cli_db, make_workspace, "recente", timedelta(days=7) - timedelta(minutes=1))
    active = make_workspace("ativo")
    old_id = old.id

    cli.main(["purge-workspaces"])

    cli_db.expire_all()
    assert not exists(cli_db, old_id) and not storage.path(f"ws/{old_id}").exists()
    assert exists(cli_db, recent.id) and storage.path(f"ws/{recent.id}").exists()
    assert exists(cli_db, active.id)
    assert capsys.readouterr().out == "1 workspace(s) apagado(s) de vez\n"


def test_purge_with_nothing_to_delete_says_zero(cli_db, capsys):
    cli.main(["purge-workspaces"])

    assert capsys.readouterr().out == "0 workspace(s) apagado(s) de vez\n"


def test_a_storage_failure_still_purges_the_rows_and_logs_the_orphans(cli_db, make_workspace, monkeypatch, caplog):
    old = trashed(cli_db, make_workspace, "velho", timedelta(days=8))
    old_id = old.id

    def broken(prefix):
        raise OSError("disk")

    monkeypatch.setattr(storage, "delete_prefix", broken)
    caplog.set_level(logging.INFO)

    cli.main(["purge-workspaces"])

    cli_db.expire_all()
    assert not exists(cli_db, old_id)
    orphan = next(rec for rec in caplog.records if rec.getMessage().startswith("workspace.files_orphaned"))
    assert orphan.levelno == logging.ERROR and f"prefix=ws/{old_id}" in orphan.getMessage()


def test_delete_workspace_with_yes_deletes_an_active_one_now(cli_db, make_workspace, capsys):
    workspace = make_workspace("a")
    wid = workspace.id

    cli.main(["delete-workspace", "a", "--yes"])

    cli_db.expire_all()
    assert not exists(cli_db, wid)
    assert capsys.readouterr().out == "a apagado de vez\n"


def test_delete_workspace_deletes_one_in_the_trash(cli_db, make_workspace):
    workspace = trashed(cli_db, make_workspace, "a", timedelta(hours=1))
    wid = workspace.id

    cli.main(["delete-workspace", "a", "--yes"])

    cli_db.expire_all()
    assert not exists(cli_db, wid) and not storage.path(f"ws/{wid}").exists()


def test_delete_workspace_asks_for_the_slug_again(cli_db, make_workspace, monkeypatch):
    workspace = make_workspace("a")
    monkeypatch.setattr("builtins.input", lambda prompt: "a")

    cli.main(["delete-workspace", "a"])

    cli_db.expire_all()
    assert not exists(cli_db, workspace.id)


def test_a_wrong_confirmation_deletes_nothing(cli_db, make_workspace, monkeypatch):
    workspace = make_workspace("a")
    monkeypatch.setattr("builtins.input", lambda prompt: "b")

    with pytest.raises(SystemExit) as exit_:
        cli.main(["delete-workspace", "a"])

    assert exit_.value.code == 1 and exists(cli_db, workspace.id)


def test_an_unknown_slug_exits_1(cli_db):
    with pytest.raises(SystemExit) as exit_:
        cli.main(["delete-workspace", "nao-existe", "--yes"])

    assert exit_.value.code == 1


def test_an_active_run_blocks_delete_workspace(cli_db, make_user, make_workspace, make_simulation):
    user = make_user("ana@x.com")
    workspace = make_workspace("a", [(user, "analyst")])
    simulation = make_simulation(workspace, user)
    cli_db.add(Run(workspace_id=workspace.id, simulation_id=simulation.id, created_by=user.id,
                   status="running", config={}, inputs={}, confirmed_warnings=[]))
    cli_db.commit()

    with pytest.raises(SystemExit) as exit_:
        cli.main(["delete-workspace", "a", "--yes"])

    assert exit_.value.code == 1 and exists(cli_db, workspace.id)
    assert cli_db.get(Simulation, simulation.id) is not None
```

Mova os imports novos para o topo do arquivo, junto dos existentes (`ruff` reclama de import no meio), e deixe o `ruff format` formatar a linha do `Run(...)`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/api/test_cli.py -q`
Expected: FAIL nos testes novos com `SystemExit: 2` (argparse não conhece os subcomandos).

- [ ] **Step 3: `accounts.purge_trash`**

Em `api/accounts.py`, depois de `purge_workspace`:

```python
def purge_trash(db: Session) -> int:
    cutoff = func.now() - timedelta(days=TRASH_DAYS)
    expired = db.scalars(select(Workspace).where(Workspace.deleted_at < cutoff)).all()
    purged = 0
    for workspace in expired:
        # one failure must not keep the others in the trash forever
        try:
            purge_workspace(db, workspace, by="cli")
            purged += 1
        except Exception:
            db.rollback()
            log.exception("workspace.purge_failed workspace_id=%s", workspace.id)
    return purged
```

- [ ] **Step 4: Comandos na CLI**

Substituir `api/cli.py` por:

```python
import argparse
import logging
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from api import runs
from api.accounts import ActiveRun, create_platform_admin, purge_trash, purge_workspace
from api.db import SessionLocal
from api.models import Run, Workspace


def delete_workspace(db: Session, slug: str, yes: bool) -> int:
    workspace = db.scalar(select(Workspace).where(Workspace.slug == slug))
    if workspace is None:
        sys.stderr.write(f"workspace {slug} não existe\n")
        return 1
    if not yes:
        typed = input(f"Apaga {workspace.name} ({slug}) de vez, sem volta. Digite o slug para confirmar: ")
        if typed.strip() != slug:
            sys.stderr.write("confirmação não confere; nada foi apagado\n")
            return 1
    runs.fail_stale(db, Run.workspace_id == workspace.id)
    try:
        purge_workspace(db, workspace, by="cli")
    except ActiveRun:
        sys.stderr.write("há uma execução em andamento; nada foi apagado\n")
        return 1
    sys.stdout.write(f"{slug} apagado de vez\n")
    return 0


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(prog="python -m api.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    create_admin = commands.add_parser("create-admin", help="cria ou promove um platform admin")
    create_admin.add_argument("email")
    create_admin.add_argument("name")
    commands.add_parser("purge-workspaces", help="apaga de vez os workspaces na lixeira há mais de 7 dias")
    delete = commands.add_parser("delete-workspace", help="apaga de vez um workspace agora, ativo ou na lixeira")
    delete.add_argument("slug")
    delete.add_argument("--yes", action="store_true", help="não pede para digitar o slug de novo")
    args = parser.parse_args(argv)

    code = 0
    with SessionLocal() as db:
        if args.command == "create-admin":
            temp = create_platform_admin(db, args.email, args.name)
            # the temp password is the command's output, not a log line: it must never go through logging
            sys.stdout.write(f"senha temporária: {temp}\n")
        elif args.command == "purge-workspaces":
            sys.stdout.write(f"{purge_trash(db)} workspace(s) apagado(s) de vez\n")
        else:
            code = delete_workspace(db, args.slug, args.yes)
    if code:
        sys.exit(code)


if __name__ == "__main__":
    main()
```

Confira em `api/runs.py` a assinatura de `fail_stale(db, *where)` (linha ~33) antes de usar.

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest tests/api/test_cli.py tests/api/test_delete_workspace.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add api/accounts.py api/cli.py tests/api/test_cli.py
git commit -m "feat(api): cli purge-workspaces e delete-workspace"
```

---

### Task 5: Tela da lixeira

**Files:**
- Modify: `web/src/components/GoogleConnectorDialog.tsx` (tipo `AdminWorkspace`), `web/src/components/DeleteWorkspace.tsx`, `web/src/routes/_auth/admin/workspaces.tsx`
- Create: `web/src/components/TrashedWorkspaces.tsx`

Sem teste automatizado de front neste repo para essa tela; a verificação é build, lint e screenshot.

- [ ] **Step 1: Tipo**

Em `web/src/components/GoogleConnectorDialog.tsx`:

```ts
export type AdminWorkspace = {
  id: number
  name: string
  slug: string
  created_at: string
  google: GoogleConfig | null
  deleted_at: string | null
  purge_at: string | null
}
```

- [ ] **Step 2: Texto do diálogo de excluir**

Em `web/src/components/DeleteWorkspace.tsx`, trocar o texto do `AlertDialogDescription` por:

```tsx
              Vai para a lixeira e some para todos os membros agora. Dá para restaurar por 7 dias; depois disso é apagado de
              vez, com simulações, execuções e arquivos. Digite a sua senha para confirmar.
```

e o toast de sucesso por `toast.success('Workspace movido para a lixeira.')`. (A spec fala em mostrar a data; antes de excluir ela ainda não existe, então o diálogo diz "por 7 dias" e a data aparece na lixeira.)

- [ ] **Step 3: Componente da lixeira**

`web/src/components/TrashedWorkspaces.tsx`:

```tsx
import { toast } from 'sonner'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowCounterClockwise } from '@phosphor-icons/react'
import { DataTable } from '@/components/DataTable'
import type { AdminWorkspace } from '@/components/GoogleConnectorDialog'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { errorMessage, meQuery } from '@/lib/auth'

const date = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString('pt-BR') : '-')

function RestoreButton({ workspace }: { workspace: AdminWorkspace }) {
  const queryClient = useQueryClient()
  const restore = useMutation({
    mutationFn: () => api<AdminWorkspace>(`/admin/workspaces/${workspace.id}/restore`, { method: 'POST' }),
    onSuccess: () => {
      toast.success('Workspace restaurado.')
      queryClient.invalidateQueries({ queryKey: ['admin', 'workspaces'] })
      queryClient.invalidateQueries({ queryKey: meQuery.queryKey })
    },
    onError: (error) => toast.error(errorMessage(error)),
  })
  return (
    <Button variant="outline" size="sm" disabled={restore.isPending} onClick={() => restore.mutate()}>
      <ArrowCounterClockwise aria-hidden />
      Restaurar
    </Button>
  )
}

export function TrashedWorkspaces({ workspaces }: { workspaces: AdminWorkspace[] }) {
  if (workspaces.length === 0) return null
  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-sm font-medium">Lixeira</h2>
        <p className="text-sm text-muted-foreground">Some para os membros agora e é apagado de vez na data indicada.</p>
      </div>
      <DataTable
        id="workspaces-lixeira"
        rows={workspaces}
        rowKey={(w) => w.id}
        columns={[
          { id: 'name', header: 'Nome', fixed: true, sort: (w) => w.name, className: 'font-medium', cell: (w) => w.name },
          { id: 'slug', header: 'Slug', sort: (w) => w.slug, className: 'font-mono text-xs text-muted-foreground', cell: (w) => w.slug },
          { id: 'deleted', header: 'Excluído em', sort: (w) => w.deleted_at ?? '', className: 'tabular-nums', cell: (w) => date(w.deleted_at) },
          { id: 'purge', header: 'Exclusão definitiva', sort: (w) => w.purge_at ?? '', className: 'tabular-nums', cell: (w) => date(w.purge_at) },
          { id: 'actions', header: '', className: 'w-32', cell: (w) => <RestoreButton workspace={w} /> },
        ]}
      />
    </section>
  )
}
```

Confira em `web/src/components/DataTable.tsx` (props a partir da linha ~66) se `toolbar` é opcional e se as chaves das colunas batem (`id`, `header`, `fixed`, `sort`, `className`, `cell`); são as mesmas usadas em `workspaces.tsx`. Se `ArrowCounterClockwise` não existir no `@phosphor-icons/react` instalado, use `ArrowUUpLeft`.

- [ ] **Step 4: Página separa ativos e lixeira**

Em `web/src/routes/_auth/admin/workspaces.tsx`:

1. Import: `import { TrashedWorkspaces } from '@/components/TrashedWorkspaces'`.
2. Logo depois da `useQuery` de `workspaces`:

```tsx
  const active = workspaces.data?.filter((w) => !w.deleted_at) ?? []
  const trashed = workspaces.data?.filter((w) => w.deleted_at) ?? []
```

3. No JSX: trocar `workspaces.data?.length === 0` por `workspaces.data && active.length === 0`, trocar `!!workspaces.data?.length` por `active.length > 0`, trocar `rows={workspaces.data}` por `rows={active}`, e depois do `</DataTable>`-bloco (antes do `<GoogleConnectorDialog`):

```tsx
        <TrashedWorkspaces workspaces={trashed} />
```

- [ ] **Step 5: Build e lint**

Run: `cd web && bun run build && bun run lint`
Expected: build ok; o lint só com os warnings que já existem em `simulacoes/$id.tsx`.

- [ ] **Step 6: Screenshot**

Com API e SPA no ar (`mise run api` + `mise run web`, ou a API servindo `web/dist`), entrar como platform admin, criar um workspace, excluí-lo com a senha e tirar screenshot de `/admin/workspaces` mostrando a seção Lixeira com as duas datas; clicar em Restaurar e tirar outro screenshot com ele de volta na tabela. Regra do `CLAUDE.md`: mudança visual só é dada como pronta com screenshot.

- [ ] **Step 7: Commit**

```bash
git add web/src/components/GoogleConnectorDialog.tsx web/src/components/DeleteWorkspace.tsx web/src/components/TrashedWorkspaces.tsx web/src/routes/_auth/admin/workspaces.tsx
git commit -m "feat(web): lixeira de workspaces com restaurar"
```

---

### Task 6: Docs

**Files:**
- Modify: `API-GUIDE.md`, `DATABASE.md`, `docs/decisoes/auth.md`, `docs/deploy.md`

- [ ] **Step 1: `API-GUIDE.md`**

Substituir a linha do `DELETE /api/admin/workspaces/{workspace_id}` por:

```markdown
| DELETE | `/api/admin/workspaces/{workspace_id}` | Platform admin. Corpo `{password}` (a senha de quem exclui); 204. Move para a lixeira: some para os membros na hora, restaurável por 7 dias, purgado pela CLI `purge-workspaces`. 400 `invalid_current_password` (conta o bloqueio), 429 `locked`, 409 com run em andamento, 404 se já está na lixeira |
| POST | `/api/admin/workspaces/{workspace_id}/restore` | Platform admin. Tira da lixeira; 200 `WorkspaceOut`. 404 se o workspace está ativo ou não existe |
```

e na linha do `GET /api/admin/workspaces` acrescentar que a lista inclui a lixeira, com `deleted_at` e `purge_at` (`null` no ativo); na do `POST /api/admin/workspaces`, acrescentar "409 com mensagem própria se o slug é de um workspace na lixeira".

- [ ] **Step 2: `DATABASE.md`**

Na linha da tabela `workspaces`, acrescentar ao fim da descrição: "`deleted_at`/`deleted_by` (lixeira: nulo = ativo; toda consulta de workspace ativo filtra `deleted_at IS NULL`; purga pela CLI após 7 dias)" e trocar a coluna de migration para `` `0001`, `0007` ``.

- [ ] **Step 3: `docs/decisoes/auth.md`**

Substituir a seção "## Excluir workspace pede a senha de quem exclui" por:

```markdown
## Workspace excluído vai para a lixeira; a CLI apaga de vez

**Sintoma:** o primeiro desenho apagava tudo na hora; um clique errado de platform admin custava um cliente inteiro.

`DELETE /api/admin/workspaces/{id}` é só do platform admin, pede a própria senha (mesma checagem e bloqueio da troca de senha, `accounts.confirm_password`) e só grava `deleted_at`. O workspace some para os membros na hora (`require_role` e `/api/me` filtram a lixeira) e pode ser restaurado por 7 dias (`TRASH_DAYS`, fixo). O slug fica reservado até a purga. Run em andamento barra com 409.

Quem apaga de vez é a CLI, não a API: a API não tem agendador. `purge-workspaces` roda no cron do servidor (`docs/deploy.md`) e apaga os vencidos; `delete-workspace <slug>` apaga um na hora, para pedido de LGPD. Sem o cron, nada é purgado e a lixeira cresce. A purga apaga as linhas por cascade e depois a pasta `ws/{id}`; se o disco falhar, o log `workspace.files_orphaned` diz o prefixo a limpar à mão. As contas dos usuários continuam.
```

- [ ] **Step 4: `docs/deploy.md`**

Na seção "## Backup e restauração", depois da linha do cron do backup:

```markdown
- Cron da purga da lixeira de workspaces (obrigatório, depois do backup das 3h para o backup do dia ainda ter o workspace): `30 3 * * * docker compose -f /opt/gem/deploy/compose.yml --env-file /opt/gem/deploy/.env exec -T api python -m api.cli purge-workspaces >> /var/log/gem-purge.log 2>&1`. Sem ele, workspace excluído fica na lixeira para sempre.
- Apagar um workspace na hora (LGPD): `docker compose -f deploy/compose.yml --env-file deploy/.env exec api python -m api.cli delete-workspace <slug>`. Um workspace purgado ainda existe nos backups por até 7 dias.
```

- [ ] **Step 5: Suíte da API inteira**

Run: `uv run pytest tests/api -q`
Expected: PASS (demora ~10 min; não rode em paralelo com outra sessão usando o mesmo Postgres de teste).

- [ ] **Step 6: Commit**

```bash
git add API-GUIDE.md DATABASE.md docs/decisoes/auth.md docs/deploy.md
git commit -m "docs: lixeira de workspace, purga e delete-workspace pela cli"
```
