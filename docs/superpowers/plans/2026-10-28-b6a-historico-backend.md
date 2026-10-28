# B6a · Histórico backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A API passa a listar os runs do workspace, expor config/inputs/publicação no `RunOut`, publicar e despublicar runs e servir o download das entradas de um run.

**Architecture:** Tudo cabe no que o B4 montou: `api/runs.py` (regra de negócio) e `api/routes/runs.py` (rotas finas). Sem migration: `runs.published_at` e `runs.published_by` existem desde a `0004`. O `Run` ganha a relationship `publisher`. Viewer continua filtrado por `runs.visible(ctx)`, e recurso de outro workspace é 404 pelo `find_run`.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2, pytest contra Postgres (`docker compose up -d`), `uv`.

Spec: `docs/superpowers/specs/2026-10-28-b6-historico-design.md` (seção B6a). Leia antes `API-GUIDE.md`, `CODE-STYLE.md` e `docs/decisoes/runs-e-jobs.md`.

---

## Arquivos

| Arquivo | Mudança |
|---|---|
| `api/models.py` | `Run.publisher` (relationship) |
| `api/runs.py` | `publish`, `unpublish`, `PUBLISHABLE`, `PUBLISH_ERROR` |
| `api/routes/runs.py` | `RunOut` com campos novos; `GET /runs`; `POST …/publish`, `POST …/unpublish`; `GET …/inputs/{key}` |
| `tests/api/test_runs.py` | testes das rotas novas |
| `tests/api/test_rbac.py` | quatro linhas novas na matriz |
| `API-GUIDE.md`, `docs/decisoes/runs-e-jobs.md`, `docs/m2/trilha-b-plataforma.md`, `CLAUDE.md` | fechamento |

Antes de começar: `docker compose up -d` e `uv run pytest -q` verde.

---

### Task 1: `RunOut` com config, inputs e publicação

**Files:**
- Modify: `api/models.py` (classe `Run`, perto de `creator`)
- Modify: `api/routes/runs.py` (`RunOut`, `run_out`, `list_runs`)
- Test: `tests/api/test_runs.py`

- [ ] **Step 1: Write the failing test**

Em `tests/api/test_runs.py`, logo depois de `test_create_run_snapshots_config_and_inputs_and_launches`:

```python
def test_run_out_carries_the_snapshot_and_the_publication(logged, ready, db, analyst):
    run = runs.create(db, ready(), set(), by=analyst)

    body = logged.get(f"/api/w/a/runs/{run.id}").json()

    assert body["config"]["column_mapping"] == MAPPING
    assert body["inputs"]["investment_file"]["filename"] == "investment.csv"
    assert body["inputs"]["generic_trends_file"] is None
    assert (body["published_at"], body["published_by_name"]) == (None, None)

    run.published_at, run.published_by = func.now(), analyst.id
    db.commit()
    body = logged.get(f"/api/w/a/runs/{run.id}").json()
    assert body["published_at"] is not None and body["published_by_name"] == "ana"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_runs.py::test_run_out_carries_the_snapshot_and_the_publication -q`
Expected: FAIL com `KeyError: 'config'`

- [ ] **Step 3: Write minimal implementation**

`api/models.py`, na classe `Run`, troque as duas relationships do fim por:

```python
    creator: Mapped[User] = relationship(foreign_keys=[created_by])
    publisher: Mapped[User | None] = relationship(foreign_keys=[published_by])
    simulation: Mapped[Simulation] = relationship()
```

`api/routes/runs.py`, `RunOut` e `run_out`:

```python
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
    config: dict
    inputs: dict
    published_at: datetime | None
    published_by_name: str | None


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
        config=r.config,
        inputs=r.inputs,
        published_at=r.published_at,
        published_by_name=r.publisher.name if r.publisher else None,
    )
```

Em `list_runs` (runs da simulação), carregue o `publisher` junto para não fazer N+1:

```python
        .options(joinedload(Run.creator), joinedload(Run.publisher), joinedload(Run.simulation))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_runs.py -q`
Expected: PASS (todos)

- [ ] **Step 5: Commit**

```bash
git add api/models.py api/routes/runs.py tests/api/test_runs.py
git commit -m "feat(api): expose config, inputs and publication on runout"
```

---

### Task 2: `GET /api/w/{slug}/runs` (histórico do workspace)

**Files:**
- Modify: `api/routes/runs.py` (constante e rota nova, depois de `list_runs`)
- Test: `tests/api/test_runs.py`, `tests/api/test_rbac.py`

