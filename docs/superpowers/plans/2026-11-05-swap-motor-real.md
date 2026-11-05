# Swap da API para o motor real — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a API passa a usar `engine.validate`, `engine.run` e o `EngineConfig` reais; o motor fake fica só para o E2E e para a suíte da API.

**Architecture:** três módulos-ponte da API mudam de dono:
- `api/validation.py` chama o `engine.validate` real, em qualquer ambiente;
- `api/engine_run.py` chama o `engine.run` real, a não ser que `ENGINE_FAKE=1`;
- `api/engine_config.py` recorta o `ParamsIn` do `EngineConfig` do motor.

Uma migration de dados renomeia os `require_*` provisórios nos configs salvos. O worker mostra a mensagem do `EngineError`.

**Tech Stack:** Python 3.13, FastAPI, pydantic 2 (`create_model`), SQLAlchemy 2, Alembic, pytest; React 19 + TypeScript (bun); Playwright.

**Spec:** `docs/superpowers/specs/2026-11-05-swap-motor-real-design.md`. Três ajustes acertados depois do spec (a Task 9 corrige o texto dele):
1. **O `validate` é sempre o real**, inclusive nos testes e no E2E: ele aprova os CSV de exemplo (`tests/samples.py`) e roda rápido. O fake de `validate` é apagado; `ENGINE_FAKE` vale só para o `run`.
2. **O worker continua gravando o dict** que o `run` devolve (`json.dumps`). Enviar o arquivo do `out_dir` quebraria os testes que trocam o `run` por um lambda, e o ganho é nulo.
3. **"REVENUE exige ticket" é checado na rota** `PUT …/params`, como erro de campo em `["body", "average_ticket"]` com tipo `revenue_needs_ticket`, que a tela traduz. Um `model_validator` daria `loc ["body"]`, que a tela não sabe pôr num campo.

**Antes de começar:** `docker compose up -d` (Postgres em `:5432`), `uv sync`. A suíte da API usa o banco `app_test`. Rode tudo da raiz do repo. Rode os testes com `-p no:warnings` para enxugar a saída.

## Mapa de arquivos

| Arquivo | Responsabilidade | Tasks |
|---|---|---|
| `api/validation.py` | `validate` = `engine.validate(...).model_dump(mode="json")` | 1 |
| `api/simulations.py` | `save_mapping` traduz `EngineError` em `InvalidInput` | 1 |
| `api/engine_run.py` | `run` real, ou o fake com `ENGINE_FAKE=1` | 2 |
| `tests/conftest.py` | fixture autouse liga `ENGINE_FAKE=1` | 2 |
| `api/worker.py` | `EngineError` vira a mensagem do run | 3 |
| `api/engine_config.py` | `ParamsIn` recortado do `EngineConfig` do motor | 4 |
| `api/routes/simulations.py` | regra REVENUE × ticket no `PUT …/params` | 5 |
| `web/src/lib/params.ts` | layout da seção Causal e mensagem do erro novo | 5, 6 |
| `api/migrations/versions/0006_rename_require_params.py` | renomeia os `require_*` em `simulations.config` e `runs.config` | 7 |
| `tests/api/test_engine_swap.py` | integração com o motor real (dataset sintético) | 8 |
| docs | ver Task 9 | 9 |

**Ordem e paralelismo:**
- **Lote A:** 1, 2, 4 e 7 são independentes e podem rodar juntas.
- **Lote B:** 3 depois da 2 (as duas mexem em `tests/api/test_runs.py`); 5 depois da 4 (as duas mexem em `tests/api/test_params.py`).
- **Lote C:** 6 depois da 5 (`params.ts`); 8 depois de 1–4.
- **Fim:** 9 e 10 por último.

---

### Task 1: `validate` real na API

**Files:**
- Modify: `api/validation.py` (arquivo inteiro)
- Modify: `api/simulations.py` (`save_mapping`, ~linhas 158–184)
- Test: `tests/api/test_simulations.py` (linhas ~199–232 e o teste `test_mapping_rejects_unreadable_data_rows`)
- Modify: `web/e2e/simulations.spec.ts:58`

- [ ] **Step 1: Ajustar os testes para o relatório real (falham hoje)**

Em `tests/api/test_simulations.py`, no teste que termina em `assert body["validation"] == {` (perto da linha 199), troque o dict esperado por:

