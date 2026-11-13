# Pontos de trava (pós-Etapa 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fechar os pontos de trava que o workflow de auditoria de 12/nov/2026 confirmou, com prioridade para o worker morto que deixa o run em "Rodando" por até 20 min.

**Architecture:** Correções pequenas e independentes. Lado da API (Track A, sequencial): reaper do subprocesso, código de saída do watchdog, sessão do worker, limite de concorrência. Lado do motor (Track B, paralelo entre si): pré-período do causal, VIF, `max_budget_step`, prazo das narrativas, SLSQP da curva, fallback do LassoCV. Infra/front (Track C): graceful shutdown e SSE em aba escondida. Docs e goldens no fim.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2, scipy, statsmodels, React 19 (TanStack). `uv` e `bun`.

**Contexto obrigatório:** branch `fix/mmm-etapa2-trava` (já tem o fix da Etapa 2). Testes de `tests/api` precisam do Postgres (`docker compose up -d`). Os de `tests/engine` não. Rodar sempre com `uv run pytest ...`. Commits em pt-br, conventional, minúsculos, terminando com a linha `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. **Não** edite `docs/` nas tasks 1–10: a Task 11 faz todos os docs (evita conflito entre tasks paralelas).

**Paralelismo:** Tasks 1→2 em sequência (mesmos arquivos de teste da API). Tasks 3, 4, 5, 6, 7, 8 em paralelo entre si e com a Track A (arquivos disjuntos; a Task 6 só lê a variável de ambiente que a Task 1 define). Task 9 e 10 em paralelo com tudo. Task 11 depois de todas. Task 12 (goldens) por último, feita pelo coordenador.

---

### Task 1: Reaper do worker, saída de timeout e sessão do worker (PRIORIDADE)

Hoje `launcher.launch` dispara o `Popen` e esquece. Worker morto (OOM, crash, restart, watchdog) deixa o run `queued`/`running` até o `fail_stale` de 20 min, com "A execução parou de responder." genérico.

**Files:**
- Modify: `api/launcher.py`
- Modify: `api/worker.py` (watchdog, `on_log`, `__main__`)
- Test: `tests/api/test_worker_process.py`, `tests/api/test_runs.py` (só o teste do on_log, no fim do arquivo)

- [ ] **Step 1: testes que falham** — em `tests/api/test_worker_process.py`, troque o teste do launch e o do watchdog e acrescente os do reaper:

```python
import subprocess
import sys
import threading
from contextlib import nullcontext
from types import SimpleNamespace

from sqlalchemy import select

from api import launcher, worker
from api.launcher import launch  # the real one: the autouse `launched` fixture patches the module attribute later
from api.models import Run, RunLog


def test_launch_pins_blas_to_one_thread_and_keeps_the_llm_setting(monkeypatch):
    calls, reaped = [], []
    proc = SimpleNamespace(wait=lambda: 0)
    monkeypatch.setattr("subprocess.Popen", lambda args, **kw: calls.append((args, kw)) or proc)
    monkeypatch.setattr(launcher, "reap", lambda p, run_id: reaped.append((p, run_id)))
    monkeypatch.setenv("SOMETHING_ELSE", "kept")
    monkeypatch.setenv("LLM_PROVIDER", "gemini")

    launch(7)

    ((args, kw),) = calls
    assert args[-3:] == ["-m", "api.worker", "7"]
    env = kw["env"]
    assert env["OMP_NUM_THREADS"] == env["OPENBLAS_NUM_THREADS"] == env["MKL_NUM_THREADS"] == "1"
    assert env["OPENBLAS_CORETYPE"] == "Haswell"
    assert "X86_V4" in env["NPY_DISABLE_CPU_FEATURES"].split()
    assert env["LLM_PROVIDER"] == "gemini"  # A9: the narratives are grounded, so the worker may call the LLM
    assert env["SOMETHING_ELSE"] == "kept"
    # Windows dev: uvicorn --reload sends Ctrl+C to its process group; the worker must not be in it
    expected = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    assert kw["creationflags"] == expected
    for _ in range(100):
        if reaped:
            break
        threading.Event().wait(0.01)
    assert reaped == [(proc, 7)]


def test_watchdog_exits_the_worker_with_the_timeout_code():
    exited = threading.Event()
    codes = []

    worker.watchdog(0.01, exit=lambda code: (codes.append(code), exited.set()))

    assert exited.wait(2)
    assert codes == [launcher.TIMEOUT_EXIT]
```

E no fim de `tests/api/test_runs.py` (usa as fixtures `db`, `ready`, `analyst` do próprio arquivo):

```python
def _reap(db, monkeypatch, run_id, code):
    monkeypatch.setattr(launcher, "SessionLocal", lambda: nullcontext(db))
    launcher.reap(SimpleNamespace(wait=lambda: code), run_id)
    return db.get(Run, run_id)


@pytest.mark.parametrize(
    ("code", "error"), [(launcher.TIMEOUT_EXIT, launcher.TIMEOUT_ERROR), (1, launcher.CRASH_ERROR), (-9, launcher.CRASH_ERROR)]
)
def test_a_dead_worker_fails_its_run_at_once(db, ready, analyst, monkeypatch, code, error):
    run = runs.create(db, ready(), set(), by=analyst)

    run = _reap(db, monkeypatch, run.id, code)

    db.refresh(run)
    assert (run.status, run.error) == ("failed", error) and run.finished_at is not None
    assert messages(db, run.id)[-1] == error


