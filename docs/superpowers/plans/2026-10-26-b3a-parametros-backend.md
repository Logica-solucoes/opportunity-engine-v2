# B3a · Parâmetros com sugestão do Gemini (backend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A API expõe o schema dos parâmetros, sugere valores a partir dos arquivos e pelo Gemini (com explicação), e grava os parâmetros da simulação validados pelo pydantic.

**Architecture:** Um `EngineConfig` provisório em `api/engine_config.py` (vira import do `engine/` no A0). `api/suggestions.py` tem as regras sobre os CSVs, o resumo agregado e a validação das respostas do Gemini; `api/gemini.py` é só a chamada ao SDK, trocada por fake nos testes. A regra de negócio fica em `api/simulations.py` e as rotas finas em `api/routes/simulations.py` e `api/routes/engine.py`.

**Tech Stack:** Python 3.13, FastAPI 0.158, pydantic 2.14, SQLAlchemy 2, pytest. SDK `google-genai` (`client.models.generate_content` com `response_json_schema`, conferido no context7, v2.32). Stdlib `statistics`, `datetime`, `json`.

**Spec:** `docs/superpowers/specs/2026-10-26-b3-parametros-gemini-design.md` (seção B3a). Leia antes, junto com `API-GUIDE.md`, `CODE-STYLE.md` e `docs/decisoes/upload-e-storage.md`.

**Antes de cada task:** `docker compose up -d` (Postgres em `:5432`). Comandos rodam da raiz do repo. O pytest inteiro leva ~3 min nesta máquina (~1,2 s por teste): rode só o arquivo da task e deixe a suíte completa para o fim de cada task, com timeout longo.

**Seams de teste:** as 4 rotas novas via `TestClient`; `suggestions.from_data(paths, mapping)` como função pura sobre CSVs em `tmp_path`; a matriz de `tests/api/test_rbac.py`. O Gemini é trocado por `monkeypatch.setattr(gemini, "ask", fake)`; nenhum teste chama a rede.

---

## Mapa de arquivos

| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `pyproject.toml`, `uv.lock` | modificar | `google-genai` |
| `api/engine_config.py` | criar | `FinancialTargets`, `ParamsIn`, `EngineConfig` provisórios |
| `api/routes/engine.py` | criar | `GET /api/engine/config-schema` |
| `api/csvfile.py` | modificar | recebe `normalize` (nome de coluna), hoje em `simulations.py` |
| `api/suggestions.py` | criar | leitura das colunas, cadência, `from_data`, `summary`, `from_gemini` |
| `api/gemini.py` | criar | `ask(prompt, schema) -> str`, `Unavailable` |
| `api/simulations.py` | modificar | `input_paths`, `require_mapping`, `suggest_params`, `gemini_params`, `save_params` |
| `api/routes/simulations.py` | modificar | 3 rotas |
| `api/main.py` | modificar | `include_router(engine.router)` |
| `tests/conftest.py` | modificar | `GEMINI_API_KEY` sempre ausente nos testes |
| `tests/api/test_params.py` | criar | testes das 4 rotas e de `from_data` |
| `tests/api/test_rbac.py` | modificar | 4 rotas na matriz; simulação do `env` com mapeamento salvo |
| docs | modificar | Task 5 |

---

### Task 1: Dependência, `EngineConfig` provisório e schema

**Files:**
- Modify: `pyproject.toml`, `uv.lock` (via `uv add`)
- Create: `api/engine_config.py`, `api/routes/engine.py`, `tests/api/test_params.py`
- Modify: `api/main.py`, `tests/api/test_rbac.py`

- [ ] **Step 1: Adicionar `google-genai`**

Run: `uv add google-genai`
Expected: `pyproject.toml` ganha `"google-genai>=…"` em `dependencies` e o `uv.lock` muda.

- [ ] **Step 2: Escrever os testes**

Crie `tests/api/test_params.py`:

```python
import pytest

from api.engine_config import EngineConfig, ParamsIn


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


def test_config_schema_lists_only_the_form_fields(logged):
    schema = logged.get("/api/engine/config-schema").json()

    props = schema["properties"]
    assert props["investment_limit_factor"]["default"] == 1.5
    assert props["optimization_target"]["enum"] == ["REVENUE", "CONVERSIONS"]
    assert {"column_mapping", "channel_groups", "controls", "gate_thresholds"}.isdisjoint(props)


def test_engine_config_is_the_form_fields_plus_the_rest():
    config = EngineConfig()

    assert config.max_budget_step == 0.2 and config.column_mapping == {}
    assert set(ParamsIn.model_fields) < set(EngineConfig.model_fields)
```

Em `tests/api/test_rbac.py`, adicione ao dicionário `ROUTES` (antes de `("GET", "/api/admin/workspaces")`):

```python
    ("GET", "/api/engine/config-schema"): (SESSION, 200, None),
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `uv run pytest tests/api/test_params.py -q`
Expected: FAIL na coleta com `ModuleNotFoundError: No module named 'api.engine_config'`.

- [ ] **Step 4: Escrever o config e a rota**

Crie `api/engine_config.py`:

```python
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

