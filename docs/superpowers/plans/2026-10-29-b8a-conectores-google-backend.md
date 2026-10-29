# B8a · Conectores Google Ads e GA4 — backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Platform admin registra por workspace os datasets do DTS do Google Ads e do export do GA4. O analista importa um período e recebe os dois CSV canônicos, já mapeados e validados pelo fluxo do upload.

**Architecture:**
- `api/bigquery.py` (novo) é a única chamada ao BigQuery: `query(sql, params) -> list[dict]`, com teto de bytes, timeout e erros traduzidos. Os testes trocam a função por um fake, como o `gemini.ask`.
- `api/google_import.py` (novo) tem:
  - os modelos do config (o regex do dataset é a defesa contra injeção, porque nome de tabela não pode ser parâmetro);
  - a montagem das duas SQL e a grade com zeros que vira CSV;
  - `run`, que encadeia tudo e entrega aos `simulations.save_file` e `save_mapping` existentes.
- O config mora em `workspaces.settings["google"]`, sem migration.

**Tech Stack:** Python 3.13, FastAPI, SQLAlchemy 2, pydantic 2, `google-cloud-bigquery` (novo), pytest contra Postgres (`docker compose up -d`), `uv`.

Spec: `docs/superpowers/specs/2026-10-29-b8-conectores-google-design.md` (seção B8a). Antes, leia `CODE-STYLE.md`, `API-GUIDE.md`, `DATABASE.md` e `SECURITY.md`.

---

## Arquivos

| Arquivo | Mudança |
|---|---|
| `pyproject.toml`, `uv.lock` | `google-cloud-bigquery` |
| `api/bigquery.py` | **novo**: `query`, `Failed`, `NoAccess`, `NoCredentials` |
| `api/google_import.py` | **novo**: `GoogleConfig`, `Period`, `ads_sql`, `ga4_sql`, `investment_csv`, `performance_csv`, `config_of`, `configure`, `fetch`, `run` |
| `api/routes/__init__.py` | `WorkspaceId` |
| `api/routes/admin.py` | `WorkspaceOut.google`, `PUT`/`DELETE /workspaces/{workspace_id}/google` |
| `api/routes/auth.py` | `MyWorkspace.google` |
| `api/routes/simulations.py` | `POST /{simulation_id}/google-import` |
| `tests/samples.py` | `GOOGLE_CONFIG`, `ADS_ROWS`, `GA4_ROWS`, `GOOGLE_PERIOD` |
| `tests/conftest.py` | fixture `fake_bigquery` |
| `tests/api/test_bigquery.py` | **novo** |
| `tests/api/test_google_import.py` | **novo** |
| `tests/api/test_admin.py` | testes do config |
| `tests/api/test_rbac.py` | três rotas novas |
| `tests/api/test_bigquery_live.py` | **novo**, pulado sem `BIGQUERY_TEST_PROJECT` |
| `tests/bigquery/seed_ads.sql` | **novo**: tabelas no formato das views do DTS |
| docs | fechamento (Task 5) |

Ordem: Task 1 → 2 → 3 em série, porque 2 e 3 mexem no `test_rbac.py` e 3 depende do `configure` da 2. A Task 4 só depende da 1 e pode rodar em paralelo com a 2 e a 3. A Task 5 vem por último.

Antes de começar: `docker compose up -d` e `uv run pytest -q` verde.

---

### Task 1: dependência, `api/bigquery.py` e as partes puras do `api/google_import.py`

**Files:**
- Modify: `pyproject.toml`, `uv.lock` (via `uv add`)
- Create: `api/bigquery.py`
- Create: `api/google_import.py`
- Modify: `tests/samples.py`
- Create: `tests/api/test_bigquery.py`
- Create: `tests/api/test_google_import.py`

- [ ] **Step 1: Adicionar a dependência**

Run: `uv add google-cloud-bigquery`
Expected: `pyproject.toml` ganha `"google-cloud-bigquery>=…"` em `dependencies` e o `uv.lock` é atualizado. Confira com `uv run python -c "from google.cloud import bigquery; print(bigquery.__version__)"`.

- [ ] **Step 2: Escrever os testes de `api/bigquery.py`, que vão falhar**

Crie `tests/api/test_bigquery.py`:

```python
from datetime import date

import pytest
from google.api_core import exceptions
from google.auth.exceptions import DefaultCredentialsError

from api import bigquery


class Row(dict):
    pass


def client_that(raises=None, rows=(), seen=None):
    class Job:
        def result(self, timeout):
            seen["timeout"] = timeout
            return [Row(r) for r in rows]

    class Client:
        def __init__(self):
            if isinstance(raises, DefaultCredentialsError):
                raise raises

        def query(self, sql, job_config):
            if raises is not None:
                raise raises
            seen["sql"], seen["config"] = sql, job_config
            return Job()

    return Client


def test_query_sends_typed_params_with_a_byte_cap(monkeypatch):
    seen = {}
    monkeypatch.setattr(bigquery.bq, "Client", client_that(rows=[{"date": date(2026, 1, 1), "kpi": 3}], seen=seen))

    rows = bigquery.query("SELECT 1", {"start": date(2026, 1, 1), "event": "purchase"})

    assert rows == [{"date": date(2026, 1, 1), "kpi": 3}]
    params = {p.name: (p.type_, p.value) for p in seen["config"].query_parameters}
    assert params == {"start": ("DATE", date(2026, 1, 1)), "event": ("STRING", "purchase")}
    assert seen["config"].maximum_bytes_billed == bigquery.MAX_BYTES_BILLED
    assert seen["timeout"] == bigquery.TIMEOUT_S


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (exceptions.Forbidden("sem acesso"), bigquery.NoAccess),
        (exceptions.NotFound("sem tabela"), bigquery.NoAccess),
        (DefaultCredentialsError("sem adc"), bigquery.NoCredentials),
        (exceptions.BadRequest("bytes billed"), bigquery.Failed),
        (TimeoutError(), bigquery.Failed),
    ],
)
def test_query_errors_become_ours(monkeypatch, error, expected):
    monkeypatch.setattr(bigquery.bq, "Client", client_that(raises=error, seen={}))

    with pytest.raises(expected):
        bigquery.query("SELECT 1", {})
```

`Row(dict)` imita o `google.cloud.bigquery.Row`, que também tem `.items()`.

- [ ] **Step 3: Rodar e ver falhar**

Run: `uv run pytest tests/api/test_bigquery.py -q`
Expected: FAIL com `ImportError: cannot import name 'bigquery' from 'api'`.

- [ ] **Step 4: Implementar `api/bigquery.py`**