def test_a_worker_that_exits_cleanly_leaves_the_run_alone(db, ready, analyst, monkeypatch):
    run = runs.create(db, ready(), set(), by=analyst)

    run = _reap(db, monkeypatch, run.id, 0)

    db.refresh(run)
    assert run.status == "queued" and messages(db, run.id) == []


def test_the_reaper_never_overwrites_a_finished_run(db, ready, analyst, monkeypatch):
    run = runs.create(db, ready(), set(), by=analyst)
    worker.execute(db, run.id)

    run = _reap(db, monkeypatch, run.id, 1)

    db.refresh(run)
    assert run.status == "succeeded" and launcher.CRASH_ERROR not in messages(db, run.id)


def test_a_failed_log_commit_does_not_lose_the_run(db, ready, analyst, monkeypatch):
    run = runs.create(db, ready(), set(), by=analyst)
    fake_engine, real_commit = engine_run.run, db.commit

    def poisoned_commit():
        db.execute(text("SELECT 1/0"))  # a real database error: the transaction is aborted until a rollback

    def engine(inputs, config, out, on_log):
        monkeypatch.setattr(db, "commit", poisoned_commit)
        try:
            on_log("info", "linha")
        except Exception:  # engine/logmessages.OnLogHandler swallows a failing on_log and the engine goes on
            pass
        monkeypatch.setattr(db, "commit", real_commit)
        return fake_engine(inputs, config, out, lambda level, message: None)

    monkeypatch.setattr(engine_run, "run", engine)

    worker.execute(db, run.id)

    db.refresh(run)
    assert run.status == "succeeded" and run.finished_at is not None
```

Acrescente aos imports de `tests/api/test_runs.py`: `from contextlib import nullcontext`, `from types import SimpleNamespace` e `text` em `from sqlalchemy import func, select, text, update` (`launcher`, `worker`, `runs`, `engine_run`, `Run` já estão importados; `messages` já existe no arquivo, linha ~447). No código antigo o `on_log` não faz rollback: a sessão fica abortada e o UPDATE final do worker levanta, deixando o run em `running` — é essa a falha esperada no Step 2.

- [ ] **Step 2: rodar e ver falhar**

Run: `uv run pytest tests/api/test_worker_process.py tests/api/test_runs.py -q -k "reap or dead_worker or cleanly or launch_pins or timeout_code or log_commit"`
Expected: FAIL (`AttributeError: module 'api.launcher' has no attribute 'reap'` / `TIMEOUT_EXIT`; o do log_commit falha porque a sessão envenenada perde o status final).

- [ ] **Step 3: implementar** — `api/launcher.py` inteiro:

```python
import logging
import os
import subprocess
import sys
import threading

from sqlalchemy import func, update

from api.db import SessionLocal
from api.models import ACTIVE_RUN_STATUSES, Run, RunLog

log = logging.getLogger(__name__)

WORKER_ENV = {
    # the models are small: multithreaded BLAS only fights itself (~99 s vs ~40 s) and changes the numbers
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    # the MMM fit is ill-conditioned: the BLAS kernel and numpy's SIMD path move the optimum, so every CPU takes the AVX2 one
    # (same pins in mise.toml and ci.yml; docs/decisoes/engine.md, "Paridade")
    "OPENBLAS_CORETYPE": "Haswell",
    "NPY_DISABLE_CPU_FEATURES": "X86_V4 AVX512_ICL AVX512_SPR",
}
TIMEOUT_EXIT = 3  # the worker's watchdog (api/worker.py)
TIMEOUT_ERROR = (
    "A execução passou do limite de 20 minutos e foi interrompida. Agrupe canais ou encurte o período e rode de novo."
)
CRASH_ERROR = "A execução foi interrompida antes de terminar."


def launch(run_id: int) -> None:
    # ponytail: subprocess on the same server, also in production (no GCP); a queue if runs ever contend for CPU
    # Windows dev: uvicorn --reload sends Ctrl+C to its process group, which killed the worker silently
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    proc = subprocess.Popen(
        [sys.executable, "-m", "api.worker", str(run_id)], env={**os.environ, **WORKER_ENV}, creationflags=flags
    )
    threading.Thread(target=reap, args=(proc, run_id), daemon=True).start()


def reap(proc, run_id: int) -> None:
    """Waits for the worker (also reaping the zombie) and fails its run at once when it died: OOM, crash, watchdog.
    Exit 0 means the worker wrote the final status itself, or skipped a run that was not queued. If the API restarts
    first, this thread dies with it and the 20-min fail_stale is the net."""
    code = proc.wait()
    if code == 0:
        return
    error = TIMEOUT_ERROR if code == TIMEOUT_EXIT else CRASH_ERROR
    with SessionLocal() as db:
        failed = db.execute(
            update(Run)
            .where(Run.id == run_id, Run.status.in_(ACTIVE_RUN_STATUSES))
            .values(status="failed", error=error, finished_at=func.now())
        ).rowcount
        if failed:
            db.add(RunLog(run_id=run_id, level="error", message=error))
        db.commit()
    log.warning("run.worker_died run_id=%s exit=%s failed=%s", run_id, code, bool(failed))
```

Em `api/worker.py`:

1. Import: `from api.launcher import TIMEOUT_EXIT` e `import time`.
2. `on_log`:

```python
    def on_log(level: str, message: str) -> None:
        # ponytail: one insert per line keeps the "running for N s" honest; batch if the engine gets chatty
        try:
            db.add(RunLog(run_id=rid, level=level, message=message))
            db.commit()
        except Exception:
            # a failed commit poisons the session: without the rollback the final status update fails too and the
            # run stays 'running'. The engine's log handler swallows the raise, so the run goes on.
            db.rollback()
            raise
