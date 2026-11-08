# B5 parte 2 · Aba Elasticidade — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Habilitar a aba Elasticidade do run: filtros mensais à esquerda e, à direita, tabela Atual/Recomendado/Saturação com degraus, curva de saturação com banda e extrapolação, iCPA, receita/ROAS, mix e curvas por canal — com o motor recusando elasticidade não conclusiva.

**Architecture:** `engine.scenario` ganha a recusa (`status != "ok"` → `EngineError`, 409 na rota que já existe), as curvas mensais dos canais identificáveis (`channels`) e o `mix` mensal nas linhas. O front lê `elasticity` do `results.json` (status, motivos, canais escondidos) e o `scenario` com os filtros (debounce de 200 ms), e só formata.

**Tech Stack:** Python 3.13 + pytest (uv), FastAPI; React 19 + TanStack Router/Query, shadcn (`chart` = Recharts, `slider` novo), Playwright (bun).

**Spec:** `docs/superpowers/specs/2026-11-07-b5-elasticidade-design.md`. Leia também `CODE-STYLE.md`, `API-GUIDE.md` e `docs/decisoes/dashboards.md` antes de começar.

**Unidades (verificado ao escrever o plano):** `response_curve[].investment` é `Daily_Investment`; `channels[].curve[].x` é `Channel_Spend` diário (`engine/elasticity_analysis.py:1033-1052`), `y` é o KPI total com os outros canais na média; `observed_spend_range` é min/max diário; `mix.*[canal]` é `Spend_{canal}_*` diário. Todos escalam pelo mesmo `factor = 30 / validation.period_days`. A participação histórica de cada canal no `mix.historical` é constante ao longo da curva (conferido no `identificavel.json`: STRONG = 0,5537 em toda linha), então o gasto atual do canal = participação × investimento atual, exato.

## Ordem e paralelismo

| Lote | Tarefas | Modelo sugerido |
|---|---|---|
| 1 | Task 1 (motor: recusa) ∥ Task 4 (web: dados) | haiku ∥ haiku |
| 2 | Task 2 (motor: canais e mix) ∥ Task 5 (web: gráficos) | sonnet ∥ sonnet |
| 3 | Task 3 (fixture e API) ∥ Task 6 (web: aba, filtros, tabela, rota) | haiku ∥ sonnet |
| 4 | Task 7 (E2E) | sonnet |
| 5 | Task 8 (docs) | haiku |

Tasks 1→2→3 mexem no mesmo arquivo do motor e são sequenciais. As tarefas web dependem só do contrato abaixo, não do código do motor.

## Contrato do `scenario` depois deste plano

```jsonc
{
  "unit": "month",
  "revenue_mode": false,
  "current":     { /* TableRow */ },
  "recommended": { /* TableRow */ } | null,
  "saturation":  { /* TableRow */ },
  "curve": [ { "investment", "kpi", "kpi_lo", "kpi_hi", "revenue", "cpa", "icpa", "roas", "iroas",
               "incremental_investment", "incremental_kpi", "pct_incrementality", "extrapolated",
               "in_filter", "mix" } ],
  "channels": [ { "name": "STRONG",
                  "curve": [ { "investment", "kpi", "kpi_lo", "kpi_hi", "extrapolated" } ],
                  "observed_range": [lo, hi] | null,
                  "current": 1234.5 | null,
                  "saturation": 2345.6 | null } ]
}
// TableRow: investment, kpi, kpi_lo, kpi_hi, revenue, cpa, roas, incremental_investment, incremental_kpi,
//           icpa, iroas, extrapolated, ramp ([{step, investment, kpi, kpi_lo, kpi_hi}] | null), notes ([str]),
//           mix ({historical|optimized|strategic: {canal: valor|null}} | null; null em `current`)
```

## Arquivos

| Arquivo | Muda |
|---|---|
| `engine/scenario.py` | recusa, `channels`, `mix` |
| `tests/engine/test_scenario.py` | Gol vira `GOL_OK` nos testes de paridade; testes novos |
| `tests/fixtures/results/scenario_fixture.py` (novo) | gera `identificavel_scenario.json` |
| `tests/fixtures/results/identificavel_scenario.json` (novo) | resposta do `scenario` sem filtro para o `identificavel.json` |
| `tests/fixtures/results/README.md` | linha do fixture novo |
| `tests/api/test_scenario_route.py` | 200 com `identificavel.json`, 409 com a Gol |
| `tests/api/test_rbac.py` | o run do `env` grava o `identificavel.json` |
| `web/src/lib/results.ts` | tipos de `elasticity`, rótulos novos |
| `web/src/lib/scenario.ts` (novo) | tipos do `scenario`, query, debounce |
| `web/src/components/ui/slider.tsx` (novo, gerado) | `bunx shadcn@latest add slider` |
| `web/src/components/elasticity/ElasticityCharts.tsx` (novo) | saturação, iCPA, receita/ROAS, mix |
| `web/src/components/elasticity/ChannelCurves.tsx` (novo) | curvas por canal, atual × saturação, escondidos |
| `web/src/components/elasticity/FiltersPanel.tsx` (novo) | painel de filtros |
| `web/src/components/elasticity/ScenarioTable.tsx` (novo) | tabela com degraus e notas |
| `web/src/components/elasticity/ElasticityTab.tsx` (novo) | estados e composição |
| `web/src/routes/_auth/w/$slug/execucoes/$runId/elasticidade.tsx` (novo) | rota |
| `web/src/routes/_auth/w/$slug/execucoes/$runId.tsx` | aba habilitada |
| `web/e2e/elasticity.spec.ts` (novo) | E2E |
| docs (Task 8) | `dashboards.md`, `API-GUIDE.md`, `trilha-b-plataforma.md`, `CLAUDE.md` |

---

### Task 1: Motor recusa elasticidade não conclusiva

**Files:**
- Modify: `engine/scenario.py`
- Test: `tests/engine/test_scenario.py`

A Gol é `inconclusive`, então os testes de paridade com o Streamlit (que usam a Gol) passam a rodar numa cópia com `status: "ok"`: eles testam a conta, não o gate.

- [ ] **Step 1: Ajustar os testes existentes e escrever os novos (falhando)**

Em `tests/engine/test_scenario.py`, logo abaixo da definição de `GOL`:

```python
# the Gol has no identifiable channel, so its elasticity is inconclusive and scenario() refuses it; the parity tests
# below check the arithmetic against the Streamlit, not the gate, so they run on a copy marked ok
GOL_OK = {**GOL, "elasticity": {**GOL["elasticity"], "status": "ok", "reasons": []}}
```

Troque `GOL` por `GOL_OK` em `_gol_filters`, `test_same_recommended_and_saturation_as_the_streamlit` (nas duas chamadas: `streamlit_pick(GOL_OK, filters)` e `scenario(GOL_OK, ...)`), `test_the_filter_that_empties_the_curve_still_answers`, `test_scenario_is_fast_enough_for_the_slider` e `test_the_gol_fixture_gives_monthly_rows_with_its_band` (incluindo o `len(GOL_OK["elasticity"]["response_curve"])`).

Em `_doc`, o dicionário de `elasticity` ganha `"status": "ok"`:

```python
    return {
        "validation": {"period_days": period_days},
        "elasticity": {"status": "ok", "response_curve": rows, "scenarios": [current]},
    }
```

Importe `NOT_CONCLUSIVE` e `NO_CURVE` (`from engine.scenario import NO_CURVE, NOT_CONCLUSIVE, TCPA_NOTE, ScenarioFilters, _saturation_index, scenario`) e acrescente, perto de `test_a_run_without_curve_is_an_engine_error`:

```python
@pytest.mark.parametrize("status", ["inconclusive", "failed"])
def test_an_elasticity_that_is_not_ok_is_refused(status):
    doc = _doc(CONVERSIONS)
    doc["elasticity"]["status"] = status

    with pytest.raises(EngineError, match=NOT_CONCLUSIVE):
        scenario(doc, ScenarioFilters(), 0.2)


def test_the_gol_is_refused_because_no_channel_is_identifiable():
    with pytest.raises(EngineError, match=NOT_CONCLUSIVE):
        scenario(GOL, ScenarioFilters(), 0.2)


def test_an_ok_elasticity_without_curve_is_still_no_curve():
    with pytest.raises(EngineError, match=NO_CURVE):
        scenario(_doc([]), ScenarioFilters(), 0.2)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/engine/test_scenario.py -q`
Expected: FAIL com `ImportError: cannot import name 'NOT_CONCLUSIVE'`.

- [ ] **Step 3: Implementar**

Em `engine/scenario.py`, abaixo de `NO_CURVE`:

```python
NOT_CONCLUSIVE = "A análise de elasticidade desta execução não é conclusiva; não há cenário para simular."
```

Em `scenario()`, logo depois de `elasticity = results.get("elasticity") or {}`:

```python
    # an inconclusive curve comes from channels the engine could not identify: no number of it reaches a screen
    if elasticity and elasticity.get("status") != "ok":
        raise EngineError(NOT_CONCLUSIVE)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/engine/test_scenario.py -q`
Expected: todos passam.

- [ ] **Step 5: Commit**

```bash
git add engine/scenario.py tests/engine/test_scenario.py
git commit -m "feat(engine): scenario refuses an elasticity that is not ok"
```

---

### Task 2: Motor devolve canais e mix mensais

**Files:**
- Modify: `engine/scenario.py`
- Test: `tests/engine/test_scenario.py`

- [ ] **Step 1: Escrever os testes (falhando)**

Em `tests/engine/test_scenario.py`, mude `_row` para aceitar um mix (o resto igual):

```python
def _row(investment, kpi, revenue=None, iroas=None, inc_inv=0.0, inc_kpi=0.0, mix=None):
    return {
        "investment": investment,
        "kpi": kpi,
        "kpi_lo": kpi * 0.9,
        "kpi_hi": kpi * 1.1,
        "revenue": revenue,
        "icpa": None,
        "iroas": iroas,
        "incremental_investment": inc_inv,
        "incremental_kpi": inc_kpi,
        "extrapolated": investment > 30,
        "mix": mix or {},
    }
```

E acrescente, no bloco dos documentos à mão:

```python
def _mixed(investment, kpi, **kw):
    # A is 60% of the spend at every point, like the engine's historical mix
    mix = {
        "historical": {"A": investment * 0.6, "Não identificados": investment * 0.4},
        "optimized": {"A": investment * 0.7, "Não identificados": investment * 0.3},
        "strategic": {"A": investment * 0.6, "Não identificados": None},
    }
    return _row(investment, kpi, mix=mix, **kw)


MIXED = [
    _mixed(0.0, 0.0),
    _mixed(10.0, 25.0),
    _mixed(20.0, 40.0),
    _mixed(30.0, 50.0, inc_inv=10.0, inc_kpi=10.0),
    _mixed(40.0, 55.0, inc_inv=20.0, inc_kpi=15.0),
]


def _with_channels(doc):
    doc["elasticity"]["channels"] = [
        {
            "name": "A",
            "identifiable": True,
            "observed_spend_range": [2.0, 8.0],
            "curve": [
                {"x": x, "y": y, "lo": y * 0.9, "hi": y * 1.1, "extrapolated": x > 8}
                for x, y in [(0, 10), (4, 20), (8, 26), (12, 28), (16, 29)]
            ],
        },
        {"name": "B", "identifiable": False, "observed_spend_range": [1.0, 3.0], "curve": []},
    ]
    return doc


def test_only_identifiable_channels_come_back_monthly():
    got = scenario(_with_channels(_doc(MIXED, period_days=7)), ScenarioFilters(), 0.2)

    factor = 30 / 7
    assert [c["name"] for c in got["channels"]] == ["A"]
    channel = got["channels"][0]
    assert channel["curve"][1] == pytest.approx(
        {"investment": 4 * factor, "kpi": 20 * factor, "kpi_lo": 18 * factor, "kpi_hi": 22 * factor, "extrapolated": False}
    )
    assert channel["observed_range"] == pytest.approx([2.0 * factor, 8.0 * factor])
    assert channel["current"] == pytest.approx(0.6 * 20.0 * factor)  # historical share x current investment


def test_a_channel_saturation_is_a_point_of_its_own_curve():
    channel = scenario(_with_channels(_doc(MIXED)), ScenarioFilters(), 0.2)["channels"][0]

    assert channel["saturation"] in [p["investment"] for p in channel["curve"]]


def test_a_document_without_channels_or_mix_still_answers():
    got = scenario(_doc(CONVERSIONS), ScenarioFilters(), 0.2)

    assert got["channels"] == []
    assert got["recommended"]["mix"] == {}
    assert got["current"]["mix"] is None


def test_table_rows_carry_the_monthly_mix_of_their_curve_point():
    got = scenario(_doc(MIXED), ScenarioFilters(), 0.2)

    mix = got["recommended"]["mix"]  # the 40.0 row
    assert mix["historical"]["A"] == pytest.approx(40.0 * 0.6 * 30)
    assert mix["optimized"]["Não identificados"] == pytest.approx(40.0 * 0.3 * 30)
    assert mix["strategic"]["Não identificados"] is None
    assert got["saturation"]["mix"]["historical"].keys() == {"A", "Não identificados"}
    assert got["current"]["mix"] is None


def test_the_identifiable_fixture_gives_only_strong():
    doc = json.loads(
        (Path(__file__).resolve().parents[1] / "fixtures" / "results" / "identificavel.json").read_text(encoding="utf-8")
    )

    got = scenario(doc, ScenarioFilters(), 0.2)

    assert [c["name"] for c in got["channels"]] == ["STRONG"]
    assert got["channels"][0]["current"] is not None and got["channels"][0]["saturation"] is not None
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/engine/test_scenario.py -q`
Expected: FAIL com `KeyError: 'channels'` / `KeyError: 'mix'`.

- [ ] **Step 3: Implementar**

Em `engine/scenario.py`:

1. Depois de `_scaled`:

```python
def _scaled_mix(mix: dict, factor: float) -> dict:
    return {variant: {ch: _scaled(v, factor) for ch, v in spend.items()} for variant, spend in mix.items()}
```

2. Em `_curve_row`, acrescente ao dicionário devolvido:

```python
        "mix": _scaled_mix(row.get("mix") or {}, factor),
```

3. Em `_table_row`, acrescente ao dicionário devolvido (o `base` não tem `mix`, então `current` sai `None`):

```python
        "mix": point.get("mix"),
```

4. Antes de `scenario()`:

```python
def _historical_share(rows: list[dict]) -> dict[str, float]:
    """Each channel's share of the spend in the historical mix: the engine keeps it the same at every curve point."""
    row = next((r for r in rows if r["investment"] and (r.get("mix") or {}).get("historical")), None)
    if row is None:
        return {}
    return {ch: v / row["investment"] for ch, v in row["mix"]["historical"].items() if v is not None}


def _channels(elasticity: dict, rows: list[dict], current_investment: float, factor: float) -> list[dict]:
    """Monthly curve, observed range, current spend and saturation of each identifiable channel; a hidden channel
    never comes back (its name and reasons are in the results.json)."""
    share = _historical_share(rows)
    out = []
    for channel in elasticity.get("channels") or []:
        points = [p for p in channel.get("curve") or [] if p.get("x") is not None and p.get("y") is not None]
        if not channel.get("identifiable") or not points:
            continue
        curve = [
            {
                "investment": p["x"] * factor,
                "kpi": p["y"] * factor,
                "kpi_lo": _scaled(p.get("lo"), factor),
                "kpi_hi": _scaled(p.get("hi"), factor),
                "extrapolated": p.get("extrapolated"),
            }
            for p in points
        ]
        observed = channel.get("observed_spend_range")
        index = _saturation_index(curve, 0.0)
        name = channel["name"]
        out.append(
            {
                "name": name,
                "curve": curve,
                "observed_range": [observed[0] * factor, observed[1] * factor]
                if observed and None not in observed
                else None,
                "current": share[name] * current_investment if name in share else None,
                "saturation": curve[index]["investment"] if index is not None else None,
            }
        )
    return out
```

5. No `return` de `scenario()`, acrescente (`base["investment"]` já é mensal, então o `factor` não entra de novo no `current`):

```python
        "channels": _channels(elasticity, rows, base["investment"], factor),
```

E ajuste a docstring de `scenario()`: "Recommended point, saturation point, the filtered curve and the identifiable channels' curves for the planner, in monthly values."

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/engine/test_scenario.py -q`
Expected: todos passam.

- [ ] **Step 5: Lint e commit**

```bash
uv run ruff check engine/scenario.py tests/engine/test_scenario.py && uv run ruff format engine/scenario.py tests/engine/test_scenario.py
git add engine/scenario.py tests/engine/test_scenario.py
git commit -m "feat(engine): scenario returns monthly channel curves and the mix of each table row"
```

---

### Task 3: Fixture do cenário e testes da API

**Files:**
- Create: `tests/fixtures/results/scenario_fixture.py`
- Create: `tests/fixtures/results/identificavel_scenario.json` (gerado)
- Modify: `tests/fixtures/results/README.md`
- Modify: `tests/engine/test_scenario.py`
- Modify: `tests/api/test_scenario_route.py`
- Modify: `tests/api/test_rbac.py`

- [ ] **Step 1: Script do fixture**

`tests/fixtures/results/scenario_fixture.py`:

```python
"""Write identificavel_scenario.json, the unfiltered scenario of identificavel.json, for the E2E of the elasticity tab:
uv run python tests/fixtures/results/scenario_fixture.py (seconds; rerun after regenerating identificavel.json)."""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from engine import EngineConfig, ScenarioFilters, scenario  # noqa: E402

SOURCE, TARGET = HERE / "identificavel.json", HERE / "identificavel_scenario.json"


def build() -> dict:
    doc = json.loads(SOURCE.read_text(encoding="utf-8"))
    return scenario(doc, ScenarioFilters(), EngineConfig().max_budget_step)


if __name__ == "__main__":
    TARGET.write_text(json.dumps(build(), ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {TARGET.name}", file=sys.stderr)
```

Run: `uv run python tests/fixtures/results/scenario_fixture.py`
Expected: `wrote identificavel_scenario.json`.

- [ ] **Step 2: Teste que prende o fixture ao motor**

Em `tests/engine/test_scenario.py`:

```python
def test_the_e2e_scenario_fixture_is_up_to_date():
    from tests.fixtures.results.scenario_fixture import TARGET, build

    assert json.loads(TARGET.read_text(encoding="utf-8")) == json.loads(json.dumps(build()))
```

Run: `uv run pytest tests/engine/test_scenario.py -q -k e2e_scenario`
Expected: PASS.

- [ ] **Step 3: Testes da rota**

Em `tests/api/test_scenario_route.py`:
- Abaixo de `GOL`, acrescente `IDENTIFIABLE = GOL.with_name("identificavel.json")`.
- `finished` ganha o parâmetro `document=IDENTIFIABLE` e grava `storage.put(key, document)` no lugar de `storage.put(key, GOL)`.
- Acrescente:

```python
def test_an_inconclusive_elasticity_is_a_conflict(logged, db, ready, analyst):
    run = finished(db, ready(), analyst, document=GOL)

    r = logged.get(url(run))

    assert r.status_code == 409 and "não é conclusiva" in r.json()["detail"]


def test_the_scenario_has_the_identifiable_channels(logged, db, ready, analyst):
    run = finished(db, ready(), analyst)

    body = logged.get(url(run)).json()

    assert [c["name"] for c in body["channels"]] == ["STRONG"]
    assert body["recommended"]["mix"]["historical"]
```

`test_analyst_reads_the_monthly_scenario` continua valendo com o `identificavel.json` (100 linhas, recomendado não nulo).

Em `tests/api/test_rbac.py`: troque a constante para o fixture identificável (a matriz espera 200 no `scenario`, e a Gol agora dá 409):

```python
# identifiable, so the scenario route answers 200 (the Gol's elasticity is inconclusive: 409)
RESULTS = Path(__file__).resolve().parents[1] / "fixtures" / "results" / "identificavel.json"
```

e use `storage.put(run.results_uri, RESULTS)`; apague `GOL` se não sobrar uso no arquivo.

- [ ] **Step 4: Rodar**

Run: `uv run pytest tests/api/test_scenario_route.py tests/api/test_rbac.py tests/api/test_results.py tests/engine/test_scenario.py -q`
Expected: todos passam (o Postgres do `docker compose` precisa estar no ar).

- [ ] **Step 5: README dos fixtures**

Em `tests/fixtures/results/README.md`, na tabela, depois da linha do `identificavel.json`:

```markdown
| `identificavel_scenario.json` | — | `engine.scenario` sem filtro sobre `identificavel.json` (o E2E da aba Elasticidade serve este arquivo); regenere com `uv run python tests/fixtures/results/scenario_fixture.py` sempre que o `identificavel.json` ou o `scenario` mudarem — `test_the_e2e_scenario_fixture_is_up_to_date` avisa |
```

- [ ] **Step 6: Commit**

```bash
git add tests/fixtures/results/ tests/engine/test_scenario.py tests/api/test_scenario_route.py tests/api/test_rbac.py
git commit -m "test: scenario fixture for the elasticity e2e and a 409 for an inconclusive elasticity"
```

---

### Task 4: Front — tipos, query e rótulos

**Files:**
- Modify: `web/src/lib/results.ts`
- Create: `web/src/lib/scenario.ts`

- [ ] **Step 1: `results.ts`**

Depois do tipo `Causal`:

```ts
export type ChannelFit = { name: string; identifiable: boolean | null; reasons: string[] }
export type Elasticity = {
  status: 'ok' | 'inconclusive' | 'failed'
  reasons: string[]
  metrics: { cv_r2: number | null; low_confidence: boolean | null; reallocation_suppressed: boolean | null } | null
  channels: ChannelFit[]
}
```

e `Results` passa a ser:

```ts
export type Results = {
  status: 'succeeded' | 'inconclusive' | 'failed'
  causal: Causal | null
  elasticity: Elasticity | null
}
```

Em `REASON_LABELS`, acrescente:

```ts
  no_identifiable_channel: 'Nenhum canal com efeito identificável',
  cv_in_sample: 'Poucos períodos para validar o modelo fora da amostra',
  model_failed: 'O modelo de elasticidade falhou',
  coef_ci_includes_zero: 'O intervalo do efeito inclui zero',
  coef_ci_too_wide: 'O intervalo do efeito é largo demais',
  collinearity: 'Investimento colinear com outro canal',
```

- [ ] **Step 2: `scenario.ts`**

```ts
import { keepPreviousData, queryOptions } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from './api'

// the engine.scenario answer (engine/scenario.py), monthly values
type Num = number | null
export type Mix = Record<'historical' | 'optimized' | 'strategic', Record<string, Num>>
export type RampStep = { step: number; investment: number; kpi: Num; kpi_lo: Num; kpi_hi: Num }
export type TableRow = {
  investment: number
  kpi: Num
  kpi_lo: Num
  kpi_hi: Num
  revenue: Num
  cpa: Num
  roas: Num
  incremental_investment: Num
  incremental_kpi: Num
  icpa: Num
  iroas: Num
  extrapolated: boolean | null
  ramp: RampStep[] | null
  notes: string[]
  mix: Partial<Mix> | null
}
export type CurveRow = {
  investment: number
  kpi: number
  kpi_lo: Num
  kpi_hi: Num
  revenue: Num
  cpa: Num
  icpa: Num
  roas: Num
  iroas: Num
  pct_incrementality: number
  extrapolated: boolean | null
  in_filter: boolean
}
export type ChannelPoint = { investment: number; kpi: number; kpi_lo: Num; kpi_hi: Num; extrapolated: boolean | null }
export type ChannelCurve = {
  name: string
  curve: ChannelPoint[]
  observed_range: [number, number] | null
  current: Num
  saturation: Num
}
export type Scenario = {
  unit: 'month'
  revenue_mode: boolean
  current: TableRow
  recommended: TableRow | null
  saturation: TableRow
  curve: CurveRow[]
  channels: ChannelCurve[]
}

export const FILTER_KEYS = [
  'min_budget',
  'max_budget',
  'target_cpa',
  'target_icpa',
  'min_roas',
  'min_iroas',
  'min_kpi',
  'min_incrementality_pct',
] as const
export type Filters = Partial<Record<(typeof FILTER_KEYS)[number], number>>

const toQuery = (filters: Filters) => {
  const params = new URLSearchParams()
  for (const key of FILTER_KEYS) if (filters[key] != null) params.set(key, String(filters[key]))
  const query = params.toString()
  return query ? `?${query}` : ''
}

export const scenarioQuery = (slug: string, runId: string, filters: Filters) =>
  queryOptions({
    queryKey: ['scenario', slug, runId, filters],
    queryFn: () => api<Scenario>(`/w/${slug}/runs/${runId}/scenario${toQuery(filters)}`),
    // same run and filters, same answer
    staleTime: Infinity,
    placeholderData: keepPreviousData,
    // 409 and 422 are answers, not hiccups
    retry: false,
  })

export function useDebounced<T>(value: T, ms = 200) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(timer)
  }, [value, ms])
  return debounced
}