```python
    assert body["validation"] == {
        "ok": True,
        "cadence": "diária",
        "period_days": 1,
        "date_range": ["2024-01-01", "2024-01-02"],
        "channels": ["SEARCH", "YOUTUBE"],
        "checks": [],
        "collinearity": {"pairs": [], "vif": {}, "suggested_groups": []},
    }
```

Substitua `test_mapping_rejects_unreadable_data_rows` inteiro por (o `validate` real não levanta por dado: vira check):

```python
def test_unreadable_values_become_a_check_not_an_error(logged, analyst, ws, make_simulation):
    huge_field = b'data,canal,investimento\n2024-01-01,SEARCH,"' + b"x" * 200_000 + b'"\n'
    simulation = make_simulation(ws, analyst, files={"investment": huge_field, "performance": PERFORMANCE})

    r = put_mapping(logged, simulation.id, MAPPING)

    assert r.status_code == 200
    validation = r.json()["validation"]
    assert validation["ok"] is False
    assert [c["id"] for c in validation["checks"]] == ["value_not_numeric"]
```

Em `test_duplicate_date_channel_blocks_the_run`, troque a lista esperada por:

```python
    assert validation["checks"] == [
        {
            "id": "duplicate_date_channel",
            "level": "error",
            "message": "Há 1 linha(s) repetida(s) para a mesma data e o mesmo canal no arquivo de investimento. "
            "Remova ou consolide as duplicatas e envie o arquivo novamente.",
            "details": {"count": 1, "examples": [{"date": "2024-01-01", "channel": "SEARCH"}]},
        }
    ]
```

Acrescente logo depois:

```python
def test_a_config_the_engine_refuses_is_422_with_its_message(logged, db, analyst, ws, make_simulation):
    simulation = make_simulation(ws, analyst, files=BOTH)
    simulation.config = {"bogus": 1}
    db.commit()

    r = put_mapping(logged, simulation.id, MAPPING)

    assert (r.status_code, r.json()["detail"]) == (
        422,
        "Configuração inválida: campo 'bogus' não é reconhecido pelo motor",
    )
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q -p no:warnings tests/api/test_simulations.py -k "mapping or duplicate or unreadable or refuses"`

Expected: FAIL nos quatro testes acima (o fake ainda devolve `cadence: None`, `rows`, e o `bogus` passa).

- [ ] **Step 3: `api/validation.py` vira o motor**

Conteúdo inteiro:

```python
from pathlib import Path

import engine


def validate(inputs: dict[str, Path | None], config: dict) -> dict:
    # a data problem is a check in the report; only a config the engine refuses raises EngineError
    return engine.validate(inputs, config).model_dump(mode="json")
```

- [ ] **Step 4: `save_mapping` traduz `EngineError`**

Em `api/simulations.py`, acrescente o import `from engine import EngineError` junto aos demais (bloco de terceiros/primeiros conforme o ruff ordenar) e troque:

```python
    try:
        report = validation.validate(inputs, simulation.config)
    except csvfile.Unreadable:
        raise InvalidInput("Não foi possível ler o arquivo de investimento.")
```

por:

```python
    try:
        report = validation.validate(inputs, simulation.config)
    except EngineError as e:
        raise InvalidInput(str(e))
```

Se `csvfile` ficar sem uso em `api/simulations.py`, o `ruff check` aponta; remova o import nesse caso.

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest -q -p no:warnings tests/api/test_simulations.py tests/api/test_runs.py tests/api/test_params.py tests/api/test_google_import.py`

Expected: PASS. Se `test_google_import.py::…` falhar porque o relatório real traz checks para a grade com zeros, troque a asserção do teste para a saída real (o conector está fora do escopo; o teste só precisa refletir o motor). Não mude `api/`.

- [ ] **Step 6: E2E com a mensagem real**

Em `web/e2e/simulations.spec.ts`, linha 58, troque `'1 linha repetida de (data, canal) no investimento'` por `'Há 1 linha(s) repetida(s) para a mesma data e o mesmo canal no arquivo de investimento.', { exact: false }`, isto é:

```ts
  await expect(
    analystPage.getByText('Há 1 linha(s) repetida(s) para a mesma data e o mesmo canal no arquivo de investimento.', {
      exact: false,
    }),
  ).toBeVisible()