```

3. `watchdog`: troque `exit(1)` por `exit(TIMEOUT_EXIT)` e a docstring por `"""Kill the worker past the deadline with TIMEOUT_EXIT, which the launcher's reaper turns into a timeout error."""`.
4. Em `if __name__ == "__main__":`, logo antes de `watchdog(...)`:

```python
    # the engine's narratives read it to stop calling the LLM before the watchdog fires (engine/narratives.py)
    os.environ["RUN_DEADLINE"] = str(time.time() + STALE_AFTER.total_seconds())
```

- [ ] **Step 4: rodar e ver passar**

Run: `uv run pytest tests/api/test_worker_process.py tests/api/test_runs.py -q`
Expected: PASS (todos).

- [ ] **Step 5: lint e commit**

```bash
uv run ruff check api tests/api && uv run ruff format api tests/api
git add api/launcher.py api/worker.py tests/api/test_worker_process.py tests/api/test_runs.py
git commit -m "fix(api): reaper falha o run assim que o worker morre" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Limite de runs simultâneos e conexão livre durante o SGS

Sem limite, vários runs pesados dividem os núcleos e passam do watchdog de 20 min (relógio de parede). E o `POST /runs` segura a conexão da request (transação aberta) durante as chamadas HTTP ao Banco Central.

**Files:**
- Modify: `api/runs.py` (`create`, `snapshot_bcb`, constantes)
- Modify: `tests/conftest.py` (fixture autouse)
- Test: `tests/api/test_runs.py`

- [ ] **Step 0: fixture** — em `tests/conftest.py`, junto das outras autouse, para o padrão (núcleos − 1, que é 1 num CI de 2 núcleos) não quebrar os testes que criam vários runs ativos:

```python
@pytest.fixture(autouse=True)
def roomy_server(monkeypatch):
    # the cap defaults to cpu_count - 1: 1 on a 2-core CI box, and many tests keep several runs active
    monkeypatch.setenv("MAX_CONCURRENT_RUNS", "100")
```

- [ ] **Step 1: testes que falham** — no fim de `tests/api/test_runs.py`:

```python
def test_the_server_refuses_a_run_past_the_concurrency_cap(logged, ready, db, monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_RUNS", "1")
    first = post_run(logged, ready())

    second = post_run(logged, ready())

    assert first.status_code == 201
    assert (second.status_code, second.json()["detail"]) == (409, runs.BUSY_ERROR)


def test_a_stale_run_elsewhere_does_not_hold_a_slot(logged, ready, db, monkeypatch):
    monkeypatch.setenv("MAX_CONCURRENT_RUNS", "1")
    make_stale(db, post_run(logged, ready()).json()["id"])

    assert post_run(logged, ready()).status_code == 201


def test_the_sgs_is_called_with_no_transaction_open(logged, ready, db, monkeypatch):
    seen = []
    monkeypatch.setattr(bcb, "fetch", lambda controls: seen.append(db.in_transaction()) or BCB_CSV)
    simulation = ready()
    simulations.save_params(db, simulation, {**PARAMS, "controls": ["bcb_ipca"]})

    assert post_run(logged, simulation).status_code == 201
    assert seen == [False]
```

Nota sobre `db.in_transaction()`: a fixture `db` usa `join_transaction_mode="create_savepoint"`; depois de `rollback()`/`commit()` a sessão não tem transação própria até a próxima query. Se o teste não conseguir distinguir no modo savepoint (ex.: `in_transaction()` sempre `True`), troque a asserção por `assert db.get_transaction() is None` e registre no relatório o que observou.

- [ ] **Step 2: rodar e ver falhar**

Run: `uv run pytest tests/api/test_runs.py -q -k "concurrency_cap or stale_run_elsewhere or no_transaction"`
Expected: FAIL (`AttributeError: BUSY_ERROR`; o do SGS vê `True`).

- [ ] **Step 3: implementar** em `api/runs.py`:

Imports: acrescente `import os` e `select` em `from sqlalchemy import func, select, update`.

Constante, junto das outras mensagens:

```python
BUSY_ERROR = "Há muitas execuções em andamento no servidor. Tente de novo em alguns minutos."


def max_concurrent_runs() -> int:
    # ponytail: soft cap without a lock (two requests can both pass); a queue if contention gets real
    return int(os.environ.get("MAX_CONCURRENT_RUNS") or max(1, (os.cpu_count() or 2) - 1))
```

`snapshot_bcb` passa a receber os dados já lidos (não toca na sessão durante o HTTP):

```python
def snapshot_bcb(controls: list[str], workspace_id: int, simulation_id: int) -> dict | None:
    """The Banco Central series the analyst asked for, stored like an upload; raises bcb.Unavailable."""
    if not controls:
        return None
    content = bcb.fetch(controls)
    sha256 = hashlib.sha256(content).hexdigest()
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / "bcb.csv"
        local.write_bytes(content)
        storage.put(simulations.input_key(workspace_id, simulation_id, sha256), local)
    return {"sha256": sha256, "filename": "bcb.csv"}
```

E em `create`, troque as linhas de `fetched_controls`/`snapshot_bcb`/`fail_stale` por:

```python
    fetched_controls = list(simulation.config.get("controls") or [])
    workspace_id, simulation_id = simulation.workspace_id, simulation.id
    db.rollback()  # no transaction (and no pooled connection) held during the HTTP calls
    bcb_file = snapshot_bcb(fetched_controls, workspace_id, simulation_id)
    fail_stale(db)  # every workspace: a dead run elsewhere must not hold a server slot
    simulations.lock(db, simulation)
    reason = block_reason(simulation, confirmed)
    if reason:
        raise Blocked(reason)
    if (simulation.config.get("controls") or []) != fetched_controls:
        raise Blocked("Os parâmetros mudaram enquanto as séries do Banco Central eram buscadas. Rode de novo.")
    # server capacity, not a workspace resource: the one query here that counts across workspaces
    if db.scalar(select(func.count()).select_from(Run).where(Run.status.in_(ACTIVE))) >= max_concurrent_runs():
        raise Blocked(BUSY_ERROR)
```

(o `fail_stale(db, Run.simulation_id == simulation.id)` antigo some: o novo `fail_stale(db)` cobre essa simulação também.) Procure outros chamadores de `snapshot_bcb` com `grep -rn snapshot_bcb api tests` e ajuste a assinatura.

- [ ] **Step 4: rodar e ver passar**

Run: `uv run pytest tests/api -q`
Expected: PASS.

- [ ] **Step 5: commit**

```bash
uv run ruff check api tests/api && uv run ruff format api tests/api
git add api/runs.py tests/api/test_runs.py tests/conftest.py
git commit -m "fix(api): limite de runs simultâneos e sgs fora da transação" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Pré-período do causal limitado a 365 linhas

`detect_events` dá `start_date = primeira data` para todo evento: cada ajuste (UnobservedComponents + LassoCV) roda num pré-período que cresce com a data do evento, então a etapa é O(eventos × linhas), ~2 min na Elo e quadrática no histórico.

**Files:**
- Modify: `engine/pipeline.py` (`detect_events`, ~linha 112-131)
- Test: `tests/engine/test_pipeline_stages.py`

- [ ] **Step 1: teste que falha** — no fim de `tests/engine/test_pipeline_stages.py`:

```python
def test_the_pre_period_looks_back_at_most_a_year_of_rows(tmp_path):
    _, prepared, legacy = _prepared(tmp_path, n_days=730)
    candidates = pipeline.detect_events(prepared, legacy)
    dates = prepared.kpi_df["Date"].sort_values().reset_index(drop=True)

    rows_before = [
        int(((dates >= row.start_date) & (dates < row.intervention_date)).sum()) for row in candidates.itertuples()
    ]

    assert max(rows_before) == pipeline.PRE_PERIOD_MAX_ROWS
    assert min(rows_before) < pipeline.PRE_PERIOD_MAX_ROWS  # early events still start at the first date
```

Se `make_dataset(n_days=730)` não gerar candidato depois da linha 365 (a 1ª asserção falharia mesmo depois do fix), confira `tests/engine/synthetic_data.py` e passe o parâmetro que põe um pico no 2º ano; não invente outro dataset.

- [ ] **Step 2: rodar e ver falhar**

Run: `uv run pytest tests/engine/test_pipeline_stages.py -q -k pre_period`
Expected: FAIL (`AttributeError: PRE_PERIOD_MAX_ROWS`).

- [ ] **Step 3: implementar** em `engine/pipeline.py`. Constante no topo do módulo, depois de `log = ...`:

```python
# rows of history before an event that its causal fit sees: from the first date, every fit grew with the event's date
# and the stage was quadratic in the history (~2 min on 1016 days × 46 channels). Daily: a year; weekly/monthly: all.
PRE_PERIOD_MAX_ROWS = 365
```

No laço de `detect_events`, troque `"start_date": first_date,` por:

```python
                "start_date": kpi_dates[max(0, kpi_dates.searchsorted(day) - PRE_PERIOD_MAX_ROWS)].strftime("%Y-%m-%d"),
```

e apague a variável `first_date` se ela ficar sem uso.

- [ ] **Step 4: rodar e ver passar**

Run: `uv run pytest tests/engine/test_pipeline_stages.py tests/engine/test_audit_causal.py tests/engine/test_controls.py -q`
Expected: PASS. Se algum teste de causal comparar números exatos de um evento com mais de 365 linhas antes dele, o número mudou de propósito: atualize o esperado e cite no relatório.

- [ ] **Step 5: commit**

```bash
uv run ruff check engine tests/engine && uv run ruff format engine tests/engine
git add engine/pipeline.py tests/engine/test_pipeline_stages.py
git commit -m "perf(engine): pré-período do causal limitado a 365 linhas" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: VIF pela inversa da correlação

`channel_vif` roda um OLS por canal (`variance_inflation_factor`), dentro do request síncrono de validação que segura o lock da simulação. Com intercepto, VIF_i = diag(inv(corr))_i: mesmo valor, uma inversão só.

**Files:**
- Modify: `engine/validation.py` (`channel_vif`, ~linha 163)
- Test: `tests/engine/test_collinearity.py`

- [ ] **Step 1: teste** — acrescente em `tests/engine/test_collinearity.py`:

```python
def test_vif_of_many_channels_matches_statsmodels_and_is_fast():
    import time

    from statsmodels.stats.outliers_influence import variance_inflation_factor

    rng = np.random.default_rng(3)
    base = rng.normal(0, 1, (1000, 1))
    wide = pd.DataFrame(base + rng.normal(0, 1, (1000, 80)), columns=[f"C{i}" for i in range(80)])
    x = np.column_stack([np.ones(1000), wide.to_numpy()])
    expected = [variance_inflation_factor(x, i) for i in range(1, 81)]

    start = time.perf_counter()
    vif = channel_vif(wide)
    elapsed = time.perf_counter() - start

    assert [vif[c] for c in wide.columns] == pytest.approx(expected, abs=1e-4)
    assert elapsed < 0.2
```

