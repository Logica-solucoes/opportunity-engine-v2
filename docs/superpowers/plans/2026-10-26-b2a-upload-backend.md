# B2a · Upload, armazenamento e validação (backend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O analista cria uma simulação, sobe investimento/performance/trends em CSV, confirma o mapeamento de colunas e recebe o `ValidationReport` — tudo por API, escopado por workspace.

**Architecture:** Duas tabelas novas (`simulations`, `simulation_files`), um storage local endereçado por conteúdo (`ws/{ws}/sim/{sim}/inputs/{sha256}.csv`), um leitor de CSV pequeno (`api/csvfile.py`), a regra de negócio em `api/simulations.py`, rotas finas em `api/routes/simulations.py` e um `validate` falso em `api/validation.py` que segue o contrato §2 até o A2 existir.

**Tech Stack:** Python 3.13, FastAPI 0.158 (`UploadFile` → `python-multipart`), SQLAlchemy 2, Alembic, Postgres 16, pytest. Stdlib `csv`, `hashlib`, `tempfile`, `unicodedata`.

**Spec:** `docs/superpowers/specs/2026-10-26-b2-upload-validacao-design.md` (seção B2a). Leia antes de começar, junto com `DATABASE.md`, `API-GUIDE.md` e `CODE-STYLE.md`.

**Antes de cada task:** `docker compose up -d` (Postgres em `:5432`). Comandos rodam da raiz do repo.

**Import de `tests/samples.py`:** `tests/` não tem `__init__.py`; `from tests.samples import …` resolve como namespace package pelo `pythonpath = ["."]` do `pyproject.toml`. Se algum pacote instalado também se chamar `tests` e sombrear o import, troque por `from samples import …` (o pytest põe `tests/` no `sys.path` por causa do `conftest.py`) em todos os arquivos.

**Seams de teste (confirmados com o usuário):** as 5 rotas HTTP via `TestClient`; `suggest_mapping` como função pura; a matriz papel × rota de `tests/api/test_rbac.py`; `tests/api/test_migrations.py`. `storage.py`, `csvfile.py` e o fake do `validate` são testados só por trás das rotas.

---

## Mapa de arquivos

| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `pyproject.toml`, `uv.lock` | modificar | `python-multipart` |
| `api/models.py` | modificar | `Simulation`, `SimulationFile`, `FileKind`, `FILE_KINDS` |
| `api/migrations/versions/0003_simulations.py` | criar | tabelas + enum `simulation_file_kind` |
| `api/storage.py` | criar | `put(key, src)`, `path(key)` sobre `STORAGE_DIR` |
| `api/csvfile.py` | criar | encoding/delimitador, `header(path)`, `rows(path)` |
| `api/simulations.py` | criar | `create`, `suggest_mapping`, `save_file`, `save_mapping` |
| `api/validation.py` | criar | fake de `engine.validate` (só `duplicate_date_channel`) |
| `api/routes/__init__.py` | modificar | tipo `SimulationId` |
| `api/routes/simulations.py` | criar | 5 rotas |
| `api/main.py` | modificar | `include_router` |
| `tests/samples.py` | criar | CSVs e mapping de exemplo compartilhados |
| `tests/conftest.py` | modificar | `storage_dir` (autouse), `make_simulation` |
| `tests/api/test_simulations.py` | criar | testes das rotas e de `suggest_mapping` |
| `tests/api/test_rbac.py` | modificar | 5 rotas na matriz + multipart |
| docs e config | modificar | Task 5 |

---

### Task 1: Dependência, models e migration

**Files:**
- Modify: `pyproject.toml`, `uv.lock` (via `uv add`)
- Modify: `api/models.py`
- Create: `api/migrations/versions/0003_simulations.py`
- Test: `tests/api/test_migrations.py` (já existe)

- [ ] **Step 1: Adicionar `python-multipart`**

Run: `uv add python-multipart`
Expected: `pyproject.toml` ganha `"python-multipart>=…"` em `dependencies` e o `uv.lock` muda.

- [ ] **Step 2: Escrever os models**

Em `api/models.py`, logo abaixo de `ROLES = get_args(Role)`, adicione:

```python
FileKind = Literal["investment", "performance", "trends"]
FILE_KINDS = get_args(FileKind)
```

No fim do arquivo, adicione:

```python
class Simulation(Base):
    __tablename__ = "simulations"

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(Text)
    config: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    validation: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    created_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    creator: Mapped[User] = relationship()
    files: Mapped[list["SimulationFile"]] = relationship()


class SimulationFile(Base):
    __tablename__ = "simulation_files"

    simulation_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("simulations.id", ondelete="CASCADE"), primary_key=True
    )
    kind: Mapped[str] = mapped_column(Enum(*FILE_KINDS, name="simulation_file_kind"), primary_key=True)
    sha256: Mapped[str] = mapped_column(Text)
    filename: Mapped[str] = mapped_column(Text)
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    columns: Mapped[list] = mapped_column(JSONB)
    uploaded_by: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

`none_as_null=True`: `validation = None` grava SQL `NULL`, não o JSON `null`.

- [ ] **Step 3: Rodar o teste de migrations e ver falhar**

Run: `uv run pytest tests/api/test_migrations.py -q`
Expected: FAIL — `compare_metadata` lista `add_table` para `simulations` e `simulation_files`.

- [ ] **Step 4: Escrever a migration**

Create `api/migrations/versions/0003_simulations.py`:

```python
"""simulations and their uploaded files

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-26
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "simulations",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "workspace_id", sa.BigInteger(), sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("config", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("validation", postgresql.JSONB(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_simulations_workspace_id", "simulations", ["workspace_id"])
    op.create_table(
        "simulation_files",
        sa.Column(
            "simulation_id",
            sa.BigInteger(),
            sa.ForeignKey("simulations.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "kind",
            sa.Enum("investment", "performance", "trends", name="simulation_file_kind"),
            primary_key=True,
        ),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("columns", postgresql.JSONB(), nullable=False),
        sa.Column("uploaded_by", sa.BigInteger(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("simulation_files")
    op.drop_index("ix_simulations_workspace_id", table_name="simulations")
    op.drop_table("simulations")
    sa.Enum(name="simulation_file_kind").drop(op.get_bind())
```

- [ ] **Step 5: Rodar o teste e conferir o downgrade**

Run: `uv run pytest tests/api/test_migrations.py -q`
Expected: PASS.

Run: `uv run alembic -c api/alembic.ini upgrade head && uv run alembic -c api/alembic.ini downgrade 0002 && uv run alembic -c api/alembic.ini upgrade head`
Expected: sem erro (roda no banco de dev `app`).

- [ ] **Step 6: Format, lint e commit**

Run: `uv run ruff format . && uv run ruff check . && uv run pytest -q`
Expected: tudo verde.

```bash
git add pyproject.toml uv.lock api/models.py api/migrations/versions/0003_simulations.py
git commit -m "feat(api): add simulations and simulation_files tables"
```

---

### Task 2: Criar, listar e abrir simulação + `suggest_mapping`

**Files:**
- Create: `api/simulations.py`
- Create: `api/routes/simulations.py`
- Modify: `api/routes/__init__.py`, `api/main.py`
- Modify: `tests/conftest.py`, `tests/api/test_rbac.py`
- Create: `tests/api/test_simulations.py`

- [ ] **Step 1: Fixture `make_simulation`**

Em `tests/conftest.py`, adicione `from api import simulations` junto dos imports de `api` e, no fim do arquivo:

```python
@pytest.fixture
def make_simulation(db):
    def make(workspace, creator, name="Simulação"):
        return simulations.create(db, workspace, name, by=creator)

    return make
```

- [ ] **Step 2: Escrever os testes que falham**

Create `tests/api/test_simulations.py`:

```python
import pytest

from api.simulations import suggest_mapping


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


def test_create_simulation_starts_empty(logged):
    r = logged.post("/api/w/a/simulations", json={"name": "  Black Friday  "})

    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Black Friday"
    assert body["config"] == {} and body["validation"] is None
    assert body["files"] == {"investment": None, "performance": None, "trends": None}
    assert logged.get(f"/api/w/a/simulations/{body['id']}").json() == body


def test_create_rejects_blank_name(logged):
    assert logged.post("/api/w/a/simulations", json={"name": "   "}).status_code == 422


def test_list_is_scoped_and_newest_first(logged, analyst, ws, make_workspace, make_simulation):
    other = make_workspace("b", [(analyst, "analyst")])
    make_simulation(ws, analyst, "Primeira")
    newest = make_simulation(ws, analyst, "Segunda")
    make_simulation(other, analyst, "De outro workspace")

    body = logged.get("/api/w/a/simulations").json()

    assert [s["name"] for s in body] == ["Segunda", "Primeira"]
    assert body[0]["id"] == newest.id and body[0]["created_by_name"] == "ana"


def test_simulation_of_another_workspace_is_404(logged, analyst, make_workspace, make_simulation):
    foreign = make_simulation(make_workspace("b", [(analyst, "analyst")]), analyst)

    assert logged.get(f"/api/w/a/simulations/{foreign.id}").status_code == 404
    assert logged.get(f"/api/w/b/simulations/{foreign.id}").status_code == 200


@pytest.mark.parametrize(
    "kind, columns, expected",
    [
        (
            "investment",
            ["data", "canal", "investimento"],
            {"date_col": "data", "channel_col": "canal", "investment_col": "investimento"},
        ),
        (
            "investment",
            ["Date", "Channel", "Spend"],
            {"date_col": "Date", "channel_col": "Channel", "investment_col": "Spend"},
        ),
        (
            "investment",
            ["Data", "Mídia", "Custo Total"],
            {"date_col": "Data", "channel_col": "Mídia", "investment_col": "Custo Total"},
        ),
        ("investment", ["x", "y"], {"date_col": None, "channel_col": None, "investment_col": None}),
        ("performance", ["data", "conversoes"], {"date_col": "data", "kpi_col": "conversoes"}),
        ("performance", ["receita", "Dia"], {"date_col": "Dia", "kpi_col": "receita"}),
        ("trends", ["data", "trends"], {"date_col": "data", "trends_col": "trends"}),
    ],
)
def test_suggest_mapping(kind, columns, expected):
    assert suggest_mapping(kind, columns) == expected
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `uv run pytest tests/api/test_simulations.py -q`
Expected: ERROR na coleta — `ModuleNotFoundError: No module named 'api.simulations'`.

- [ ] **Step 4: Serviço**

Create `api/simulations.py`:

```python
import logging
import unicodedata

from sqlalchemy.orm import Session

from api.models import Simulation, User, Workspace

log = logging.getLogger(__name__)

FIELDS = {
    "investment": ("date_col", "channel_col", "investment_col"),
    "performance": ("date_col", "kpi_col"),
    "trends": ("date_col", "trends_col"),
}
ALIASES = {
    "date_col": ("data", "date", "dia", "day"),
    "channel_col": ("canal", "channel", "midia", "media"),
    "investment_col": ("investimento", "invest", "spend", "custo", "cost", "valor"),
}


def create(db: Session, workspace: Workspace, name: str, by: User) -> Simulation:
    simulation = Simulation(workspace_id=workspace.id, name=name, config={}, created_by=by.id)
    db.add(simulation)
    db.commit()
    log.info("simulation.created simulation_id=%s workspace_id=%s by=%s", simulation.id, workspace.id, by.id)
    return simulation


def normalize(column: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", column.lower()) if c.isalnum())


def suggest_mapping(kind: str, columns: list[str]) -> dict[str, str | None]:
    normalized = [normalize(c) for c in columns]
    suggestion = {}
    for field in FIELDS[kind]:
        if field in ALIASES:
            suggestion[field] = next((c for c, n in zip(columns, normalized) if n.startswith(ALIASES[field])), None)
        else:
            # the KPI / trends file has one value column besides the date
            suggestion[field] = next((c for c in columns if c != suggestion["date_col"]), None)
    return suggestion
```

- [ ] **Step 5: Tipo do path param**

Em `api/routes/__init__.py`, abaixo de `UserId`:

```python
SimulationId = Annotated[int, Path(ge=1, le=2**63 - 1)]
```

- [ ] **Step 6: Rotas**

Create `api/routes/simulations.py`:

```python
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, StringConstraints
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from api import simulations
from api.auth import Ctx, require_role
from api.db import get_db
from api.models import FILE_KINDS, Simulation, SimulationFile
from api.routes import SimulationId

router = APIRouter(prefix="/api/w/{slug}/simulations")
analyst = require_role("analyst")

SimulationName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]


class SimulationIn(BaseModel):
    name: SimulationName


class SimulationSummary(BaseModel):
    id: int
    name: str
    created_by_name: str
    created_at: datetime
    updated_at: datetime


class FileOut(BaseModel):
    filename: str
    size_bytes: int
    sha256: str
    columns: list[str]
    suggested: dict[str, str | None]
    uploaded_at: datetime


class SimulationOut(BaseModel):
    id: int
    name: str
    config: dict
    validation: dict | None
    files: dict[str, FileOut | None]


def file_out(f: SimulationFile) -> FileOut:
    return FileOut(
        filename=f.filename,
        size_bytes=f.size_bytes,
        sha256=f.sha256,
        columns=f.columns,
        suggested=simulations.suggest_mapping(f.kind, f.columns),
        uploaded_at=f.uploaded_at,
    )


def simulation_out(s: Simulation) -> SimulationOut:
    files = {f.kind: f for f in s.files}
    return SimulationOut(
        id=s.id,
        name=s.name,
        config=s.config,
        validation=s.validation,
        files={kind: file_out(files[kind]) if kind in files else None for kind in FILE_KINDS},
    )


def find_simulation(db: Session, ctx: Ctx, simulation_id: int) -> Simulation:
    simulation = db.scalar(
        select(Simulation).where(Simulation.id == simulation_id, Simulation.workspace_id == ctx.workspace.id)
    )
    if simulation is None:
        raise HTTPException(404)
    return simulation


@router.get("", response_model=list[SimulationSummary])
def list_simulations(ctx: Ctx = Depends(analyst), db: Session = Depends(get_db)):
    rows = db.scalars(
        select(Simulation)
        .options(joinedload(Simulation.creator))
        .where(Simulation.workspace_id == ctx.workspace.id)
        .order_by(Simulation.updated_at.desc(), Simulation.id.desc())
    )
    return [
        SimulationSummary(
            id=s.id, name=s.name, created_by_name=s.creator.name, created_at=s.created_at, updated_at=s.updated_at
        )
        for s in rows
    ]


@router.post("", status_code=201, response_model=SimulationOut)
def create_simulation(body: SimulationIn, ctx: Ctx = Depends(analyst), db: Session = Depends(get_db)):
    return simulation_out(simulations.create(db, ctx.workspace, body.name, by=ctx.user))


@router.get("/{simulation_id}", response_model=SimulationOut)
def get_simulation(simulation_id: SimulationId, ctx: Ctx = Depends(analyst), db: Session = Depends(get_db)):
    return simulation_out(find_simulation(db, ctx, simulation_id))
```

Em `api/main.py`, troque `from api.routes import admin, members` por `from api.routes import admin, members, simulations` e adicione `app.include_router(simulations.router)` depois de `app.include_router(admin.router)`.

- [ ] **Step 7: Rodar e ver passar**

Run: `uv run pytest tests/api/test_simulations.py -q`
Expected: PASS (11 testes).

- [ ] **Step 8: Matriz RBAC falha sem as rotas novas**

Run: `uv run pytest tests/api/test_rbac.py -q`
Expected: FAIL em `test_matrix_covers_every_api_route` (3 rotas novas fora de `ROUTES`).

- [ ] **Step 9: Pôr as rotas na matriz**

Em `tests/api/test_rbac.py`, adicione ao dict `ROUTES`, depois da linha de `DELETE /api/w/{slug}/members/{user_id}`:

```python
    ("GET", "/api/w/{slug}/simulations"): ("analyst", 200, None),
    ("POST", "/api/w/{slug}/simulations"): ("analyst", 201, lambda e: {"name": "Nova"}),
    ("GET", "/api/w/{slug}/simulations/{simulation_id}"): ("analyst", 200, None),
```

Troque o fixture `env` por:

```python
@pytest.fixture
def env(make_user, make_workspace, make_simulation, password):
    users = {role: make_user(f"{role}@x.com") for role in ("viewer", "analyst", "admin")}
    users["platform"] = make_user("platform@x.com", platform=True)
    target = make_user("target@x.com")
    make_user("fora@x.com")
    ws = make_workspace("a", [(users[r], r) for r in ("viewer", "analyst", "admin")] + [(target, "viewer")])
    simulation = make_simulation(ws, users["analyst"])
    return {"users": users, "target": target, "password": password, "simulation": simulation}
```

Em `test_role_matrix`, troque a linha do `path` por:

```python
    path = template.format(slug="a", user_id=env["target"].id, simulation_id=env["simulation"].id)
```

- [ ] **Step 10: Suíte inteira, format, lint, commit**

Run: `uv run ruff format . && uv run ruff check . && uv run pytest -q`
Expected: tudo verde.

```bash
git add api/simulations.py api/routes/simulations.py api/routes/__init__.py api/main.py tests/conftest.py tests/api/test_simulations.py tests/api/test_rbac.py
git commit -m "feat(api): create, list and get simulations with column mapping suggestions"
```

---

### Task 3: Upload de arquivo (storage + leitura do CSV)

**Files:**
- Create: `api/storage.py`, `api/csvfile.py`, `tests/samples.py`
- Modify: `api/simulations.py`, `api/routes/simulations.py`
- Modify: `tests/conftest.py`, `tests/api/test_simulations.py`, `tests/api/test_rbac.py`

- [ ] **Step 1: Dados de exemplo compartilhados**

Create `tests/samples.py`:

```python
INVESTMENT = b"data,canal,investimento\n2024-01-01,SEARCH,100\n2024-01-01,YOUTUBE,50\n2024-01-02,SEARCH,120\n"
PERFORMANCE = b"data,conversoes\n2024-01-01,10\n2024-01-02,12\n"
TRENDS = b"data,trends\n2024-01-01,40\n2024-01-02,42\n"

MAPPING = {
    "investment_file": {"date_col": "data", "channel_col": "canal", "investment_col": "investimento"},
    "performance_file": {"date_col": "data", "kpi_col": "conversoes"},
}
TRENDS_MAPPING = {"date_col": "data", "trends_col": "trends"}
```

- [ ] **Step 2: Fixtures de storage e simulação com arquivos**

Em `tests/conftest.py`: adicione `import io` no topo, troque `from api import simulations` por `from api import simulations, storage`, e substitua o fixture `make_simulation` por:

```python
@pytest.fixture(autouse=True)
def storage_dir(tmp_path, monkeypatch):
    # never write uploads into the repo's ./data
    root = tmp_path / "storage"
    monkeypatch.setattr(storage, "ROOT", root)
    return root


@pytest.fixture
def make_simulation(db):
    def make(workspace, creator, name="Simulação", files=None):
        simulation = simulations.create(db, workspace, name, by=creator)
        for kind, content in (files or {}).items():
            simulations.save_file(db, simulation, kind, io.BytesIO(content), f"{kind}.csv", by=creator)
        return simulation

    return make
```

(O `storage_dir` só funciona depois que `api/storage.py` existir — Step 5.)

- [ ] **Step 3: Testes que falham**

Em `tests/api/test_simulations.py`, troque o bloco de imports por:

```python
import hashlib

import pytest

from api import simulations
from api.simulations import suggest_mapping
from tests.samples import INVESTMENT
```

e adicione no fim:

```python
def upload(client, simulation_id, kind, content, filename="dados.csv", slug="a"):
    return client.put(
        f"/api/w/{slug}/simulations/{simulation_id}/files/{kind}",
        files={"file": (filename, content, "text/csv")},
    )


def test_upload_stores_file_under_its_workspace(logged, analyst, ws, make_simulation, storage_dir):
    simulation = make_simulation(ws, analyst)

    r = upload(logged, simulation.id, "investment", INVESTMENT, filename="C:\\fakepath\\investimento.csv")

    assert r.status_code == 200
    sha = hashlib.sha256(INVESTMENT).hexdigest()
    assert r.json()["files"]["investment"] | {"uploaded_at": None} == {
        "filename": "investimento.csv",
        "size_bytes": len(INVESTMENT),
        "sha256": sha,
        "columns": ["data", "canal", "investimento"],
        "suggested": {"date_col": "data", "channel_col": "canal", "investment_col": "investimento"},
        "uploaded_at": None,
    }
    assert (storage_dir / f"ws/{ws.id}/sim/{simulation.id}/inputs/{sha}.csv").read_bytes() == INVESTMENT


def test_upload_to_another_workspace_simulation_is_404(logged, analyst, make_workspace, make_simulation, storage_dir):
    foreign = make_simulation(make_workspace("b", [(analyst, "analyst")]), analyst)

    assert upload(logged, foreign.id, "investment", INVESTMENT).status_code == 404
    assert not storage_dir.exists()


def test_upload_rejects_file_over_the_limit(logged, analyst, ws, make_simulation, monkeypatch):
    monkeypatch.setattr(simulations, "MAX_UPLOAD_BYTES", 10)
    simulation = make_simulation(ws, analyst)

    r = upload(logged, simulation.id, "investment", INVESTMENT)

    assert (r.status_code, r.json()["detail"]) == (413, "Arquivo maior que 30 MB.")


@pytest.mark.parametrize(
    "filename, content, message",
    [
        ("dados.txt", INVESTMENT, "Envie um arquivo .csv."),
        ("dados.csv", b"data\n2024-01-01\n", "Não foi possível ler o cabeçalho do CSV."),
        ("dados.csv", b"", "Não foi possível ler o cabeçalho do CSV."),
        ("dados.csv", b"data,,canal\n", "Não foi possível ler o cabeçalho do CSV."),
    ],
)
def test_upload_rejects_unreadable_file(logged, analyst, ws, make_simulation, filename, content, message):
    simulation = make_simulation(ws, analyst)

    r = upload(logged, simulation.id, "investment", content, filename=filename)

    assert (r.status_code, r.json()["detail"]) == (422, message)


def test_upload_reads_latin1_semicolon_csv(logged, analyst, ws, make_simulation):
    simulation = make_simulation(ws, analyst)
    content = "Data;Mídia;Custo\n01/01/2024;Busca;1.234,56\n".encode("latin-1")

    file = upload(logged, simulation.id, "investment", content).json()["files"]["investment"]

    assert file["columns"] == ["Data", "Mídia", "Custo"]
    assert file["suggested"] == {"date_col": "Data", "channel_col": "Mídia", "investment_col": "Custo"}


def test_reupload_replaces_the_file(logged, analyst, ws, make_simulation):
    simulation = make_simulation(ws, analyst, files={"investment": INVESTMENT})
    new = b"dia,canal,valor\n2024-01-01,SEARCH,1\n"

    body = upload(logged, simulation.id, "investment", new).json()

    assert body["files"]["investment"]["sha256"] == hashlib.sha256(new).hexdigest()
    assert body["files"]["investment"]["columns"] == ["dia", "canal", "valor"]
```

- [ ] **Step 4: Rodar e ver falhar**

Run: `uv run pytest tests/api/test_simulations.py -q`
Expected: ERROR — `ImportError: cannot import name 'storage' from 'api'` (vindo do `conftest.py`).

- [ ] **Step 5: Storage local**

Create `api/storage.py`:

```python
import os
import shutil
from pathlib import Path

# ponytail: local dir only; GCS comes in B11, chosen by env here, with path() downloading to a temp file
ROOT = Path(os.environ.get("STORAGE_DIR", "data"))


def path(key: str) -> Path:
    return ROOT / key


def put(key: str, src: Path) -> None:
    dest = path(key)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    shutil.copyfile(src, part)
    os.replace(part, dest)
```

- [ ] **Step 6: Leitor de CSV**

Create `api/csvfile.py`:

```python
import csv
from collections.abc import Iterator
from pathlib import Path

DELIMITERS = ",;\t|"


class Unreadable(Exception):
    pass


def detect(path: Path) -> tuple[str, str]:
    # ponytail: reads the whole file to pick the encoding; fine under the 30 MB upload cap
    data = path.read_bytes()
    try:
        data.decode("utf-8-sig")
        encoding = "utf-8-sig"
    except UnicodeDecodeError:
        encoding = "latin-1"
    # decided on the header line only: csv.Sniffer picks "," in BR files that use ";" and decimal commas
    first_line = data.split(b"\n", 1)[0].decode(encoding)
    delimiter = max(DELIMITERS, key=first_line.count)
    if first_line.count(delimiter) == 0:
        raise Unreadable
    return encoding, delimiter


def rows(path: Path) -> Iterator[list[str]]:
    encoding, delimiter = detect(path)
    with path.open(newline="", encoding=encoding) as f:
        yield from csv.reader(f, delimiter=delimiter)


def header(path: Path) -> list[str]:
    encoding, delimiter = detect(path)
    with path.open(newline="", encoding=encoding) as f:
        try:
            first = next(csv.reader(f, delimiter=delimiter), [])
        except csv.Error:
            raise Unreadable
    columns = [c.strip() for c in first]
    if len(columns) < 2 or not all(columns):
        raise Unreadable
    return columns
```

- [ ] **Step 7: `save_file` no serviço**

Em `api/simulations.py`, troque o bloco de imports por:

```python
import hashlib
import logging
import tempfile
import unicodedata
from pathlib import Path
from typing import BinaryIO

from sqlalchemy import func
from sqlalchemy.orm import Session

from api import csvfile, storage
from api.models import Simulation, SimulationFile, User, Workspace
```

Abaixo de `log = logging.getLogger(__name__)`, adicione:

```python
# Cloud Run caps HTTP/1 request bodies at 32 MiB; aggregated daily data is well under 1 MB
MAX_UPLOAD_BYTES = 30 * 1024 * 1024
CHUNK_BYTES = 1024 * 1024
```

Abaixo de `ALIASES`, adicione:

```python
class TooLarge(Exception):
    pass


class InvalidInput(Exception):
    pass
```

No fim do arquivo, adicione:

```python
def input_key(simulation: Simulation, sha256: str) -> str:
    return f"ws/{simulation.workspace_id}/sim/{simulation.id}/inputs/{sha256}.csv"


def save_file(db: Session, simulation: Simulation, kind: str, src: BinaryIO, filename: str, by: User) -> None:
    if not filename.lower().endswith(".csv"):
        raise InvalidInput("Envie um arquivo .csv.")
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / "upload.csv"
        digest, size = hashlib.sha256(), 0
        with local.open("wb") as out:
            while chunk := src.read(CHUNK_BYTES):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise TooLarge
                digest.update(chunk)
                out.write(chunk)
        try:
            columns = csvfile.header(local)
        except csvfile.Unreadable:
            raise InvalidInput("Não foi possível ler o cabeçalho do CSV.")
        sha256 = digest.hexdigest()
        storage.put(input_key(simulation, sha256), local)

    row = db.get(SimulationFile, (simulation.id, kind)) or SimulationFile(simulation_id=simulation.id, kind=kind)
    row.sha256 = sha256
    # display only, never a path; browsers on Windows may send "C:\fakepath\name.csv"
    row.filename = filename.replace("\\", "/").rsplit("/", 1)[-1][:200]
    row.size_bytes = size
    row.columns = columns
    row.uploaded_by = by.id
    row.uploaded_at = func.now()
    db.add(row)
    simulation.validation = None
    simulation.updated_at = func.now()
    db.commit()
    log.info(
        "simulation.file_uploaded simulation_id=%s kind=%s sha256=%s size_bytes=%s", simulation.id, kind, sha256, size
    )
```

- [ ] **Step 8: Rota de upload**

Em `api/routes/simulations.py`: troque `from fastapi import APIRouter, Depends, HTTPException` por `from fastapi import APIRouter, Depends, HTTPException, UploadFile` e `from api.models import FILE_KINDS, Simulation, SimulationFile` por `from api.models import FILE_KINDS, FileKind, Simulation, SimulationFile`. No fim do arquivo:

```python
@router.put("/{simulation_id}/files/{kind}", response_model=SimulationOut)
def upload_file(
    simulation_id: SimulationId,
    kind: FileKind,
    file: UploadFile,
    ctx: Ctx = Depends(analyst),
    db: Session = Depends(get_db),
):
    simulation = find_simulation(db, ctx, simulation_id)
    try:
        simulations.save_file(db, simulation, kind, file.file, file.filename or "", by=ctx.user)
    except simulations.TooLarge:
        raise HTTPException(413, "Arquivo maior que 30 MB.")
    except simulations.InvalidInput as e:
        raise HTTPException(422, str(e))
    return simulation_out(simulation)
```

- [ ] **Step 9: Rodar e ver passar**

Run: `uv run pytest tests/api/test_simulations.py -q`
Expected: PASS.

- [ ] **Step 10: Upload na matriz RBAC**

Em `tests/api/test_rbac.py`, adicione abaixo de `import pytest`:

```python
from tests.samples import INVESTMENT
```

Abaixo de `UNSCOPED = {...}`:

```python
class Files(dict):
    """multipart body: sent as client.request(files=...) instead of json="""
```

Em `ROUTES`, depois de `GET /api/w/{slug}/simulations/{simulation_id}`:

```python
    ("PUT", "/api/w/{slug}/simulations/{simulation_id}/files/{kind}"): (
        "analyst",
        200,
        lambda e: Files(file=("investimento.csv", INVESTMENT, "text/csv")),
    ),
```

Em `test_role_matrix`, troque as duas últimas linhas antes do `assert` (a do `path` e a do `r = client.request(...)`) por:

```python
    path = template.format(slug="a", user_id=env["target"].id, simulation_id=env["simulation"].id, kind="investment")
    payload = body(env) if body else None

    if isinstance(payload, Files):
        r = client.request(method, path, files=payload)
    else:
        r = client.request(method, path, json=payload)
```

- [ ] **Step 11: Suíte inteira, format, lint, commit**

Run: `uv run ruff format . && uv run ruff check . && uv run pytest -q`
Expected: tudo verde (viewer → 403 no upload).

```bash
git add api/storage.py api/csvfile.py api/simulations.py api/routes/simulations.py tests/samples.py tests/conftest.py tests/api/test_simulations.py tests/api/test_rbac.py
git commit -m "feat(api): upload simulation csv files to content-addressed local storage"
```

---

### Task 4: Mapeamento e validação

**Files:**
- Create: `api/validation.py`
- Modify: `api/simulations.py`, `api/routes/simulations.py`
- Modify: `tests/api/test_simulations.py`, `tests/api/test_rbac.py`

- [ ] **Step 1: Testes que falham**

Em `tests/api/test_simulations.py`, troque `from tests.samples import INVESTMENT` por:

```python
from tests.samples import INVESTMENT, MAPPING, PERFORMANCE, TRENDS, TRENDS_MAPPING
```

e adicione no fim:

```python
BOTH = {"investment": INVESTMENT, "performance": PERFORMANCE}


def put_mapping(client, simulation_id, mapping, slug="a"):
    return client.put(f"/api/w/{slug}/simulations/{simulation_id}/mapping", json=mapping)


def test_mapping_runs_the_validation(logged, analyst, ws, make_simulation):
    simulation = make_simulation(ws, analyst, files=BOTH)

    r = put_mapping(logged, simulation.id, MAPPING)

    assert r.status_code == 200
    body = r.json()
    assert body["config"] == {"column_mapping": MAPPING}
    assert body["validation"] == {
        "ok": True,
        "cadence": None,
        "period_days": None,
        "date_range": None,
        "channels": ["SEARCH", "YOUTUBE"],
        "checks": [],
        "collinearity": None,
    }


def test_duplicate_date_channel_blocks_the_run(logged, analyst, ws, make_simulation):
    duplicated = INVESTMENT + b"2024-01-01,SEARCH,30\n"
    simulation = make_simulation(ws, analyst, files={"investment": duplicated, "performance": PERFORMANCE})

    validation = put_mapping(logged, simulation.id, MAPPING).json()["validation"]

    assert validation["ok"] is False
    assert validation["checks"] == [
        {
            "id": "duplicate_date_channel",
            "level": "error",
            "message": "1 linha repetida de (data, canal) no investimento",
            "details": {"rows": [{"date": "2024-01-01", "channel": "SEARCH", "count": 2}]},
        }
    ]


def test_mapping_with_trends(logged, analyst, ws, make_simulation):
    simulation = make_simulation(ws, analyst, files=BOTH | {"trends": TRENDS})
    mapping = MAPPING | {"generic_trends_file": TRENDS_MAPPING}

    r = put_mapping(logged, simulation.id, mapping)

    assert r.status_code == 200
    assert r.json()["config"]["column_mapping"] == mapping


@pytest.mark.parametrize(
    "files, mapping, message",
    [
        ({"investment": INVESTMENT}, MAPPING, "Envie investimento e performance antes de validar."),
        (
            BOTH,
            MAPPING | {"generic_trends_file": TRENDS_MAPPING},
            "Envie o arquivo de trends antes de mapeá-lo.",
        ),
        (BOTH | {"trends": TRENDS}, MAPPING, "Mapeie as colunas do arquivo de trends."),
        (
            BOTH,
            MAPPING | {"investment_file": MAPPING["investment_file"] | {"date_col": "dia"}},
            "Coluna 'dia' não existe no arquivo de investimento.",
        ),
    ],
)
def test_mapping_rejects_inconsistent_input(logged, analyst, ws, make_simulation, files, mapping, message):
    simulation = make_simulation(ws, analyst, files=files)

    r = put_mapping(logged, simulation.id, mapping)

    assert (r.status_code, r.json()["detail"]) == (422, message)


def test_mapping_of_another_workspace_simulation_is_404(logged, analyst, make_workspace, make_simulation):
    foreign = make_simulation(make_workspace("b", [(analyst, "analyst")]), analyst, files=BOTH)

    assert put_mapping(logged, foreign.id, MAPPING).status_code == 404


def test_reupload_clears_the_validation(logged, analyst, ws, make_simulation):
    simulation = make_simulation(ws, analyst, files=BOTH)
    put_mapping(logged, simulation.id, MAPPING)

    body = upload(logged, simulation.id, "investment", INVESTMENT).json()

    assert body["validation"] is None
    assert body["config"] == {"column_mapping": MAPPING}
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/api/test_simulations.py -q`
Expected: FAIL — as rotas de mapping respondem 405 (`Method Not Allowed`).

- [ ] **Step 3: Fake do validate**

Create `api/validation.py`:

```python
from collections import Counter
from pathlib import Path

from api import csvfile

MAX_DETAIL_ROWS = 20


def validate(inputs: dict[str, Path | None], config: dict) -> dict:
    # ponytail: stand-in for engine.validate (A2, docs/m2/README.md contract §2) with one check;
    # when engine/ exists this module becomes `from engine import validate`
    mapping = config["column_mapping"]["investment_file"]
    rows = csvfile.rows(inputs["investment_file"])
    header = [c.strip() for c in next(rows)]
    date_i, channel_i = header.index(mapping["date_col"]), header.index(mapping["channel_col"])
    pairs = Counter((r[date_i].strip(), r[channel_i].strip()) for r in rows if len(r) > max(date_i, channel_i))

    checks = []
    repeated = [(date, channel, n) for (date, channel), n in pairs.items() if n > 1]
    if repeated:
        extra = sum(n - 1 for _, _, n in repeated)
        noun = "linha repetida" if extra == 1 else "linhas repetidas"
        checks.append(
            {
                "id": "duplicate_date_channel",
                "level": "error",
                "message": f"{extra} {noun} de (data, canal) no investimento",
                "details": {
                    "rows": [{"date": d, "channel": c, "count": n} for d, c, n in repeated[:MAX_DETAIL_ROWS]]
                },
            }
        )
    return {
        "ok": not any(c["level"] == "error" for c in checks),
        "cadence": None,
        "period_days": None,
        "date_range": None,
        "channels": sorted({channel for _, channel in pairs}),
        "checks": checks,
        "collinearity": None,
    }
```

- [ ] **Step 4: `save_mapping` no serviço**

Em `api/simulations.py`, troque `from api import csvfile, storage` por `from api import csvfile, storage, validation`. Abaixo de `CHUNK_BYTES`, adicione:

```python
# EngineConfig.column_mapping key -> uploaded file kind
MAPPING_FILES = {"investment_file": "investment", "performance_file": "performance", "generic_trends_file": "trends"}
FILE_LABELS = {"investment": "investimento", "performance": "performance", "trends": "trends"}
```

No fim do arquivo:

```python
def save_mapping(db: Session, simulation: Simulation, mapping: dict) -> None:
    files = {f.kind: f for f in simulation.files}
    if "investment" not in files or "performance" not in files:
        raise InvalidInput("Envie investimento e performance antes de validar.")
    if "trends" in files and "generic_trends_file" not in mapping:
        raise InvalidInput("Mapeie as colunas do arquivo de trends.")
    if "trends" not in files and "generic_trends_file" in mapping:
        raise InvalidInput("Envie o arquivo de trends antes de mapeá-lo.")
    for key, columns in mapping.items():
        file = files[MAPPING_FILES[key]]
        for column in columns.values():
            if column not in file.columns:
                raise InvalidInput(f"Coluna '{column}' não existe no arquivo de {FILE_LABELS[file.kind]}.")

    inputs = {
        key: storage.path(input_key(simulation, files[kind].sha256)) if kind in files else None
        for key, kind in MAPPING_FILES.items()
    }
    simulation.config = {**simulation.config, "column_mapping": mapping}
    simulation.validation = validation.validate(inputs, simulation.config)
    simulation.updated_at = func.now()
    db.commit()
    log.info("simulation.validated simulation_id=%s ok=%s", simulation.id, simulation.validation["ok"])
```

- [ ] **Step 5: Rota de mapping**

Em `api/routes/simulations.py`, abaixo de `class SimulationIn`, adicione:

```python
class InvestmentColumns(BaseModel):
    date_col: str
    channel_col: str
    investment_col: str


class PerformanceColumns(BaseModel):
    date_col: str
    kpi_col: str


class TrendsColumns(BaseModel):
    date_col: str
    trends_col: str


class MappingIn(BaseModel):
    investment_file: InvestmentColumns
    performance_file: PerformanceColumns
    generic_trends_file: TrendsColumns | None = None
```

No fim do arquivo:

```python
@router.put("/{simulation_id}/mapping", response_model=SimulationOut)
def save_mapping(
    simulation_id: SimulationId, body: MappingIn, ctx: Ctx = Depends(analyst), db: Session = Depends(get_db)
):
    simulation = find_simulation(db, ctx, simulation_id)
    try:
        simulations.save_mapping(db, simulation, body.model_dump(exclude_none=True))
    except simulations.InvalidInput as e:
        raise HTTPException(422, str(e))
    return simulation_out(simulation)
```

- [ ] **Step 6: Rodar e ver passar**

Run: `uv run pytest tests/api/test_simulations.py -q`
Expected: PASS.

- [ ] **Step 7: Mapping na matriz RBAC**

Em `tests/api/test_rbac.py`: troque `from tests.samples import INVESTMENT` por `from tests.samples import INVESTMENT, MAPPING, PERFORMANCE`. Em `ROUTES`, depois da entrada do upload:

```python
    ("PUT", "/api/w/{slug}/simulations/{simulation_id}/mapping"): ("analyst", 200, lambda e: MAPPING),
```

No fixture `env`, troque `simulation = make_simulation(ws, users["analyst"])` por:

```python
    simulation = make_simulation(ws, users["analyst"], files={"investment": INVESTMENT, "performance": PERFORMANCE})
```

- [ ] **Step 8: Suíte inteira, format, lint, commit**

Run: `uv run ruff format . && uv run ruff check . && uv run pytest -q`
Expected: tudo verde.

```bash
git add api/validation.py api/simulations.py api/routes/simulations.py tests/api/test_simulations.py tests/api/test_rbac.py
git commit -m "feat(api): save column mapping and validate uploads with a stand-in for engine.validate"
```

---

### Task 5: Config, imagem e documentação

**Files:**
- Modify: `.gitignore`, `.dockerignore`, `.env.example`, `Dockerfile`
- Modify: `API-GUIDE.md`, `DATABASE.md`, `SECURITY.md`, `CLAUDE.md`
- Create: `docs/decisoes/upload-e-storage.md`
- Modify: `docs/decisoes/README.md`, `docs/m2/trilha-b-plataforma.md`, `docs/m2/README.md`

- [ ] **Step 1: Ignorar o storage local**

`.gitignore`: abaixo de `outputs/`, adicione `/data/`. `.dockerignore`: adicione `data/` no fim.

`.env.example`, no fim:

```
# Diretorio dos arquivos enviados (storage local; GCS entra no B11). Default: data
# STORAGE_DIR=data
```

- [ ] **Step 2: Diretório gravável na imagem**

No `Dockerfile`, troque `RUN groupadd -r app && useradd -r -m -d /home/app -g app app` por:

```dockerfile
RUN groupadd -r app && useradd -r -m -d /home/app -g app app \
    && mkdir /app/data && chown app:app /app/data
```

(O `STORAGE_DIR` default é `data` relativo a `/app`, que é do root; sem isso o upload falha no container.)

Run: `docker build -t gem-b2a . && docker run --rm gem-b2a sh -c "touch /app/data/x && echo ok"`
Expected: `ok`.

- [ ] **Step 3: `API-GUIDE.md`**

Em **Status de erro**, troque `422 entrada inválida;` por `413 upload acima de 30 MB; 422 entrada inválida;`.

Na tabela **Endpoints**, depois da linha de `DELETE /api/w/{slug}/members/{user_id}`, adicione:

```markdown
| GET | `/api/w/{slug}/simulations` | Analyst+. `[{id, name, created_by_name, created_at, updated_at}]`, mais recente primeiro |
| POST | `/api/w/{slug}/simulations` | Analyst+. `{name}` (1–120) → 201 `SimulationOut` = `{id, name, config, validation, files: {investment\|performance\|trends: {filename, size_bytes, sha256, columns, suggested, uploaded_at} \| null}}` |
| GET | `/api/w/{slug}/simulations/{simulation_id}` | Analyst+. `SimulationOut` |
| PUT | `/api/w/{slug}/simulations/{simulation_id}/files/{kind}` | Analyst+. Multipart `file` (`.csv`, ≤ 30 MB) → `SimulationOut`; substitui o arquivo do `kind` e zera `validation`. 413 acima de 30 MB; 422 extensão ou cabeçalho ilegível |
| PUT | `/api/w/{slug}/simulations/{simulation_id}/mapping` | Analyst+. `{investment_file, performance_file, generic_trends_file?}` (formato do `column_mapping`) → salva em `config`, roda o validate e devolve `SimulationOut`; 422 arquivo faltando ou coluna inexistente |
```

Troque `Os demais entram com B2 (upload e validação), B3 (sugestão de parâmetros)` por `Os demais entram com B3 (sugestão de parâmetros)`.

- [ ] **Step 4: `DATABASE.md`**

Na tabela **Tabelas**, adicione:

```markdown
| `simulations` | `workspace_id` (index), `name`, `config jsonb` (rascunho do `EngineConfig`; o B2 grava `column_mapping`), `validation jsonb` (último `ValidationReport`: snapshot de propósito, revalidar relê o CSV inteiro; zerado a cada upload), `created_by`, `created_at`, `updated_at` | `0003` |
| `simulation_files` | PK `(simulation_id, kind)`, `kind` enum `simulation_file_kind` (investment\|performance\|trends), `sha256` (compõe a chave no storage), `filename` (só exibição), `size_bytes`, `columns jsonb` (cabeçalho), `uploaded_by`, `uploaded_at` | `0003` |
```

- [ ] **Step 5: `SECURITY.md`**

Troque a linha `- Upload (B2): validar tipo e tamanho antes de processar; …` por:

```markdown
- Upload (B2): só `.csv` até 30 MB, conferido antes de guardar; o conteúdo só é lido pelo `csv` da stdlib, nunca executado. O nome original só é exibido; o arquivo vive em `ws/{workspace_id}/sim/{simulation_id}/inputs/{sha256}.csv`, chave montada pela API. CSV exportado deve escapar texto que começa com `=`, `+`, `-`, `@`, tab ou CR (o Excel executaria a fórmula).
```

- [ ] **Step 6: `docs/decisoes/upload-e-storage.md`**

Create:

```markdown
# Upload e storage

Decisões do B2 (spec `docs/superpowers/specs/2026-10-26-b2-upload-validacao-design.md`).

## Simulação é um rascunho no banco

O analista cria a simulação e vai preenchendo: arquivos (`simulation_files`), mapeamento e, no B3, parâmetros (`simulations.config`, jsonb no formato do `EngineConfig`). Fechar a aba não perde nada, e o B3/B4 continuam o mesmo recurso. A alternativa (wizard só no front, submit no fim) perdia o progresso no reload e mandava até 90 MB numa requisição.

## Mapeamento antes da validação

O `trilha-b` listava "validar → confirmar mapeamento", mas o `validate` recebe o `column_mapping` dentro do config: sem saber qual coluna é a data e qual é o canal, não há como achar duplicata de (data, canal). A ordem é upload → mapeamento confirmado → validate. A sugestão de mapeamento sai da API (cabeçalho + apelidos em `suggest_mapping`), não do motor: é casamento de nomes, não matemática.

## 30 MB, não 200 MB

O protótipo aceitava 200 MB. O Cloud Run corta corpo de requisição HTTP/1 em 32 MiB, e o dado é agregado por dia e canal: 2 anos × 15 canais ≈ 11 mil linhas, menos de 1 MB. 30 MB é ~30× o arquivo real e cabe no Cloud Run sem signed URL.

## Storage local, endereçado por conteúdo

`api/storage.py` tem só `put` e `path` sobre `STORAGE_DIR`. O GCS entra no B11, quando houver bucket para testar; até lá uma implementação sem teste real seria só aparência. A chave `ws/{workspace_id}/sim/{simulation_id}/inputs/{sha256}.csv` dá rastreabilidade (o run do B4 guarda o sha256) e torna o re-upload idempotente. O blob substituído fica: quem apaga é a retenção do B9.

## Leitura do CSV

Encoding: o arquivo inteiro decodifica como `utf-8-sig`? senão `latin-1` (exports de BI brasileiros). Delimitador: o mais frequente de `,;\t|` na linha do cabeçalho. O `csv.Sniffer` foi descartado porque em arquivo com `;` e decimal com vírgula (`1.234,56`) a vírgula aparece em todas as linhas de dado e ele pode escolhê-la.

## `validate` falso até o A2

O `engine/` não existe ainda. `api/validation.py` segue a assinatura e o formato do contrato §2 e implementa só `duplicate_date_channel`, o suficiente para o aceite "duplicata bloqueia o Rodar" rodar fim a fim. Quando o A2 sair, o módulo vira `from engine import validate` e o fake é apagado. O formato de `inputs` (`{"investment_file", "performance_file", "generic_trends_file"}` → caminho) foi proposto ao dev A no `docs/m2/README.md` › contrato §2.

## O gate do Rodar é do B4

O B2 só devolve o report; as confirmações de warning ficam na tela. Quem recusa um run com `error` ou warning não confirmado é a criação do run no B4, no servidor.
```

Em `docs/decisoes/README.md`, adicione à tabela:

```markdown
| [upload-e-storage.md](upload-e-storage.md) | Simulação como rascunho, mapeamento antes do validate, limite de 30 MB, storage local por conteúdo, leitura do CSV, validate falso até o A2 |
```

- [ ] **Step 7: `docs/m2/trilha-b-plataforma.md` (item B2)**

Logo abaixo de `## B2 · Upload, armazenamento e validação — semana 2`, insira (com a data do dia no formato `dd/mmm/2026`, como no B1):

```markdown
- **Status:** 🟡 B2a (backend) feito em <dd/mmm/2026>, verificado por `tests/api/test_simulations.py` e `tests/api/test_rbac.py`. B2b (telas) pendente. Desvios em `docs/decisoes/upload-e-storage.md`.
```

Em **Fazer**, troque o item do `storage.py` por:

```markdown
  - `storage.py` com `put/path` sobre diretório local; GCS (`gs://bucket`) entra no B11.
```

Troque os passos 1–6 do **Fluxo** por:

```markdown
    1. criar a simulação (nome; alvo e KPI vêm no B3);
    2. subir investimento, performance e trends opcional;
    3. o analista confirma o mapeamento de colunas (sugerido pela API a partir do cabeçalho);
    4. a API chama `engine.validate` e devolve o `ValidationReport`;
    5. a tela mostra `error` (bloqueia), `warning` (checkbox de confirmação) e `info`;
    6. se houver colinearidade, a tela de agrupamento (A3) oferece agrupar ou bloquear por canal.
```

Troque `- Só CSV, ≤ 200 MB, nome sanitizado; nunca executar nada do arquivo.` por `- Só CSV, ≤ 30 MB (teto do Cloud Run), nome sanitizado; nunca executar nada do arquivo.`

- [ ] **Step 8: `docs/m2/README.md` › contrato §2**

Depois do parágrafo que começa com `` `level`: `error` bloqueia o run``, adicione:

```markdown
`inputs` (proposto pelo B2, a confirmar no spec do A2): `{"investment_file": Path, "performance_file": Path, "generic_trends_file": Path | None}`, as mesmas chaves do `column_mapping`. Até o A2 existir, a API usa um `validate` falso com a mesma assinatura (`api/validation.py`).
```

- [ ] **Step 9: `CLAUDE.md`**

No bloco **Estrutura**, troque a linha `  models.py       User, Workspace, Membership, UserSession` por `  models.py       User, Workspace, Membership, UserSession, Simulation, SimulationFile` e, abaixo de `  accounts.py …`, adicione:

```
  simulations.py  regra de negócio de simulações: upload, sugestão de mapeamento, validação
  storage.py      put/path sobre STORAGE_DIR (local; GCS no B11)
  csvfile.py      encoding, delimitador e cabeçalho de CSV
  validation.py   validate falso até o A2 (vira `from engine import validate`)
```

Troque `  routes/         routers finos (auth, members, admin)` por `  routes/         routers finos (auth, members, admin, simulations)`.

Em **Estado atual**, depois da frase do B1b, adicione: `**B2a (upload backend) concluído em <dd/mmm/2026>**: tabelas `simulations`/`simulation_files` (migration `0003`), upload de CSV ≤ 30 MB para storage local por conteúdo, sugestão e confirmação do mapeamento de colunas, `validate` falso (só `duplicate_date_channel`) até o A2.` e troque `Faltam, em ordem: B2–B4` por `Faltam, em ordem: B2b (telas do upload), B3–B4`.

Na tabela de áreas, adicione:

```markdown
| Simulação, upload, storage, validate | `docs/decisoes/upload-e-storage.md` |
```

- [ ] **Step 10: Verificação final e commit**

Run: `uv run ruff format --check . && uv run ruff check . && uv run pytest -q`
Expected: tudo verde.

```bash
git add .gitignore .dockerignore .env.example Dockerfile API-GUIDE.md DATABASE.md SECURITY.md CLAUDE.md docs/decisoes/upload-e-storage.md docs/decisoes/README.md docs/m2/trilha-b-plataforma.md docs/m2/README.md
git commit -m "docs: record b2a upload backend routes, tables and decisions"
```

---

## Ordem de execução

Sequencial: 1 → 2 → 3 → 4 → 5. As tasks 2–4 mexem nos mesmos arquivos (`api/simulations.py`, `api/routes/simulations.py`, `tests/api/test_rbac.py`); a 5 descreve o que 1–4 entregaram. Modelo sugerido: haiku para 1 e 5, sonnet para 2–4.