```python
import logging
from datetime import date

from google.api_core import exceptions
from google.auth.exceptions import DefaultCredentialsError
from google.cloud import bigquery as bq

log = logging.getLogger(__name__)

# ponytail: 20 GB per query caps the bill; raise it if a real GA4 export needs more
MAX_BYTES_BILLED = 20 * 1024**3
TIMEOUT_S = 60
TYPES = {date: "DATE", str: "STRING"}


class Failed(Exception):
    pass


class NoAccess(Failed):
    pass


class NoCredentials(Failed):
    pass


def query(sql: str, params: dict[str, date | str]) -> list[dict]:
    config = bq.QueryJobConfig(
        query_parameters=[bq.ScalarQueryParameter(name, TYPES[type(v)], v) for name, v in params.items()],
        maximum_bytes_billed=MAX_BYTES_BILLED,
    )
    try:
        # project and credentials come from ADC: GOOGLE_APPLICATION_CREDENTIALS locally, the attached SA on Cloud Run
        rows = bq.Client().query(sql, job_config=config).result(timeout=TIMEOUT_S)
        return [dict(row.items()) for row in rows]
    except (exceptions.Forbidden, exceptions.NotFound) as e:
        log.exception("bigquery.no_access")
        raise NoAccess from e
    except DefaultCredentialsError as e:
        log.exception("bigquery.no_credentials")
        raise NoCredentials from e
    except Exception as e:  # byte cap, timeout, network: the import answers with a message, never a 500
        log.exception("bigquery.failed")
        raise Failed from e
```

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest tests/api/test_bigquery.py -q`
Expected: 6 passed.

- [ ] **Step 6: Amostras compartilhadas**

Acrescente ao fim de `tests/samples.py`:

```python
GOOGLE_CONFIG = {
    "ads": {"dataset": "proj-teste.google_ads", "customer_ids": ["1111111111", "2222222222"]},
    "ga4": {"dataset": "proj-teste.analytics_123", "event": "purchase", "metric": "count"},
}
GOOGLE_PERIOD = {"start": "2026-01-01", "end": "2026-01-03"}
ADS_ROWS = [
    {"date": date(2026, 1, 1), "channel_type": "SEARCH", "spend": 100.0},
    {"date": date(2026, 1, 1), "channel_type": "VIDEO", "spend": 50.5},
    {"date": date(2026, 1, 2), "channel_type": "SEARCH", "spend": 120.0},
    {"date": date(2026, 1, 3), "channel_type": "DISPLAY", "spend": 10.0},
]
GA4_ROWS = [{"date": date(2026, 1, 1), "kpi": 10}, {"date": date(2026, 1, 3), "kpi": 12}]
```

E no topo do arquivo: `from datetime import date`.

- [ ] **Step 7: Escrever os testes das partes puras, que vão falhar**

Crie `tests/api/test_google_import.py`:

```python
from datetime import date, timedelta

import pytest
from pydantic import ValidationError

from api import google_import, simulations
from api.google_import import Ga4Config, GoogleConfig, Period
from tests.samples import ADS_ROWS, GA4_ROWS, GOOGLE_CONFIG

PERIOD = Period(start=date(2026, 1, 1), end=date(2026, 1, 3))


def test_investment_csv_fills_every_day_and_channel_with_zero():
    content, channels = google_import.investment_csv(ADS_ROWS, PERIOD)

    assert channels == ["DISPLAY", "SEARCH", "YOUTUBE"]
    assert content.decode() == (
        "data,canal,investimento\n"
        "2026-01-01,DISPLAY,0.0\n2026-01-01,SEARCH,100.0\n2026-01-01,YOUTUBE,50.5\n"
        "2026-01-02,DISPLAY,0.0\n2026-01-02,SEARCH,120.0\n2026-01-02,YOUTUBE,0.0\n"
        "2026-01-03,DISPLAY,10.0\n2026-01-03,SEARCH,0.0\n2026-01-03,YOUTUBE,0.0\n"
    )


def test_investment_csv_maps_fixed_channels_and_keeps_the_rest_by_name():
    rows = [
        {"date": date(2026, 1, 1), "channel_type": t, "spend": 1.0}
        for t in ("SEARCH", "PERFORMANCE_MAX", "VIDEO", "DEMAND_GEN", "SHOPPING", None)
    ]

    _, channels = google_import.investment_csv(rows, Period(start=date(2026, 1, 1), end=date(2026, 1, 1)))

    assert channels == ["DEMAND_GEN", "PMAX", "SEARCH", "SHOPPING", "UNKNOWN", "YOUTUBE"]


def test_investment_csv_sums_rows_that_land_on_the_same_day_and_channel():
    rows = [{"date": date(2026, 1, 1), "channel_type": "SEARCH", "spend": 0.1}] * 3

    content, _ = google_import.investment_csv(rows, Period(start=date(2026, 1, 1), end=date(2026, 1, 1)))

    assert content.decode().splitlines()[1] == "2026-01-01,SEARCH,0.3"


@pytest.mark.parametrize("rows", [[], [{"date": date(2026, 1, 1), "channel_type": "SEARCH", "spend": 0.0}]])
def test_investment_csv_without_spend_is_invalid(rows):
    with pytest.raises(simulations.InvalidInput, match="Nenhum investimento no Google Ads neste período."):
        google_import.investment_csv(rows, PERIOD)


def test_performance_csv_fills_missing_days_and_null_revenue_with_zero():
    rows = [*GA4_ROWS, {"date": date(2026, 1, 2), "kpi": None}]

    content = google_import.performance_csv(rows, PERIOD, "purchase")

    assert content.decode() == "data,kpi\n2026-01-01,10\n2026-01-02,0\n2026-01-03,12\n"


def test_performance_csv_without_events_is_invalid():
    with pytest.raises(simulations.InvalidInput, match="Nenhum evento 'purchase' no GA4 neste período."):
        google_import.performance_csv([], PERIOD, "purchase")


def test_ads_sql_reads_each_account_and_keeps_dates_as_params():
    sql = google_import.ads_sql(GoogleConfig.model_validate(GOOGLE_CONFIG).ads)

    for cid in ("1111111111", "2222222222"):
        assert f"`proj-teste.google_ads.ads_CampaignBasicStats_{cid}`" in sql
        assert f"`proj-teste.google_ads.ads_Campaign_{cid}`" in sql
    assert sql.count("UNION ALL") == 1
    assert "c._DATA_DATE = c._LATEST_DATE" in sql
    assert "2026" not in sql and "@start" in sql and "@end" in sql


@pytest.mark.parametrize(("metric", "expression"), [("count", "COUNT(*)"), ("revenue", "SUM(ecommerce.purchase_revenue)")])
def test_ga4_sql_picks_the_metric_and_keeps_the_event_as_param(metric, expression):
    sql = google_import.ga4_sql(Ga4Config(dataset="proj-teste.analytics_123", event="purchase", metric=metric))

    assert "`proj-teste.analytics_123.events_*`" in sql
    assert expression in sql
    assert "purchase'" not in sql and "@event" in sql and "@start_suffix" in sql


@pytest.mark.parametrize(
    "change",
    [
        {"ads": {"dataset": "proj-teste.ds`; DROP TABLE x; --", "customer_ids": ["1111111111"]}},
        {"ads": {"dataset": "proj-teste.ds x", "customer_ids": ["1111111111"]}},
        {"ads": {"dataset": "semponto", "customer_ids": ["1111111111"]}},
        {"ads": {"dataset": "proj-teste.ds", "customer_ids": ["123-456-7890"]}},
        {"ads": {"dataset": "proj-teste.ds", "customer_ids": ["abcdefghij"]}},
        {"ads": {"dataset": "proj-teste.ds", "customer_ids": []}},
        {"ads": {"dataset": "proj-teste.ds", "customer_ids": ["1111111111", "1111111111"]}},
        {"ads": {"dataset": "proj-teste.ds", "customer_ids": [str(1000000000 + n) for n in range(21)]}},
        {"ga4": {"dataset": "proj-teste.a", "event": "1compra", "metric": "count"}},
        {"ga4": {"dataset": "proj-teste.a", "event": "compra'--", "metric": "count"}},
        {"ga4": {"dataset": "proj-teste.a", "event": "purchase", "metric": "sum"}},
    ],
)
def test_google_config_rejects_anything_that_could_reach_the_sql(change):
    with pytest.raises(ValidationError):
        GoogleConfig.model_validate({**GOOGLE_CONFIG, **change})