- [ ] **Step 1: Write the failing tests**

Em `tests/api/test_runs.py`, depois de `test_simulation_runs_newest_first`:

```python
def test_workspace_runs_list_every_simulation_newest_first_and_stay_in_the_workspace(
    logged, ready, db, analyst, make_user, make_workspace
):
    old = runs.create(db, ready(), set(), by=analyst)
    new = runs.create(db, ready(), set(), by=analyst)
    other = make_workspace("b", [(make_user("bo@x.com"), "analyst")])
    runs.create(db, ready(workspace=other), set(), by=analyst)

    body = logged.get("/api/w/a/runs").json()

    assert [r["id"] for r in body] == [new.id, old.id]
    assert body[0]["config"]["column_mapping"] == MAPPING


def test_workspace_runs_fail_stale_runs_before_listing(logged, ready, db, analyst):
    run = runs.create(db, ready(), set(), by=analyst)
    make_stale(db, run.id)

    body = logged.get("/api/w/a/runs").json()

    assert (body[0]["status"], body[0]["error"]) == ("failed", runs.STALE_ERROR)
```

`make_stale` já existe no arquivo (definido antes de `test_a_run_active_for_over_20_minutes…`); a função nova precisa vir depois dela.

Em `tests/api/test_rbac.py`, no dicionário `ROUTES`, depois de `("GET", "/api/w/{slug}/runs/{run_id}/logs/stream")`:

```python
    ("GET", "/api/w/{slug}/runs"): ("viewer", 200, None),
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_runs.py -k workspace_runs tests/api/test_rbac.py -q`
Expected: FAIL (404 na rota, e a matriz acusa rota faltando)

- [ ] **Step 3: Write minimal implementation**

`api/routes/runs.py`, junto das outras constantes do topo:

```python
# ponytail: the history filters run in the browser over the newest 500; past that, move them to query params
HISTORY_LIMIT = 500
```

E a rota, logo depois de `list_runs`:

```python
@router.get("/runs", response_model=list[RunOut])
def list_workspace_runs(ctx: Ctx = Depends(viewer), db: Session = Depends(get_db)):
    runs.fail_stale(db, Run.workspace_id == ctx.workspace.id)
    rows = db.scalars(
        select(Run)
        .options(joinedload(Run.creator), joinedload(Run.publisher), joinedload(Run.simulation))
        .where(*runs.visible(ctx))
        .order_by(Run.id.desc())
        .limit(HISTORY_LIMIT)
    )
    return [run_out(r) for r in rows]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_runs.py tests/api/test_rbac.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/routes/runs.py tests/api/test_runs.py tests/api/test_rbac.py
git commit -m "feat(api): list the workspace runs for the history page"
```

---

### Task 3: publicar e despublicar

**Files:**
- Modify: `api/runs.py` (constantes no topo e duas funções no fim)
- Modify: `api/routes/runs.py` (duas rotas, depois de `get_run`)
- Test: `tests/api/test_runs.py`, `tests/api/test_rbac.py`

- [ ] **Step 1: Write the failing tests**

Em `tests/api/test_runs.py`, depois de `test_viewer_does_not_see_unpublished_runs`:

```python
def finished(db, simulation, analyst, status="succeeded"):
    run = runs.create(db, simulation, set(), by=analyst)
    run.status = status
    db.commit()
    return run


def test_publishing_shows_the_run_to_viewers_until_unpublished(
    logged, make_client, ready, db, ws, analyst, make_user, login_as
):
    run = finished(db, ready(), analyst)
    viewer = make_user("vi@x.com")
    db.add(Membership(user_id=viewer.id, workspace_id=ws.id, role="viewer"))
    db.commit()
    viewer_client = make_client()
    login_as(viewer_client, viewer)
    assert viewer_client.get("/api/w/a/runs").json() == []

    published = logged.post(f"/api/w/a/runs/{run.id}/publish")

    assert published.status_code == 200, published.text
    assert published.json()["published_by_name"] == "ana" and published.json()["published_at"] is not None
    assert [r["id"] for r in viewer_client.get("/api/w/a/runs").json()] == [run.id]

    unpublished = logged.post(f"/api/w/a/runs/{run.id}/unpublish")

    assert unpublished.status_code == 200
    assert (unpublished.json()["published_at"], unpublished.json()["published_by_name"]) == (None, None)
    assert viewer_client.get("/api/w/a/runs").json() == []
    assert viewer_client.get(f"/api/w/a/runs/{run.id}").status_code == 404


@pytest.mark.parametrize("status", ["queued", "running", "failed"])
def test_only_finished_runs_can_be_published(logged, ready, db, analyst, status):
    run = finished(db, ready(), analyst, status)

    r = logged.post(f"/api/w/a/runs/{run.id}/publish")

    assert (r.status_code, r.json()["detail"]) == (409, "Só execuções concluídas podem ser publicadas.")
    db.refresh(run)
    assert run.published_at is None


@pytest.mark.parametrize("status", ["succeeded", "inconclusive"])
def test_succeeded_and_inconclusive_runs_can_be_published(logged, ready, db, analyst, status):
    run = finished(db, ready(), analyst, status)

    assert logged.post(f"/api/w/a/runs/{run.id}/publish").status_code == 200


def test_publishing_again_records_the_new_publisher(logged, make_client, ready, db, ws, analyst, make_user, login_as):
    run = finished(db, ready(), analyst)
    logged.post(f"/api/w/a/runs/{run.id}/publish")
    other = make_user("bia@x.com")
    db.add(Membership(user_id=other.id, workspace_id=ws.id, role="analyst"))
    db.commit()
    other_client = make_client()
    login_as(other_client, other)

    body = other_client.post(f"/api/w/a/runs/{run.id}/publish").json()

    assert body["published_by_name"] == "bia"


def test_unpublishing_a_run_never_published_is_a_no_op(logged, ready, db, analyst):
    run = finished(db, ready(), analyst)

    r = logged.post(f"/api/w/a/runs/{run.id}/unpublish")

    assert (r.status_code, r.json()["published_at"]) == (200, None)
```

Em `tests/api/test_rbac.py`, em `ROUTES`, depois da linha de `GET /api/w/{slug}/runs`:

```python
    ("POST", "/api/w/{slug}/runs/{run_id}/publish"): ("analyst", 200, None),
    ("POST", "/api/w/{slug}/runs/{run_id}/unpublish"): ("analyst", 200, None),
```

(o run do fixture `env` já é `succeeded` e publicado, então publicar de novo e despublicar dão 200)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_runs.py -k publish tests/api/test_rbac.py -q`
Expected: FAIL (404/405 nas rotas novas)

- [ ] **Step 3: Write minimal implementation**

`api/runs.py`, junto das constantes do topo:

```python
PUBLISHABLE = ("succeeded", "inconclusive")
PUBLISH_ERROR = "Só execuções concluídas podem ser publicadas."
```

E no fim do arquivo:

```python
def publish(db: Session, run: Run, by: User) -> None:
    # the engine already marks what failed a gate; this is the analyst's review before viewers see it
    if run.status not in PUBLISHABLE:
        raise Blocked(PUBLISH_ERROR)
    run.published_at, run.published_by = func.now(), by.id
    db.commit()
    log.info("run.published run_id=%s workspace_id=%s by=%s", run.id, run.workspace_id, by.id)


def unpublish(db: Session, run: Run, by: User) -> None:
    run.published_at, run.published_by = None, None
    db.commit()
    log.info("run.unpublished run_id=%s workspace_id=%s by=%s", run.id, run.workspace_id, by.id)
```

`api/routes/runs.py`, depois de `get_run`:

```python
@router.post("/runs/{run_id}/publish", response_model=RunOut)
def publish_run(run_id: RunId, ctx: Ctx = Depends(analyst), db: Session = Depends(get_db)):
    run = find_run(db, ctx, run_id)
    try:
        runs.publish(db, run, by=ctx.user)
    except runs.Blocked as e:
        raise HTTPException(409, str(e))
    return run_out(run)


@router.post("/runs/{run_id}/unpublish", response_model=RunOut)
def unpublish_run(run_id: RunId, ctx: Ctx = Depends(analyst), db: Session = Depends(get_db)):
    run = find_run(db, ctx, run_id)
    runs.unpublish(db, run, by=ctx.user)
    return run_out(run)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_runs.py tests/api/test_rbac.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add api/runs.py api/routes/runs.py tests/api/test_runs.py tests/api/test_rbac.py
