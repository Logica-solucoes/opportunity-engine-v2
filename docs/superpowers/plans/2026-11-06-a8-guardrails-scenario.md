# A8 · Guardrails do planner e `engine.scenario` — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Banda p5/p95 e flag de extrapolação em todo ponto projetado, curvas individuais dentro do cap, `ramp` e nota de tCPA/tROAS nos cenários, `engine.scenario` com os filtros do Streamlit e a rota `GET /api/w/{slug}/runs/{run_id}/scenario`.

**Architecture:** O `run` calcula banda e `extrapolated` em `elasticity_analysis.py` (onde o mix de cada ponto é conhecido) e o `results.py` publica, junto com `ramp` e `notes`. `engine/scenario.py` é puro sobre o dict do `results.json`: filtra a curva já simulada, acha recomendado e saturação, converte para mensal. A API só lê o `results.json` do storage e chama `engine.scenario`.

**Tech Stack:** Python 3.13, numpy, pandas, pydantic 2, FastAPI 0.158, pytest. `uv` para tudo.

**Spec:** `docs/superpowers/specs/2026-11-06-a8-guardrails-scenario-design.md`. Leia antes de começar, junto com `CODE-STYLE.md` (motor) e `API-GUIDE.md` (Task 6).

---

## File Structure

| Arquivo | Papel |
|---|---|
| `engine/scenario.py` (novo) | `ramp`, `bid_note`, `ScenarioFilters`, `scenario()` e o port do `find_saturation_point` |
| `engine/elasticity_analysis.py` | `kpi_band` (módulo), banda e `Extrapolated` na curva agregada, nos pontos e nas curvas individuais; tira o bypass do cap |
| `engine/results_schema.py` | `Scenario.notes` |
| `engine/results.py` | publica banda, `extrapolated`, `ramp` e `notes` |
| `engine/__init__.py` | exporta `scenario` e `ScenarioFilters` |
| `api/runs.py`, `api/routes/runs.py` | leitura do `results.json` e a rota |
| `tests/engine/test_ramp.py` (novo) | `ramp` e `bid_note` |
| `tests/engine/test_guardrails.py` (novo) | banda, extrapolação, cap e publicação, rodando o motor |
| `tests/engine/test_scenario.py` (novo) | `scenario()`, paridade com o Streamlit, saturação, tempo |
| `tests/api/test_scenario.py` (novo) | rota |
| `tests/engine/test_parity.py`, `tests/engine/test_elasticity_analysis.py`, `tests/engine/test_pipeline_stages.py` | ajustes às colunas novas |

## Ordem e paralelismo

- Lote 1 (paralelo): Task 1, Task 2.
- Lote 2 (paralelo): Task 3 (depois da 2, mesmo arquivo), Task 5 (depois da 1, mesmo arquivo).
- Lote 3 (paralelo): Task 4 (depois de 1, 2 e 3), Task 6 (depois da 5).
- Lote 4: Task 7 (docs), depois de tudo.

Modelo sugerido: Task 1 e 7 haiku; as demais sonnet.

Comandos: `uv run pytest tests/engine/<arquivo> -v` (motor, sem banco) e `uv run pytest tests/api/<arquivo> -v` (precisa do Postgres do `docker compose up -d`). `uv run ruff check . && uv run ruff format --check .` antes de cada commit.

---

### Task 1: `ramp` e `bid_note`

**Files:**
- Create: `engine/scenario.py`
- Test: `tests/engine/test_ramp.py`

- [ ] **Step 1: Write the failing test**

```python
import pytest

from engine.scenario import TCPA_NOTE, TROAS_NOTE, bid_note, ramp

CURVE = [
    {"investment": 0.0, "kpi": 0.0, "kpi_lo": 0.0, "kpi_hi": 0.0},
    {"investment": 200.0, "kpi": 400.0, "kpi_lo": 300.0, "kpi_hi": 500.0},
]


def levels(steps):
    return [s["investment"] for s in steps]


def test_plus_50_percent_in_20_percent_steps_is_three_steps_ending_on_target():
    steps = ramp(100.0, 150.0, 0.2, CURVE)

    assert levels(steps) == pytest.approx([120.0, 144.0, 150.0])
    assert [s["step"] for s in steps] == [1, 2, 3]


def test_minus_50_percent_needs_four_steps_down():
    assert levels(ramp(100.0, 50.0, 0.2, CURVE)) == pytest.approx([80.0, 64.0, 51.2, 50.0])


def test_a_move_within_the_step_needs_no_ramp():
    assert ramp(100.0, 115.0, 0.2, CURVE) is None
    assert ramp(100.0, 120.0, 0.2, CURVE) is None
    assert ramp(100.0, 100.0, 0.2, CURVE) is None


def test_landing_exactly_on_a_step_does_not_add_a_tiny_last_step():
    assert levels(ramp(100.0, 144.0, 0.2, CURVE)) == pytest.approx([120.0, 144.0])


def test_no_ramp_without_a_current_investment():
    assert ramp(0.0, 150.0, 0.2, CURVE) is None
    assert ramp(None, 150.0, 0.2, CURVE) is None


def test_step_kpi_and_band_are_interpolated_on_the_curve():
    first = ramp(100.0, 150.0, 0.2, CURVE)[0]

    assert first["kpi"] == pytest.approx(240.0)
    assert first["kpi_lo"] == pytest.approx(180.0)
    assert first["kpi_hi"] == pytest.approx(300.0)


def test_a_curve_without_band_gives_steps_without_band():
    curve = [{**row, "kpi_lo": None, "kpi_hi": None} for row in CURVE]

    first = ramp(100.0, 150.0, 0.2, curve)[0]

    assert first["kpi"] == pytest.approx(240.0)
    assert first["kpi_lo"] is None and first["kpi_hi"] is None


def test_the_bid_note_follows_the_mode():
    assert bid_note(revenue_mode=False) == TCPA_NOTE
    assert bid_note(revenue_mode=True) == TROAS_NOTE
    assert "tCPA" in TCPA_NOTE and "tROAS" in TROAS_NOTE
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_ramp.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.scenario'`

- [ ] **Step 3: Write minimal implementation**

`engine/scenario.py`:

```python
"""Planner guardrails and the interactive scenario (A8). Pure over the results.json dict: no model, no I/O."""

import numpy as np

TCPA_NOTE = (
    "Campanhas com CPA desejado (tCPA): mudar a verba pode pedir ajuste do CPA desejado. Espere o período de "
    "aprendizado do lance automático antes de ler o resultado ou dar o próximo degrau."
)
TROAS_NOTE = (
    "Campanhas com ROAS desejado (tROAS): mudar a verba pode pedir ajuste do ROAS desejado. Espere o período de "
    "aprendizado do lance automático antes de ler o resultado ou dar o próximo degrau."
)
_TOLERANCE = 1e-9


def bid_note(revenue_mode: bool) -> str:
    return TROAS_NOTE if revenue_mode else TCPA_NOTE


def _at(investment: float, curve: list[dict], key: str) -> float | None:
    values = [row[key] for row in curve]
    if not curve or any(v is None for v in values):
        return None
    return float(np.interp(investment, [row["investment"] for row in curve], values))


def ramp(current: float | None, target: float, max_step: float, curve: list[dict]) -> list[dict] | None:
    """Compounding steps of at most `max_step` from `current` to `target` (the last one lands on it), with KPI and
    band interpolated on `curve` (ascending investment). None when a single move is within the step."""
    if not current or current <= 0 or abs(target / current - 1) <= max_step + _TOLERANCE:
        return None
    up = target > current
    factor = 1 + max_step if up else 1 - max_step
    tolerance = _TOLERANCE * current
    levels, level = [], current
    while True:
        level *= factor
        if (level >= target - tolerance) if up else (level <= target + tolerance):
            levels.append(target)
            break
        levels.append(level)
    return [
        {
            "step": i,
            "investment": investment,
            "kpi": _at(investment, curve, "kpi"),
            "kpi_lo": _at(investment, curve, "kpi_lo"),
            "kpi_hi": _at(investment, curve, "kpi_hi"),
        }
        for i, investment in enumerate(levels, 1)
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/engine/test_ramp.py -v`
Expected: 8 passed