def test_period_rules():
    today = google_import.today()
    Period(start=today - timedelta(days=1095), end=today)

    for start, end in [
        (date(2026, 1, 3), date(2026, 1, 1)),
        (today, today + timedelta(days=1)),
        (today - timedelta(days=1096), today),
    ]:
        with pytest.raises(ValidationError):
            Period(start=start, end=end)
```

- [ ] **Step 8: Rodar e ver falhar**

Run: `uv run pytest tests/api/test_google_import.py -q`
Expected: FAIL com `ImportError: cannot import name 'google_import' from 'api'`.

- [ ] **Step 9: Implementar as partes puras de `api/google_import.py`**

```python
import csv
import io
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo

from pydantic import AfterValidator, BaseModel, Field, StringConstraints, model_validator

from api import simulations

log = logging.getLogger(__name__)

SAO_PAULO = ZoneInfo("America/Sao_Paulo")
MAX_DAYS = 1096

# advertising_channel_type -> channel; any other type keeps its own name so no spend is dropped
CHANNELS = {"SEARCH": "SEARCH", "PERFORMANCE_MAX": "PMAX", "VIDEO": "YOUTUBE", "DEMAND_GEN": "DEMAND_GEN"}
METRICS = {"count": "COUNT(*)", "revenue": "SUM(ecommerce.purchase_revenue)"}


def unique(ids: list[str]) -> list[str]:
    if len(set(ids)) != len(ids):
        raise ValueError("customer id repetido")
    return ids


# `project.dataset`. Table names can't be query parameters: this pattern is what keeps the SQL safe
Dataset = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9-]{4,28}[a-z0-9]\.[A-Za-z0-9_]{1,1024}$")]
CustomerId = Annotated[str, StringConstraints(pattern=r"^[0-9]{10}$")]


class AdsConfig(BaseModel):
    dataset: Dataset
    customer_ids: Annotated[list[CustomerId], Field(min_length=1, max_length=20), AfterValidator(unique)]


class Ga4Config(BaseModel):
    dataset: Dataset
    event: Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_]{0,39}$")]
    metric: Literal["count", "revenue"]


class GoogleConfig(BaseModel):
    ads: AdsConfig
    ga4: Ga4Config


def today() -> date:
    return datetime.now(SAO_PAULO).date()


class Period(BaseModel):
    start: date
    end: date

    @model_validator(mode="after")
    def check(self):
        if self.start > self.end:
            raise ValueError("O início vem antes do fim.")
        if self.end > today():
            raise ValueError("O fim não pode estar no futuro.")
        if (self.end - self.start).days >= MAX_DAYS:
            raise ValueError("O período vai até 3 anos.")
        return self

    def days(self) -> list[date]:
        return [self.start + timedelta(days=n) for n in range((self.end - self.start).days + 1)]


def ads_sql(config: AdsConfig) -> str:
    # _DATA_DATE prunes the partitions; the outer date filter keeps a backfilled row of another day out
    blocks = "\nUNION ALL\n".join(
        f"""SELECT CAST(s.segments_date AS DATE) AS date, c.campaign_advertising_channel_type AS channel_type,
       s.metrics_cost_micros AS cost_micros
FROM `{config.dataset}.ads_CampaignBasicStats_{cid}` s
JOIN `{config.dataset}.ads_Campaign_{cid}` c
  ON c.campaign_id = s.campaign_id AND c._DATA_DATE = c._LATEST_DATE
WHERE s._DATA_DATE BETWEEN @start AND @end"""
        for cid in config.customer_ids
    )
    return f"""SELECT date, channel_type, SUM(cost_micros) / 1e6 AS spend FROM (
{blocks}
) WHERE date BETWEEN @start AND @end
GROUP BY 1, 2"""


def ga4_sql(config: Ga4Config) -> str:
    # events_* also matches events_intraday_*, whose suffix starts with a letter and falls outside the range
    return f"""SELECT PARSE_DATE('%Y%m%d', event_date) AS date, {METRICS[config.metric]} AS kpi
FROM `{config.dataset}.events_*`
WHERE _TABLE_SUFFIX BETWEEN @start_suffix AND @end_suffix AND event_name = @event
GROUP BY 1"""


def to_csv(header: list[str], rows: list[list]) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return out.getvalue().encode()


def investment_csv(rows: list[dict], period: Period) -> tuple[bytes, list[str]]:
    spend = defaultdict(float)
    for r in rows:
        channel_type = r["channel_type"] or "UNKNOWN"
        spend[(r["date"], CHANNELS.get(channel_type, channel_type))] += r["spend"] or 0
    if not any(spend.values()):
        raise simulations.InvalidInput("Nenhum investimento no Google Ads neste período.")
    channels = sorted({channel for _, channel in spend})
    # the engine needs a continuous series: a day the DTS has no row for is a day with no spend
    grid = [[day.isoformat(), c, str(round(spend[(day, c)], 2))] for day in period.days() for c in channels]
    return to_csv(["data", "canal", "investimento"], grid), channels


def performance_csv(rows: list[dict], period: Period, event: str) -> bytes:
    kpi = {r["date"]: r["kpi"] or 0 for r in rows}
    if not any(kpi.values()):
        raise simulations.InvalidInput(f"Nenhum evento '{event}' no GA4 neste período.")
    return to_csv(["data", "kpi"], [[day.isoformat(), str(round(kpi.get(day, 0), 2))] for day in period.days()])
```

Conta da grade do teste: `spend[(day, c)]` num `defaultdict(float)` devolve `0.0`, e `str(round(0.0, 2))` dá `"0.0"`. Já `round(10, 2)` de um `int` continua `int` e vira `"10"`. É o formato que os testes esperam.

- [ ] **Step 10: Rodar e ver passar**

Run: `uv run pytest tests/api/test_google_import.py tests/api/test_bigquery.py -q`
Expected: todos passam.

- [ ] **Step 11: Lint e commit**

```bash
uv run ruff format . && uv run ruff check .
git add pyproject.toml uv.lock api/bigquery.py api/google_import.py tests/samples.py tests/api/test_bigquery.py tests/api/test_google_import.py
git commit -m "feat(api): bigquery client and google import sql and csv builders"
```

---

### Task 2: config do conector pelo platform admin e `google` no `/api/me`

**Files:**
- Modify: `api/google_import.py` (`config_of`, `configure`, `NotConfigured`)
- Modify: `api/routes/__init__.py`
- Modify: `api/routes/admin.py`
- Modify: `api/routes/auth.py:25-57`
- Modify: `tests/api/test_admin.py`
- Modify: `tests/api/test_rbac.py`

- [ ] **Step 1: Escrever os testes, que vão falhar**

Acrescente ao fim de `tests/api/test_admin.py` (e `from tests.samples import GOOGLE_CONFIG` no topo):

```python
def test_platform_admin_sets_and_removes_the_google_connector(client, db, make_user, make_workspace, login_as):
    ws = make_workspace("a")
    ws.settings = {"outra": 1}
    db.flush()
    login_as(client, make_user("root@x.com", platform=True))

    r = client.put(f"/api/admin/workspaces/{ws.id}/google", json=GOOGLE_CONFIG)

    assert r.status_code == 200 and r.json()["google"] == GOOGLE_CONFIG
    assert client.get("/api/admin/workspaces").json()[0]["google"] == GOOGLE_CONFIG
    db.refresh(ws)
    assert ws.settings == {"outra": 1, "google": GOOGLE_CONFIG}

    assert client.delete(f"/api/admin/workspaces/{ws.id}/google").status_code == 204
    assert client.delete(f"/api/admin/workspaces/{ws.id}/google").status_code == 204
    assert client.get("/api/admin/workspaces").json()[0]["google"] is None
    db.refresh(ws)
    assert ws.settings == {"outra": 1}