# ponytail: stand-in for engine/config.py (A0, docs/m2/README.md contract §1). Names and defaults of the causal
# fields are provisional; when engine/ exists EngineConfig comes from there and ParamsIn follows its fields


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FinancialTargets(Strict):
    target_cpa: float | None = Field(default=None, gt=0)
    target_icpa: float | None = Field(default=None, gt=0)
    target_roas: float | None = Field(default=None, gt=0)
    target_iroas: float | None = Field(default=None, gt=0)


class ParamsIn(Strict):
    """What the analyst fills in on the parameters form."""

    optimization_target: Literal["REVENUE", "CONVERSIONS"] = "CONVERSIONS"
    kpi_is_monetary: bool = False
    average_ticket: float | None = Field(default=None, gt=0)
    conversion_rate_from_kpi_to_bo: float = Field(default=1.0, gt=0, le=1)
    financial_targets: FinancialTargets = Field(default_factory=FinancialTargets)
    investment_limit_factor: float = Field(default=1.5, gt=1, le=5)
    max_budget_step: float = Field(default=0.2, gt=0, le=1)
    p_value_threshold: float = Field(default=0.05, gt=0, lt=1)
    min_pre_period_days: int = Field(default=28, ge=7)
    r_squared_threshold: float = Field(default=0.5, ge=0, le=1)
    increase_threshold_percent: float = Field(default=20, gt=0)
    decrease_threshold_percent: float = Field(default=20, gt=0)
    require_significance: bool = True
    require_good_fit: bool = True


class EngineConfig(ParamsIn):
    # written by other screens: the mapping (B2), groups (A3) and controls (A4)
    column_mapping: dict = Field(default_factory=dict)
    channel_groups: list[list[str]] = Field(default_factory=list)
    controls: list[str] = Field(default_factory=list)
    gate_thresholds: dict = Field(default_factory=dict)
```

Crie `api/routes/engine.py`:

```python
from fastapi import APIRouter, Depends

from api.auth import active_user
from api.engine_config import ParamsIn
from api.models import User

router = APIRouter(prefix="/api/engine")


@router.get("/config-schema")
def config_schema(_: User = Depends(active_user)) -> dict:
    return ParamsIn.model_json_schema()
```

Em `api/main.py`, troque `from api.routes import admin, members, simulations` por `from api.routes import admin, engine, members, simulations` e acrescente, depois de `app.include_router(simulations.router)`:

```python
    app.include_router(engine.router)
```

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest tests/api/test_params.py tests/api/test_rbac.py -q`
Expected: PASS (a matriz leva ~2 min).

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock api/engine_config.py api/routes/engine.py api/main.py tests/api/test_params.py tests/api/test_rbac.py
git commit -m "feat(api): add a provisional engine config and its json schema route"
```

---

### Task 2: Sugestões dos dados

**Files:**
- Modify: `api/csvfile.py`, `api/simulations.py`, `api/routes/simulations.py`, `tests/api/test_rbac.py`, `tests/api/test_params.py`
- Create: `api/suggestions.py`

- [ ] **Step 1: Escrever os testes**

No topo de `tests/api/test_params.py`, troque os imports por:

```python
from datetime import date, timedelta

import pytest

from api import simulations, suggestions
from api.engine_config import EngineConfig, ParamsIn
from tests.samples import INVESTMENT, MAPPING, PERFORMANCE
```

E acrescente ao fim do arquivo:

```python
@pytest.fixture
def mapped(db, ws, analyst, make_simulation):
    simulation = make_simulation(ws, analyst, files={"investment": INVESTMENT, "performance": PERFORMANCE})
    simulations.save_mapping(db, simulation, MAPPING)
    return simulation


def days(n, step=1):
    return [date(2024, 1, 1) + timedelta(days=i * step) for i in range(n)]


def from_performance(tmp_path, dates, kpi="conversoes"):
    path = tmp_path / "performance.csv"
    path.write_text(f"data,{kpi}\n" + "".join(f"{d.isoformat()},10\n" for d in dates), encoding="utf-8")
    return suggestions.from_data({"performance_file": path}, {"performance_file": {"date_col": "data", "kpi_col": kpi}})


@pytest.mark.parametrize(
    "dates, value, reason",
    [
        (days(200), 50, "Um quarto dos 200 dias de histórico."),
        (days(400), 90, "Teto para série diária: um quarto dos 400 dias passaria disso."),
        (days(3), 28, "Mínimo para série diária: o histórico tem só 3 dias."),
        (days(100, step=7), 175, "Um quarto dos 700 dias de histórico."),
        (days(20, step=7), 56, "Mínimo para série semanal: o histórico tem só 140 dias."),
    ],
)
def test_pre_period_is_a_quarter_of_the_history_within_the_cadence_bounds(tmp_path, dates, value, reason):
    got = from_performance(tmp_path, dates)["min_pre_period_days"]

    assert got == {"value": value, "reason": reason, "source": "dados"}


def test_unknown_cadence_or_unreadable_dates_suggest_no_pre_period(tmp_path):
    assert "min_pre_period_days" not in from_performance(tmp_path, days(30, step=3))
    path = tmp_path / "br.csv"
    path.write_text("data,conversoes\n01/01/2024,1\n02/01/2024,2\n", encoding="utf-8")
    got = suggestions.from_data({"performance_file": path}, {"performance_file": {"date_col": "data", "kpi_col": "conversoes"}})
    assert "min_pre_period_days" not in got