git commit -m "feat(api): publish and unpublish finished runs"
```

---

### Task 4: download das entradas do run

**Files:**
- Modify: `api/routes/runs.py` (imports, tipo `InputKey`, rota nova)
- Test: `tests/api/test_runs.py`, `tests/api/test_rbac.py`

- [ ] **Step 1: Write the failing tests**

Em `tests/api/test_runs.py`, depois dos testes de publicação:

```python
def test_input_download_serves_the_snapshot_even_after_a_new_upload(logged, ready, db, analyst):
    simulation = ready()
    run = runs.create(db, simulation, set(), by=analyst)
    simulations.save_file(db, simulation, "investment", io.BytesIO(DUPLICATE), "novo.csv", by=analyst)

    r = logged.get(f"/api/w/a/runs/{run.id}/inputs/investment_file")

    assert r.status_code == 200
    assert r.content == INVESTMENT
    assert r.headers["content-type"].startswith("text/csv")
    assert 'filename="investment.csv"' in r.headers["content-disposition"]


def test_input_download_of_a_missing_or_unknown_input(logged, ready, db, analyst):
    run = runs.create(db, ready(), set(), by=analyst)

    assert logged.get(f"/api/w/a/runs/{run.id}/inputs/generic_trends_file").status_code == 404
    assert logged.get(f"/api/w/a/runs/{run.id}/inputs/senhas").status_code == 422


def test_history_routes_hide_runs_of_another_workspace(logged, ready, db, analyst, make_user, make_workspace):
    other = make_workspace("b", [(make_user("bo@x.com"), "analyst")])
    run = finished(db, ready(workspace=other), analyst)

    for method, path in [
        ("POST", f"/api/w/a/runs/{run.id}/publish"),
        ("POST", f"/api/w/a/runs/{run.id}/unpublish"),
        ("GET", f"/api/w/a/runs/{run.id}/inputs/investment_file"),
        ("POST", f"/api/w/b/runs/{run.id}/publish"),
    ]:
        assert logged.request(method, path).status_code == 404, (method, path)
```

No topo do arquivo, acrescente `import io` aos imports da stdlib (`import io` entre `import json` e `import logging`).

Em `tests/api/test_rbac.py`, em `ROUTES`, depois das linhas de publish/unpublish:

```python
    ("GET", "/api/w/{slug}/runs/{run_id}/inputs/{key}"): ("analyst", 200, None),
```

E no `template.format(...)` de `test_role_matrix`, acrescente `key="investment_file",` depois de `kind="investment",`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_runs.py -k "input or another_workspace" tests/api/test_rbac.py -q`
Expected: FAIL (rota não existe)

- [ ] **Step 3: Write minimal implementation**

`api/routes/runs.py`, imports:

```python
from typing import Annotated, Literal

from fastapi.responses import FileResponse, StreamingResponse

from api import runs, simulations, storage
```

(mantenha os demais imports; `FileResponse` entra na linha do `StreamingResponse` já existente, e `simulations, storage` na linha do `from api import runs`)

Depois de `HISTORY_LIMIT`:

```python
InputKey = Literal["investment_file", "performance_file", "generic_trends_file"]
```

E a rota, depois de `unpublish_run`:

```python
@router.get("/runs/{run_id}/inputs/{key}")
def download_input(run_id: RunId, key: InputKey, ctx: Ctx = Depends(analyst), db: Session = Depends(get_db)):
    # viewers see the published result, never the client's raw csv
    run = find_run(db, ctx, run_id)
    entry = run.inputs.get(key)
    if entry is None:
        raise HTTPException(404)
    path = storage.path(simulations.input_key(run.workspace_id, run.simulation_id, entry["sha256"]))
    return FileResponse(path, media_type="text/csv", filename=entry["filename"])
```