```

- [ ] **Step 7: Lint e commit**

```bash
uv run ruff check api tests && uv run ruff format api tests
git add api/validation.py api/simulations.py tests/api/test_simulations.py tests/api/test_google_import.py web/e2e/simulations.spec.ts
git commit -m "feat(api): validate uploads with the real engine"
```

---

### Task 2: `run` real, fake só com `ENGINE_FAKE=1`

**Files:**
- Modify: `api/engine_run.py` (arquivo inteiro)
- Modify: `tests/conftest.py` (fixture `fast_engine`, ~linha 76)
- Modify: `web/e2e/env.ts`
- Modify: `.env.example`
- Test: `tests/api/test_runs.py` (topo do arquivo)

- [ ] **Step 1: Teste do desvio para o motor (falha hoje)**

Em `tests/api/test_runs.py`, logo depois de `test_fake_engine_fails_on_request`, acrescente:

```python
def test_without_engine_fake_the_real_engine_runs(tmp_path, monkeypatch):
    import engine

    calls = []
    monkeypatch.delenv("ENGINE_FAKE")
    monkeypatch.setattr(engine, "run", lambda *args: calls.append(args) or {"status": "succeeded"})

    engine_run.run({"investment_file": None}, {"a": 1}, tmp_path, print)

    assert calls == [({"investment_file": None}, {"a": 1}, tmp_path, print)]
```

E troque a fixture em `tests/conftest.py`:

```python
@pytest.fixture(autouse=True)
def fast_engine(monkeypatch):
    # a real run needs months of data and ~40 s; tests/api/test_engine_swap.py turns this off
    monkeypatch.setenv("ENGINE_FAKE", "1")
    monkeypatch.setenv("FAKE_ENGINE_STEP_SECONDS", "0")
    monkeypatch.delenv("FAKE_ENGINE_FAIL", raising=False)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q -p no:warnings tests/api/test_runs.py -k "engine_runs or fake_engine"`

Expected: FAIL em `test_without_engine_fake_the_real_engine_runs` (o fake roda e `calls == []`).

- [ ] **Step 3: `api/engine_run.py`**

Conteúdo inteiro:

```python
import os
import time
from collections.abc import Callable
from pathlib import Path

import engine

STEPS = [
    "Lendo os arquivos de investimento e performance",
    "Detectando eventos de investimento",
    "Estimando o impacto causal dos eventos",
    "Ajustando as curvas de saturação",
    "Calculando os cenários de orçamento",
    "Montando o resultado",
]


def run(inputs: dict[str, Path | None], config: dict, out_dir: Path, on_log: Callable[[str, str], None]) -> dict:
    if os.environ.get("ENGINE_FAKE") == "1":
        return fake_run(on_log)
    return engine.run(inputs, config, out_dir, on_log)


def fake_run(on_log: Callable[[str, str], None]) -> dict:
    # ponytail: only paces log lines, for the E2E and the API tests; never set ENGINE_FAKE in production
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

- [ ] **Step 4: E2E e `.env.example`**

Em `web/e2e/env.ts`, troque o comentário e as duas linhas `FAKE_ENGINE_*` por:

```ts
  // the worker subprocess inherits this env: the fake engine takes ~5 s per run, long enough to see "Rodando"
  // and reload mid-run; the real one needs months of data
  ENGINE_FAKE: '1',
  FAKE_ENGINE_STEP_SECONDS: '1',
  FAKE_ENGINE_FAIL: '',
```

Em `.env.example`, troque o bloco que começa em `# engine.run falso até o swap do motor real:` por:

```
# Motor fake (só E2E e testes): 1 troca o engine.run por um que só escreve o log. Nunca em produção
# ENGINE_FAKE=
# Com o fake: pausa entre as etapas do log (s) e falha forçada (1) para ver o caminho de erro
# FAKE_ENGINE_STEP_SECONDS=1
# FAKE_ENGINE_FAIL=
```

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest -q -p no:warnings tests/api/test_runs.py`

Expected: PASS (todos; os que usam `engine_run.STEPS` continuam no fake pela fixture).

- [ ] **Step 6: Commit**

```bash
uv run ruff check api tests && uv run ruff format api tests
git add api/engine_run.py tests/conftest.py tests/api/test_runs.py web/e2e/env.ts .env.example
git commit -m "feat(api): run the real engine unless ENGINE_FAKE is set"
```

---

### Task 3: `EngineError` aparece na tela do run

**Depends on:** Task 2 (mesmo arquivo de teste).

**Files:**
- Modify: `api/worker.py` (bloco `try/except` de `execute`, ~linhas 48–70)
- Test: `tests/api/test_runs.py`

- [ ] **Step 1: Teste (falha hoje)**

Em `tests/api/test_runs.py`, depois de `test_a_failed_engine_status_shows_the_ptbr_error`, acrescente:

```python
def test_an_engine_error_shows_the_engine_message(db, ready, analyst, monkeypatch):
    from engine import EngineError

    run = runs.create(db, ready(), set(), by=analyst)

    def refuse(*args):
        raise EngineError("Há linhas repetidas no investimento.", check_id="duplicate_date_channel")

    monkeypatch.setattr(engine_run, "run", refuse)

    worker.execute(db, run.id)

    db.refresh(run)
    assert (run.status, run.error) == ("failed", "Há linhas repetidas no investimento.")
    assert messages(db, run.id)[-1] == run.error
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q -p no:warnings tests/api/test_runs.py -k engine_error_shows`

Expected: FAIL, `run.error` é a mensagem genérica "O motor falhou…".

- [ ] **Step 3: Ramo do `EngineError` no worker**

Em `api/worker.py`, acrescente `from engine import EngineError` aos imports e, **antes** do `except Exception:` de `execute`, insira:

```python
    except EngineError as e:  # pt-BR and safe for the screen by contract: no paths, no client data
        log.warning("worker.engine_refused run_id=%s check_id=%s", rid, e.check_id)
        db.rollback()
        db.add(RunLog(run_id=rid, level="error", message=str(e)))
        values = {"status": "failed", "error": str(e)}
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest -q -p no:warnings tests/api/test_runs.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff check api tests && uv run ruff format api tests
git add api/worker.py tests/api/test_runs.py
git commit -m "feat(worker): show the engine's own message when it refuses a run"
```

---

### Task 4: `ParamsIn` recortado do `EngineConfig` do motor

**Files:**
- Modify: `api/engine_config.py` (arquivo inteiro)
- Test: `tests/api/test_params.py` (testes do topo, ~linhas 29–43)

- [ ] **Step 1: Testes (falham hoje)**

Em `tests/api/test_params.py`, troque o import `from api.engine_config import EngineConfig, ParamsIn` por:

```python
from api.engine_config import ANALYST_FIELDS, ParamsIn
from engine.config import EngineConfig
```

Substitua `test_config_schema_lists_only_the_form_fields` e `test_engine_config_is_the_form_fields_plus_the_rest` por:

```python
def test_config_schema_lists_only_the_form_fields(logged):
    schema = logged.get("/api/engine/config-schema").json()

    props = schema["properties"]
    assert list(props) == list(ANALYST_FIELDS)
    assert props["min_pre_period_days"]["default"] == 14
    assert props["optimization_target"]["enum"] == ["REVENUE", "CONVERSIONS"]
    assert {"column_mapping", "treat_outliers", "require_significance", "require_good_fit"}.isdisjoint(props)


def test_params_in_copies_default_and_limits_from_the_engine():
    for name in ANALYST_FIELDS:
        ours, engine_field = ParamsIn.model_fields[name], EngineConfig.model_fields[name]
        assert ours.get_default(call_default_factory=True) == engine_field.get_default(call_default_factory=True)
        assert ours.metadata == engine_field.metadata, name


def test_the_old_provisional_names_are_refused(logged, mapped):
    r = logged.put(f"/api/w/a/simulations/{mapped.id}/params", json={"require_good_fit": True})

    assert [(e["loc"], e["type"]) for e in r.json()["detail"]] == [(["body", "require_good_fit"], "extra_forbidden")]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q -p no:warnings tests/api/test_params.py -k "schema or copies or old_provisional"`

Expected: FAIL (`ANALYST_FIELDS` não existe).

- [ ] **Step 3: `api/engine_config.py`**

Conteúdo inteiro:

```python
from copy import copy

from pydantic import ConfigDict, create_model

from engine.config import EngineConfig

# what the analyst edits on the parameters form; default and limits come from the engine (contract §1).
# treat_outliers stays at the engine's default: it takes a list of channels the generated form can't draw
ANALYST_FIELDS = (
    "optimization_target",
    "kpi_is_monetary",
    "average_ticket",
    "conversion_rate_from_kpi_to_bo",
    "financial_targets",
    "investment_limit_factor",
    "max_budget_step",
    "p_value_threshold",
    "min_pre_period_days",
    "post_event_days",
    "r_squared_threshold",
    "increase_threshold_percent",
    "decrease_threshold_percent",
    "max_events_to_analyze",
    "require_statistical_significance",
    "require_logical_direction",
    "require_model_fit",
)