@pytest.mark.parametrize(
    "kpi, target, monetary",
    [("Receita Líquida", "REVENUE", True), ("conversões", "CONVERSIONS", False), ("pedidos", "CONVERSIONS", False)],
)
def test_kpi_column_name_suggests_the_target(tmp_path, kpi, target, monetary):
    got = from_performance(tmp_path, days(10), kpi=kpi)

    assert got["optimization_target"]["value"] == target
    assert got["kpi_is_monetary"]["value"] is monetary
    assert f"'{kpi}'" in got["optimization_target"]["reason"]


def test_unknown_kpi_name_suggests_no_target(tmp_path):
    got = from_performance(tmp_path, days(10), kpi="kpi")

    assert "optimization_target" not in got and "kpi_is_monetary" not in got


def test_suggestions_route_reads_the_uploaded_files(logged, mapped):
    body = logged.get(f"/api/w/a/simulations/{mapped.id}/suggestions").json()

    assert body["min_pre_period_days"]["value"] == 28
    assert body["optimization_target"] == {
        "value": "CONVERSIONS",
        "reason": "A coluna de KPI se chama 'conversoes', uma contagem de conversões.",
        "source": "dados",
    }


def test_suggestions_need_a_confirmed_mapping(logged, analyst, ws, mapped, make_simulation):
    bare = make_simulation(ws, analyst, files={"investment": INVESTMENT, "performance": PERFORMANCE})
    assert logged.get(f"/api/w/a/simulations/{bare.id}/suggestions").status_code == 422

    logged.put(
        f"/api/w/a/simulations/{mapped.id}/files/investment",
        files={"file": ("investimento.csv", INVESTMENT, "text/csv")},
    )
    r = logged.get(f"/api/w/a/simulations/{mapped.id}/suggestions")
    assert (r.status_code, r.json()) == (422, {"detail": "Confirme o mapeamento de colunas antes."})


def test_suggestions_of_another_workspace_are_404(logged, analyst, make_workspace, make_simulation):
    foreign = make_simulation(make_workspace("b", [(analyst, "analyst")]), analyst)

    assert logged.get(f"/api/w/a/simulations/{foreign.id}/suggestions").status_code == 404
```

Em `tests/api/test_rbac.py`:

1. No `ROUTES`, depois da linha do `mapping`, acrescente:

```python
    ("GET", "/api/w/{slug}/simulations/{simulation_id}/suggestions"): ("analyst", 200, None),
```

2. A simulação do `env` precisa de mapeamento confirmado. Troque a fixture `env` por:

```python
@pytest.fixture
def env(db, make_user, make_workspace, make_simulation, password):
    users = {role: make_user(f"{role}@x.com") for role in ("viewer", "analyst", "admin")}
    users["platform"] = make_user("platform@x.com", platform=True)
    target = make_user("target@x.com")
    make_user("fora@x.com")
    ws = make_workspace("a", [(users[r], r) for r in ("viewer", "analyst", "admin")] + [(target, "viewer")])
    simulation = make_simulation(ws, users["analyst"], files={"investment": INVESTMENT, "performance": PERFORMANCE})
    simulations.save_mapping(db, simulation, MAPPING)
    return {"users": users, "target": target, "password": password, "simulation": simulation}
```

e acrescente `from api import simulations` aos imports do arquivo.

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/api/test_params.py -q`
Expected: FAIL na coleta com `ImportError: cannot import name 'suggestions' from 'api'`.

- [ ] **Step 3: Mover `normalize` para o `csvfile`**

`suggestions.py` precisa de `normalize`, e `simulations.py` vai importar `suggestions`: deixar `normalize` em `simulations.py` criaria import circular. Em `api/simulations.py`, apague a função `normalize` e o `import unicodedata`, e troque a chamada em `suggest_mapping` por `csvfile.normalize(c)`. No fim de `api/csvfile.py`, acrescente `import unicodedata` no topo e:

```python
def normalize(column: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", column.lower()) if c.isalnum())
```

Run: `uv run pytest tests/api/test_simulations.py -q -k suggest`
Expected: PASS (o `suggest_mapping` continua igual).

- [ ] **Step 4: Escrever `api/suggestions.py`**