- [ ] **Step 2: rodar e ver falhar**

Run: `uv run pytest tests/engine/test_collinearity.py -q -k "vif"`
Expected: o novo FAIL por tempo (`elapsed < 0.2`). Se passar já no código antigo, meça e registre o tempo no relatório e siga: a troca ainda reduz o custo de O(N) regressões para uma inversão.

- [ ] **Step 3: implementar** — `channel_vif`:

```python
def channel_vif(wide: pd.DataFrame) -> dict[str, float | None]:
    """VIF of each channel's spend on the others (with an intercept): the diagonal of the inverse correlation matrix.
    None when one channel is an exact mix of the others."""
    with np.errstate(divide="ignore", invalid="ignore"):
        try:
            values = np.diag(np.linalg.inv(np.corrcoef(wide.to_numpy(dtype=float), rowvar=False)))
        except np.linalg.LinAlgError:
            values = np.full(wide.shape[1], np.inf)
    return {
        name: round(float(v), 4) if np.isfinite(v) and 0 < v <= MAX_FINITE_VIF else None
        for name, v in zip(wide.columns, values, strict=True)
    }
```

Remova o import de `variance_inflation_factor` de `engine/validation.py` se ficar sem uso.

Atenção: `test_perfect_collinearity_is_a_none_vif_not_an_error` exige `A` e `B` `None` e `C` não `None`. Se a `inv` não levantar `LinAlgError` mas der valores finitos pequenos para A/B (singularidade numérica), troque o `except` por uma checagem de condição: `if np.linalg.cond(corr) > 1 / np.finfo(float).eps: ` caia no laço antigo (mantenha a implementação antiga como função `_vif_by_regression` só para esse caso). Rode o teste para decidir.

- [ ] **Step 4: rodar e ver passar**

Run: `uv run pytest tests/engine/test_collinearity.py tests/engine/test_validate_checks.py tests/engine/test_audit_gates.py -q`
Expected: PASS.

- [ ] **Step 5: commit**

```bash
uv run ruff check engine tests/engine && uv run ruff format engine tests/engine
git add engine/validation.py tests/engine/test_collinearity.py
git commit -m "perf(engine): vif pela inversa da correlação" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: `max_budget_step` com piso e `ramp` com teto

`max_budget_step` aceita qualquer valor > 0; com 1e-17, `1 + step == 1` e o `while True` de `ramp()` nunca termina — no worker (results/narratives) e em cada request do `scenario`. Runs já salvos com valor pequeno precisam do teto no `ramp`.

**Files:**
- Modify: `engine/config.py:46`, `engine/scenario.py` (`ramp`)
- Test: `tests/engine/test_config.py`, `tests/engine/test_ramp.py`

- [ ] **Step 1: testes que falham**

Em `tests/engine/test_ramp.py`:

```python
def test_a_step_too_small_to_ever_arrive_gives_no_ramp_instead_of_looping():
    assert ramp(100.0, 150.0, 1e-17, CURVE) is None
    assert ramp(100.0, 150.0, 1e-4, CURVE) is None  # thousands of steps is not a plan either
```

Em `tests/engine/test_config.py` (siga o estilo do arquivo; `EngineError` vem de `engine.errors`):

```python
def test_max_budget_step_has_a_floor():
    with pytest.raises(EngineError, match="max_budget_step"):
        EngineConfig.from_input({"max_budget_step": 0.001})
    assert EngineConfig.from_input({"max_budget_step": 0.01}).max_budget_step == 0.01
```

- [ ] **Step 2: rodar e ver falhar**

Run: `uv run pytest tests/engine/test_ramp.py tests/engine/test_config.py -q -k "too_small or floor"` com `timeout 60` na frente (o teste do ramp trava no código antigo: o timeout é a falha esperada).

- [ ] **Step 3: implementar**

`engine/config.py:46`:

```python
    max_budget_step: float = Field(default=0.2, ge=0.01, le=1)
```

`engine/scenario.py`: constante perto de `_TOLERANCE`:

```python
MAX_RAMP_STEPS = 200  # past this a ramp is not a plan, and a step near 0 never reaches the target (1 + 1e-17 == 1)
```

Em `ramp`, logo depois de `factor = ...`:

```python
    if math.log(target / current) / math.log(factor) > MAX_RAMP_STEPS:
        return None
```

(`target/current` e `factor` estão do mesmo lado de 1, então a razão dos logs é positiva; com `factor == 1` o `log` é 0 e a divisão dá `inf` ou `ZeroDivisionError` em float puro — use `math.log(factor) == 0 or ... > MAX_RAMP_STEPS` para cobrir.)

- [ ] **Step 4: rodar e ver passar**

Run: `uv run pytest tests/engine/test_ramp.py tests/engine/test_config.py tests/engine/test_guardrails.py tests/engine/test_scenario.py -q`
Expected: PASS. Se `tests/api/test_params.py` tiver caso de `max_budget_step` entre 0 e 0.01 válido, ajuste (rodar com Postgres no ar: `uv run pytest tests/api/test_params.py -q`).

- [ ] **Step 5: commit**

```bash
uv run ruff check engine tests && uv run ruff format engine tests/engine
git add engine/config.py engine/scenario.py tests/engine/test_ramp.py tests/engine/test_config.py
git commit -m "fix(engine): max_budget_step com piso e ramp com teto de passos" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Narrativas respeitam o prazo do run