def test_google_connector_rejects_bad_config_and_unknown_workspace(client, make_user, make_workspace, login_as):
    ws = make_workspace("a")
    login_as(client, make_user("root@x.com", platform=True))
    bad = {**GOOGLE_CONFIG, "ads": {"dataset": "proj-teste.ds`; DROP", "customer_ids": ["1111111111"]}}

    assert client.put(f"/api/admin/workspaces/{ws.id}/google", json=bad).status_code == 422
    assert client.put("/api/admin/workspaces/999999/google", json=GOOGLE_CONFIG).status_code == 404
    assert client.delete("/api/admin/workspaces/999999/google").status_code == 404


def test_me_says_which_workspaces_have_google_without_the_datasets(client, db, make_user, make_workspace, login_as):
    ana = make_user("ana@x.com")
    with_google = make_workspace("a", [(ana, "analyst")])
    with_google.settings = {"google": GOOGLE_CONFIG}
    make_workspace("b", [(ana, "analyst")])
    db.flush()
    login_as(client, ana)

    r = client.get("/api/me")

    assert [(w["slug"], w["google"]) for w in r.json()["workspaces"]] == [("a", True), ("b", False)]
    assert "proj-teste" not in r.text
```

O teste existente `test_platform_admin_sees_all_workspaces_as_admin` compara o `/api/me` inteiro. Acrescente `"google": False` nos dois dicts esperados:

```python
    assert client.get("/api/me").json()["workspaces"] == [
        {"slug": "a", "name": "A", "role": "admin", "google": False},
        {"slug": "b", "name": "B", "role": "admin", "google": False},
    ]
```

Em `tests/api/test_rbac.py`:
- importe `GOOGLE_CONFIG` de `tests.samples`;
- acrescente em `ROUTES`, depois de `("POST", "/api/admin/workspaces")`:

```python
    ("PUT", "/api/admin/workspaces/{workspace_id}/google"): (PLATFORM, 200, lambda e: GOOGLE_CONFIG),
    ("DELETE", "/api/admin/workspaces/{workspace_id}/google"): (PLATFORM, 204, None),
```

- no fixture `env`, devolva o workspace: `return {..., "workspace": ws}`;
- no `test_role_matrix`, passe `workspace_id=env["workspace"].id` no `template.format(...)`.

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/api/test_admin.py tests/api/test_rbac.py -q`
Expected: FAIL. Os testes novos dão 404/405 nas rotas e `KeyError: 'google'`; `test_matrix_covers_every_api_route` falha porque as rotas da matriz não existem.

- [ ] **Step 3: Implementar o serviço**

Em `api/google_import.py`, acrescente os imports (`from pydantic import ValidationError`, `from sqlalchemy.orm import Session` e `from api.models import User, Workspace`) e, depois de `GoogleConfig`:

```python
class NotConfigured(Exception):
    pass


def config_of(workspace: Workspace) -> GoogleConfig:
    raw = workspace.settings.get("google")
    if raw is None:
        raise NotConfigured
    try:
        # validated again: a value written straight to the db must not reach the SQL either
        return GoogleConfig.model_validate(raw)
    except ValidationError:
        log.error("google.bad_config workspace_id=%s", workspace.id)
        raise NotConfigured


def configure(db: Session, workspace: Workspace, config: GoogleConfig | None, by: User) -> None:
    settings = {k: v for k, v in workspace.settings.items() if k != "google"}
    if config is not None:
        settings["google"] = config.model_dump()
    # a new dict: SQLAlchemy doesn't see in-place changes to a JSONB column
    workspace.settings = settings
    db.commit()
    log.info("google.%s workspace_id=%s by=%s", "configured" if config else "removed", workspace.id, by.id)
```

- [ ] **Step 4: Implementar as rotas**

Em `api/routes/__init__.py`, acrescente:

```python
WorkspaceId = Annotated[int, Path(ge=1, le=2**63 - 1)]
```

Em `api/routes/admin.py`:
- importe `google_import` em `from api import accounts, google_import, runs, usage`;
- importe `WorkspaceId` de `api.routes`;
- troque `WorkspaceOut` por uma versão sem `from_attributes`, com o builder:

```python
class WorkspaceOut(BaseModel):
    id: int
    name: str
    slug: str
    created_at: datetime
    google: google_import.GoogleConfig | None


def workspace_out(w: Workspace) -> WorkspaceOut:
    return WorkspaceOut(id=w.id, name=w.name, slug=w.slug, created_at=w.created_at, google=w.settings.get("google"))


def find_workspace(db: Session, workspace_id: int) -> Workspace:
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(404)
    return workspace
```

As duas rotas existentes passam a usar o builder:

```python
@router.get("/workspaces", response_model=list[WorkspaceOut])
def list_workspaces(_: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    return [workspace_out(w) for w in db.scalars(select(Workspace).order_by(Workspace.name))]


@router.post("/workspaces", status_code=201, response_model=WorkspaceOut)
def create_workspace(body: WorkspaceIn, _: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    try:
        return workspace_out(accounts.create_workspace(db, body.name, body.slug))
    except accounts.Conflict:
        raise HTTPException(409, "Já existe um workspace com esse slug")
```

E logo abaixo delas:

```python
@router.put("/workspaces/{workspace_id}/google", response_model=WorkspaceOut)
def set_google(
    workspace_id: WorkspaceId,
    body: google_import.GoogleConfig,
    admin: User = Depends(require_platform_admin),
    db: Session = Depends(get_db),
):
    workspace = find_workspace(db, workspace_id)
    google_import.configure(db, workspace, body, by=admin)
    return workspace_out(workspace)


@router.delete("/workspaces/{workspace_id}/google", status_code=204)
def remove_google(workspace_id: WorkspaceId, admin: User = Depends(require_platform_admin), db: Session = Depends(get_db)):
    google_import.configure(db, find_workspace(db, workspace_id), None, by=admin)
```

Em `api/routes/auth.py`, `MyWorkspace` ganha `google: bool`, e o `me_out` monta:

```python
        workspaces=[
            MyWorkspace(slug=w.slug, name=w.name, role=role, google="google" in w.settings) for w, role in rows
        ],
```

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest tests/api/test_admin.py tests/api/test_rbac.py tests/api/test_auth.py -q`
Expected: todos passam.

- [ ] **Step 6: Suíte inteira, lint e commit**

```bash
uv run pytest -q
uv run ruff format . && uv run ruff check .
git add api/google_import.py api/routes/__init__.py api/routes/admin.py api/routes/auth.py tests/api/test_admin.py tests/api/test_rbac.py
git commit -m "feat(api): platform admin sets the google connector per workspace"
```

---

### Task 3: import na simulação

**Files:**
- Modify: `api/google_import.py` (`SourceError`, `fetch`, `FIXED_MAPPING`, `trends_mapping`, `run`)
- Modify: `api/routes/simulations.py`
- Modify: `tests/conftest.py`
- Modify: `tests/api/test_google_import.py`
- Modify: `tests/api/test_rbac.py`

- [ ] **Step 1: Fixture do fake**

Em `tests/conftest.py`:
- acrescente `bigquery` ao `from api import launcher, passwords, simulations, storage`;
- acrescente `from types import SimpleNamespace`;
- acrescente `from tests.samples import ADS_ROWS, GA4_ROWS`;
- acrescente o fixture:

```python
@pytest.fixture
def fake_bigquery(monkeypatch):
    # answers by table: the GA4 query is the only one reading events_*
    fake = SimpleNamespace(calls=[], answers={"ads": ADS_ROWS, "ga4": GA4_ROWS})

    def query(sql, params):
        fake.calls.append((sql, params))
        return fake.answers["ga4" if "events_*" in sql else "ads"]

    monkeypatch.setattr(bigquery, "query", query)
    return fake