```python
import statistics
from collections.abc import Iterator
from datetime import date
from pathlib import Path

from api import csvfile

# history step in days -> (label, lowest, highest pre-period in days)
PRE_PERIOD = {1: ("diária", 28, 90), 7: ("semanal", 56, 182)}
# stems of the normalized KPI column name
MONETARY = ("receita", "revenue", "faturamento", "gmv", "valor")
CONVERSIONS = ("convers", "venda", "pedido", "lead")


def suggestion(value, reason: str) -> dict:
    return {"value": value, "reason": reason, "source": "dados"}


def columns(path: Path, *names: str) -> Iterator[list[str]]:
    rows = csvfile.rows(path)
    header = [c.strip() for c in next(rows)]
    at = [header.index(n) for n in names]
    for row in rows:
        if len(row) > max(at):
            yield [row[i].strip() for i in at]


def parse_date(text: str) -> date | None:
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def history(path: Path, date_col: str) -> tuple[int | None, list[date]]:
    """(step in days if daily or weekly, sorted distinct dates); unreadable dates are skipped."""
    dates = sorted({d for (text,) in columns(path, date_col) if (d := parse_date(text))})
    gaps = [(b - a).days for a, b in zip(dates, dates[1:])]
    step = statistics.median(gaps) if gaps else None
    return (int(step) if step in PRE_PERIOD else None), dates


def pre_period(step: int, dates: list[date]) -> dict:
    label, lowest, highest = PRE_PERIOD[step]
    span = (dates[-1] - dates[0]).days + step
    quarter = span // 4
    if quarter < lowest:
        return suggestion(lowest, f"Mínimo para série {label}: o histórico tem só {span} dias.")
    if quarter > highest:
        return suggestion(highest, f"Teto para série {label}: um quarto dos {span} dias passaria disso.")
    return suggestion(quarter, f"Um quarto dos {span} dias de histórico.")


def from_data(paths: dict[str, Path | None], mapping: dict) -> dict[str, dict]:
    performance = mapping["performance_file"]
    found = {}
    step, dates = history(paths["performance_file"], performance["date_col"])
    if step:
        found["min_pre_period_days"] = pre_period(step, dates)

    kpi = csvfile.normalize(performance["kpi_col"])
    name = performance["kpi_col"]
    if any(stem in kpi for stem in MONETARY):
        reason = f"A coluna de KPI se chama '{name}', um valor em dinheiro."
        found["optimization_target"] = suggestion("REVENUE", reason)
        found["kpi_is_monetary"] = suggestion(True, reason)
    elif any(stem in kpi for stem in CONVERSIONS):
        reason = f"A coluna de KPI se chama '{name}', uma contagem de conversões."
        found["optimization_target"] = suggestion("CONVERSIONS", reason)
        found["kpi_is_monetary"] = suggestion(False, reason)
    return found
```

- [ ] **Step 5: Serviço e rota**

Em `api/simulations.py`, acrescente `suggestions` ao import (`from api import csvfile, storage, suggestions, validation`) e, depois de `input_key`:

```python
def input_paths(simulation: Simulation) -> dict[str, Path | None]:
    files = {f.kind: f for f in simulation.files}
    return {
        key: storage.path(input_key(simulation, files[kind].sha256)) if kind in files else None
        for key, kind in MAPPING_FILES.items()
    }


def require_mapping(simulation: Simulation) -> dict:
    # every upload resets the report: no report means the mapping wasn't confirmed for these files
    if simulation.validation is None:
        raise InvalidInput("Confirme o mapeamento de colunas antes.")
    return simulation.config["column_mapping"]


def suggest_params(simulation: Simulation) -> dict[str, dict]:
    mapping = require_mapping(simulation)
    try:
        return suggestions.from_data(input_paths(simulation), mapping)
    except csvfile.Unreadable:
        raise InvalidInput("Não foi possível ler o arquivo de performance.")
```

Em `save_mapping`, troque o bloco que monta `inputs` por `inputs = input_paths(simulation)`.

Em `api/routes/simulations.py`, acrescente ao fim:

```python
@router.get("/{simulation_id}/suggestions")
def get_suggestions(simulation_id: SimulationId, ctx: Ctx = Depends(analyst), db: Session = Depends(get_db)) -> dict:
    try:
        return simulations.suggest_params(find_simulation(db, ctx, simulation_id))
    except simulations.InvalidInput as e:
        raise HTTPException(422, str(e))
```

- [ ] **Step 6: Rodar e ver passar**

Run: `uv run pytest tests/api/test_params.py tests/api/test_simulations.py -q`
Expected: PASS.

Run: `uv run pytest tests/api/test_rbac.py -q` (~2 min)
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add api/csvfile.py api/simulations.py api/suggestions.py api/routes/simulations.py tests/api/test_params.py tests/api/test_rbac.py
git commit -m "feat(api): suggest pre-period and target from the uploaded files"
```

---

### Task 3: Sugestão do Gemini

**Files:**
- Create: `api/gemini.py`
- Modify: `api/suggestions.py`, `api/simulations.py`, `api/routes/simulations.py`, `tests/conftest.py`, `tests/api/test_params.py`, `tests/api/test_rbac.py`

- [ ] **Step 1: Escrever os testes**

Em `tests/conftest.py`, acrescente depois da fixture `fast_scrypt`:

```python
@pytest.fixture(autouse=True)
def no_gemini_key(monkeypatch):
    # tests never reach the real API; the ones that need an answer replace gemini.ask
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
```

Em `tests/api/test_params.py`, acrescente `import json` no topo e `gemini` ao import de `api` (`from api import gemini, simulations, suggestions`). No fim do arquivo:

```python
def answer(*items):
    return lambda prompt, schema: json.dumps({"suggestions": [dict(zip(("field", "value", "reason"), i)) for i in items]})