`narratives.build` tem orçamento fixo de 300 s para a IA, sem olhar o watchdog. Um run que já calculou tudo pode morrer na etapa de narrativas e perder o resultado. O worker (Task 1) grava `RUN_DEADLINE` (epoch, `time.time()`) no ambiente; o motor roda no mesmo processo.

**Files:**
- Modify: `engine/narratives.py` (`build`, constantes)
- Test: `tests/engine/test_narratives.py`

- [ ] **Step 1: teste que falha** — em `tests/engine/test_narratives.py`, junto do teste do orçamento (usa `FakeLLM`, `_build`, `_document`, `INCONCLUSIVE`, `EVENT_NARRATIVE` do arquivo):

```python
def test_close_to_the_run_deadline_no_llm_is_called(monkeypatch):
    monkeypatch.setenv("RUN_DEADLINE", str(time.time() + narratives.DEADLINE_RESERVE_S - 1))
    llm = FakeLLM([json.dumps(EVENT_NARRATIVE)])

    reports = _build(_document(INCONCLUSIVE), llm)

    assert llm.calls == []
    assert reports["global"]["source"] == "deterministic"


def test_without_a_run_deadline_the_budget_is_unchanged(monkeypatch):
    monkeypatch.delenv("RUN_DEADLINE", raising=False)
    llm = FakeLLM([json.dumps(EVENT_NARRATIVE)] * 4)

    _build(_document(INCONCLUSIVE), llm)

    assert llm.calls
```

(acrescente `import time` se o arquivo não tiver.)

- [ ] **Step 2: rodar e ver falhar**

Run: `uv run pytest tests/engine/test_narratives.py -q -k "deadline"`
Expected: FAIL (`AttributeError: DEADLINE_RESERVE_S`).

- [ ] **Step 3: implementar** em `engine/narratives.py`. Imports: `import os` (e `time` já existe). Constante abaixo de `LLM_BUDGET_S`:

```python
DEADLINE_RESERVE_S = 120  # left before the worker's watchdog (RUN_DEADLINE, api/worker.py) to write results.json
```

Em `build`, troque `started = time.monotonic()` e a checagem do orçamento:

```python
    started = time.monotonic()
    budget = min(LLM_BUDGET_S, float(os.environ.get("RUN_DEADLINE", "inf")) - time.time() - DEADLINE_RESERVE_S)
    reports: dict = {"events": {}, "global": None, "grounding": None}
    for key, kind, payload, published in jobs_:
        narrative, judged = None, None
        if llm is not None and time.monotonic() - started > budget:
```

(o resto do laço fica igual; com `budget <= 0` a primeira volta já desliga a IA com o aviso existente.)

- [ ] **Step 4: rodar e ver passar**

Run: `uv run pytest tests/engine/test_narratives.py -q`
Expected: PASS (incluindo o `test_once_the_time_budget_is_spent...` existente).

- [ ] **Step 5: commit**

```bash
uv run ruff check engine tests/engine && uv run ruff format engine tests/engine
git add engine/narratives.py tests/engine/test_narratives.py
git commit -m "fix(engine): narrativas param antes do prazo do run" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: SLSQP da curva vetorizado, com jacobiano

`optimize_spend_mix_for_budget` (dentro de `generate_aggregated_response_curve`, `engine/elasticity_analysis.py`) roda ~103 SLSQP sem `jac`: cada avaliação faz N `hill_transform` escalares e passa pelo `MinMaxScaler.transform` do sklearn (e emite warning de feature names). Com N=46, ~2 s por solve (~4 min). Quando o SLSQP não converge, `result.x` é descartado mesmo sendo melhor que o chute. Só roda quando o run confia na realocação (CV ≥ 0,1 e todos os canais identificáveis).

**Files:**
- Modify: `engine/elasticity_analysis.py` (`optimize_spend_mix_for_budget`)
- Test: `tests/engine/test_audit_planner.py`

- [ ] **Step 1: ler** `tests/engine/test_audit_planner.py` para ver como ele monta um `elasticity_results` à mão e chama `generate_aggregated_response_curve`. Reuse esse construtor.

- [ ] **Step 2: teste que falha** — acrescente em `tests/engine/test_audit_planner.py` um teste que, com um MMM montado à mão com 40 canais (Hill k entre 0,3 e 1, s perto da média, coeficientes positivos, `reallocation_min_cv_r2` abaixo do `cv_r_squared` para liberar a realocação, `suppress_reallocation=False`):
  1. gera a curva e mede o tempo: `assert elapsed < 20` (no código antigo leva minutos);
  2. confere, para 3 níveis de investimento da curva, que `Projected_Total_KPIs` ≥ `Projected_Total_KPIs_Historical - 1e-6` (o mix otimizado nunca é pior que o histórico; vale também quando o SLSQP não converge).

Escreva o teste completo no arquivo (o construtor do MMM vem do próprio arquivo); rode com `timeout 600`.

- [ ] **Step 3: rodar e ver falhar**

Run: `timeout 600 uv run pytest tests/engine/test_audit_planner.py -q -k <nome_do_teste>`
Expected: FAIL por tempo.

- [ ] **Step 4: implementar.** Dentro de `generate_aggregated_response_curve`, antes de `def optimize_spend_mix_for_budget`, calcule uma vez:

```python
    ks = np.asarray(opt_params["ks"], dtype=float)
    ss = np.asarray(opt_params["ss"], dtype=float)
    multipliers_arr = np.array([adstock_multipliers[col] for col in active_spend_cols])
    caps = np.array([historical_max_daily_spend.get(col, 0) * per_channel_limit_factor for col in active_spend_cols])
    caps = np.where(caps > 0, caps, np.inf)
    weights = np.asarray(mkt_model.coef_, dtype=float) * mkt_scaler.scale_
    shifts = mkt_scaler.min_
    level = organic_baseline_mean + float(mkt_model.intercept_)

    def mix_objective(spend):
        # the same KPI as simulate_kpi (hill_transform + predict_clipped_kpi), in numpy, with its gradient
        x = np.minimum(spend, caps) * multipliers_arr
        on = x > 1e-9
        ratio = np.where(on, np.maximum(x / (ss + 1e-9), 1e-9), 1.0)
        h = np.where(on, 1 / (1 + ratio**-ks), 0.0)
        z = h * mkt_scaler.scale_ + shifts
        active = z > 0
        value = level + float(np.asarray(mkt_model.coef_) @ np.where(active, z, 0.0))
        dh_dx = np.where(on, ks * h * (1 - h) / np.where(on, x, 1.0), 0.0)
        grad = weights * active * dh_dx * multipliers_arr * (spend < caps)
        return -value, -grad