- [ ] **Step 5: Commit**

```bash
git add engine/scenario.py tests/engine/test_ramp.py
git commit -m "feat(engine): budget ramp in steps of at most max_budget_step and the tCPA/tROAS note"
```

---

### Task 2: banda e extrapolação na curva agregada

**Files:**
- Modify: `engine/elasticity_analysis.py` (`predict_clipped_kpi` em ~128; `generate_aggregated_response_curve` em ~574-933)
- Modify: `tests/engine/test_elasticity_analysis.py:~232` (o `_make_results` ganha `coef_samples`)
- Test: `tests/engine/test_guardrails.py`

Contexto: `elasticity_results["coef_samples"]` é a matriz `(200, canais)` do bootstrap, no mesmo espaço escalado do `mkt_model.coef_` (A5). O modelo não tem intercepto (`fit_intercept=False`), então `KPI = organic_baseline_mean + coef · features_escaladas`.

- [ ] **Step 1: Write the failing test**

`tests/engine/test_guardrails.py`:

```python
import numpy as np
import pandas as pd
from sklearn.linear_model import Ridge
from sklearn.preprocessing import MinMaxScaler

from engine.elasticity_analysis import generate_aggregated_response_curve, geometric_adstock, hill_transform
from tests.engine.helpers import full_config


def _small_mmm() -> dict:
    """Two channels with spend uniform in [100, 200]: the historical total sits in ~[200, 400], the average ~300."""
    rng = np.random.default_rng(0)
    n = 120
    a, b = rng.uniform(100, 200, n), rng.uniform(100, 200, n)
    df = pd.DataFrame({"A": a, "B": b, "kpi": 1000 + 5 * a + b + rng.normal(0, 10, n)})
    df["kpi_organic_baseline"] = 1000.0
    params = {"alphas": [0.0, 0.0], "ks": [1.0, 1.0], "ss": [150.0, 150.0]}
    features = np.column_stack(
        [hill_transform(geometric_adstock(df[c].values, params["alphas"][i]), 1.0, 150.0) for i, c in enumerate("AB")]
    )
    scaler = MinMaxScaler().fit(features)
    y = df["kpi"] - df["kpi_organic_baseline"]
    model = Ridge(alpha=1.0, positive=True, fit_intercept=False).fit(scaler.transform(features), y)
    samples = model.coef_ * rng.uniform(0.8, 1.2, (200, 2))
    model.coef_ = samples.mean(axis=0)
    return {
        "dataframe": df,
        "spend_cols": ["A", "B"],
        "optimal_params": params,
        "model": model,
        "scaler": scaler,
        "organic_baseline_mean": 1000.0,
        "contribution_pct": {"A": 80.0, "B": 20.0},
        "cv_r_squared": 0.9,
        "coef_samples": samples,
    }


def _curve(mmm):
    cfg = full_config({"investment_limit_factor": 3.0, "max_channel_mix_share": 0.9})
    return generate_aggregated_response_curve(mmm, cfg)


def test_every_curve_row_has_a_band_around_the_point():
    frame = _curve(_small_mmm())[0]

    assert frame[["KPI_Lo", "KPI_Hi"]].notna().all().all()
    tol = 1e-6 * frame["Projected_Total_KPIs"].abs()
    assert (frame["KPI_Lo"] <= frame["Projected_Total_KPIs"] + tol).all()
    assert (frame["Projected_Total_KPIs"] <= frame["KPI_Hi"] + tol).all()
    assert (frame["KPI_Hi"] - frame["KPI_Lo"]).iloc[1:].gt(0).all()


def test_rows_outside_the_historical_total_are_extrapolated():
    mmm = _small_mmm()
    frame = _curve(mmm)[0]
    total = mmm["dataframe"][["A", "B"]].sum(axis=1)

    outside = (frame["Daily_Investment"] < total.min()) | (frame["Daily_Investment"] > total.max())
    assert frame.loc[outside, "Extrapolated"].all()
    assert bool(frame["Extrapolated"].iloc[0]) is True


def test_the_notable_points_carry_band_and_flag():
    _, baseline, max_efficiency, strategic_limit, _, _, reallocation = _curve(_small_mmm())

    for point in (baseline, max_efficiency, strategic_limit, reallocation):
        assert point["KPI_Lo"] <= point["KPI_Hi"]
        assert point["Extrapolated"] in (True, False)
    assert bool(baseline["Extrapolated"]) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_guardrails.py -v`
Expected: FAIL with `KeyError: 'KPI_Lo'`

- [ ] **Step 3: Write minimal implementation**

Em `engine/elasticity_analysis.py`, logo depois de `predict_clipped_kpi`:

```python
def kpi_band(organic_baseline_mean, coef_samples, mkt_scaler, mkt_features) -> tuple[float, float]:
    """p5/p95 of the KPI over the bootstrap resamples of the Ridge (A8). Hill, adstock and scaler stay fixed, so the
    band is optimistic: it carries the uncertainty of the split, not of the curve shapes."""
    scaled = np.clip(mkt_scaler.transform([mkt_features]), 0.0, None)[0]
    lo, hi = np.percentile(organic_baseline_mean + np.asarray(coef_samples) @ scaled, [5, 95])
    return float(lo), float(hi)
```

Em `generate_aggregated_response_curve`, logo depois da definição de `simulate_kpi`:

```python
    coef_samples = elasticity_results["coef_samples"]
    total_history = df[active_spend_cols].sum(axis=1)
    total_range = (total_history.min(), total_history.max())
    channel_range = {col: (df[col].min(), df[col].max()) for col in active_spend_cols}

    def simulate_band(total_spend, mix):
        mkt_features = []
        for i, col in enumerate(active_spend_cols):
            simulated_daily_spend = _capped_channel_spend(total_spend * mix.get(col, 0), col)
            simulated_adstocked = simulated_daily_spend * adstock_multipliers[col]
            mkt_features.append(hill_transform(simulated_adstocked, opt_params["ks"][i], opt_params["ss"][i]))
        return kpi_band(organic_baseline_mean, coef_samples, mkt_scaler, mkt_features)

    def is_extrapolated(total_spend, mix):
        # outside the observed spend, total or any channel's share of it (A8)
        if not total_range[0] <= total_spend <= total_range[1]:
            return True
        return any(
            not channel_range[col][0] <= total_spend * mix.get(col, 0) <= channel_range[col][1]
            for col in active_spend_cols
        )

    def with_guardrails(point, mix):
        point["KPI_Lo"], point["KPI_Hi"] = simulate_band(point["Daily_Investment"], mix)
        point["Extrapolated"] = is_extrapolated(point["Daily_Investment"], mix)
        return point
```

No laço `for m in multipliers:`, depois de montar `res_dict` com `Projected_Total_KPIs_Optimized` e antes do laço dos `Spend_`:

```python
        res_dict["KPI_Lo"], res_dict["KPI_Hi"] = simulate_band(current_total_daily_spend, current_optimal_mix)
        res_dict["Extrapolated"] = is_extrapolated(current_total_daily_spend, current_optimal_mix)
```