def test_gemini_suggestions_come_validated_with_their_reason(logged, mapped, monkeypatch):
    monkeypatch.setattr(
        gemini,
        "ask",
        answer(
            ("investment_limit_factor", "2", "Os canais ainda têm folga."),
            ("financial_targets.target_cpa", "35.5", "CPA médio do período."),
            ("max_budget_step", "7", "Fora do limite."),
            ("column_mapping", "{}", "Campo que não é do formulário."),
        ),
    )

    r = logged.post(f"/api/w/a/simulations/{mapped.id}/suggestions/gemini")

    assert r.status_code == 200
    assert r.json() == {
        "available": True,
        "suggestions": {
            "investment_limit_factor": {"value": 2.0, "reason": "Os canais ainda têm folga.", "source": "gemini"},
            "financial_targets.target_cpa": {"value": 35.5, "reason": "CPA médio do período.", "source": "gemini"},
        },
    }


def test_gemini_prompt_carries_a_summary_and_no_rows(logged, mapped, monkeypatch):
    prompts = []

    def ask(prompt, schema):
        prompts.append(prompt)
        return json.dumps({"suggestions": []})

    monkeypatch.setattr(gemini, "ask", ask)
    logged.post(f"/api/w/a/simulations/{mapped.id}/suggestions/gemini")

    assert "SEARCH" in prompts[0] and "conversoes" in prompts[0]
    for line in (INVESTMENT + PERFORMANCE).decode().splitlines():
        if line[:1].isdigit():
            assert line not in prompts[0]


def sdk_error(prompt, schema):
    raise gemini.Unavailable("Timeout")


@pytest.mark.parametrize(
    "ask",
    [None, sdk_error, lambda prompt, schema: "isto não é json"],
    ids=["no key", "sdk error", "bad answer"],
)
def test_gemini_unavailable_answers_200_and_nothing(logged, mapped, monkeypatch, ask):
    if ask:
        monkeypatch.setattr(gemini, "ask", ask)

    r = logged.post(f"/api/w/a/simulations/{mapped.id}/suggestions/gemini")

    assert (r.status_code, r.json()) == (200, {"available": False, "suggestions": {}})


def test_gemini_needs_a_confirmed_mapping(logged, analyst, ws, make_simulation):
    bare = make_simulation(ws, analyst, files={"investment": INVESTMENT, "performance": PERFORMANCE})

    assert logged.post(f"/api/w/a/simulations/{bare.id}/suggestions/gemini").status_code == 422
```

Em `tests/api/test_rbac.py`, no `ROUTES`, depois da linha das `suggestions`:

```python
    ("POST", "/api/w/{slug}/simulations/{simulation_id}/suggestions/gemini"): ("analyst", 200, None),
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/api/test_params.py -q -k gemini`
Expected: FAIL na coleta com `ImportError: cannot import name 'gemini' from 'api'`.

- [ ] **Step 3: Escrever `api/gemini.py`**

```python
import os

from google import genai
from google.genai import types

# alias that follows the current Flash model; pin a version if the suggestions start drifting
MODEL = "gemini-flash-latest"
TIMEOUT_MS = 20_000


class Unavailable(Exception):
    pass


def ask(prompt: str, response_schema: dict) -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise Unavailable("no_key")
    client = genai.Client(api_key=key, http_options=types.HttpOptions(timeout=TIMEOUT_MS))
    try:
        response = client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json", response_json_schema=response_schema, temperature=0.2
            ),
        )
    except Exception as e:  # noqa: BLE001 - any SDK or network failure falls back to the data suggestions
        raise Unavailable(type(e).__name__) from e
    return response.text or ""
```

- [ ] **Step 4: Resumo, prompt e validação em `api/suggestions.py`**

Acrescente aos imports:

```python
import json
import logging
from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, ValidationError

from api import csvfile, gemini
from api.engine_config import ParamsIn
```

(o `from api import csvfile` antigo some, substituído pela linha acima) e, abaixo dos imports, `log = logging.getLogger(__name__)`. No fim do arquivo:

```python
def field_paths(model: type[BaseModel] = ParamsIn, prefix: str = "") -> list[str]:
    paths = []
    for name, field in model.model_fields.items():
        if isinstance(field.annotation, type) and issubclass(field.annotation, BaseModel):
            paths += field_paths(field.annotation, f"{prefix}{name}.")
        else:
            paths.append(prefix + name)
    return paths


PARAM_PATHS = tuple(field_paths())


class GeminiSuggestion(BaseModel):
    field: Literal[PARAM_PATHS]
    # a string so the schema stays simple; ParamsIn coerces "2" or "true" to the field's type
    value: str
    reason: str


class GeminiAnswer(BaseModel):
    suggestions: list[GeminiSuggestion]


PROMPT = """Você ajuda um analista de mídia a configurar uma análise de investimento em mídia.
Com base no resumo dos dados abaixo, sugira valores para os parâmetros do schema que dá para justificar com esses dados.
Para cada sugestão, explique em uma frase curta, em português do Brasil, por que o valor faz sentido.
Não sugira o que o resumo não justifica.

Resumo dos dados:
{summary}

Schema dos parâmetros:
{schema}
"""


def number(text: str) -> float | None:
    # exports come as "1.234,56" (pt-BR) or "1234.56"
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    try:
        return float(text)
    except ValueError:
        return None