ParamsIn = create_model(
    "ParamsIn",
    __config__=ConfigDict(extra="forbid", allow_inf_nan=False),
    **{name: (EngineConfig.model_fields[name].annotation, copy(EngineConfig.model_fields[name])) for name in ANALYST_FIELDS},
)
```

Outros módulos importam `ParamsIn` daqui (`api/routes/engine.py`, `api/routes/simulations.py`, `api/suggestions.py`, `tests/api/test_runs.py`) e não mudam. Se algum arquivo importar `EngineConfig` de `api.engine_config`, troque para `from engine.config import EngineConfig` (busque com `rg "from api.engine_config import" api tests`).

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest -q -p no:warnings tests/api/test_params.py tests/api/test_runs.py`

Expected: PASS. Se um teste de sugestões falhar porque esperava `min_pre_period_days` com default 28, a sugestão dos dados continua valendo (ela não usa o default); ajuste só a expectativa do default para 14.

- [ ] **Step 5: Commit**

```bash
uv run ruff check api tests && uv run ruff format api tests
git add api/engine_config.py tests/api/test_params.py
git commit -m "feat(api): derive the parameters form from the engine's EngineConfig"
```

---

### Task 5: REVENUE exige ticket médio

**Depends on:** Task 4 (mesmo arquivo de teste).

**Files:**
- Modify: `api/routes/simulations.py` (`save_params`, ~linha 189)
- Modify: `web/src/lib/params.ts` (`ERROR_MESSAGES`, ~linha 197)
- Test: `tests/api/test_params.py`

- [ ] **Step 1: Teste (falha hoje)**

Em `tests/api/test_params.py`, depois de `test_invalid_params_are_422_with_the_field`, acrescente:

```python
def test_revenue_without_a_ticket_is_422_on_the_ticket(logged, mapped):
    r = logged.put(f"/api/w/a/simulations/{mapped.id}/params", json={"optimization_target": "REVENUE"})

    assert r.status_code == 422
    assert [(e["loc"], e["type"]) for e in r.json()["detail"]] == [(["body", "average_ticket"], "revenue_needs_ticket")]


def test_revenue_with_a_ticket_saves(logged, mapped):
    r = logged.put(
        f"/api/w/a/simulations/{mapped.id}/params", json={"optimization_target": "REVENUE", "average_ticket": 80}
    )

    assert r.status_code == 200
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q -p no:warnings tests/api/test_params.py -k revenue`

Expected: FAIL no primeiro (hoje salva com 200).

- [ ] **Step 3: Checagem na rota**

Em `api/routes/simulations.py`, acrescente `from fastapi.exceptions import RequestValidationError` aos imports e, no começo de `save_params`, antes de `find_simulation`:

```python
    # the engine's EngineConfig checks this too, but as a model error the form couldn't pin to a field
    if body.optimization_target == "REVENUE" and not body.average_ticket:
        raise RequestValidationError(
            [
                {
                    "type": "revenue_needs_ticket",
                    "loc": ("body", "average_ticket"),
                    "msg": "Obrigatório para otimizar por receita.",
                    "input": None,
                }
            ]
        )
```

- [ ] **Step 4: Mensagem na tela**

Em `web/src/lib/params.ts`, dentro de `ERROR_MESSAGES`, acrescente a última entrada:

```ts
  revenue_needs_ticket: () => 'Obrigatório para otimizar por receita.',
```

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest -q -p no:warnings tests/api/test_params.py` e `cd web && bun run lint`

Expected: PASS e lint sem erro.

- [ ] **Step 6: Commit**

```bash
uv run ruff check api tests && uv run ruff format api tests
git add api/routes/simulations.py web/src/lib/params.ts tests/api/test_params.py
git commit -m "feat(api): require the average ticket when optimizing for revenue"
```

---

### Task 6: Formulário com os campos do motor

**Depends on:** Tasks 4 e 5.

**Files:**
- Modify: `web/src/lib/params.ts` (grupo `'Causal'`, ~linhas 62–73)

- [ ] **Step 1: Layout**

Troque o grupo `Causal` por:

```ts
  {
    title: 'Causal',
    fields: [
      { path: 'p_value_threshold', label: 'p-valor máximo' },
      { path: 'min_pre_period_days', label: 'Pré-período mínimo (dias)' },
      { path: 'post_event_days', label: 'Pós-evento (dias)', help: 'Janela medida depois de cada evento.' },
      { path: 'r_squared_threshold', label: 'R² mínimo' },
      { path: 'increase_threshold_percent', label: 'Aumento mínimo para evento (%)' },
      { path: 'decrease_threshold_percent', label: 'Queda mínima para evento (%)' },
      { path: 'max_events_to_analyze', label: 'Máximo de eventos analisados' },
      { path: 'require_statistical_significance', label: 'Exigir significância' },
      {
        path: 'require_logical_direction',
        label: 'Exigir direção lógica',
        help: 'O efeito precisa ir na direção da mudança de investimento.',
      },
      { path: 'require_model_fit', label: 'Exigir bom ajuste' },
    ],
  },
```

- [ ] **Step 2: Build e lint**

Run: `cd web && bun run build && bun run lint`

Expected: build e lint sem erro.

- [ ] **Step 3: Ver na tela**

Com `mise run api` e `mise run web` no ar, abra uma simulação com mapeamento confirmado em `http://localhost:5173` (MCP `playwright`), tire screenshot da seção de parâmetros e confira:
- os três campos novos com o default do motor (14, 5, marcado);
- "Exigir significância" e "Exigir bom ajuste" marcados.

- [ ] **Step 4: Commit**

```bash
git add web/src/lib/params.ts
git commit -m "feat(web): show post-event window, max events and the logical direction gate"
```

---

### Task 7: Migration dos nomes `require_*`

**Files:**
- Create: `api/migrations/versions/0006_rename_require_params.py`
- Test: `tests/api/test_migrations.py`

- [ ] **Step 1: Teste (falha hoje)**

Acrescente em `tests/api/test_migrations.py`:

```python
import importlib.util
from pathlib import Path

from sqlalchemy import text

from api.models import Run

MIGRATION = Path(__file__).resolve().parents[2] / "api/migrations/versions/0006_rename_require_params.py"


def load_0006():
    spec = importlib.util.spec_from_file_location("migration_0006", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_0006_renames_the_require_keys_and_keeps_their_values(db, make_user, make_workspace, make_simulation):
    user = make_user("ana@x.com")
    ws = make_workspace("a", [(user, "analyst")])
    simulation = make_simulation(ws, user)
    simulation.config = {"require_significance": False, "require_good_fit": True, "p_value_threshold": 0.1}
    run = Run(
        workspace_id=ws.id,
        simulation_id=simulation.id,
        created_by=user.id,
        status="succeeded",
        config={"require_good_fit": False},
        inputs={},
        confirmed_warnings=[],
    )
    db.add(run)
    db.flush()
    migration = load_0006()

    for sql in migration.statements(migration.RENAMES):
        db.execute(text(sql))
    db.refresh(simulation)
    db.refresh(run)

    assert simulation.config == {
        "require_statistical_significance": False,
        "require_model_fit": True,
        "p_value_threshold": 0.1,
    }
    assert run.config == {"require_model_fit": False}
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest -q -p no:warnings tests/api/test_migrations.py`

Expected: FAIL com `FileNotFoundError` (a migration não existe).

- [ ] **Step 3: A migration**

`api/migrations/versions/0006_rename_require_params.py`:

```python
"""rename the provisional require_* params to the engine's names

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-05
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

# keeps the values: a saved False may be the analyst's choice, and nothing tells it from a default
RENAMES = {"require_significance": "require_statistical_significance", "require_good_fit": "require_model_fit"}


def statements(renames: dict[str, str]) -> list[str]:
    return [
        f"UPDATE {table} SET config = (config - '{old}') || jsonb_build_object('{new}', config -> '{old}') "
        f"WHERE config ? '{old}'"
        for table in ("simulations", "runs")
        for old, new in renames.items()
    ]


def upgrade() -> None:
    for sql in statements(RENAMES):
        op.execute(sql)


def downgrade() -> None:
    for sql in statements({new: old for old, new in RENAMES.items()}):
        op.execute(sql)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest -q -p no:warnings tests/api/test_migrations.py` e `uv run alembic -c api/alembic.ini upgrade head` (banco de dev) e `uv run alembic -c api/alembic.ini downgrade -1 && uv run alembic -c api/alembic.ini upgrade head`.