Imediatamente antes do `return (res_df, baseline_point, …)` do fim da função:

```python
    with_guardrails(baseline_point, historical_mix)
    with_guardrails(max_efficiency_point, optimized_mix)
    with_guardrails(strategic_reallocation_point, reallocated_optimal_mix)
```

O `strategic_limit_point` é uma linha do `res_df` (`res_df.loc[…].to_dict()` ou `iloc`) e já herda `KPI_Lo`, `KPI_Hi` e `Extrapolated`.

Em `tests/engine/test_elasticity_analysis.py`, no dict devolvido por `_make_results`, acrescente a chave:

```python
            "coef_samples": model.coef_[None, :],
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/engine/test_guardrails.py tests/engine/test_elasticity_analysis.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add engine/elasticity_analysis.py tests/engine/test_guardrails.py tests/engine/test_elasticity_analysis.py
git commit -m "feat(engine): p5/p95 band and extrapolation flag on the aggregated response curve and its points"
```

---

### Task 3: curvas individuais com cap, banda e flag

**Files:**
- Modify: `engine/elasticity_analysis.py` (`generate_individual_response_curves`, ~935-1005)
- Modify: `tests/engine/test_pipeline_stages.py:~94` (lista de colunas)
- Test: `tests/engine/test_guardrails.py` (acrescentar)

- [ ] **Step 1: Write the failing test**

Acrescente a `tests/engine/test_guardrails.py`:

```python
from engine.elasticity_analysis import generate_individual_response_curves


def test_individual_curves_stay_within_the_channel_cap_even_past_the_recommended_spend():
    mmm = _small_mmm()
    cfg = full_config({"investment_limit_factor": 3.0, "per_channel_investment_limit_factor": 1.2})
    cap = mmm["dataframe"]["A"].max() * 1.2
    far_recommendation = {"Spend_A_Strategic": cap * 2, "Spend_B_Strategic": cap * 2}

    curves = generate_individual_response_curves(mmm, cfg, strategic_limit_point=far_recommendation)

    for channel in ("A", "B"):
        own = curves[curves["Channel"] == channel]
        assert own["Channel_Spend"].max() <= mmm["dataframe"][channel].max() * 1.2 + 1e-9


def test_individual_curve_points_carry_band_and_flag():
    mmm = _small_mmm()
    curves = generate_individual_response_curves(mmm, full_config({}))

    assert (curves["KPI_Lo"] <= curves["KPI_Hi"]).all()
    own = curves[curves["Channel"] == "A"]
    low, high = mmm["dataframe"]["A"].min(), mmm["dataframe"]["A"].max()
    expected = (own["Channel_Spend"] < low) | (own["Channel_Spend"] > high)
    assert (own["Extrapolated"] == expected).all()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_guardrails.py -k individual -v`
Expected: FAIL (o primeiro por passar do cap, o segundo com `KeyError: 'KPI_Lo'`)

- [ ] **Step 3: Write minimal implementation**

Em `generate_individual_response_curves`:

1. Depois de `per_channel_limit_factor = …`:

```python
    coef_samples = elasticity_results["coef_samples"]
    historical_min_daily_spend = {col: df[col].min() for col in active_spend_cols}
```

2. Troque o bloco do cap (hoje com o bypass):

```python
        channel_cap = historical_max_daily_spend.get(target_channel, 0) * per_channel_limit_factor
        if channel_cap > 0:
            if rec_spend is not None and rec_spend * 1.2 > channel_cap:
                max_spend = rec_spend * 1.2
            else:
                max_spend = min(max_spend, channel_cap)
```

por:

```python
        # A8: the curve never passes the range the Hill fit is trusted in, not even to reach the recommended spend
        channel_cap = historical_max_daily_spend.get(target_channel, 0) * per_channel_limit_factor
        if channel_cap > 0:
            max_spend = min(max_spend, channel_cap)
```

e ajuste o comentário logo acima (tire a frase "However, if we have a recommended investment that exceeds the channel cap, we bypass the cap…").

3. No laço `for spend in spend_points:`, depois de `predicted_kpi = predict_clipped_kpi(…)`:

```python
            kpi_lo, kpi_hi = kpi_band(organic_baseline_mean, coef_samples, mkt_scaler, mkt_features)
            observed = historical_min_daily_spend[target_channel] <= spend <= historical_max_daily_spend[target_channel]
```

e acrescente ao dict do `individual_curves.append(...)`, depois de `"Recommended": rec_spend,`:

```python
                    "KPI_Lo": kpi_lo,
                    "KPI_Hi": kpi_hi,
                    "Extrapolated": not observed,
```

Em `tests/engine/test_pipeline_stages.py`, no `test_individual_curves_function_returns_the_frame`, a lista esperada vira:

```python
    assert list(frame.columns) == [
        "Channel", "Channel_Spend", "Projected_Total_KPIs", "Historical_Avg", "Recommended", "KPI_Lo", "KPI_Hi", "Extrapolated"
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/engine/test_guardrails.py tests/engine/test_pipeline_stages.py -v`
Expected: all passed

- [ ] **Step 5: Commit**

```bash
git add engine/elasticity_analysis.py tests/engine/test_guardrails.py tests/engine/test_pipeline_stages.py
git commit -m "feat(engine): individual curves respect the channel cap and carry band and extrapolation flag"
```

---

### Task 4: publicar banda, flag, `ramp` e `notes` no `results.json`

**Files:**
- Modify: `engine/results_schema.py` (classe `Scenario`)
- Modify: `engine/results.py` (`_response_rows`, `_scenarios`, `_channel_fits`, `_elasticity`)
- Modify: `tests/engine/test_parity.py` (`test_response_curve_and_points_match`)
- Test: `tests/engine/test_guardrails.py` (acrescentar)

- [ ] **Step 1: Write the failing test**

Acrescente a `tests/engine/test_guardrails.py`:

```python
import math

from engine import results


def test_results_publish_band_flag_ramp_and_notes(identifiable_computed):
    doc = results.dump_results(results.build_results(identifiable_computed, "test"))
    elasticity = doc["elasticity"]

    assert all(r["kpi_lo"] is not None and r["kpi_hi"] is not None for r in elasticity["response_curve"])
    assert all(r["extrapolated"] in (True, False) for r in elasticity["response_curve"])

    scenarios = {s["name"]: s for s in elasticity["scenarios"]}
    current = scenarios["current"]["investment"]
    assert scenarios["current"]["ramp"] is None and scenarios["current"]["notes"] == []
    for s in scenarios.values():
        assert s["kpi_lo"] is not None and s["kpi_hi"] is not None and s["extrapolated"] in (True, False)
        assert (s["ramp"] is not None) == (abs(s["investment"] / current - 1) > 0.2 + 1e-9)
        assert bool(s["notes"]) == (not math.isclose(s["investment"], current))

    published = [c for c in elasticity["channels"] if c["identifiable"]]
    assert published and all(p["lo"] is not None and p["extrapolated"] is not None for c in published for p in c["curve"])
```