def summary(paths: dict[str, Path | None], mapping: dict) -> dict:
    """Aggregates only: no row of the client's files leaves the platform."""
    investment, performance = mapping["investment_file"], mapping["performance_file"]
    spend = defaultdict(float)
    for channel, value in columns(paths["investment_file"], investment["channel_col"], investment["investment_col"]):
        if (n := number(value)) is not None:
            spend[channel] += n
    kpi = [n for (value,) in columns(paths["performance_file"], performance["kpi_col"]) if (n := number(value)) is not None]
    step, dates = history(paths["performance_file"], performance["date_col"])
    total = sum(spend.values())
    return {
        "kpi_column": performance["kpi_col"],
        "cadence": {1: "daily", 7: "weekly"}.get(step),
        "period": [dates[0].isoformat(), dates[-1].isoformat()] if dates else None,
        "total_investment": round(total, 2),
        "channels": [
            {"name": channel, "investment_share_pct": round(100 * s / total, 1) if total else 0}
            for channel, s in sorted(spend.items())
        ],
        "kpi": {"min": min(kpi), "mean": round(statistics.fmean(kpi), 2), "max": max(kpi)} if kpi else None,
    }


def checked(path: str, value: str):
    """The value coerced by ParamsIn; raises ValidationError when the field rejects it."""
    params = ParamsIn().model_dump()
    *parents, leaf = path.split(".")
    node = params
    for key in parents:
        node = node[key]
    node[leaf] = value
    valid = ParamsIn.model_validate(params).model_dump(mode="json")
    for key in parents:
        valid = valid[key]
    return valid[leaf]


def from_gemini(paths: dict[str, Path | None], mapping: dict) -> dict[str, dict] | None:
    """None when Gemini can't answer; the form keeps the data suggestions."""
    prompt = PROMPT.format(
        summary=json.dumps(summary(paths, mapping), ensure_ascii=False),
        schema=json.dumps(ParamsIn.model_json_schema(), ensure_ascii=False),
    )
    try:
        items = json.loads(gemini.ask(prompt, GeminiAnswer.model_json_schema()))["suggestions"]
    except gemini.Unavailable as e:
        log.warning("simulation.gemini_unavailable reason=%s", e)
        return None
    except (ValueError, KeyError, TypeError):
        log.warning("simulation.gemini_unavailable reason=bad_answer")
        return None

    found = {}
    # one by one: a bad item drops only itself, not the whole answer
    for item in items:
        try:
            s = GeminiSuggestion.model_validate(item)
            value = checked(s.field, s.value)
        except ValidationError:
            log.info("simulation.gemini_dropped field=%r", item.get("field") if isinstance(item, dict) else None)
            continue
        found[s.field] = {"value": value, "reason": s.reason[:300], "source": "gemini"}
    return found
```

- [ ] **Step 5: Serviço e rota**

Em `api/simulations.py`, depois de `suggest_params`:

```python
def gemini_params(simulation: Simulation) -> dict[str, dict] | None:
    mapping = require_mapping(simulation)
    try:
        return suggestions.from_gemini(input_paths(simulation), mapping)
    except csvfile.Unreadable:
        raise InvalidInput("Não foi possível ler os arquivos da simulação.")
```

Em `api/routes/simulations.py`, no fim:

```python
@router.post("/{simulation_id}/suggestions/gemini")
def gemini_suggestions(simulation_id: SimulationId, ctx: Ctx = Depends(analyst), db: Session = Depends(get_db)) -> dict:
    try:
        found = simulations.gemini_params(find_simulation(db, ctx, simulation_id))
    except simulations.InvalidInput as e:
        raise HTTPException(422, str(e))
    return {"available": found is not None, "suggestions": found or {}}
```

- [ ] **Step 6: Rodar e ver passar**

Run: `uv run pytest tests/api/test_params.py -q`
Expected: PASS.

Run: `uv run pytest tests/api/test_rbac.py -q` (~2 min)
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add api/gemini.py api/suggestions.py api/simulations.py api/routes/simulations.py tests/conftest.py tests/api/test_params.py tests/api/test_rbac.py
git commit -m "feat(api): ask gemini for parameter suggestions from an aggregate summary"
```

---

### Task 4: Salvar os parâmetros

**Files:**
- Modify: `api/simulations.py`, `api/routes/simulations.py`, `tests/api/test_params.py`, `tests/api/test_rbac.py`

- [ ] **Step 1: Escrever os testes**

No fim de `tests/api/test_params.py`:

```python
def test_params_are_saved_with_defaults_and_keep_the_mapping(logged, mapped):
    url = f"/api/w/a/simulations/{mapped.id}"

    r = logged.put(f"{url}/params", json={"investment_limit_factor": 2, "financial_targets": {"target_cpa": 30}})

    assert r.status_code == 200
    config = r.json()["config"]
    assert config["column_mapping"] == MAPPING
    assert config["investment_limit_factor"] == 2.0 and config["max_budget_step"] == 0.2
    assert config["financial_targets"] == {"target_cpa": 30.0, "target_icpa": None, "target_roas": None, "target_iroas": None}
    assert r.json()["validation"] is not None

    remapped = logged.put(f"{url}/mapping", json=MAPPING).json()
    assert remapped["config"]["investment_limit_factor"] == 2.0


@pytest.mark.parametrize(
    "body, loc, kind",
    [
        ({"investment_limit_factor": 1}, ["body", "investment_limit_factor"], "greater_than"),
        ({"financial_targets": {"target_cpa": -1}}, ["body", "financial_targets", "target_cpa"], "greater_than"),
        ({"optimization_target": "CLICKS"}, ["body", "optimization_target"], "literal_error"),
        ({"column_mapping": {}}, ["body", "column_mapping"], "extra_forbidden"),
    ],
)
def test_invalid_params_are_422_with_the_field(logged, mapped, body, loc, kind):
    r = logged.put(f"/api/w/a/simulations/{mapped.id}/params", json=body)

    assert r.status_code == 422
    assert [(e["loc"], e["type"]) for e in r.json()["detail"]] == [(loc, kind)]


def test_params_need_a_confirmed_mapping(logged, analyst, ws, make_simulation):
    bare = make_simulation(ws, analyst, files={"investment": INVESTMENT, "performance": PERFORMANCE})

    r = logged.put(f"/api/w/a/simulations/{bare.id}/params", json={})

    assert (r.status_code, r.json()) == (422, {"detail": "Confirme o mapeamento de colunas antes."})
```

Em `tests/api/test_rbac.py`, no `ROUTES`, depois da linha do Gemini:

```python
    ("PUT", "/api/w/{slug}/simulations/{simulation_id}/params"): ("analyst", 200, lambda e: {}),
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/api/test_params.py -q -k params`
Expected: FAIL nos testes de params com `assert 404 == 200` (a rota ainda não existe).

- [ ] **Step 3: Serviço e rota**

Em `api/simulations.py`, depois de `save_mapping`:

```python
def save_params(db: Session, simulation: Simulation, params: dict) -> None:
    lock(db, simulation)
    mapping = require_mapping(simulation)
    # the parameters never touch the report: the stand-in validate reads only the mapping
    simulation.config = {**params, "column_mapping": mapping}
    simulation.updated_at = func.now()
    db.commit()
    log.info("simulation.params_saved simulation_id=%s", simulation.id)
```

Em `api/routes/simulations.py`, acrescente `from api.engine_config import ParamsIn` aos imports e, no fim:

```python
@router.put("/{simulation_id}/params", response_model=SimulationOut)
def save_params(simulation_id: SimulationId, body: ParamsIn, ctx: Ctx = Depends(analyst), db: Session = Depends(get_db)):
    simulation = find_simulation(db, ctx, simulation_id)
    try:
        simulations.save_params(db, simulation, body.model_dump(mode="json"))
    except simulations.InvalidInput as e:
        raise HTTPException(422, str(e))
    return simulation_out(simulation)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/api/test_params.py -q`
Expected: PASS.

Run: `uv run ruff check . && uv run ruff format --check .`
Expected: `All checks passed!` e nenhum arquivo para reformatar (rode `uv run ruff format .` se precisar).

Run: `uv run pytest -q` (suíte inteira, ~3 min; use timeout de 10 min)
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/simulations.py api/routes/simulations.py tests/api/test_params.py tests/api/test_rbac.py
git commit -m "feat(api): save simulation parameters validated by the engine config"
```

---

### Task 5: Documentação

**Files:**
- Modify: `API-GUIDE.md`, `docs/m2/README.md`, `docs/m2/trilha-b-plataforma.md`, `docs/decisoes/README.md`, `.env.example`, `CLAUDE.md`
- Create: `docs/decisoes/parametros-e-gemini.md`

- [ ] **Step 1: `API-GUIDE.md`**

Na tabela de rotas, depois da linha do `PUT …/mapping`:

```markdown
| GET | `/api/engine/config-schema` | Sessão ativa. JSON Schema do `ParamsIn` (campos do formulário de parâmetros, com defaults e limites) |
| GET | `/api/w/{slug}/simulations/{simulation_id}/suggestions` | Analyst+. `{campo: {value, reason, source: "dados"}}` tirado dos arquivos; campo com ponto (`financial_targets.target_cpa`). 422 sem mapeamento confirmado para os arquivos atuais |
| POST | `/api/w/{slug}/simulations/{simulation_id}/suggestions/gemini` | Analyst+. `{available, suggestions: {campo: {value, reason, source: "gemini"}}}`; Gemini sem chave, fora do ar ou com resposta ruim → 200 `available: false`. 422 sem mapeamento confirmado |
| PUT | `/api/w/{slug}/simulations/{simulation_id}/params` | Analyst+. `ParamsIn` → `SimulationOut`; grava em `config` com os defaults e preserva o `column_mapping`; não mexe no `validation`. 422 do pydantic com `loc` por campo; 422 sem mapeamento confirmado |
```

E troque `Os demais entram com B3 (sugestão de parâmetros), B4` por `Os demais entram com B4`.

- [ ] **Step 2: `docs/decisoes/parametros-e-gemini.md`**

```markdown
# Parâmetros e sugestão do Gemini

Decisões do B3, 26/out/2026. Spec: `docs/superpowers/specs/2026-10-26-b3-parametros-gemini-design.md`.

## `EngineConfig` provisório em `api/`