```

- [ ] **Step 2: Escrever os testes da rota, que vão falhar**

Acrescente a `tests/api/test_google_import.py`:
- nos imports: `bigquery` em `from api import bigquery, google_import, simulations`, e `GOOGLE_PERIOD, INVESTMENT, MAPPING, PERFORMANCE, TRENDS, TRENDS_MAPPING` no `from tests.samples import …`;
- depois dos testes existentes:

```python
@pytest.fixture
def ana(make_user):
    return make_user("ana@x.com")


@pytest.fixture
def ws(db, ana, make_workspace):
    workspace = make_workspace("a", [(ana, "analyst")])
    workspace.settings = {"google": GOOGLE_CONFIG}
    db.flush()
    return workspace


@pytest.fixture
def logged(client, ana, login_as):
    login_as(client, ana)
    return client


@pytest.fixture
def sim(ws, ana, make_simulation):
    return make_simulation(ws, ana)


def url(simulation):
    return f"/api/w/a/simulations/{simulation.id}/google-import"


def test_import_writes_mapped_and_validated_canonical_files(logged, sim, fake_bigquery, db):
    r = logged.post(url(sim), json=GOOGLE_PERIOD)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["files"]["investment"]["filename"] == "google-ads_2026-01-01_2026-01-03.csv"
    assert body["files"]["performance"]["filename"] == "ga4-purchase-count_2026-01-01_2026-01-03.csv"
    assert body["config"]["column_mapping"] == google_import.FIXED_MAPPING
    assert body["validation"]["ok"] is True
    assert body["validation"]["channels"] == ["DISPLAY", "SEARCH", "YOUTUBE"]
    db.refresh(sim)
    paths = simulations.input_paths(sim)
    assert paths["investment_file"].read_text().splitlines()[1] == "2026-01-01,DISPLAY,0.0"
    assert paths["performance_file"].read_text() == "data,kpi\n2026-01-01,10\n2026-01-02,0\n2026-01-03,12\n"


def test_import_sends_dates_and_event_as_params(logged, sim, fake_bigquery):
    logged.post(url(sim), json=GOOGLE_PERIOD)

    (ads_sql, ads_params), (ga4_sql, ga4_params) = fake_bigquery.calls
    assert "`proj-teste.google_ads.ads_CampaignBasicStats_2222222222`" in ads_sql
    assert ads_params == {"start": date(2026, 1, 1), "end": date(2026, 1, 3)}
    assert "`proj-teste.analytics_123.events_*`" in ga4_sql
    assert ga4_params == {"start_suffix": "20260101", "end_suffix": "20260103", "event": "purchase"}


def test_import_replaces_uploads_and_keeps_the_trends_mapping(logged, ws, ana, make_simulation, fake_bigquery, db):
    files = {"investment": INVESTMENT, "performance": PERFORMANCE, "trends": TRENDS}
    simulation = make_simulation(ws, ana, files=files)
    simulations.save_mapping(db, simulation, {**MAPPING, "generic_trends_file": TRENDS_MAPPING})

    r = logged.post(url(simulation), json=GOOGLE_PERIOD)

    assert r.status_code == 200, r.text
    assert r.json()["config"]["column_mapping"] == {**google_import.FIXED_MAPPING, "generic_trends_file": TRENDS_MAPPING}
    assert r.json()["files"]["trends"]["filename"] == "trends.csv"


def test_import_without_spend_saves_nothing(logged, sim, fake_bigquery):
    fake_bigquery.answers["ads"] = []

    r = logged.post(url(sim), json=GOOGLE_PERIOD)

    assert r.status_code == 422
    assert r.json()["detail"] == "Nenhum investimento no Google Ads neste período."
    assert logged.get(f"/api/w/a/simulations/{sim.id}").json()["files"]["investment"] is None


def test_import_without_events_is_422(logged, sim, fake_bigquery):
    fake_bigquery.answers["ga4"] = []

    r = logged.post(url(sim), json=GOOGLE_PERIOD)

    assert (r.status_code, r.json()["detail"]) == (422, "Nenhum evento 'purchase' no GA4 neste período.")


def test_import_without_connector_is_409(logged, sim, ws, db, fake_bigquery):
    ws.settings = {}
    db.flush()

    r = logged.post(url(sim), json=GOOGLE_PERIOD)

    assert (r.status_code, r.json()["detail"]) == (409, "Workspace sem conector Google configurado.")
    assert fake_bigquery.calls == []


def test_tampered_config_never_reaches_bigquery(logged, sim, ws, db, fake_bigquery):
    ws.settings = {"google": {**GOOGLE_CONFIG, "ga4": {**GOOGLE_CONFIG["ga4"], "dataset": "x.y` OR 1=1 --"}}}
    db.flush()

    assert logged.post(url(sim), json=GOOGLE_PERIOD).status_code == 409
    assert fake_bigquery.calls == []


@pytest.mark.parametrize(
    "period",
    [
        {"start": "2026-01-03", "end": "2026-01-01"},
        {"start": "2026-01-01", "end": "2999-01-01"},
        {"start": "2020-01-01", "end": "2023-01-01"},
        {"start": "ontem", "end": "2026-01-01"},
    ],
)
def test_import_rejects_bad_periods(logged, sim, fake_bigquery, period):
    assert logged.post(url(sim), json=period).status_code == 422
    assert fake_bigquery.calls == []


@pytest.mark.parametrize(
    ("error", "message"),
    [
        (
            bigquery.NoAccess,
            "A service account não tem acesso ao dataset ou a tabela não existe: proj-teste.google_ads.",
        ),
        (bigquery.NoCredentials, "Conector Google sem credenciais neste ambiente."),
        (bigquery.Failed, "Não foi possível consultar o BigQuery."),
    ],
)
def test_bigquery_errors_are_502_with_a_message(logged, sim, monkeypatch, error, message):
    def query(sql, params):
        raise error

    monkeypatch.setattr(bigquery, "query", query)

    r = logged.post(url(sim), json=GOOGLE_PERIOD)

    assert (r.status_code, r.json()["detail"]) == (502, message)


def test_simulation_of_another_workspace_is_404(logged, db, make_user, make_workspace, make_simulation, fake_bigquery):
    owner = make_user("bia@x.com")
    other = make_workspace("b", [(owner, "admin")])
    other.settings = {"google": GOOGLE_CONFIG}
    db.flush()
    foreign = make_simulation(other, owner)

    assert logged.post(f"/api/w/a/simulations/{foreign.id}/google-import", json=GOOGLE_PERIOD).status_code == 404
    assert logged.post(f"/api/w/b/simulations/{foreign.id}/google-import", json=GOOGLE_PERIOD).status_code == 404