(`identifiable_computed` é a fixture de sessão de `tests/engine/conftest.py`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_guardrails.py::test_results_publish_band_flag_ramp_and_notes -v`
Expected: FAIL (`kpi_lo` nulo na curva)

- [ ] **Step 3: Write minimal implementation**

`engine/results_schema.py`, classe `Scenario`, depois de `ramp`:

```python
    notes: list[str] = Field(default_factory=list)  # tCPA/tROAS note when the budget changes (A8)
```

`engine/results.py`:

1. Import: `from engine import identifiability, scenario`, e `import math` já existe.
2. Helper perto de `_num`:

```python
def _flag(value: Any) -> bool | None:
    return None if value is None else bool(value)
```

3. Em `_response_rows`, no `ResponseRow(...)`, acrescente:

```python
                kpi_lo=_num(record.get("KPI_Lo")),
                kpi_hi=_num(record.get("KPI_Hi")),
                extrapolated=_flag(record.get("Extrapolated")),
```

4. `_scenarios` passa a receber as linhas já montadas:

```python
def _scenarios(computed: "Computed", rows: list[ResponseRow]) -> list[Scenario]:
    cfg = computed.effective_config
    curve = [row.model_dump() for row in rows]
    current = _num((computed.baseline_point or {}).get("Daily_Investment"))
    note = scenario.bid_note(_revenue_mode(cfg))
    scenarios = []
    for name, attribute in SCENARIO_SOURCES.items():
        point = getattr(computed, attribute)
        if not point or (
            name == "strategic_reallocation" and identifiability.none_identifiable(computed.identifiability)
        ):
            continue
        investment = _num(point.get("Daily_Investment"))
        changes = current is not None and investment is not None and not math.isclose(investment, current)
        scenarios.append(
            Scenario(
                name=name,
                investment=investment,
                kpi=_num(point.get("Projected_Total_KPIs")),
                kpi_lo=_num(point.get("KPI_Lo")),
                kpi_hi=_num(point.get("KPI_Hi")),
                icpa=_icpa(point),
                incremental_investment=_num(point.get("Incremental_Investment")),
                incremental_kpi=_num(point.get("Incremental_KPI")),
                extrapolated=_flag(point.get("Extrapolated")),
                ramp=scenario.ramp(current, investment, cfg["max_budget_step"], curve) if changes else None,
                notes=[note] if changes else [],
            )
        )
    return scenarios
```

5. Em `_channel_fits`, o `CurvePoint`:

```python
                fit.curve = [
                    CurvePoint(
                        x=_num(r.Channel_Spend),
                        y=_num(r.Projected_Total_KPIs),
                        lo=_num(r.KPI_Lo),
                        hi=_num(r.KPI_Hi),
                        extrapolated=_flag(r.Extrapolated),
                    )
                    for r in own.itertuples()
                ]
```

6. Em `_elasticity`, monte as linhas uma vez:

```python
    rows = _response_rows(computed)
```

antes do `return Elasticity(...)`, e use `response_curve=rows, scenarios=_scenarios(computed, rows)`.

`tests/engine/test_parity.py`, acima de `test_response_curve_and_points_match`:

```python
A8_KEYS = {"KPI_Lo", "KPI_Hi", "Extrapolated"}  # added by A8; the prototype has no such columns


def without_a8(obj):
    if isinstance(obj, dict):
        return {key: without_a8(value) for key, value in obj.items() if key not in A8_KEYS}
    if isinstance(obj, list):
        return [without_a8(value) for value in obj]
    return obj
```

e, no teste, `assert_close(without_a8(jsonable(computed.response_curve_df)), …)` e `assert_close(without_a8(jsonable(points)), …)`. O teste só roda no Linux (CI); no Windows ele é pulado, e é esperado.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/engine -q`
Expected: tudo passa (a paridade fica `skipped` no Windows). Se algum teste de `test_results_build.py`, `test_results_run.py` ou `test_results_fixtures.py` comparar o cenário inteiro, ajuste a expectativa às chaves novas (`kpi_lo`, `kpi_hi`, `extrapolated`, `ramp`, `notes`) sem mudar o que ele verifica. Os fixtures de `tests/fixtures/results/` continuam válidos (campos opcionais).

- [ ] **Step 5: Commit**

```bash
git add engine/results_schema.py engine/results.py tests/engine/test_guardrails.py tests/engine/test_parity.py
git commit -m "feat(engine): results.json carries band, extrapolation, ramp and bid notes"
```

---

### Task 5: `engine.scenario`

**Files:**
- Modify: `engine/scenario.py`
- Modify: `engine/__init__.py`
- Test: `tests/engine/test_scenario.py`

Contexto: as linhas da `response_curve` no `results.json` estão **por período** (dia em dado diário); `validation.period_days` dá a cadência. O Streamlit (`opportunity-engine/scripts/streamlit_app.py:1999-2235`) multiplica por `30 / period_days` e filtra. `gol_anonimizada.json` é diário, modo conversões, sem banda.

- [ ] **Step 1: Write the failing test**

`tests/engine/test_scenario.py`:

```python
import json
import time
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from engine import EngineError
from engine.scenario import TCPA_NOTE, ScenarioFilters, _saturation_index, scenario

GOL = json.loads(
    (Path(__file__).resolve().parents[1] / "fixtures" / "results" / "gol_anonimizada.json").read_text(encoding="utf-8")
)


# --- oracle: the prototype's filter and saturation, copied as they are (frozen repo opportunity-engine) ---


def find_saturation_point(df, optimal_point, min_investment=None):
    """dashboard_charts.py:15-62, verbatim."""
    search_df = df
    if min_investment is not None:
        search_df = df[df["Daily_Investment"] >= min_investment]
    incremental_kpis = search_df["Projected_Total_KPIs"].diff().fillna(0).values
    investment_steps = search_df["Daily_Investment"].diff().fillna(1).values
    first_derivative = incremental_kpis / investment_steps
    if len(first_derivative) <= 1:
        return optimal_point
    peak_marginal_gain = first_derivative.max()
    if peak_marginal_gain <= 0:
        return optimal_point
    above_threshold = np.where(first_derivative > peak_marginal_gain * 0.1)[0]
    if len(above_threshold) == 0:
        return optimal_point
    saturation_idx = above_threshold[-1] + 1
    if saturation_idx >= len(search_df):
        return optimal_point
    return search_df.iloc[saturation_idx]


def streamlit_pick(doc, filters):
    """streamlit_app.py:1999-2235 on the results.json rows (conversion mode): monthly investment of the recommended
    point (None when nothing passes) and of the saturation point."""
    rows = doc["elasticity"]["response_curve"]
    days_in_month = 30 / doc["validation"]["period_days"]
    current = next(s for s in doc["elasticity"]["scenarios"] if s["name"] == "current")
    df = pd.DataFrame(
        {
            "Daily_Investment": [r["investment"] for r in rows],
            "Projected_Total_KPIs": [r["kpi"] for r in rows],
            "Incremental_Investment": [r["incremental_investment"] for r in rows],
            "Incremental_KPI": [r["incremental_kpi"] for r in rows],
        }
    )
    df["Monthly_Investment"] = df["Daily_Investment"] * days_in_month
    df["Monthly_KPI"] = df["Projected_Total_KPIs"] * days_in_month
    df["CPA"] = (df["Daily_Investment"] / df["Projected_Total_KPIs"]).replace([np.inf, -np.inf], float("nan"))
    df["iCPA"] = np.where(df["Incremental_KPI"] > 0, df["Incremental_Investment"] / df["Incremental_KPI"], np.nan)
    df["Pct_Incrementality"] = np.where(
        df["Projected_Total_KPIs"] > 0, df["Incremental_KPI"] / df["Projected_Total_KPIs"] * 100, 0.0
    )
    out = df[
        (df["Monthly_Investment"] >= filters.get("min_budget", df["Monthly_Investment"].min()))
        & (df["Monthly_Investment"] <= filters.get("max_budget", df["Monthly_Investment"].max()))
    ]
    if "target_cpa" in filters:
        out = out[out["CPA"] <= filters["target_cpa"]]
    if "target_icpa" in filters:
        out = out[out["iCPA"] <= filters["target_icpa"]]
    if "min_kpi" in filters:
        out = out[out["Monthly_KPI"] >= filters["min_kpi"]]
    if "min_incrementality_pct" in filters:
        out = out[out["Pct_Incrementality"] >= filters["min_incrementality_pct"]]
    optimal = out.iloc[-1] if not out.empty else df.iloc[-1]
    saturation = find_saturation_point(df, optimal, min_investment=current["investment"])
    recommended = None if out.empty else out.iloc[-1]["Monthly_Investment"]
    return recommended, saturation["Daily_Investment"] * days_in_month


def _gol_filters():
    curve = scenario(GOL, ScenarioFilters(), 0.2)["curve"]
    # thresholds between two values: the CPA here and in the oracle may differ in the last bit
    cpas = sorted(r["cpa"] for r in curve if r["cpa"] is not None)
    icpas = sorted(r["icpa"] for r in curve if r["icpa"])  # target_icpa must be > 0
    investments = [r["investment"] for r in curve]
    mid_cpa, mid_icpa = len(cpas) // 2, len(icpas) // 2
    return [
        {},
        {"min_budget": investments[20], "max_budget": investments[70]},
        {"target_cpa": (cpas[mid_cpa] + cpas[mid_cpa + 1]) / 2},
        {"target_icpa": (icpas[mid_icpa] + icpas[mid_icpa + 1]) / 2},
        {"min_kpi": curve[60]["kpi"]},
        {"min_incrementality_pct": 30.0},
        {"max_budget": investments[80], "target_icpa": icpas[-1]},
        {"target_cpa": cpas[0] / 10},  # nothing passes
    ]


@pytest.mark.parametrize("index", range(8))
def test_same_recommended_and_saturation_as_the_streamlit(index):
    filters = _gol_filters()[index]
    expected_recommended, expected_saturation = streamlit_pick(GOL, filters)

    got = scenario(GOL, ScenarioFilters(**filters), 0.2)

    if expected_recommended is None:
        assert got["recommended"] is None
    else:
        assert got["recommended"]["investment"] == pytest.approx(expected_recommended, rel=1e-9)
    assert got["saturation"]["investment"] == pytest.approx(expected_saturation, rel=1e-9)


def test_the_filter_that_empties_the_curve_still_answers():
    got = scenario(GOL, ScenarioFilters(target_cpa=1e-9), 0.2)

    assert got["recommended"] is None
    assert not any(r["in_filter"] for r in got["curve"])
    assert got["saturation"] is not None


def test_scenario_is_fast_enough_for_the_slider():
    filters = ScenarioFilters(target_icpa=50.0)
    start = time.perf_counter()
    for _ in range(10):
        scenario(GOL, filters, 0.2)
    assert (time.perf_counter() - start) / 10 < 0.3


def test_a_fixture_without_band_gives_rows_without_band():
    got = scenario(GOL, ScenarioFilters(), 0.2)

    assert got["unit"] == "month" and got["revenue_mode"] is False
    assert len(got["curve"]) == len(GOL["elasticity"]["response_curve"])
    assert got["current"]["kpi_lo"] is None and got["curve"][0]["kpi_lo"] is None


# --- hand-made documents ---


def _row(investment, kpi, revenue=None, iroas=None, inc_inv=0.0, inc_kpi=0.0):
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
        "mix": {},
    }


def _doc(rows, current_investment=20.0, current_kpi=40.0, period_days=1):
    current = {
        "name": "current",
        "investment": current_investment,
        "kpi": current_kpi,
        "kpi_lo": current_kpi * 0.9,
        "kpi_hi": current_kpi * 1.1,
        "extrapolated": False,
    }
    return {"validation": {"period_days": period_days}, "elasticity": {"response_curve": rows, "scenarios": [current]}}


CONVERSIONS = [_row(0.0, 0.0), _row(10.0, 25.0), _row(20.0, 40.0), _row(30.0, 50.0, inc_inv=10.0, inc_kpi=10.0),
               _row(40.0, 55.0, inc_inv=20.0, inc_kpi=15.0)]


def test_values_are_monthly_for_the_cadence():
    got = scenario(_doc(CONVERSIONS, period_days=7), ScenarioFilters(), 0.2)

    factor = 30 / 7
    assert got["curve"][1]["investment"] == pytest.approx(10.0 * factor)
    assert got["curve"][1]["kpi"] == pytest.approx(25.0 * factor)
    assert got["curve"][1]["cpa"] == pytest.approx(10.0 / 25.0)
    assert got["current"]["investment"] == pytest.approx(20.0 * factor)


def test_the_table_rows_compare_against_the_current_scenario():
    got = scenario(_doc(CONVERSIONS), ScenarioFilters(), 0.2)

    assert got["current"]["incremental_investment"] == 0 and got["current"]["icpa"] == 0.0
    assert got["current"]["ramp"] is None and got["current"]["notes"] == []
    recommended = got["recommended"]
    assert recommended["investment"] == pytest.approx(40.0 * 30)
    assert recommended["incremental_investment"] == pytest.approx(20.0 * 30)
    assert recommended["incremental_kpi"] == pytest.approx(15.0 * 30)
    assert recommended["icpa"] == pytest.approx(20.0 / 15.0)
    assert recommended["extrapolated"] is True
    assert recommended["notes"] == [TCPA_NOTE]
    assert [s["investment"] for s in recommended["ramp"]] == pytest.approx([24.0 * 30, 28.8 * 30, 34.56 * 30, 40.0 * 30])


def test_roas_filters_apply_only_in_revenue_mode():
    revenue = [
        _row(10.0, 10.0, revenue=50.0),
        _row(20.0, 20.0, revenue=80.0),
        _row(30.0, 25.0, revenue=90.0, iroas=1.0, inc_inv=10.0, inc_kpi=5.0),
    ]
    got = scenario(_doc(revenue, current_kpi=20.0), ScenarioFilters(min_roas=3.5), 0.2)

    assert got["revenue_mode"] is True
    assert got["recommended"]["investment"] == pytest.approx(20.0 * 30)  # roas 50/10=5, 80/20=4, 90/30=3
    assert got["recommended"]["roas"] == pytest.approx(4.0)

    got = scenario(_doc(revenue, current_kpi=20.0), ScenarioFilters(min_iroas=0.5), 0.2)
    assert got["recommended"]["investment"] == pytest.approx(30.0 * 30)  # the only row with iROAS >= 0.5

    got = scenario(_doc(CONVERSIONS), ScenarioFilters(min_roas=100.0), 0.2)
    assert got["recommended"]["investment"] == pytest.approx(40.0 * 30)  # no revenue: ROAS filter ignored


def test_a_run_without_curve_is_an_engine_error():
    with pytest.raises(EngineError):
        scenario({"validation": {"period_days": 1}, "elasticity": None}, ScenarioFilters(), 0.2)
    with pytest.raises(EngineError):
        scenario(_doc([]), ScenarioFilters(), 0.2)


def test_filters_reject_bad_values():
    with pytest.raises(ValidationError):
        ScenarioFilters(min_budget=-1)
    with pytest.raises(ValidationError):
        ScenarioFilters(min_budget=10, max_budget=5)
    with pytest.raises(ValidationError):
        ScenarioFilters(foo=1)


# --- find_saturation_point, ported from opportunity-engine/tests/test_dashboard_charts.py ---


def _curve(xs, ys):
    return [{"investment": float(x), "kpi": float(y)} for x, y in zip(xs, ys, strict=True)]


def test_saturation_skips_a_transient_dip():
    curve = _curve(range(0, 100, 10), [0, 1000, 1900, 1950, 2750, 3450, 4050, 4080, 4100, 4110])

    assert curve[_saturation_index(curve, 0.0)]["investment"] == 70


def test_saturation_floor_keeps_the_ceiling_at_or_above_current_spend():
    curve = _curve(range(0, 100, 10), [0, 1000, 1500, 1700, 1780, 1860, 1940, 2020, 2100, 2180])

    assert curve[_saturation_index(curve, 0.0)]["investment"] < 50
    floored = _saturation_index(curve, 50.0)
    assert floored is None or curve[floored]["investment"] >= 50


def test_saturation_falls_back_when_the_curve_never_rises_or_is_too_short():
    assert _saturation_index(_curve([0, 10, 20], [100, 90, 80]), 0.0) is None
    assert _saturation_index(_curve([0], [100]), 0.0) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/engine/test_scenario.py -v`
Expected: FAIL with `ImportError: cannot import name 'ScenarioFilters'`

- [ ] **Step 3: Write minimal implementation**

Acrescente a `engine/scenario.py` (imports no topo do arquivo):

```python
import math
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from engine.errors import EngineError

DAYS_PER_MONTH = 30
NO_CURVE = "Esta execução não tem curva de resposta para simular cenários."


class ScenarioFilters(BaseModel):
    """The planner filters, all monthly and optional (streamlit_app.py:2208-2232)."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    min_budget: float | None = Field(default=None, ge=0)
    max_budget: float | None = Field(default=None, ge=0)
    target_cpa: float | None = Field(default=None, gt=0)
    target_icpa: float | None = Field(default=None, gt=0)
    min_roas: float | None = Field(default=None, ge=0)
    min_iroas: float | None = Field(default=None, ge=0)
    min_kpi: float | None = Field(default=None, ge=0)
    min_incrementality_pct: float | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def _budget_range(self) -> Self:
        if self.min_budget is not None and self.max_budget is not None and self.min_budget > self.max_budget:
            raise ValueError("o orçamento mínimo passa do máximo")
        return self


def _scaled(value: float | None, factor: float) -> float | None:
    return None if value is None else value * factor


def _ratio(a: float | None, b: float | None) -> float | None:
    return a / b if a is not None and b else None


def _icpa(incremental_investment: float | None, incremental_kpi: float | None) -> float | None:
    # compute_incremental_cpa of the prototype: no KPI gained means no meaningful cost, not a cost of 0
    if incremental_investment is None or incremental_kpi is None or incremental_kpi <= 0:
        return None
    return incremental_investment / incremental_kpi


def _curve_row(row: dict, factor: float) -> dict:
    investment, kpi = row["investment"] * factor, _scaled(row["kpi"], factor)
    revenue = _scaled(row["revenue"], factor)
    incremental_kpi = row["incremental_kpi"]
    return {
        "investment": investment,
        "kpi": kpi,
        "kpi_lo": _scaled(row["kpi_lo"], factor),
        "kpi_hi": _scaled(row["kpi_hi"], factor),
        "revenue": revenue,
        "cpa": _ratio(investment, kpi),
        "icpa": _icpa(row["incremental_investment"], incremental_kpi),
        "roas": _ratio(revenue, investment),
        "iroas": row["iroas"],
        "incremental_investment": _scaled(row["incremental_investment"], factor),
        "incremental_kpi": _scaled(incremental_kpi, factor),
        "pct_incrementality": incremental_kpi / row["kpi"] * 100
        if row["kpi"] and row["kpi"] > 0 and incremental_kpi is not None
        else 0.0,
        "extrapolated": row["extrapolated"],
    }


def _keeps(row: dict, f: ScenarioFilters, revenue_mode: bool) -> bool:
    """Same tests, same order as the Streamlit sidebar; ROAS filters only exist in revenue mode there."""
    return all(
        (
            f.min_budget is None or row["investment"] >= f.min_budget,
            f.max_budget is None or row["investment"] <= f.max_budget,
            f.target_cpa is None or (row["cpa"] is not None and row["cpa"] <= f.target_cpa),
            f.target_icpa is None or (row["icpa"] is not None and row["icpa"] <= f.target_icpa),
            not revenue_mode or f.min_roas is None or (row["roas"] is not None and row["roas"] >= f.min_roas),
            not revenue_mode or f.min_iroas is None or (row["iroas"] or 0.0) >= f.min_iroas,
            f.min_kpi is None or (row["kpi"] is not None and row["kpi"] >= f.min_kpi),
            f.min_incrementality_pct is None or row["pct_incrementality"] >= f.min_incrementality_pct,
        )
    )


def _saturation_index(curve: list[dict], start_investment: float) -> int | None:
    """find_saturation_point (prototype dashboard_charts.py:15): the row right after the last one whose marginal gain
    is above 10% of the peak, searching from `start_investment` up. None means "fall back"."""
    idx = [i for i, row in enumerate(curve) if row["investment"] >= start_investment]
    if len(idx) <= 1:
        return None
    xs = np.array([curve[i]["investment"] for i in idx])
    ys = np.array([curve[i]["kpi"] for i in idx])
    derivative = np.concatenate([[0.0], np.diff(ys) / np.diff(xs)])
    peak = derivative.max()
    if peak <= 0:
        return None
    above = np.where(derivative > peak * 0.1)[0]
    position = above[-1] + 1
    return idx[position] if position < len(idx) else None


def _table_row(point: dict, base: dict, max_step: float, curve: list[dict], note: str) -> dict:
    incremental_investment = point["investment"] - base["investment"]
    incremental_kpi = point["kpi"] - base["kpi"]
    incremental_revenue = (
        point["revenue"] - base["revenue"] if point["revenue"] is not None and base["revenue"] is not None else None
    )
    changes = not math.isclose(point["investment"], base["investment"])
    return {
        "investment": point["investment"],
        "kpi": point["kpi"],
        "kpi_lo": point["kpi_lo"],
        "kpi_hi": point["kpi_hi"],
        "revenue": point["revenue"],
        "cpa": _ratio(point["investment"], point["kpi"]),
        "roas": _ratio(point["revenue"], point["investment"]),
        "incremental_investment": incremental_investment,
        "incremental_kpi": incremental_kpi,
        "icpa": _icpa(incremental_investment, incremental_kpi),
        "iroas": _ratio(incremental_revenue, incremental_investment),
        "extrapolated": point["extrapolated"],
        "ramp": ramp(base["investment"], point["investment"], max_step, curve) if changes else None,
        "notes": [note] if changes else [],
    }


def scenario(results: dict, filters: ScenarioFilters, max_budget_step: float) -> dict:
    """Recommended point, saturation point and the filtered curve for the planner, in monthly values.

    Pure over the results.json dict: the curve is the one the run simulated; filters only pick points of it.
    """
    elasticity = results.get("elasticity") or {}
    rows = elasticity.get("response_curve") or []
    current = next((s for s in elasticity.get("scenarios") or [] if s["name"] == "current"), None)
    period_days = (results.get("validation") or {}).get("period_days")
    if not rows or current is None or not period_days:
        raise EngineError(NO_CURVE)

    factor = DAYS_PER_MONTH / period_days
    revenue_mode = any(row["revenue"] is not None for row in rows)
    curve = [_curve_row(row, factor) for row in rows]
    for row in curve:
        row["in_filter"] = _keeps(row, filters, revenue_mode)
    kept = [row for row in curve if row["in_filter"]]
    recommended = max(kept, key=lambda row: row["investment"]) if kept else None

    revenue_per_kpi = next((row["revenue"] / row["kpi"] for row in curve if row["revenue"] is not None and row["kpi"]), None)
    base = {
        "investment": current["investment"] * factor,
        "kpi": current["kpi"] * factor,
        "kpi_lo": _scaled(current.get("kpi_lo"), factor),
        "kpi_hi": _scaled(current.get("kpi_hi"), factor),
        "extrapolated": current.get("extrapolated"),
    }
    base["revenue"] = base["kpi"] * revenue_per_kpi if revenue_per_kpi is not None else None

    index = _saturation_index(curve, base["investment"])
    saturation = curve[index] if index is not None else (recommended or curve[-1])

    note = bid_note(revenue_mode)
    current_row = _table_row(base, base, max_budget_step, curve, note)
    current_row["icpa"] = 0.0
    current_row["iroas"] = 0.0 if revenue_mode else None
    return {
        "unit": "month",
        "revenue_mode": revenue_mode,
        "current": current_row,
        "recommended": _table_row(recommended, base, max_budget_step, curve, note) if recommended else None,
        "saturation": _table_row(saturation, base, max_budget_step, curve, note),
        "curve": curve,
    }
```

Atenção ao ramp do teste `test_the_table_rows_compare_against_the_current_scenario`: atual 20 → alvo 40 por dia é +100%; 24, 28,8, 34,56, 41,47 passaria; o último degrau corta em 40. Mensal multiplica tudo por 30.

`engine/__init__.py`:

```python
from engine.config import EngineConfig
from engine.errors import EngineError
from engine.pipeline import run
from engine.results_schema import ResultsV1, ValidationReport
from engine.scenario import ScenarioFilters, scenario
from engine.validation import validate

__all__ = ["EngineConfig", "EngineError", "ResultsV1", "ScenarioFilters", "ValidationReport", "run", "scenario", "validate"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/engine/test_scenario.py tests/engine/test_ramp.py -v`
Expected: all passed. Se um caso de paridade falhar, compare linha a linha com o oráculo antes de mexer em qualquer coisa: o oráculo é o protótipo e não muda. Os desvios aceitos (ROAS, base `current`) estão no spec e não entram nesse fixture.

- [ ] **Step 5: Commit**

```bash
git add engine/scenario.py engine/__init__.py tests/engine/test_scenario.py
git commit -m "feat(engine): engine.scenario with the Streamlit planner filters, monthly"
```

---

### Task 6: rota `GET /api/w/{slug}/runs/{run_id}/scenario`

**Files:**
- Modify: `api/runs.py`
- Modify: `api/routes/runs.py`
- Modify: `API-GUIDE.md` (tabela de endpoints, depois da linha de `GET /api/w/{slug}/runs/{run_id}/inputs/{key}`)
- Test: `tests/api/test_scenario.py`

- [ ] **Step 1: Write the failing test**

`tests/api/test_scenario.py`:

```python
from pathlib import Path

import pytest

from api import runs, simulations, storage
from api.engine_config import ParamsIn
from api.models import Membership
from tests.samples import INVESTMENT, MAPPING, PERFORMANCE

GOL = Path(__file__).resolve().parents[1] / "fixtures" / "results" / "gol_anonimizada.json"
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
    def make(workspace=None):
        simulation = make_simulation(
            workspace or ws, analyst, files={"investment": INVESTMENT, "performance": PERFORMANCE}
        )
        simulations.save_mapping(db, simulation, MAPPING)
        simulations.save_params(db, simulation, PARAMS)
        return simulation

    return make


def finished(db, simulation, analyst, with_results=True):
    run = runs.create(db, simulation, set(), by=analyst)
    run.status = "succeeded"
    if with_results:
        key = f"ws/{run.workspace_id}/sim/{run.simulation_id}/runs/{run.id}/results.json"
        storage.put(key, GOL)
        run.results_uri = key
    db.commit()
    return run


def url(run, slug="a", query=""):
    return f"/api/w/{slug}/runs/{run.id}/scenario{query}"


def test_analyst_reads_the_monthly_scenario(logged, db, ready, analyst):
    run = finished(db, ready(), analyst)

    r = logged.get(url(run))

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["unit"] == "month" and body["recommended"] is not None and len(body["curve"]) == 100


def test_filters_go_through_the_query(logged, db, ready, analyst):
    run = finished(db, ready(), analyst)

    r = logged.get(url(run, query="?target_cpa=0.000000001"))

    assert r.status_code == 200 and r.json()["recommended"] is None


def test_viewer_sees_only_a_published_run(make_client, login_as, make_user, db, ws, ready, analyst):
    run = finished(db, ready(), analyst)
    viewer = make_user("vi@x.com")
    db.add(Membership(user_id=viewer.id, workspace_id=ws.id, role="viewer"))
    db.commit()
    client = make_client()
    login_as(client, viewer)

    assert client.get(url(run)).status_code == 404
    runs.publish(db, run, by=analyst)
    assert client.get(url(run)).status_code == 200


def test_a_run_of_another_workspace_is_not_found(logged, db, ready, analyst, make_workspace):
    other = make_workspace("b", [(analyst, "analyst")])
    run = finished(db, ready(workspace=other), analyst)

    assert logged.get(url(run, slug="a")).status_code == 404


def test_a_run_without_results_is_a_conflict(logged, db, ready, analyst):
    run = finished(db, ready(), analyst, with_results=False)

    r = logged.get(url(run))

    assert r.status_code == 409 and "cenários" in r.json()["detail"]


@pytest.mark.parametrize("query", ["?min_budget=-1", "?min_budget=10&max_budget=5", "?foo=1"])
def test_bad_filters_are_rejected(logged, db, ready, analyst, query):
    run = finished(db, ready(), analyst)

    assert logged.get(url(run, query=query)).status_code == 422
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_scenario.py -v`
Expected: FAIL com 404 em todos (a rota não existe)

- [ ] **Step 3: Write minimal implementation**

`api/runs.py`, imports:

```python
import json
```

```python
import engine
from api import launcher, simulations, storage
```

e, no fim do arquivo:

```python
NO_RESULTS = "Esta execução não tem resultado para simular cenários."


def scenario(run: Run, filters: engine.ScenarioFilters) -> dict:
    if run.results_uri is None:
        raise Blocked(NO_RESULTS)
    results = json.loads(storage.path(run.results_uri).read_text(encoding="utf-8"))
    # ponytail: parses results.json on every slider move (~10 ms for 1 MB); cache by run id if it shows up in latency
    step = run.config.get("max_budget_step", engine.EngineConfig().max_budget_step)
    try:
        return engine.scenario(results, filters, step)
    except engine.EngineError as e:
        raise Blocked(str(e)) from e
```

`api/routes/runs.py`: acrescente `Query` ao import do FastAPI (`from fastapi import APIRouter, Depends, Header, HTTPException, Query`), `import engine` nos imports, e depois de `download_input`:

```python
@router.get("/runs/{run_id}/scenario")
def get_scenario(
    run_id: RunId,
    filters: Annotated[engine.ScenarioFilters, Query()],
    ctx: Ctx = Depends(viewer),
    db: Session = Depends(get_db),
):
    run = find_run(db, ctx, run_id)
    try:
        return runs.scenario(run, filters)
    except runs.Blocked as e:
        raise HTTPException(409, str(e))
```

`API-GUIDE.md`, linha nova na tabela, depois da de `…/inputs/{key}`:

```markdown
| GET | `/api/w/{slug}/runs/{run_id}/scenario` | Viewer+ (viewer só vê publicados). Query com os filtros mensais opcionais (`min_budget`, `max_budget`, `target_cpa`, `target_icpa`, `min_roas`, `min_iroas`, `min_kpi`, `min_incrementality_pct`) → `{unit, revenue_mode, current, recommended, saturation, curve}` do `engine.scenario`; `recommended` é `null` quando nada passa; 409 se o run não tem curva; 422 em filtro inválido ou desconhecido |
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/api/test_scenario.py tests/api/test_runs.py -v`
Expected: all passed. Se o `?foo=1` não der 422, confira que o `ScenarioFilters` tem `extra="forbid"` (o FastAPI respeita isso em modelo de query).

- [ ] **Step 5: Commit**

```bash
git add api/runs.py api/routes/runs.py API-GUIDE.md tests/api/test_scenario.py
git commit -m "feat(api): scenario route for the planner slider"
```

---

### Task 7: documentação

**Files:**
- Modify: `docs/m2/trilha-a-motor.md` (A8: linha `Status` logo abaixo do título, como na A5)
- Modify: `docs/m2/trilha-b-plataforma.md` (B5: `Status`)
- Modify: `docs/m2/README.md` (§3 cenário com `notes`; §4 assinatura e saída)
- Modify: `docs/decisoes/engine.md` (seção nova "A8")
- Modify: `tests/fixtures/results/README.md` (o que ainda sai `null` nos fixtures)
- Modify: `CLAUDE.md` (parágrafo "Estado atual")

- [ ] **Step 1: Rodar a suíte inteira e guardar a contagem**

Run: `uv run pytest -q`
Expected: tudo passa; anote "N passed, M skipped" para os status.

- [ ] **Step 2: Escrever os status e as decisões**

`docs/m2/trilha-a-motor.md`, abaixo de `## A8 · Guardrails do planner e \`engine.scenario\` — semana 3`:

```markdown
- **Status:** ✅ feito em 06/nov/2026. Banda p5/p95 das 200 reamostragens da Ridge (Hill, adstock e scaler fixos: banda otimista, para a A10) e `extrapolated` (total ou canal fora do `[min, max]` histórico) em toda linha da curva, cenário e ponto de curva individual; curvas individuais sempre dentro do cap; `ramp` em degraus compostos de `max_budget_step` e `notes` tCPA/tROAS nos cenários. `engine.scenario(results, filters, max_budget_step)` puro sobre o `results.json`, com os filtros do Streamlit e saída mensal, exposto em `GET /api/w/{slug}/runs/{run_id}/scenario`. Learning/budget-limited cortado (conector fora do escopo). Verificado: `tests/engine/test_ramp.py`, `test_guardrails.py`, `test_scenario.py` (paridade com o filtro e o `find_saturation_point` do Streamlit em 8 combinações sobre a Gol; < 300 ms), `tests/api/test_scenario.py`; suíte inteira <N passed, M skipped> no Windows. Falta: paridade no Linux e regenerar os fixtures do A1 com banda (precisa da Gol). Spec: `docs/superpowers/specs/2026-11-06-a8-guardrails-scenario-design.md`.
```

`docs/m2/trilha-b-plataforma.md`, troque o `Status` do B5 por:

```markdown
- **Status:** desbloqueado em 06/nov/2026. Os fixtures do A1 estão em `tests/fixtures/results/` (04/nov) e o `engine.scenario` do A8 está em `GET /api/w/{slug}/runs/{run_id}/scenario` (06/nov). Os fixtures ainda saem sem banda e sem `extrapolated` (`null`) até serem regenerados com a Gol. Antes de mostrar o `incremental_investment` dos eventos, ver a pendência em `docs/decisoes/engine.md`.
```

`docs/m2/README.md`: no exemplo do §3, acrescente `"notes":["…"]` ao objeto de cenário, ao lado de `"ramp"`. No §4, troque a assinatura por `engine.scenario(results, filters, max_budget_step) -> dict` e acrescente: "Filtros e saída mensais; devolve `{unit, revenue_mode, current, recommended, saturation, curve}`. A API exposta como `GET /api/w/{slug}/runs/{run_id}/scenario?...`."

`docs/decisoes/engine.md`, seção nova no fim:

```markdown
## A8 · Guardrails do planner e `engine.scenario` (06/nov/2026)

- **Banda só da Ridge.** `kpi_lo`/`kpi_hi` são p5/p95 do KPI sobre as 200 reamostragens de `coef_samples`, com Hill, adstock e scaler fixos. Não carrega a incerteza do formato das curvas: é otimista. A A10 mede a cobertura; propagar K, n e α exigiria re-ajustar o Hill por reamostragem.
- **A banda é calculada no `run`, não no `scenario`.** O filtro só escolhe pontos da curva já simulada, então a matriz do bootstrap não vai para o disco.
- **`extrapolated`**: total por período ou spend do canal (no mix do ponto) fora do `[min, max]` histórico. Abaixo do mínimo também conta.
- **Curvas individuais sempre dentro do cap** (`per_channel_investment_limit_factor`), sem o bypass que as estendia até o recomendado × 1,2.
- **`ramp`**: degraus compostos de no máximo `max_budget_step` a partir do atual; −50% com 20% são 4 degraus (0,8; 0,64; 0,512; 0,5).
- **`scenario` em valores mensais** (× 30 / `period_days`); o `results.json` continua por período. Recebe `max_budget_step` como argumento porque o `results.json` não guarda config; a API passa o do `run.config`.
- **Desvios do Streamlit:** o ROAS do filtro é `receita / investimento` no mesmo período (o protótipo dividia receita por período por investimento mensal); a base dos incrementais é o cenário `current` do `results.json`, não um baseline recalculado dos CSV; com o KPI em modo receita a tabela traz ROAS e iROAS (o protótipo só mostrava com `kpi_is_monetary`).
- **Paridade com o protótipo:** o teste tira `KPI_Lo`, `KPI_Hi` e `Extrapolated` antes de comparar; o resto continua idêntico.
- **Cortado:** status de learning/budget-limited do Google Ads (precisa do conector, fora do escopo).
```

`tests/fixtures/results/README.md`: na lista do que sai `null`, troque "curve intervals and `extrapolated` for now" por "curve intervals, `extrapolated`, `ramp` and `notes` until the fixtures are regenerated with the Gol (A8 fills them on a new run)".

`CLAUDE.md`, parágrafo "Estado atual": antes de "Pendência da Trilha A:", acrescente:

```markdown
**A8 (guardrails e `engine.scenario`) concluído em 06/nov/2026**: banda p5/p95 do bootstrap da Ridge e `extrapolated` em todo ponto da curva, cenário e curva individual; curvas individuais dentro do cap; `ramp` em degraus de `max_budget_step` e nota tCPA/tROAS nos cenários; `engine.scenario` com os filtros do Streamlit em valores mensais, exposto em `GET /api/w/{slug}/runs/{run_id}/scenario`. Learning/budget-limited do Google Ads cortado. B5 desbloqueado.
```

e, no "Faltam:", troque "A4 e A6–A10 (Trilha A), B7 (depende do B5)" por "A4, A6, A7, A9 e A10 (Trilha A), B5 (dashboards, desbloqueado), B7 (depende do B5)".

- [ ] **Step 3: Commit**

```bash
git add docs/m2/trilha-a-motor.md docs/m2/trilha-b-plataforma.md docs/m2/README.md docs/decisoes/engine.md tests/fixtures/results/README.md CLAUDE.md
git commit -m "docs(a8): record the planner guardrails and unblock B5"
```