Expected: PASS; upgrade, downgrade e upgrade sem erro.

- [ ] **Step 5: Commit**

```bash
uv run ruff check api tests && uv run ruff format api tests
git add api/migrations/versions/0006_rename_require_params.py tests/api/test_migrations.py
git commit -m "feat(db): rename the provisional require params in saved configs"
```

---

### Task 8: Integração com o motor real

**Depends on:** Tasks 1–4.

**Files:**
- Create: `tests/api/test_engine_swap.py`

- [ ] **Step 1: Os testes**

```python
import json

import pytest
from threadpoolctl import threadpool_limits

from api import runs, simulations, storage, worker
from api.engine_config import ParamsIn
from tests.engine.synthetic_data import make_dataset

MAPPING = {
    "investment_file": {"date_col": "dates", "channel_col": "product_group", "investment_col": "total_revenue"},
    "performance_file": {"date_col": "date", "kpi_col": "Sessions"},
}


@pytest.fixture(autouse=True)
def real_engine(monkeypatch):
    monkeypatch.delenv("ENGINE_FAKE")
    monkeypatch.setenv("LLM_PROVIDER", "none")


@pytest.fixture
def analyst(make_user):
    return make_user("ana@x.com")


@pytest.fixture
def synthetic(db, make_workspace, analyst, make_simulation, tmp_path):
    ws = make_workspace("a", [(analyst, "analyst")])
    paths = make_dataset(tmp_path / "data", n_days=364, with_trends=False)
    files = {
        "investment": paths["investment_file"].read_bytes(),
        "performance": paths["performance_file"].read_bytes(),
    }
    simulation = make_simulation(ws, analyst, files=files)
    simulations.save_mapping(db, simulation, MAPPING)
    return simulation


def test_the_upload_gets_the_engine_report(synthetic):
    report = synthetic.validation

    assert report["ok"] is True
    assert (report["cadence"], report["period_days"]) == ("diária", 1)
    assert report["channels"] == ["DISPLAY", "PMAX", "SEARCH", "SOCIAL", "YOUTUBE"]


def test_a_run_stores_the_engine_results_json(db, synthetic, analyst):
    simulations.save_params(db, synthetic, ParamsIn().model_dump(mode="json"))
    warnings = {c["id"] for c in synthetic.validation["checks"] if c["level"] == "warning"}
    run = runs.create(db, synthetic, warnings, by=analyst)

    with threadpool_limits(limits=1):
        worker.execute(db, run.id)

    db.refresh(run)
    assert run.status in ("succeeded", "inconclusive"), run.error
    results = json.loads(storage.path(run.results_uri).read_text(encoding="utf-8"))
    assert results["schema_version"] == 1 and results["status"] == run.status
    assert results["validation"]["ok"] is True
    assert run.engine_version == results["engine_version"]
```

- [ ] **Step 2: Rodar**

Run: `uv run pytest -q -p no:warnings tests/api/test_engine_swap.py`

Expected: 2 passed (o segundo leva ~30–60 s). Se o run sair `failed`, `run.error` diz por quê: é bug de integração, investigue antes de seguir (`mattpocock-skills:diagnosing-bugs`).

- [ ] **Step 3: Commit**

```bash
uv run ruff check tests && uv run ruff format tests
git add tests/api/test_engine_swap.py
git commit -m "test(api): upload, validate and run end to end on the real engine"
```

---

### Task 9: Documentação

**Files:** os listados abaixo; nada de código.

- [ ] **Step 1: Spec** (`docs/superpowers/specs/2026-11-05-swap-motor-real-design.md`). Ajuste as linhas da tabela de decisões e as seções "Componentes" e "Testes" aos três ajustes do topo deste plano:
  - o `validate` é sempre real;
  - o worker grava o dict;
  - a regra REVENUE fica na rota.