```

`{"start": "2020-01-01", "end": "2023-01-01"}` tem 1.097 dias, então passa do teto. O 2º `assert` do último teste cai no 404 do `require_role`, porque `ana` não é membro de `b`.

Em `tests/api/test_rbac.py`:
- importe `GOOGLE_PERIOD` de `tests.samples`;
- acrescente em `ROUTES`, depois de `("PUT", "/api/w/{slug}/simulations/{simulation_id}/params")`:

```python
    ("POST", "/api/w/{slug}/simulations/{simulation_id}/google-import"): ("analyst", 200, lambda e: GOOGLE_PERIOD),
```

- no fixture `env`, peça `fake_bigquery` nos parâmetros e configure o workspace logo depois de `make_workspace(...)`: `ws.settings = {"google": GOOGLE_CONFIG}` seguido de `db.flush()`.

- [ ] **Step 3: Rodar e ver falhar**

Run: `uv run pytest tests/api/test_google_import.py tests/api/test_rbac.py -q`
Expected: FAIL com 404/405 em `/google-import` e a matriz acusando a rota faltando.

- [ ] **Step 4: Implementar `run`**

Em `api/google_import.py`:
- acrescente `from api import bigquery, simulations`;
- acrescente `from api.models import Simulation, User, Workspace`;
- acrescente no fim do arquivo:

```python
FIXED_MAPPING = {
    "investment_file": {"date_col": "data", "channel_col": "canal", "investment_col": "investimento"},
    "performance_file": {"date_col": "data", "kpi_col": "kpi"},
}


class SourceError(Exception):
    pass


def fetch(dataset: str, sql: str, params: dict) -> list[dict]:
    try:
        return bigquery.query(sql, params)
    except bigquery.NoAccess:
        raise SourceError(f"A service account não tem acesso ao dataset ou a tabela não existe: {dataset}.")
    except bigquery.NoCredentials:
        raise SourceError("Conector Google sem credenciais neste ambiente.")
    except bigquery.Failed:
        raise SourceError("Não foi possível consultar o BigQuery.")


def trends_mapping(simulation: Simulation) -> dict:
    trends = next((f for f in simulation.files if f.kind == "trends"), None)
    if trends is None:
        return {}
    current = simulation.config.get("column_mapping", {}).get("generic_trends_file")
    # ponytail: a trends file never mapped gets the suggestion; a bad one fails in save_mapping with its message
    return {"generic_trends_file": current or simulations.suggest_mapping("trends", trends.columns)}


def run(db: Session, workspace: Workspace, simulation: Simulation, period: Period, by: User) -> None:
    config = config_of(workspace)
    simulation_id = simulation.id
    # hand the connection back to the pool: each query can take 60 s
    db.rollback()
    ads = fetch(config.ads.dataset, ads_sql(config.ads), {"start": period.start, "end": period.end})
    ga4 = fetch(
        config.ga4.dataset,
        ga4_sql(config.ga4),
        {
            "start_suffix": period.start.strftime("%Y%m%d"),
            "end_suffix": period.end.strftime("%Y%m%d"),
            "event": config.ga4.event,
        },
    )
    investment, channels = investment_csv(ads, period)
    performance = performance_csv(ga4, period, config.ga4.event)

    span = f"{period.start}_{period.end}"
    performance_name = f"ga4-{config.ga4.event}-{config.ga4.metric}_{span}.csv"
    simulations.save_file(db, simulation, "investment", io.BytesIO(investment), f"google-ads_{span}.csv", by)
    simulations.save_file(db, simulation, "performance", io.BytesIO(performance), performance_name, by)
    simulations.save_mapping(db, simulation, {**FIXED_MAPPING, **trends_mapping(simulation)})
    log.info(
        "simulation.google_imported simulation_id=%s start=%s end=%s channels=%s",
        simulation_id,
        period.start,
        period.end,
        ",".join(channels),
    )
```

- [ ] **Step 5: Implementar a rota**

Em `api/routes/simulations.py`, importe `google_import` (`from api import google_import, runs, simulations`) e acrescente depois de `save_params`:

```python
@router.post("/{simulation_id}/google-import", response_model=SimulationOut)
def import_from_google(
    simulation_id: SimulationId,
    body: google_import.Period,
    ctx: Ctx = Depends(analyst),
    db: Session = Depends(get_db),
):
    simulation = find_simulation(db, ctx, simulation_id)
    try:
        google_import.run(db, ctx.workspace, simulation, body, by=ctx.user)
    except google_import.NotConfigured:
        raise HTTPException(409, "Workspace sem conector Google configurado.")
    except google_import.SourceError as e:
        raise HTTPException(502, str(e))
    except simulations.InvalidInput as e:
        raise HTTPException(422, str(e))
    return simulation_out(simulation)
```

- [ ] **Step 6: Rodar e ver passar**

Run: `uv run pytest tests/api/test_google_import.py tests/api/test_rbac.py -q`
Expected: todos passam.

- [ ] **Step 7: Suíte inteira, lint e commit**

```bash
uv run pytest -q
uv run ruff format . && uv run ruff check .
git add api/google_import.py api/routes/simulations.py tests/conftest.py tests/api/test_google_import.py tests/api/test_rbac.py
git commit -m "feat(api): import a simulation's investment and kpi from google ads and ga4"
```

---

### Task 4: SQL real no BigQuery sandbox

**Files:**
- Create: `tests/bigquery/seed_ads.sql`
- Create: `tests/api/test_bigquery_live.py`

Sem `BIGQUERY_TEST_PROJECT` o teste é pulado; o CI nunca roda. Quem executa a task precisa de uma conta Google com BigQuery sandbox: crie um projeto em console.cloud.google.com, sem billing, e rode `gcloud auth application-default login`. Se não houver como rodar, entregue os arquivos com o teste pulado e diga isso no relatório da task.

- [ ] **Step 1: Seed no formato das views do DTS**

Crie `tests/bigquery/seed_ads.sql`. São duas contas, e cada tabela de campanha tem dois snapshots (5 e 10/jan). A campanha 4 era `VIDEO` no primeiro snapshot e é `DEMAND_GEN` no último:

```sql
-- Same columns the DTS views expose (docs.cloud.google.com/bigquery/docs/google-ads-transfer). CTAS only: the sandbox has no DML.
CREATE SCHEMA IF NOT EXISTS b8_ads_seed;

CREATE OR REPLACE TABLE b8_ads_seed.ads_CampaignBasicStats_1111111111 AS
SELECT d AS segments_date, d AS _DATA_DATE, 1111111111 AS customer_id, x.campaign_id, x.cost AS metrics_cost_micros
FROM UNNEST(GENERATE_DATE_ARRAY(DATE '2026-01-01', DATE '2026-01-10')) AS d,
  UNNEST([STRUCT(1 AS campaign_id, 1000000 AS cost), STRUCT(2 AS campaign_id, 2000000 AS cost)]) AS x;

CREATE OR REPLACE TABLE b8_ads_seed.ads_Campaign_1111111111 AS
SELECT s AS _DATA_DATE, DATE '2026-01-10' AS _LATEST_DATE, 1111111111 AS customer_id, x.campaign_id,
  x.channel AS campaign_advertising_channel_type
FROM UNNEST([DATE '2026-01-05', DATE '2026-01-10']) AS s,
  UNNEST([STRUCT(1 AS campaign_id, 'SEARCH' AS channel), STRUCT(2 AS campaign_id, 'PERFORMANCE_MAX' AS channel)]) AS x;