```

e dentro de `optimize_spend_mix_for_budget` troque o `def objective` + `minimize(...)` + `optimal_spends = ...` por:

```python
        bounds = [(0, total_budget) for _ in active_spend_cols]
        constraints = [{"type": "eq", "fun": lambda x: np.sum(x) - total_budget, "jac": lambda x: np.ones_like(x)}]
        result = minimize(
            mix_objective, init_guess, jac=True, bounds=bounds, constraints=constraints, method="SLSQP"
        )
        # past maxiter SLSQP still often lands above the start: keep it when it does
        better = result.success or mix_objective(result.x)[0] < mix_objective(init_guess)[0]
        optimal_spends = result.x if better else init_guess
```

Antes de trocar, valide a equivalência: num script de rascunho (fora do repo), compare `-mix_objective(s)[0]` com `simulate_kpi`-equivalente (`predict_clipped_kpi` sobre os `hill_transform` escalares) para 20 vetores aleatórios: diferença relativa < 1e-9. E o gradiente contra `scipy.optimize.approx_fprime`: relativa < 1e-4. Cite os números no relatório.

- [ ] **Step 5: rodar e ver passar**

Run: `timeout 900 uv run pytest tests/engine/test_audit_planner.py tests/engine/test_elasticity_analysis.py tests/engine/test_guardrails.py -q`
Expected: PASS. Números da curva mudam um pouco (ótimo melhor); só a Task 12 regenera os goldens.

- [ ] **Step 6: commit**

```bash
uv run ruff check engine tests/engine && uv run ruff format engine tests/engine
git add engine/elasticity_analysis.py tests/engine/test_audit_planner.py
git commit -m "perf(engine): slsqp da curva vetorizado com jacobiano" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Fallback do LassoCV sem todos os canais

Em `engine/analysis.py` (~linhas 525-536), quando a variância ou o LassoCV não deixa feature, o modelo causal recebe **todos** os canais como exógenas (46 na Elo): cada ajuste de UnobservedComponents fica ~5× mais lento. Os canais tratados já são acrescentados logo abaixo.

**Files:**
- Modify: `engine/analysis.py`
- Test: `tests/engine/test_audit_causal.py`

- [ ] **Step 1: teste que falha** — em `tests/engine/test_audit_causal.py`, um teste que monta um caso em que o LassoCV zera tudo (KPI ruído puro, sem relação com o gasto; 3+ canais) e captura as features passadas a `_fit_state_space` via `monkeypatch.setattr(analysis, "_fit_state_space", spy)` (o spy grava `selected_features` e chama o original). Asserção: as features usadas são só as `*_transformed` dos canais do evento (as `treated`), não as dos outros canais. Use os helpers que o arquivo já tem para preparar dados e chamar `analyze_events`/`detect_events`.

- [ ] **Step 2: rodar e ver falhar**

Run: `uv run pytest tests/engine/test_audit_causal.py -q -k <nome>`
Expected: FAIL (aparecem os outros canais).

- [ ] **Step 3: implementar** — nas duas linhas `selected_features = list(transformed_features.keys())` (ramo sem variância e ramo do Lasso vazio) troque por `selected_features = []`, e logo depois da linha que monta `selected_features = treated + [...]` acrescente:

```python
        if not selected_features:
            # nothing survived and the event's own channel has no variance: the old all-channels fallback
            selected_features = list(transformed_features.keys())
```

- [ ] **Step 4: rodar e ver passar**

Run: `uv run pytest tests/engine/test_audit_causal.py tests/engine/test_controls.py tests/engine/test_pipeline_stages.py -q`
Expected: PASS.

- [ ] **Step 5: commit**