O storage é por conteúdo (`…/inputs/<sha256>.csv`), então trocar o arquivo da simulação não apaga o do run.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest -q`
Expected: PASS (suíte inteira)

- [ ] **Step 5: Lint**

Run: `uv run ruff format --check . && uv run ruff check .`
Expected: sem erros (rode `uv run ruff format .` se o format acusar)

- [ ] **Step 6: Commit**

```bash
git add api/routes/runs.py tests/api/test_runs.py tests/api/test_rbac.py
git commit -m "feat(api): download the inputs a run used"
```

---

### Task 5: fechamento (docs)

**Files:**
- Modify: `API-GUIDE.md`, `docs/decisoes/runs-e-jobs.md`, `docs/m2/trilha-b-plataforma.md`, `CLAUDE.md`

- [ ] **Step 1: `API-GUIDE.md`**

Na tabela de endpoints, troque a linha de `GET /api/w/{slug}/runs/{run_id}` por:

```markdown
| GET | `/api/w/{slug}/runs` | Viewer+ (viewer só vê publicados). Até 500 `RunOut` do workspace, mais recente primeiro; os filtros do histórico rodam no front |
| GET | `/api/w/{slug}/runs/{run_id}` | Viewer+ (viewer só vê publicado; senão 404). `RunOut`: `{id, status, simulation: {id, name}, created_by_name, created_at, started_at, finished_at, error, summary, engine_version, config, inputs: {investment_file\|performance_file\|generic_trends_file: {filename, sha256} \| null}, published_at, published_by_name}` |
| POST | `/api/w/{slug}/runs/{run_id}/publish` | Analyst+. → `RunOut`; só `succeeded`/`inconclusive`, senão 409 "Só execuções concluídas podem ser publicadas."; publicar de novo atualiza `published_at/by` |
| POST | `/api/w/{slug}/runs/{run_id}/unpublish` | Analyst+. → `RunOut`; idempotente |
| GET | `/api/w/{slug}/runs/{run_id}/inputs/{key}` | Analyst+. `key` ∈ `investment_file`, `performance_file`, `generic_trends_file` (outro → 422). CSV do snapshot do run, como anexo com o nome do upload; entrada ausente → 404 |
```

- [ ] **Step 2: `docs/decisoes/runs-e-jobs.md`**

Substitua a seção `## Viewer e publicação` inteira por:

```markdown
## Histórico e publicação (B6)

Spec: `docs/superpowers/specs/2026-10-28-b6-historico-design.md`.

- **Publicar é revisão humana, não gate.** Os gates são do motor e vêm marcados no `results.json`; o analista só decide quando o viewer passa a ver o run. Só `succeeded` e `inconclusive` podem ser publicados (o inconclusivo mostra o experiment design, que interessa ao viewer). Publicar de novo atualiza quem e quando; despublicar é idempotente. Viewer só enxerga run com `published_at`, e o resto é 404, como recurso de outro workspace.
- **Filtros no front, sobre os últimos 500 runs.** `GET …/runs` devolve até 500 `RunOut`; busca, status, autor e período rodam na tela. Sem endpoint de autores e sem paginação. Passando de 500 runs por workspace, os mais antigos somem da busca: a saída é mover os filtros para query params (marcado com `ponytail:` na rota).
- **Download das entradas só para analyst+.** O viewer vê o resultado publicado, não o CSV bruto do cliente. O storage é por conteúdo, então o arquivo do snapshot continua lá depois de a simulação trocar o arquivo.
- **"Rodar de novo" restaura na simulação.** O front faz `PUT …/params` com o `config` do run e leva à simulação; o gate da B4 continua sendo o único caminho para criar run. Os arquivos são os atuais da simulação.
- **Fora até o A1:** comparar runs lado a lado e colunas de métricas do `summary` (hoje ele só repete o status). **Fora até haver dataset anonimizado e motor real:** o modo demo.
```

- [ ] **Step 3: `docs/m2/trilha-b-plataforma.md`**

Em `## B6 · Histórico de simulações — semana 3`, logo abaixo do título, acrescente:

```markdown
- **Status:** 🟡 em andamento. B6a (backend) em <data de hoje>, verificado por `tests/api/test_runs.py` (histórico do workspace, publicar/despublicar, 409 de run não concluído, download do snapshot, isolamento entre workspaces) e `tests/api/test_rbac.py`. Falta o B6b (telas). Fora: comparar runs (até o A1 trazer métricas no `summary`) e modo demo (até haver dataset anonimizado e motor real). Desvios em `docs/decisoes/runs-e-jobs.md`.
```

Troque `<data de hoje>` pela data real no formato `28/out/2026`.

- [ ] **Step 4: `CLAUDE.md`**

No parágrafo "Estado atual", depois da frase do B4b, acrescente:

```markdown
**B6a (histórico backend) concluído em <data de hoje>**: `GET …/runs` do workspace (até 500, filtros no front), `RunOut` com config, inputs e publicação, publicar/despublicar (só run concluído), download das entradas do snapshot (analyst+).
```

E troque "Faltam, em ordem: B5–B9" por "B5 bloqueado nos fixtures do A1 e no `scenario` do A8. Faltam: B6b, B7–B9".

- [ ] **Step 5: Commit**

```bash
git add API-GUIDE.md docs/decisoes/runs-e-jobs.md docs/m2/trilha-b-plataforma.md CLAUDE.md
git commit -m "docs: record the b6a history backend"
```