O A0 ainda não entregou o `engine/`, e o B3 e o B4 dependem do config. `api/engine_config.py` define `ParamsIn` (os campos do formulário) e `EngineConfig` (`ParamsIn` + `column_mapping`, `channel_groups`, `controls`, `gate_thresholds`) com os campos do contrato §1. Os nomes `require_significance`/`require_good_fit` e os defaults causais foram escolhidos aqui e são provisórios: o A0 decide. Quando o `engine/config.py` existir, o arquivo vira import de lá. Mesmo caminho do `validate` falso do B2.

## Rotas sob o workspace e schema fora dele

O trilha-b citava `POST /api/simulations/{id}/suggest`. Dado de cliente fica sob `/api/w/{slug}/…` (regra do `API-GUIDE.md`), então sugestões e params ficam lá. O schema é o mesmo para todos e não é dado de cliente: `/api/engine/config-schema`, com cache infinito no front.

## Sugestão dos dados escrita do zero

O time não tem acesso ao `suggest_causal_config` do protótipo. O B3 sugere só o que sai dos arquivos com regra simples: `min_pre_period_days` (um quarto do histórico, entre 28 e 90 dias se diário, entre 56 e 182 se semanal) e `optimization_target`/`kpi_is_monetary` pelo nome da coluna de KPI. Cadência estranha, data fora do ISO ou nome de KPI desconhecido não sugerem nada: o campo fica no default, sem selo. As sugestões exigem `validation` presente, porque todo upload zera o report e o mapeamento salvo pode apontar para coluna que o arquivo novo não tem.

## O Gemini só vê agregados

O BRD é confidencial e os arquivos são dados de mídia das marcas. O prompt leva nomes de colunas, cadência, período, investimento total, participação por canal e mínimo/média/máximo do KPI; nenhuma linha. O teste `test_gemini_prompt_carries_a_summary_and_no_rows` garante isso. Prompt e resposta nunca vão para o log.

## Resposta do Gemini validada item a item

A saída estruturada pede `{field, value, reason}` com `value` em string, e cada item passa pelo `ParamsIn`: valor fora do limite ou campo que não é do formulário cai sozinho, sem derrubar os outros. Sem chave (`GEMINI_API_KEY`), com erro do SDK, timeout de 20 s ou resposta ilegível, a rota responde 200 com `available: false`: a tela segue com as sugestões dos dados (aceite do BRD). O modelo é o alias `gemini-flash-latest`; fixar uma versão se as sugestões mudarem de comportamento. A chave sai da variável de ambiente até o B11 trazer o Secret Manager.

## Parâmetros não zeram a validação

O `validate` falso só lê o `column_mapping`, que o formulário não toca. Quando o `validate` real (A2) passar a depender de outro campo, o `PUT …/params` passa a zerar o report.
```

Em `docs/decisoes/README.md`, acrescente à tabela:

```markdown
| [parametros-e-gemini.md](parametros-e-gemini.md) | `EngineConfig` provisório, rotas de sugestão, sugestão dos dados, o que o Gemini vê, validação das respostas |
```

- [ ] **Step 3: Contrato, env e trilha**

Em `docs/m2/README.md` › contrato §1, acrescente ao fim do parágrafo do `EngineConfig`:

```markdown
Até o A0, a API usa um `EngineConfig` provisório em `api/engine_config.py` (B3), com `require_significance` e `require_good_fit` como nomes dos `require_*` e defaults causais `p_value_threshold=0.05`, `min_pre_period_days=28`, `r_squared_threshold=0.5`, `increase/decrease_threshold_percent=20`. O A0 decide os definitivos e avisa a trilha B.
```

Em `.env.example`, no fim:

```
# Chave do Gemini para as sugestões de parâmetros (sem ela, só as sugestões dos dados). Secret Manager no B11
# GEMINI_API_KEY=
```

Em `docs/m2/trilha-b-plataforma.md`, logo abaixo do título `## B3 · …`, acrescente:

```markdown
- **Status:** 🟡 B3a (backend) feito em <data>, verificado por `tests/api/test_params.py` e `tests/api/test_rbac.py`; B3b (tela) pendente. Desvios em `docs/decisoes/parametros-e-gemini.md`.
```

(troque `<data>` pela data do commit, no formato `26/out/2026`).

- [ ] **Step 4: `CLAUDE.md`**

No bloco `## Estrutura`, debaixo de `simulations.py`, acrescente:

```
  engine_config.py EngineConfig provisório até o A0 (vira `from engine.config import …`)
  suggestions.py  sugestões de parâmetros: regras dos dados, resumo e validação do Gemini
  gemini.py       chamada ao Gemini (GEMINI_API_KEY); trocada por fake nos testes
```

No parágrafo "Estado atual", depois da frase do B2b, acrescente: `**B3a (parâmetros backend) concluído em <data>**: \`EngineConfig\` provisório, schema em \`/api/engine/config-schema\`, sugestões dos dados e do Gemini (só agregados no prompt), \`PUT …/params\`.` e troque `Faltam, em ordem: B3–B4 (Gemini, jobs)` por `Faltam, em ordem: B3b (tela de parâmetros), B4 (jobs)`.

- [ ] **Step 5: Commit**

```bash
git add API-GUIDE.md docs/m2/README.md docs/m2/trilha-b-plataforma.md docs/decisoes/README.md docs/decisoes/parametros-e-gemini.md .env.example CLAUDE.md
git commit -m "docs: record b3a params backend routes and decisions"
```