```bash
uv run ruff check engine tests/engine && uv run ruff format engine tests/engine
git add engine/analysis.py tests/engine/test_audit_causal.py
git commit -m "perf(engine): causal sem fallback para todos os canais" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: Graceful shutdown do uvicorn

O uvicorn espera indefinidamente os streams SSE abertos ao desligar (reload no dev, deploy em produção). O `EventSource` reconecta com `Last-Event-ID`, então cortar não perde linha.

**Files:**
- Modify: `mise.toml:17`, `Dockerfile` (linha do `CMD`)

- [ ] **Step 1:** `mise.toml:17` vira:

```toml
run = "uv run uvicorn api.main:app --reload --port 8000 --timeout-graceful-shutdown 3"
```

- [ ] **Step 2:** no `CMD` do `Dockerfile`, acrescente `--timeout-graceful-shutdown 3` depois de `--port ${PORT:-8080}`.

- [ ] **Step 3: verificar** — `uv run uvicorn --help | grep timeout-graceful` lista a opção. (Não rode `docker build`.)

- [ ] **Step 4: commit**

```bash
git add mise.toml Dockerfile
git commit -m "fix(deploy): uvicorn não espera os streams sse para desligar" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: SSE só com a aba visível

Cada aba de "Detalhes" de um run ativo segura uma conexão SSE, inclusive escondida. Em HTTP/1.1 o navegador abre 6 por host: a 6ª trava todas as requests do app.

**Files:**
- Modify: `web/src/lib/runs.ts` (`useRunLog`)

- [ ] **Step 1: implementar** — troque o `useEffect` de `useRunLog` por:

```ts
  useEffect(() => {
    let source: EventSource | null = null
    let ended = false
    const open = () => {
      if (source || ended) return
      source = new EventSource(`/api/w/${slug}/runs/${runId}/logs/stream`)
      source.onmessage = (e) => {
        const line: LogLine = { id: Number(e.lastEventId), ...JSON.parse(e.data) }
        // a reopened stream replays the backlog: keep only lines past the last one we have
        setLines((prev) => (prev.length && prev[prev.length - 1].id >= line.id ? prev : [...prev, line].slice(-MAX_LINES)))
      }
      source.addEventListener('end', () => {
        ended = true
        setState('ended')
        close()
      })
      // a dropped connection is retried by the browser; CLOSED means an answer it won't retry (401, 404)
      source.onerror = () => {
        if (source?.readyState === EventSource.CLOSED) setState('lost')
      }
    }
    const close = () => {
      source?.close()
      source = null
    }
    // a hidden tab gives its connection back: over HTTP/1.1 the browser allows 6 per host, and the 6th froze the app
    const onVisibility = () => (document.visibilityState === 'visible' ? open() : close())
    document.addEventListener('visibilitychange', onVisibility)
    onVisibility()
    return () => {
      document.removeEventListener('visibilitychange', onVisibility)
      close()
    }
  }, [slug, runId])
```

- [ ] **Step 2: verificar**

Run: `cd web && bun run build && bun run lint`
Expected: sem erros.

- [ ] **Step 3: commit**

```bash
git add web/src/lib/runs.ts
git commit -m "fix(web): stream do log só com a aba visível" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: Docs

Depois das Tasks 1–10. Um commit só.

- [ ] `docs/decisoes/runs-e-jobs.md`: parágrafo "Reaper (12/nov/2026)": `launcher.reap` espera o subprocesso; saída ≠ 0 falha o run na hora (`TIMEOUT_EXIT = 3` do watchdog → mensagem de 20 min; outro código → "interrompida"); saída 0 não mexe; se a API reinicia, a thread morre e o `fail_stale` de 20 min continua sendo a rede. `CREATE_NEW_PROCESS_GROUP` no Windows. Limite `MAX_CONCURRENT_RUNS` (padrão núcleos − 1, sem lock, 409 com `BUSY_ERROR`; é a única query que conta entre workspaces, de propósito). `POST /runs` faz `rollback` antes do SGS. `on_log` faz rollback em commit falho. `RUN_DEADLINE` no ambiente do worker.
- [ ] `docs/decisoes/engine.md`: na seção "Etapa 2 do MMM com muitos canais" acrescente bullets: pré-período limitado a `PRE_PERIOD_MAX_ROWS = 365` linhas (muda eventos com mais de 1 ano de histórico antes); VIF pela inversa da correlação; `max_budget_step ≥ 0,01` e `ramp` com teto de 200 passos; narrativas param `DEADLINE_RESERVE_S = 120` antes do `RUN_DEADLINE`; SLSQP da curva vetorizado com jacobiano e `result.x` mantido quando melhora; fallback do LassoCV só com os canais tratados.
- [ ] `docs/decisoes/infra-e-operacao.md`: `--timeout-graceful-shutdown 3` no uvicorn (dev e imagem) e por quê; `MAX_CONCURRENT_RUNS` como variável do `.env` do servidor. Acrescente `MAX_CONCURRENT_RUNS=` comentado em `deploy/.env.example` e `.env.example`.
- [ ] `API-GUIDE.md`: na linha do `POST /runs` da tabela, o novo 409 de capacidade.
- [ ] `docs/status.md`: uma linha em pendências/histórico com a data e o que foi feito; e "goldens a regenerar" até a Task 12.

```bash
git add docs API-GUIDE.md deploy/.env.example .env.example
git commit -m "docs: reaper, limites e pontos de trava corrigidos" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Goldens e verificação final (coordenador)

- [ ] `uv run pytest -q` com o Postgres no ar: tudo verde.
- [ ] Run completo da Diageo e da Elo com os pins do worker (scratchpad da sessão): tempo e status.
- [ ] Regenerar os goldens num container Linux (`mise run parity-golden`, ver `tests/fixtures/parity/README.md`), mostrar os deltas ao usuário e só então comitar `tests/fixtures/parity/engine_snapshot.json` (o `real/gol_engine.json` não é versionado).