// FastAPI's 422 body: {detail: [{msg: "Value error, o orçamento mínimo passa do máximo", ...}]}
export const filterErrors = (body: Record<string, unknown>) =>
  Array.isArray(body.detail)
    ? body.detail.map((d: { msg?: string }) => String(d.msg ?? '').replace(/^Value error, /, ''))
    : []
```

- [ ] **Step 3: Typecheck**

Run: `cd web && bunx tsc -b`
Expected: sem erro.

- [ ] **Step 4: Commit**

```bash
git add web/src/lib/results.ts web/src/lib/scenario.ts
git commit -m "feat(web): elasticity types, scenario query and reason labels"
```

---

### Task 5: Front — gráficos da elasticidade

**Files:**
- Create: `web/src/components/elasticity/ElasticityCharts.tsx`
- Create: `web/src/components/elasticity/ChannelCurves.tsx`

Depende só dos tipos da Task 4 (contrato acima). As séries "observado" e "extrapolado" são a mesma curva separada pelo flag `extrapolated` de cada ponto (mapeamento, não conta); os pontos fora do filtro vão numa terceira série esmaecida.

- [ ] **Step 1: `ElasticityCharts.tsx`**

```tsx
import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceDot,
  XAxis,
  YAxis,
} from 'recharts'
import {
  type ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from '@/components/ui/chart'
import { formatCompact, formatMoney } from '@/lib/results'
import type { CurveRow, Mix, Scenario, TableRow } from '@/lib/scenario'

const investmentAxis = (
  <XAxis
    dataKey="investment"
    type="number"
    domain={['dataMin', 'dataMax']}
    tickFormatter={formatCompact}
    minTickGap={32}
  />
)
const moneyLabel = (_: unknown, payload: { payload?: { investment?: number } }[]) =>
  formatMoney(payload[0]?.payload?.investment)

const saturationConfig = {
  band: { label: 'Faixa p5–p95', color: 'var(--chart-2)' },
  observed: { label: 'KPI projetado', color: 'var(--chart-1)' },
  extrapolated: { label: 'Extrapolado', color: 'var(--chart-1)' },
  filtered_out: { label: 'Fora do filtro', color: 'var(--muted-foreground)' },
} satisfies ChartConfig

export function SaturationChart({ scenario }: { scenario: Scenario }) {
  const data = scenario.curve.map((r) => ({
    investment: r.investment,
    band: r.kpi_lo != null && r.kpi_hi != null ? [r.kpi_lo, r.kpi_hi] : null,
    observed: r.extrapolated ? null : r.kpi,
    extrapolated: r.extrapolated ? r.kpi : null,
    filtered_out: r.in_filter ? null : r.kpi,
  }))
  const marks: [string, TableRow | null, string][] = [
    ['Atual', scenario.current, 'var(--chart-3)'],
    ['Recomendado', scenario.recommended, 'var(--chart-4)'],
    ['Saturação', scenario.saturation, 'var(--chart-5)'],
  ]
  return (
    <ChartContainer config={saturationConfig} className="h-80 w-full">
      <ComposedChart data={data} margin={{ left: 4, right: 4 }}>
        <CartesianGrid vertical={false} />
        {investmentAxis}
        <YAxis tickFormatter={formatCompact} width={56} />
        <Area dataKey="band" stroke="none" fill="var(--color-band)" fillOpacity={0.2} isAnimationActive={false} />
        <Line dataKey="observed" stroke="var(--color-observed)" strokeWidth={2} dot={false} isAnimationActive={false} />
        <Line
          dataKey="extrapolated"
          stroke="var(--color-extrapolated)"
          strokeWidth={2}
          strokeDasharray="4 4"
          dot={false}
          isAnimationActive={false}
        />
        <Line
          dataKey="filtered_out"
          stroke="var(--color-filtered_out)"
          strokeOpacity={0.5}
          strokeWidth={4}
          dot={false}
          isAnimationActive={false}
        />
        {marks.map(
          ([label, row, color]) =>
            row?.kpi != null && (
              <ReferenceDot
                key={label}
                x={row.investment}
                y={row.kpi}
                r={5}
                fill={color}
                stroke="var(--background)"
                label={{ value: label, position: 'top', fontSize: 11 }}
              />
            ),
        )}
        <ChartTooltip content={<ChartTooltipContent labelFormatter={moneyLabel} />} />
        <ChartLegend content={<ChartLegendContent />} />
      </ComposedChart>
    </ChartContainer>
  )
}

const icpaConfig = { icpa: { label: 'iCPA', color: 'var(--chart-1)' } } satisfies ChartConfig

export function IcpaChart({ curve }: { curve: CurveRow[] }) {
  return (
    <ChartContainer config={icpaConfig} className="h-56 w-full">
      <ComposedChart data={curve}>
        <CartesianGrid vertical={false} />
        {investmentAxis}
        <YAxis tickFormatter={formatCompact} width={56} />
        <Line dataKey="icpa" stroke="var(--color-icpa)" strokeWidth={2} dot={false} connectNulls={false} />
        <ChartTooltip content={<ChartTooltipContent labelFormatter={moneyLabel} />} />
      </ComposedChart>
    </ChartContainer>
  )
}

const revenueConfig = {
  revenue: { label: 'Receita', color: 'var(--chart-1)' },
  roas: { label: 'ROAS', color: 'var(--chart-3)' },
} satisfies ChartConfig

export function RevenueChart({ curve }: { curve: CurveRow[] }) {
  return (
    <ChartContainer config={revenueConfig} className="h-56 w-full">
      <ComposedChart data={curve}>
        <CartesianGrid vertical={false} />
        {investmentAxis}
        <YAxis yAxisId="revenue" tickFormatter={formatCompact} width={56} />
        <YAxis yAxisId="roas" orientation="right" width={40} />
        <Line yAxisId="revenue" dataKey="revenue" stroke="var(--color-revenue)" strokeWidth={2} dot={false} />
        <Line yAxisId="roas" dataKey="roas" stroke="var(--color-roas)" dot={false} />
        <ChartTooltip content={<ChartTooltipContent labelFormatter={moneyLabel} />} />
        <ChartLegend content={<ChartLegendContent />} />
      </ComposedChart>
    </ChartContainer>
  )
}

const mixConfig = {
  historical: { label: 'Histórico', color: 'var(--chart-2)' },
  optimized: { label: 'Otimizado', color: 'var(--chart-1)' },
  strategic: { label: 'Estratégico', color: 'var(--chart-4)' },
} satisfies ChartConfig

export function MixChart({ mix }: { mix: Partial<Mix> }) {
  const channels = Object.keys(mix.historical ?? mix.optimized ?? mix.strategic ?? {})
  const data = channels.map((channel) => ({
    channel,
    historical: mix.historical?.[channel] ?? null,
    optimized: mix.optimized?.[channel] ?? null,
    strategic: mix.strategic?.[channel] ?? null,
  }))
  return (
    <ChartContainer config={mixConfig} className="h-64 w-full">
      <BarChart data={data}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="channel" />
        <YAxis tickFormatter={formatCompact} width={56} />
        <Bar dataKey="historical" fill="var(--color-historical)" radius={4} />
        <Bar dataKey="optimized" fill="var(--color-optimized)" radius={4} />
        <Bar dataKey="strategic" fill="var(--color-strategic)" radius={4} />
        <ChartTooltip content={<ChartTooltipContent />} />
        <ChartLegend content={<ChartLegendContent />} />
      </BarChart>
    </ChartContainer>
  )
}
```

- [ ] **Step 2: `ChannelCurves.tsx`**

```tsx
import { Area, Bar, BarChart, CartesianGrid, ComposedChart, Line, ReferenceArea, ReferenceLine, XAxis, YAxis } from 'recharts'
import { type ChartConfig, ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent } from '@/components/ui/chart'
import { type ChannelFit, formatCompact, formatMoney, reasonLabel } from '@/lib/results'
import type { ChannelCurve } from '@/lib/scenario'

const curveConfig = {
  band: { label: 'Faixa p5–p95', color: 'var(--chart-2)' },
  observed: { label: 'KPI projetado', color: 'var(--chart-1)' },
  extrapolated: { label: 'Extrapolado', color: 'var(--chart-1)' },
} satisfies ChartConfig

function ChannelChart({ channel }: { channel: ChannelCurve }) {
  const data = channel.curve.map((p) => ({
    investment: p.investment,
    band: p.kpi_lo != null && p.kpi_hi != null ? [p.kpi_lo, p.kpi_hi] : null,
    observed: p.extrapolated ? null : p.kpi,
    extrapolated: p.extrapolated ? p.kpi : null,
  }))
  return (
    <figure className="space-y-1 rounded-lg border p-3">
      <figcaption className="text-sm font-medium">{channel.name}</figcaption>
      <ChartContainer config={curveConfig} className="h-44 w-full">
        <ComposedChart data={data}>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="investment" type="number" domain={['dataMin', 'dataMax']} tickFormatter={formatCompact} minTickGap={24} />
          <YAxis tickFormatter={formatCompact} width={48} />
          {channel.observed_range && (
            <ReferenceArea x1={channel.observed_range[0]} x2={channel.observed_range[1]} fill="var(--muted-foreground)" fillOpacity={0.08} />
          )}
          <Area dataKey="band" stroke="none" fill="var(--color-band)" fillOpacity={0.2} isAnimationActive={false} />
          <Line dataKey="observed" stroke="var(--color-observed)" strokeWidth={2} dot={false} isAnimationActive={false} />
          <Line dataKey="extrapolated" stroke="var(--color-extrapolated)" strokeWidth={2} strokeDasharray="4 4" dot={false} isAnimationActive={false} />
          {channel.current != null && <ReferenceLine x={channel.current} stroke="var(--chart-3)" label={{ value: 'Atual', fontSize: 10 }} />}
          {channel.saturation != null && (
            <ReferenceLine x={channel.saturation} stroke="var(--chart-5)" label={{ value: 'Saturação', fontSize: 10 }} />
          )}
          <ChartTooltip content={<ChartTooltipContent labelFormatter={(_, p) => formatMoney(p[0]?.payload?.investment)} />} />
        </ComposedChart>
      </ChartContainer>
    </figure>
  )
}

const compareConfig = {
  current: { label: 'Atual', color: 'var(--chart-3)' },
  saturation: { label: 'Saturação', color: 'var(--chart-5)' },
} satisfies ChartConfig

export function ChannelCurves({ channels, hidden }: { channels: ChannelCurve[]; hidden: ChannelFit[] }) {
  return (
    <section aria-label="Canais" className="space-y-4">
      <h2 className="text-lg font-semibold">Canais</h2>
      {channels.length > 0 && (
        <>
          <div className="grid gap-3 lg:grid-cols-2">
            {channels.map((c) => (
              <ChannelChart key={c.name} channel={c} />
            ))}
          </div>
          <ChartContainer config={compareConfig} className="h-56 w-full">
            <BarChart data={channels.map((c) => ({ name: c.name, current: c.current, saturation: c.saturation }))}>
              <CartesianGrid vertical={false} />
              <XAxis dataKey="name" />
              <YAxis tickFormatter={formatCompact} width={56} />
              <Bar dataKey="current" fill="var(--color-current)" radius={4} />
              <Bar dataKey="saturation" fill="var(--color-saturation)" radius={4} />
              <ChartTooltip content={<ChartTooltipContent />} />
              <ChartLegend content={<ChartLegendContent />} />
            </BarChart>
          </ChartContainer>
        </>
      )}
      {hidden.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-medium">Sem efeito identificável (fora das curvas, do mix e dos cenários)</h3>
          <ul className="space-y-1 text-sm">
            {hidden.map((c) => (
              <li key={c.name}>
                <span className="font-medium">{c.name}</span>
                <span className="text-muted-foreground"> — {c.reasons.map(reasonLabel).join('; ') || 'não identificável'}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
```

- [ ] **Step 3: Typecheck e lint**

Run: `cd web && bunx tsc -b && bun run lint`
Expected: sem erro. Se o tipo do `labelFormatter` do `ChartTooltipContent` não aceitar a assinatura, use `(_, payload) => formatMoney((payload[0]?.payload as { investment?: number } | undefined)?.investment)` — o objetivo é o tooltip mostrar o investimento em R$.

- [ ] **Step 4: Commit**

```bash
git add web/src/components/elasticity/ElasticityCharts.tsx web/src/components/elasticity/ChannelCurves.tsx
git commit -m "feat(web): elasticity charts (saturation band, icpa, revenue, mix, channel curves)"
```

---

### Task 6: Front — aba, filtros, tabela e rota

**Files:**
- Create: `web/src/components/ui/slider.tsx` (gerado)
- Create: `web/src/components/elasticity/FiltersPanel.tsx`
- Create: `web/src/components/elasticity/ScenarioTable.tsx`
- Create: `web/src/components/elasticity/ElasticityTab.tsx`
- Create: `web/src/routes/_auth/w/$slug/execucoes/$runId/elasticidade.tsx`
- Modify: `web/src/routes/_auth/w/$slug/execucoes/$runId.tsx`

Depende das Tasks 4 e 5 (importa `ElasticityCharts` e `ChannelCurves`).

- [ ] **Step 1: Slider do shadcn**

Run: `cd web && bunx shadcn@latest add slider`
Expected: cria `src/components/ui/slider.tsx` (e a dependência `@radix-ui/react-slider` ou `radix-ui`, conforme o estilo `radix-nova`).

- [ ] **Step 2: `FiltersPanel.tsx`**

```tsx
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Slider } from '@/components/ui/slider'
import { formatMoney } from '@/lib/results'
import type { Filters } from '@/lib/scenario'

type Key = keyof Filters
const FIELDS: [Key, string, boolean][] = [
  ['target_cpa', 'CPA máximo', false],
  ['target_icpa', 'iCPA máximo', false],
  ['min_roas', 'ROAS mínimo', true],
  ['min_iroas', 'iROAS mínimo', true],
  ['min_kpi', 'KPI mínimo', false],
  ['min_incrementality_pct', '% de incrementalidade mínima', false],
]

type Props = {
  filters: Filters
  onChange: (filters: Filters) => void
  bounds: [number, number] | null
  revenueMode: boolean
  errors: string[]
}

export function FiltersPanel({ filters, onChange, bounds, revenueMode, errors }: Props) {
  const set = (key: Key, value: number | undefined) => onChange({ ...filters, [key]: value })
  const budget: [number, number] | null = bounds && [filters.min_budget ?? bounds[0], filters.max_budget ?? bounds[1]]

  return (
    <aside aria-label="Filtros" className="space-y-4">
      <h2 className="text-sm font-medium">Filtros (valores mensais)</h2>
      {bounds && budget && (
        <div className="space-y-2">
          <Label>Orçamento</Label>
          <Slider
            aria-label="Orçamento"
            min={bounds[0]}
            max={bounds[1]}
            step={1}
            value={budget}
            onValueChange={([min, max]) => onChange({ ...filters, min_budget: min, max_budget: max })}
          />
          <p className="text-xs text-muted-foreground">
            {formatMoney(budget[0])} – {formatMoney(budget[1])}
          </p>
        </div>
      )}
      {FIELDS.filter(([, , revenueOnly]) => revenueMode || !revenueOnly).map(([key, label]) => (
        <div key={key} className="space-y-1">
          <Label htmlFor={key}>{label}</Label>
          <Input
            id={key}
            type="number"
            inputMode="decimal"
            min={0}
            value={filters[key] ?? ''}
            onChange={(e) => set(key, e.target.value === '' ? undefined : Number(e.target.value))}
          />
        </div>
      ))}
      <Button variant="outline" size="sm" onClick={() => onChange({})}>
        Limpar
      </Button>
      {errors.length > 0 && (
        <ul role="alert" className="text-sm text-destructive">
          {errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
    </aside>
  )
}
```

- [ ] **Step 3: `ScenarioTable.tsx`**

```tsx
import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow as Row } from '@/components/ui/table'
import { formatDecimal, formatInteger, formatMoney, formatSigned } from '@/lib/results'
import type { Scenario, TableRow } from '@/lib/scenario'

type Line = [string, (r: TableRow) => string, boolean]
const LINES: Line[] = [
  ['Investimento', (r) => formatMoney(r.investment), false],
  ['KPI', (r) => formatInteger(r.kpi), false],
  ['KPI p5–p95', (r) => (r.kpi_lo == null ? '—' : `${formatInteger(r.kpi_lo)} – ${formatInteger(r.kpi_hi)}`), false],
  ['CPA', (r) => formatMoney(r.cpa), false],
  ['iCPA', (r) => formatMoney(r.icpa), false],
  ['ROAS', (r) => formatDecimal(r.roas), true],
  ['iROAS', (r) => formatDecimal(r.iroas), true],
  ['Investimento incremental', (r) => formatMoney(r.incremental_investment), false],
  ['KPI incremental', (r) => formatSigned(r.incremental_kpi), false],
]

export function ScenarioTable({ scenario }: { scenario: Scenario }) {
  const [open, setOpen] = useState<string | null>(null)
  const columns: [string, TableRow | null][] = [
    ['Atual', scenario.current],
    ['Recomendado', scenario.recommended],
    ['Saturação', scenario.saturation],
  ]
  const lines = LINES.filter(([, , revenueOnly]) => scenario.revenue_mode || !revenueOnly)
  const notes = [...new Set(columns.flatMap(([, r]) => r?.notes ?? []))]
  const ramp = columns.find(([name]) => name === open)?.[1]?.ramp

  return (
    <section aria-label="Cenários" className="space-y-3">
      <Table>
        <TableHeader>
          <Row>
            <TableHead />
            {columns.map(([name, r]) => (
              <TableHead key={name} className="text-right">
                {name} {r?.extrapolated && <Badge variant="outline">extrapolado</Badge>}
              </TableHead>
            ))}
          </Row>
        </TableHeader>
        <TableBody>
          {lines.map(([label, show]) => (
            <Row key={label}>
              <TableCell className="text-muted-foreground">{label}</TableCell>
              {columns.map(([name, r]) => (
                <TableCell key={name} className="text-right tabular-nums">
                  {r ? show(r) : label === 'Investimento' ? 'Nenhum ponto da curva atende aos filtros' : ''}
                </TableCell>
              ))}
            </Row>
          ))}
          <Row>
            <TableCell className="text-muted-foreground">Rampa</TableCell>
            {columns.map(([name, r]) => (
              <TableCell key={name} className="text-right">
                {r?.ramp && (
                  <Button variant="link" size="sm" aria-expanded={open === name} onClick={() => setOpen(open === name ? null : name)}>
                    {r.ramp.length} degraus
                  </Button>
                )}
              </TableCell>
            ))}
          </Row>
        </TableBody>
      </Table>
      {ramp && (
        <ol aria-label={`Degraus até ${open}`} className="space-y-1 text-sm">
          {ramp.map((s) => (
            <li key={s.step} className="tabular-nums">
              {s.step}. {formatMoney(s.investment)} → KPI {formatInteger(s.kpi)}
              {s.kpi_lo != null && ` (${formatInteger(s.kpi_lo)} – ${formatInteger(s.kpi_hi)})`}
            </li>
          ))}
        </ol>
      )}
      {notes.map((n) => (
        <p key={n} className="text-sm text-muted-foreground">
          {n}
        </p>
      ))}
    </section>
  )
}
```

- [ ] **Step 4: `ElasticityTab.tsx`**

```tsx
import { useQuery } from '@tanstack/react-query'
import { TriangleAlert } from 'lucide-react'
import { useRef, useState } from 'react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { ApiError } from '@/lib/api'
import { type Elasticity, formatDecimal, reasonLabel, resultsQuery } from '@/lib/results'
import { type Filters, type Scenario, filterErrors, scenarioQuery, useDebounced } from '@/lib/scenario'
import { ChannelCurves } from './ChannelCurves'
import { IcpaChart, MixChart, RevenueChart, SaturationChart } from './ElasticityCharts'
import { FiltersPanel } from './FiltersPanel'
import { ScenarioTable } from './ScenarioTable'

export function ElasticityTab({ slug, runId }: { slug: string; runId: string }) {
  const query = useQuery(resultsQuery(slug, runId))
  if (query.isPending) return <p className="text-sm text-muted-foreground">Carregando…</p>
  if (query.isError)
    return (
      <p role="alert" className="text-sm text-destructive">
        Não foi possível carregar o resultado.
      </p>
    )
  const elasticity = query.data.elasticity
  return (
    <section aria-label="Elasticidade">
      {!elasticity ? (
        <p className="text-sm text-muted-foreground">Sem análise de elasticidade nesta execução.</p>
      ) : elasticity.status !== 'ok' ? (
        <Inconclusive lines={elasticity.reasons.map(reasonLabel)} />
      ) : (
        <Planner slug={slug} runId={runId} elasticity={elasticity} />
      )}
    </section>
  )
}

function Inconclusive({ lines }: { lines: string[] }) {
  return (
    <Alert>
      <TriangleAlert />
      <AlertTitle>Análise de elasticidade inconclusiva</AlertTitle>
      <AlertDescription>
        <ul className="list-disc pl-5">
          {lines.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      </AlertDescription>
    </Alert>
  )
}

function Planner({ slug, runId, elasticity }: { slug: string; runId: string; elasticity: Elasticity }) {
  const [filters, setFilters] = useState<Filters>({})
  const query = useQuery(scenarioQuery(slug, runId, useDebounced(filters)))
  // the slider's range is the whole curve, so it comes from the unfiltered answer (cached by its key)
  const unfiltered = useQuery(scenarioQuery(slug, runId, {})).data
  // a 422 on a bad filter keeps the last good answer on screen
  const last = useRef<Scenario | undefined>(undefined)
  if (query.data) last.current = query.data
  const scenario = query.data ?? last.current

  const error = query.error instanceof ApiError ? query.error : null
  if (!scenario) {
    if (query.isPending) return <p className="text-sm text-muted-foreground">Carregando…</p>
    if (error?.status === 409) return <Inconclusive lines={[error.detail]} />
    return (
      <p role="alert" className="text-sm text-destructive">
        Não foi possível carregar o cenário.
      </p>
    )
  }

  const curve = unfiltered?.curve
  const bounds: [number, number] | null = curve?.length ? [curve[0].investment, curve[curve.length - 1].investment] : null
  const mixRow = scenario.recommended ?? scenario.saturation
  const hidden = elasticity.channels.filter((c) => c.identifiable === false)
  const metrics = elasticity.metrics

  return (
    <div className="grid gap-6 md:grid-cols-[18rem_minmax(0,1fr)]">
      <FiltersPanel
        filters={filters}
        onChange={setFilters}
        bounds={bounds}
        revenueMode={scenario.revenue_mode}
        errors={error?.status === 422 ? filterErrors(error.body) : []}
      />
      <div className="min-w-0 space-y-8">
        {metrics?.low_confidence && (
          <Alert>
            <TriangleAlert />
            <AlertTitle>Baixa confiança</AlertTitle>
            <AlertDescription>
              O modelo explica pouco fora da amostra (CV R² {formatDecimal(metrics.cv_r2)}). Use as curvas como
              direção, não como meta.
            </AlertDescription>
          </Alert>
        )}
        <ScenarioTable scenario={scenario} />
        <section aria-label="Curva de saturação" className="space-y-2">
          <h2 className="text-lg font-semibold">Curva de saturação</h2>
          <SaturationChart scenario={scenario} />
        </section>
        <div className="grid gap-6 lg:grid-cols-2">
          <section aria-label="iCPA" className="space-y-2">
            <h2 className="text-lg font-semibold">iCPA</h2>
            <IcpaChart curve={scenario.curve} />
          </section>
          {scenario.revenue_mode && (
            <section aria-label="Receita e ROAS" className="space-y-2">
              <h2 className="text-lg font-semibold">Receita e ROAS</h2>
              <RevenueChart curve={scenario.curve} />
            </section>
          )}
        </div>
        {mixRow.mix && (
          <section aria-label="Mix por canal" className="space-y-2">
            <h2 className="text-lg font-semibold">Mix por canal</h2>
            {metrics?.reallocation_suppressed && (
              <Alert>
                <TriangleAlert />
                <AlertDescription>
                  O motor não confia na redistribuição entre canais desta execução: leia o otimizado e o estratégico
                  como hipótese, não como recomendação.
                </AlertDescription>
              </Alert>
            )}
            <MixChart mix={mixRow.mix} />
          </section>
        )}
        <ChannelCurves channels={scenario.channels} hidden={hidden} />
      </div>
    </div>
  )
}
```

- [ ] **Step 5: Rota e aba**

`web/src/routes/_auth/w/$slug/execucoes/$runId/elasticidade.tsx` (crie com a ferramenta Write, não heredoc; ver `CLAUDE.md` › cuidado com o gerador do TanStack):

```tsx
import { useQuery } from '@tanstack/react-query'
import { Navigate, createFileRoute } from '@tanstack/react-router'
import { ElasticityTab } from '@/components/elasticity/ElasticityTab'
import { isPublishable, runQuery } from '@/lib/runs'

export const Route = createFileRoute('/_auth/w/$slug/execucoes/$runId/elasticidade')({ component: ElasticityRoute })

function ElasticityRoute() {
  const { slug, runId } = Route.useParams()
  const { data: run } = useQuery(runQuery(slug, runId))
  // same as causal: a URL opened before the run ends would cache the results 404 for good
  if (run && !isPublishable(run.status))
    return <Navigate to="/w/$slug/execucoes/$runId/detalhes" params={{ slug, runId }} replace />
  return <ElasticityTab slug={slug} runId={runId} />
}
```

Em `web/src/routes/_auth/w/$slug/execucoes/$runId.tsx`, o tipo do `to` em `tab` passa a incluir a rota nova:

```tsx
  const tab = (
    to:
      | '/w/$slug/execucoes/$runId/causal'
      | '/w/$slug/execucoes/$runId/elasticidade'
      | '/w/$slug/execucoes/$runId/detalhes',
    label: ReactNode,
  ) => (
```

e o `<span aria-disabled…>Elasticidade (em breve)</span>` vira:

```tsx
        {isPublishable(run.status) && tab('/w/$slug/execucoes/$runId/elasticidade', 'Elasticidade')}
```

- [ ] **Step 6: Build e lint**

Run: `cd web && bunx vite build && bun run build && bun run lint`
Expected: sem erro (o primeiro `vite build` regenera o `routeTree.gen.ts`).

- [ ] **Step 7: Olhar na tela**

Com `docker compose up -d`, `mise run api` e `mise run web` no ar: crie uma simulação, rode (com `ENGINE_FAKE=1` e `FAKE_ENGINE_RESULTS=tests/fixtures/results/identificavel.json` no ambiente da API) e abra a aba Elasticidade. Pelo MCP `playwright`, tire screenshots nos temas claro e escuro: tabela, curva com banda e tracejado, mix com aviso, STRONG com curva, NOEFFECT só com o motivo. Troque para `FAKE_ENGINE_RESULTS=…/gol_anonimizada.json`, rode de novo e confira o alerta inconclusivo sem número. Mexa no slider e confira no DevTools que cada resposta do `scenario` volta em < 500 ms.

- [ ] **Step 8: Commit**

```bash
git add web/src/components/ui/slider.tsx web/src/components/elasticity/ web/src/routes/ web/package.json web/bun.lock
git commit -m "feat(web): elasticity tab with monthly filters, scenario table and charts"
```

---

### Task 7: E2E da aba

**Files:**
- Create: `web/e2e/elasticity.spec.ts`

- [ ] **Step 1: Escrever o spec**

```ts
import { join } from 'node:path'
import { expect, test } from '@playwright/test'
import { ROOT } from './env'
import { createWorkspace, loggedInAdmin, runToCompletion } from './helpers'

const FIXTURES = join(ROOT, 'tests', 'fixtures', 'results')

test('an inconclusive elasticity shows only its reasons', async ({ page }) => {
  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  await runToCompletion(page, slug, 'Gol')

  await page.getByRole('link', { name: 'Elasticidade' }).click()
  await expect(page).toHaveURL(/\/elasticidade$/)
  const tab = page.getByRole('region', { name: 'Elasticidade' })
  await expect(tab).toContainText('Análise de elasticidade inconclusiva')
  await expect(tab).toContainText('Nenhum canal com efeito identificável')
  await expect(tab).not.toContainText('R$')
  await expect(tab.locator('.recharts-surface')).toHaveCount(0)
})

test('an identifiable run shows the planner and filters go to the scenario', async ({ page }) => {
  // the fake engine always returns the Gol; this run's results and scenario come from the identifiable synthetic
  await page.route(/\/runs\/\d+\/results$/, (route) => route.fulfill({ path: join(FIXTURES, 'identificavel.json') }))
  const scenarioUrls: string[] = []
  await page.route(/\/runs\/\d+\/scenario(\?|$)/, (route) => {
    scenarioUrls.push(route.request().url())
    return route.fulfill({ path: join(FIXTURES, 'identificavel_scenario.json') })
  })

  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  await runToCompletion(page, slug, 'Sintético')
  await page.getByRole('link', { name: 'Elasticidade' }).click()

  const table = page.getByRole('region', { name: 'Cenários' })
  for (const column of ['Atual', 'Recomendado', 'Saturação']) await expect(table).toContainText(column)
  await expect(table).toContainText('R$')
  await expect(page.getByText('Baixa confiança')).toBeVisible()
  await expect(page.getByRole('region', { name: 'Curva de saturação' }).locator('.recharts-surface')).toBeVisible()
  await expect(page.getByRole('region', { name: 'Mix por canal' })).toContainText('não confia na redistribuição')

  const channels = page.getByRole('region', { name: 'Canais' })
  await expect(channels.getByRole('figure')).toHaveCount(1)
  await expect(channels).toContainText('STRONG')
  await expect(channels).toContainText('NOEFFECT — O intervalo do efeito inclui zero')

  await page.getByLabel('CPA máximo').fill('5')
  await expect.poll(() => scenarioUrls.some((u) => u.includes('target_cpa=5'))).toBe(true)
})
```

- [ ] **Step 2: Rodar**

Run: `mise run e2e`
Expected: os specs novos e todos os antigos passam (`results.spec.ts`, `history.spec.ts`, `simulations.spec.ts` abrem o run e não devem mudar). Se o `role="figure"` não casar com o `<figure>` do `ChannelChart`, ajuste o seletor para `channels.locator('figure')`.

- [ ] **Step 3: Commit**

```bash
git add web/e2e/elasticity.spec.ts
git commit -m "test(e2e): elasticity tab, inconclusive and identifiable"
```

---

### Task 8: Docs

**Files:**
- Modify: `docs/decisoes/dashboards.md`
- Modify: `API-GUIDE.md` (linha 48)
- Modify: `docs/m2/trilha-b-plataforma.md` (Status do B5, linha 150)
- Modify: `CLAUDE.md` (Estado atual)

- [ ] **Step 1: `dashboards.md`** — acrescente, antes de "## O front não calcula":

```markdown
## Elasticidade não conclusiva não mostra número (07/nov/2026)

Com `elasticity.status` diferente de `ok`, o `engine.scenario` recusa (`NOT_CONCLUSIVE`, 409 na rota) e a aba mostra só o alerta com os motivos. A Gol sai `inconclusive` por `no_identifiable_channel`, e a curva dela, com recomendado e saturação, vinha inteira de canais que o motor não identificou. É a regra do evento rejeitado aplicada à elasticidade, e o gate mora no motor para nenhum outro consumidor (export do B7) escapar dele.

## Tudo mensal, escalado no motor (07/nov/2026)

As curvas por canal, a faixa observada e o mix estão no `results.json` em valores diários do período. O `scenario` devolve tudo já em valores mensais, pelo mesmo `30 / period_days` do agregado; o gasto atual de cada canal é a participação histórica (constante ao longo da curva) × o investimento atual.

## Mix com as três séries mesmo com a realocação suprimida (07/nov/2026)

Com `metrics.reallocation_suppressed`, o gráfico de mix mostra histórico, otimizado e estratégico sob um aviso de que o motor não confia na redistribuição, em vez de esconder o otimizado. Decisão do time em 07/nov/2026: o analista prefere ver a hipótese marcada a perder a comparação.

## Filtros num painel à esquerda (07/nov/2026)

Como a sidebar do Streamlit e a lista de eventos da aba Causal: os filtros ficam sempre ao lado do que mudam. Ficam no estado do componente, não na URL, até alguém precisar de link com filtro.
```

- [ ] **Step 2: `API-GUIDE.md`** — na linha do `scenario`, troque `→ {unit, revenue_mode, current, recommended, saturation, curve} do engine.scenario; recommended é null quando nada passa; 409 se o run não tem curva;` por:

```
→ `{unit, revenue_mode, current, recommended, saturation, curve, channels}` do `engine.scenario` (as linhas da tabela trazem `mix`; `channels` só os identificáveis, mensais); `recommended` é `null` quando nada passa; 409 se o run não tem curva ou se a elasticidade não é conclusiva;
```

- [ ] **Step 3: `trilha-b-plataforma.md`** — o Status do B5 vira (preencha a contagem real do E2E):

```markdown
- **Status:** ✅ parte 1 (Causal) em 06/nov/2026 e parte 2 (Elasticidade) em 07/nov/2026. Parte 2: aba Elasticidade com filtros mensais à esquerda (slider de orçamento, CPA, iCPA, ROAS/iROAS em modo receita, KPI, % incrementalidade; debounce de 200 ms), tabela Atual/Recomendado/Saturação com degraus e notas tCPA/tROAS, curva de saturação com banda p5/p95, trecho extrapolado tracejado e pontos fora do filtro, iCPA, receita/ROAS, mix (com aviso quando a realocação é suprimida) e curvas por canal só dos identificáveis; elasticidade não `ok` é recusada pelo `engine.scenario` (409) e a aba mostra só os motivos. Verificado: `tests/engine/test_scenario.py`, `tests/api/test_scenario_route.py`, `tests/api/test_rbac.py`, `web/e2e/elasticity.spec.ts` (Gol inconclusiva e o `identificavel.json` servido por `page.route`; E2E completo N/N), screenshots nos dois temas e o slider abaixo de 500 ms. Desvios em `docs/decisoes/dashboards.md`. Falta: o card do experiment design (A7) e o selo de grounding (A9).
```

- [ ] **Step 4: `CLAUDE.md`** — no "Estado atual", depois da frase do B5 parte 1, acrescente:

```markdown
**B5 parte 2 (aba Elasticidade) concluída em 07/nov/2026**: filtros mensais num painel à esquerda sobre o `engine.scenario`, tabela com degraus, curva com banda e extrapolação, iCPA, receita/ROAS, mix e curvas por canal só dos identificáveis; o `scenario` recusa elasticidade não `ok` (409) e devolve `channels` e `mix` mensais.
```

e, na lista do "Faltam", troque "B5 parte 2 (aba Elasticidade sobre o `scenario`), B7 (depende do B5)" por "B7 (export; o B5 está pronto)".

- [ ] **Step 5: Verificação final e commit**

Run: `mise run test && cd web && bun run build && bun run lint`
Expected: tudo passa.

```bash
git add docs/decisoes/dashboards.md API-GUIDE.md docs/m2/trilha-b-plataforma.md CLAUDE.md
git commit -m "docs: b5 part 2 elasticity tab, decisions and status"
```