CREATE OR REPLACE TABLE b8_ads_seed.ads_CampaignBasicStats_2222222222 AS
SELECT d AS segments_date, d AS _DATA_DATE, 2222222222 AS customer_id, x.campaign_id, x.cost AS metrics_cost_micros
FROM UNNEST(GENERATE_DATE_ARRAY(DATE '2026-01-01', DATE '2026-01-10')) AS d,
  UNNEST([
    STRUCT(3 AS campaign_id, 500000 AS cost),
    STRUCT(4 AS campaign_id, 3000000 AS cost),
    STRUCT(5 AS campaign_id, 4000000 AS cost)
  ]) AS x;

CREATE OR REPLACE TABLE b8_ads_seed.ads_Campaign_2222222222 AS
SELECT s AS _DATA_DATE, DATE '2026-01-10' AS _LATEST_DATE, 2222222222 AS customer_id, x.campaign_id,
  IF(x.campaign_id = 4 AND s < DATE '2026-01-10', 'VIDEO', x.channel) AS campaign_advertising_channel_type
FROM UNNEST([DATE '2026-01-05', DATE '2026-01-10']) AS s,
  UNNEST([
    STRUCT(3 AS campaign_id, 'DISPLAY' AS channel),
    STRUCT(4 AS campaign_id, 'DEMAND_GEN' AS channel),
    STRUCT(5 AS campaign_id, 'SEARCH' AS channel)
  ]) AS x;
```

- [ ] **Step 2: Escrever o teste**

Crie `tests/api/test_bigquery_live.py`:

```python
import os
from datetime import date
from pathlib import Path

import pytest

from api import bigquery, google_import
from api.google_import import AdsConfig, Ga4Config, Period

PROJECT = os.environ.get("BIGQUERY_TEST_PROJECT")
SEED = Path(__file__).resolve().parents[1] / "bigquery" / "seed_ads.sql"
GA4_SAMPLE = "bigquery-public-data.ga4_obfuscated_sample_ecommerce"

pytestmark = pytest.mark.skipif(not PROJECT, reason="BIGQUERY_TEST_PROJECT não definido")


@pytest.fixture(scope="module", autouse=True)
def billing_project():
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("GOOGLE_CLOUD_PROJECT", PROJECT)
        yield


@pytest.fixture(scope="module")
def ads_dataset():
    bigquery.query(SEED.read_text(encoding="utf-8"), {})
    return f"{PROJECT}.b8_ads_seed"


def test_ads_sql_sums_accounts_and_uses_the_latest_campaign_type(ads_dataset):
    period = Period(start=date(2026, 1, 2), end=date(2026, 1, 4))
    config = AdsConfig(dataset=ads_dataset, customer_ids=["1111111111", "2222222222"])

    rows = google_import.fetch(ads_dataset, google_import.ads_sql(config), {"start": period.start, "end": period.end})
    content, channels = google_import.investment_csv(rows, period)

    # campaign 4 counts as DEMAND_GEN (latest snapshot) and only once (one snapshot joined), never as YOUTUBE
    assert channels == ["DEMAND_GEN", "DISPLAY", "PMAX", "SEARCH"]
    assert content.decode().splitlines()[1:5] == [
        "2026-01-02,DEMAND_GEN,3.0",
        "2026-01-02,DISPLAY,0.5",
        "2026-01-02,PMAX,2.0",
        "2026-01-02,SEARCH,5.0",
    ]
    assert len(content.decode().splitlines()) == 1 + 3 * 4


@pytest.mark.parametrize("metric", ["count", "revenue"])
def test_ga4_sql_runs_against_a_real_export(metric):
    period = Period(start=date(2020, 11, 1), end=date(2020, 11, 7))
    config = Ga4Config(dataset=GA4_SAMPLE, event="purchase", metric=metric)
    params = {"start_suffix": "20201101", "end_suffix": "20201107", "event": "purchase"}

    rows = google_import.fetch(GA4_SAMPLE, google_import.ga4_sql(config), params)

    assert sorted(r["date"] for r in rows) == period.days()
    assert all(r["kpi"] > 0 for r in rows)
```

O `SEARCH` dá 5.0 porque soma a campanha 1 (conta 1, 1.0) com a campanha 5 (conta 2, 4.0): é a soma entre contas.

- [ ] **Step 3: Confirmar que pula sem a env**

Run: `uv run pytest tests/api/test_bigquery_live.py -q`
Expected: `3 skipped`.

- [ ] **Step 4: Rodar contra o sandbox**

Run (Git Bash): `BIGQUERY_TEST_PROJECT=<id-do-projeto> uv run pytest tests/api/test_bigquery_live.py -v`
Expected: 3 passed.

Se falhar por nome de coluna, a SQL do `ads_sql` e o seed seguem a doc do DTS. Confira a doc antes de mexer, e mexa nos dois. Se falhar por sintaxe, o erro do BigQuery aparece no `log.exception("bigquery.failed")`; rode com `-o log_cli=true`.

- [ ] **Step 5: Commit**

```bash
uv run ruff format . && uv run ruff check .
git add tests/bigquery/seed_ads.sql tests/api/test_bigquery_live.py
git commit -m "test(api): run the google import sql against a bigquery sandbox"
```

---

### Task 5: fechamento da documentação

**Files:**
- Modify: `API-GUIDE.md`, `DATABASE.md`, `SECURITY.md`, `CLAUDE.md`, `.env.example`
- Create: `docs/decisoes/conectores-google.md`
- Modify: `docs/decisoes/README.md`, `docs/m2/trilha-b-plataforma.md`

- [ ] **Step 1: `API-GUIDE.md`**

Na lista de status de erro (bullet "**Status de erro**"), troque `provedor externo fora do ar degrada, nunca vira 500` por:

`502 quando o BigQuery do conector Google falha ou nega acesso (mensagem pt-BR pronta); fora isso, provedor externo fora do ar degrada, nunca vira 500`

Na tabela de endpoints:
- a linha `GET /api/me` passa a terminar em `workspaces: [{slug, name, role, google}]}` (`google` é bool: o workspace tem conector; os datasets nunca saem daqui);
- a linha `GET /api/admin/workspaces` vira `Platform admin. [{id, name, slug, created_at, google: GoogleConfig | null}]`;
- depois de `PUT …/params`, entra:

```markdown
| POST | `/api/w/{slug}/simulations/{simulation_id}/google-import` | Analyst+. `{start, end}` (datas; `start <= end`, `end` até hoje em São Paulo, até 1.096 dias; senão 422) → `SimulationOut`; consulta o DTS do Ads e o export do GA4 do workspace, grava os dois CSV canônicos como upload (`google-ads_…`, `ga4-…`) e roda o mapeamento + validate. 409 sem conector; 422 sem investimento ou sem evento no período; 502 com a mensagem quando o BigQuery falha |
```

- depois de `POST /api/admin/workspaces`, entram:

```markdown
| PUT | `/api/admin/workspaces/{workspace_id}/google` | Platform admin. `GoogleConfig` = `{ads: {dataset, customer_ids}, ga4: {dataset, event, metric: count\|revenue}}` → `WorkspaceOut`; 422 fora do formato (dataset `projeto.dataset`, customer id de 10 dígitos); 404 workspace inexistente |
| DELETE | `/api/admin/workspaces/{workspace_id}/google` | Platform admin. Remove o conector; 204, idempotente |
```

- a frase `Os demais entram com B5–B8.` vira `Os demais entram com B5–B7.`

- [ ] **Step 2: `DATABASE.md`**

Na linha da tabela `workspaces`, depois de `settings jsonb` (default `{}`), acrescente: `; chave `google` = config do conector (B8, formato `GoogleConfig` de `api/google_import.py`, gravada só pelo platform admin)`.

- [ ] **Step 3: `SECURITY.md`**

Na seção `## Escopo por workspace`, acrescente o bullet:

```markdown
- **Conector Google só pelo platform admin.** A service account do BigQuery é uma só e lê os datasets de todos os clientes; quem aponta o dataset de um workspace lê os dados de quem estiver lá. Por isso o admin do workspace não grava o `settings["google"]`, e o `/api/me` expõe só `google: bool`. Nome de dataset entra na SQL por interpolação (não pode ser parâmetro): o regex do `GoogleConfig` roda ao gravar e de novo antes de cada query.
```

- [ ] **Step 4: `.env.example`**

Acrescente ao fim:

```bash
# Conector Google (B8): o BigQuery usa ADC. Local: `gcloud auth application-default login` ou o JSON de uma service account
# GOOGLE_APPLICATION_CREDENTIALS=/caminho/sa.json
# Projeto que paga as queries (sem ele, o do ADC)
# GOOGLE_CLOUD_PROJECT=
# Só para tests/api/test_bigquery_live.py, contra um BigQuery sandbox
# BIGQUERY_TEST_PROJECT=
```

- [ ] **Step 5: `docs/decisoes/conectores-google.md`**

```markdown
# Conectores Google (B8)

## Fallback do BRD primeiro, OAuth nunca por ora

O BRD autoriza puxar Ads e GA4 pelo BigQuery (Data Transfer Service do Google Ads + export nativo do GA4) em vez de OAuth próprio. O OAuth depende de developer token que não saiu e é o último da ordem de corte (`docs/m2/README.md`). A carga diária fica com o DTS; a plataforma só lê.

## Sem acesso real: schema documentado + sandbox

Em 29/out/2026 não havia projeto GCP nem dataset de nenhuma conta Core. As queries foram escritas contra a doc do DTS (Google Ads API v25) e do export do GA4, e rodam de verdade num BigQuery sandbox (`tests/api/test_bigquery_live.py`): o GA4 contra `bigquery-public-data.ga4_obfuscated_sample_ecommerce` (export real) e o Ads contra tabelas semeadas com as colunas das views do DTS. O aceite de ±1% contra o Google Ads UI fica pendente até haver uma conta real. A doc não diz o tipo de `segments_date`, por isso o `CAST(… AS DATE)`.

## Um import, o mesmo caminho do upload

O import gera os mesmos dois CSV canônicos (`data,canal,investimento` e `data,kpi`) e chama `save_file` e `save_mapping`. O `validate`, o snapshot do run e o download das entradas não sabem de onde veio o dado. O nome do arquivo (`google-ads_<início>_<fim>.csv`) diz a origem, e não há coluna nova. O import é síncrono: duas queries de até 60 s, com a conexão do banco devolvida ao pool durante a espera. Vira job se os dados reais passarem disso.

## Grade com zeros

O BigQuery não distingue "dia sem linha" de "dia com zero", e o motor precisa da série contínua: todo dia do período × todo canal que apareceu sai no CSV, com 0 onde não houve gasto. O KPI também. Período sem gasto ou sem evento algum é 422, porque quase sempre é config errada (evento com outro nome, conta errada).

## Canais

`SEARCH→SEARCH`, `PERFORMANCE_MAX→PMAX`, `VIDEO→YOUTUBE`, `DEMAND_GEN→DEMAND_GEN`, fixo no código. Os outros tipos (`DISPLAY`, `SHOPPING`…) viram canal com o próprio nome: descartar faria o total não bater com o Google Ads UI, e juntar em "OUTROS" misturaria mídias diferentes. O tipo é o do snapshot mais recente da campanha (`_DATA_DATE = _LATEST_DATE`, como na query de exemplo da doc). Isso também evita contar a campanha uma vez por snapshot.

## Uma service account, config só do platform admin

A plataforma lê com uma service account só (*BigQuery Data Viewer* em cada dataset de cliente, *Job User* no projeto da plataforma, que paga as queries), e o config guarda `projeto.dataset` completo. Assim tanto faz se o DTS de cada cliente mora no projeto Omnicom ou no do cliente. O preço é que apontar um dataset equivale a ler os dados de quem estiver lá. Por isso só o platform admin configura (`SECURITY.md`). Se um dia o admin do workspace precisar configurar sozinho, isso exige uma service account por cliente. Quem configura o export do GA4 de cada Core é pergunta em aberto com o Data Tech.

## Teto de custo

Cada query leva `maximum_bytes_billed` de 20 GB (`api/bigquery.py`). Um GA4 grande com 3 anos pode passar disso; o erro vira 502 "Não foi possível consultar o BigQuery." e o teto sobe com dado real na mão.
```

- [ ] **Step 6: `docs/decisoes/README.md`**

Acrescente a linha na tabela:

```markdown
| [conectores-google.md](conectores-google.md) | Fallback DTS/GA4, sandbox sem acesso real, import pelo caminho do upload, grade com zeros, canais, service account única, teto de custo |
```

- [ ] **Step 7: `CLAUDE.md`**

- Na árvore `## Estrutura`, depois da linha `gemini.py`, acrescente:
  - `  bigquery.py     query no BigQuery (ADC), com teto de bytes e timeout; trocada por fake nos testes`
  - `  google_import.py conector Google: config por workspace, SQL do DTS/GA4, CSV canônicos e import`
- Na tabela de áreas de "Onde as decisões estão escritas", acrescente: `| Conectores Google Ads/GA4, BigQuery | `docs/decisoes/conectores-google.md` |`.
- No "Estado atual", antes de `Faltam:`, acrescente:

  > **B8a (conectores backend) concluído em <data>**: config do conector Google por workspace em `settings["google"]` (só platform admin), import do DTS do Ads e do export do GA4 por período, que gera os CSV canônicos e passa pelo mesmo mapeamento e validate; SQL verificada num BigQuery sandbox; o ±1% contra o Google Ads UI espera acesso a uma conta real.

  Troque `Faltam: B7 (depende do B5), B8, B10` por `Faltam: B7 (depende do B5), B8b (telas do conector), B10`.

- [ ] **Step 8: `docs/m2/trilha-b-plataforma.md`**

No item `## B8`, logo abaixo do título, acrescente:

```markdown
- **Status:** 🟡 B8a (backend) em <data>, verificado por `tests/api/test_google_import.py` (grade com zeros, canais, SQL com parâmetros, arquivos mapeados e validados, 409/422/502, 404 entre workspaces), `tests/api/test_admin.py` (config só do platform admin, regex contra injeção, `/api/me` sem datasets), `tests/api/test_rbac.py` e `tests/api/test_bigquery_live.py` (<rodado no sandbox em <data> | pulado: sem sandbox>). Falta o B8b (telas). O aceite de ±1% contra o Google Ads UI fica pendente até haver acesso a uma conta Core com DTS. Respostas do "Em aberto" e desvios em `docs/decisoes/conectores-google.md`.
```

Troque `<data>` pela data do dia e escolha um dos dois textos entre `<…>` de acordo com o que aconteceu na Task 4.

- [ ] **Step 9: Verificar e commitar**

```bash
uv run pytest -q
uv run ruff format --check . && uv run ruff check .
git add API-GUIDE.md DATABASE.md SECURITY.md CLAUDE.md .env.example docs/decisoes/conectores-google.md docs/decisoes/README.md docs/m2/trilha-b-plataforma.md docs/superpowers/specs/2026-10-29-b8-conectores-google-design.md
git commit -m "docs: b8a google connectors backend"
```