- [ ] **Step 2: `docs/decisoes/engine.md`** › "Passos do swap": marque como feitos (com "feito em 05/nov/2026") os passos 2, 3, 4, 5 e 7, descrevendo:
  - o `ParamsIn` recortado por `ANALYST_FIELDS`;
  - a migration `0006`;
  - o `validate` real em todo lugar;
  - `ENGINE_FAKE` só para o `run`;
  - o `EngineError` no worker.

  No passo 10, registre que o worker continua gravando o dict, e por quê. Na tabela "Divergências com `api/engine_config.py`", troque o título para "Divergências que a API tinha (resolvidas em 05/nov/2026)".

  Em "Limitações conhecidas", acrescente: **a `message` de `value_not_numeric` (e dos checks que mostram exemplos) leva o valor bruto da coluna, sem limite de tamanho**. Um campo de 200 KB vira uma mensagem de 200 KB no banco e na tela, e o valor é dado do cliente. Truncar os exemplos é da Trilha A.
- [ ] **Step 3: `docs/decisoes/upload-e-storage.md`**: a seção `validate` falso até o swap vira "`validate` do motor (05/nov/2026)". A API chama `engine.validate(...).model_dump(mode="json")`, `EngineError` vira 422, e um problema no dado é check, nunca exceção. A frase do `csvfile.Unreadable` → 422 sai.
- [ ] **Step 4: `docs/decisoes/runs-e-jobs.md`**:
  - `engine.run` real;
  - `ENGINE_FAKE=1` só no E2E e na suíte da API;
  - `EngineError` mostra a mensagem do motor e o resto continua genérico.

  Atualize o índice em `docs/decisoes/README.md` (`engine.run` falso → motor real com fake por env).
- [ ] **Step 5: `docs/decisoes/parametros-e-gemini.md`**:
  - o `ParamsIn` vem do `EngineConfig` do motor via `ANALYST_FIELDS`;
  - `treat_outliers` fica fora;
  - REVENUE sem ticket dá 422 em `average_ticket`.
- [ ] **Step 6: `docs/m2/README.md`** contrato §1: a frase "Até o A0, a API usa um `EngineConfig` provisório…" vira "Desde 05/nov/2026 a API usa o `EngineConfig` do motor: o formulário é o recorte `ANALYST_FIELDS` (`api/engine_config.py`)". Nas §2 e §3, troque "A API ainda usa o falso…" por "A API usa o motor real desde 05/nov/2026".
- [ ] **Step 7: `DATABASE.md`**: na lista/tabela de migrations, acrescente `0006`, "migration de dados: renomeia `require_significance`/`require_good_fit` em `simulations.config` e `runs.config`".
- [ ] **Step 8: `CLAUDE.md`**:
  - **árvore:** `engine_config.py` passa a ser "`ParamsIn` recortado do `EngineConfig` do motor (`ANALYST_FIELDS`)", `validation.py` "chama `engine.validate`" e `engine_run.py` "chama `engine.run`; fake com `ENGINE_FAKE=1` (E2E e testes)";
  - **"Estado atual":** troque "**A API ainda usa os falsos** (…): o swap é do Dev B, com 10 passos em `docs/decisoes/engine.md` (…)" por "**Swap concluído em 05/nov/2026**: a API usa `engine.validate`, `engine.run` e o `EngineConfig` reais (migration `0006` renomeia os `require_*`), com o fake só atrás de `ENGINE_FAKE=1`";
  - **"Faltam":** tire "o swap" da lista;
  - **o trecho antigo do A0:** troque "**A API ainda usa o motor falso**: o swap (`api/engine_run.py`, `api/engine_config.py`, `Dockerfile`, `api/gemini.py` → `llm/`) é do Dev B…" por "`api/gemini.py` → `llm/` ainda está pendente".
- [ ] **Step 9: Commit**

```bash
git add docs CLAUDE.md DATABASE.md
git commit -m "docs: record the swap to the real engine"
```

---

### Task 10: Verificação final

- [ ] **Step 1:** `uv run ruff check . && uv run ruff format --check .` → sem erro.
- [ ] **Step 2:** `uv run pytest -q -p no:warnings` → tudo passa (a suíte do motor leva ~10 min; os testes de paridade pulam fora do Linux).
- [ ] **Step 3:** `cd web && bun run build && bun run lint` → sem erro.
- [ ] **Step 4:** `mise run e2e` → todos passam. Se algum teste de validação falhar porque o relatório real traz um aviso nos templates do E2E (`web/e2e/templates/`), confirme o aviso no teste (o gate do Rodar pede "Estou ciente") em vez de mudar o template. A exceção é um template quebrado de verdade.
- [ ] **Step 5:** `superpowers:verification-before-completion` antes de declarar pronto.
