# A4 · Controles causais livres de contaminação — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O causal deixa de usar métricas geradas pela mídia como controle, tria por evento os controles exógenos (Trends e as séries do BCB marcadas pelo analista) e seleciona variáveis com folds temporais.

**Architecture:** O motor lê um CSV fixo de séries do BCB (`inputs["bcb_file"]`) e nunca acessa a rede; a API busca as séries na SGS ao criar o run, grava o CSV no snapshot de entradas e devolve 502 se a SGS falhar. A triagem é uma função pura (`screen_controls`) chamada dentro de `run_causal_impact_analysis`; o resultado vai para `CausalEvent.controls`.

**Tech Stack:** Python 3.13, pandas, scikit-learn (`TimeSeriesSplit`, `LassoCV`), pydantic 2, FastAPI, httpx; React 19 + TypeScript (bun), Playwright.

Spec: `docs/superpowers/specs/2026-11-06-a4-controles-causais-design.md`. Leia antes de começar, junto de `CODE-STYLE.md` (motor e testes) e `API-GUIDE.md` (rota).

---

## File Structure

| Arquivo | Papel |
|---|---|
| `engine/config.py` | `BcbControl`, `controls` tipado e sem repetição, `control_spend_corr` no `GATE_DEFAULTS` e no dict legado |
| `api/engine_config.py` | `controls` no `ANALYST_FIELDS` |
| `engine/inputs.py` | `read_controls` (CSV fixo do BCB); `RawInputs` perde `performance_df` |
| `engine/data_preprocessor.py` | `PreparedData.controls_df` no lugar de `performance_df` |
| `engine/__main__.py` | aceita `bcb_file` |
| `engine/analysis.py` | sem covariáveis de mídia; `with_controls`, `screen_controls`, `lasso_folds`; `controls` no `results_dict` |
| `engine/pipeline.py` | passa `prepared.controls_df` ao causal |
| `engine/logmessages.py` | regra pt-BR do controle descartado; tira a regra morta das covariáveis |
| `engine/results_schema.py`, `engine/results.py` | `CausalControl`, `CausalEvent.controls`, `control_rejected` |
| `api/bcb.py` (novo) | busca na SGS e monta o CSV |
| `api/runs.py`, `api/routes/runs.py` | snapshot do `bcb_file`, 502, `InputKey` |
| `tests/conftest.py` | bloqueia rede da SGS em todo teste |
| `web/src/lib/params.ts`, `web/src/components/ParamsForm.tsx`, `web/src/components/RunDetails.tsx` | checkboxes dos controles, exibição e download |
| `tests/engine/test_controls.py` (novo), `tests/api/test_bcb.py` (novo) | testes novos |
| `tests/engine/test_parity.py`, `tests/engine/test_parity_real.py` | eventos comparados só no que o A4 não mudou |

## Ordem e paralelismo

- Lote 1 (paralelo): Task 1, Task 2, Task 5.
- Lote 2 (paralelo): Task 3 (depois de 1 e 2), Task 6 (depois de 1 e 5), Task 7 (depois da 1).
- Lote 3: Task 4 (depois da 3).
- Lote 4: Task 8 (docs), depois de tudo.

Modelo sugerido: Task 1, 2 e 8 haiku; 3, 4, 5, 6 e 7 sonnet.

Comandos: `uv run pytest tests/engine/<arquivo> -v` (motor, sem banco) e `uv run pytest tests/api/<arquivo> -v` (precisa do Postgres do `docker compose up -d`). `uv run ruff check . && uv run ruff format --check .` antes de cada commit. Front: `cd web && bun run build && bun run lint`.

**Branch em paralelo:** o A8 (`feat/a8-guardrails-scenario`) mexe em `api/runs.py` e `api/routes/runs.py`, e a tela de agrupamento mexe em `ANALYST_FIELDS` e `params.ts`. Faça as inserções nos pontos indicados aqui, sem reordenar nem reformatar o resto desses arquivos.

---

### Task 1: `controls` e `control_spend_corr` no `EngineConfig`

**Files:**
- Modify: `engine/config.py`
- Modify: `api/engine_config.py`
- Test: `tests/engine/test_config.py`, `tests/api/test_params.py`

- [ ] **Step 1: Write the failing tests**

No fim de `tests/engine/test_config.py` (adicione `from pydantic import ValidationError` aos imports se faltar):

```python
def test_controls_accept_only_the_bcb_series_and_drop_repeats():
    assert EngineConfig(controls=["bcb_ipca", "bcb_ipca", "bcb_selic"]).controls == ["bcb_ipca", "bcb_selic"]
    assert EngineConfig().controls == []
    with pytest.raises(ValidationError):
        EngineConfig(controls=["Clicks"])


def test_control_spend_corr_defaults_to_half_and_reaches_the_legacy_dict():
    assert EngineConfig().to_legacy_dict()["control_spend_corr"] == 0.5
    tuned = EngineConfig(gate_thresholds={"control_spend_corr": 0.7})
    assert tuned.to_legacy_dict()["control_spend_corr"] == 0.7
```

No fim de `tests/api/test_params.py`:

```python
def test_params_carry_the_bcb_controls():
    assert ParamsIn().controls == []
    assert ParamsIn(controls=["bcb_ipca", "bcb_ipca"]).controls == ["bcb_ipca"]
    items = ParamsIn.model_json_schema()["properties"]["controls"]["items"]
    assert items["enum"] == ["bcb_ipca", "bcb_selic", "bcb_ibc_br"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/engine/test_config.py -k "controls or control_spend" -v && uv run pytest tests/api/test_params.py -k bcb -v`
Expected: FAIL (`Clicks` aceito, `KeyError: 'control_spend_corr'`, `controls` fora do `ParamsIn`).

- [ ] **Step 3: Implement**

Em `engine/config.py`, imports: troque `from typing import Literal, Self` por `from typing import Annotated, Literal, Self` e acrescente `AfterValidator` ao import do pydantic:

```python
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
```

Troque o `GATE_DEFAULTS`:

```python
# gate thresholds: A3's collinearity and A4's control screening; A5's collinearity_vif when it uses it
GATE_DEFAULTS = {"collinearity_r": 0.85, "control_spend_corr": 0.5}

# Banco Central series the platform fetches for the causal model (api/bcb.py maps each to its SGS code)
BcbControl = Literal["bcb_ipca", "bcb_selic", "bcb_ibc_br"]
```

Troque a linha `controls: list[str] = Field(default_factory=list)` por (o validador vai no `Annotated` para o `ParamsIn` copiá-lo junto):

```python
    controls: Annotated[list[BcbControl], AfterValidator(lambda names: list(dict.fromkeys(names)))] = Field(
        default_factory=list
    )
```

Em `to_legacy_dict`, antes do `return legacy`:

```python
        legacy["control_spend_corr"] = self.gate_threshold("control_spend_corr")
```

Em `api/engine_config.py`, acrescente `"controls",` como **último** item do `ANALYST_FIELDS` (depois de `"require_model_fit",`).

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/engine/test_config.py tests/engine/test_defaults.py -v && uv run pytest tests/api/test_params.py -v`
Expected: PASS. `test_params_in_copies_default_and_limits_from_the_engine` e `assert list(props) == list(ANALYST_FIELDS)` continuam verdes.

- [ ] **Step 5: Commit**

```bash
git add engine/config.py api/engine_config.py tests/engine/test_config.py tests/api/test_params.py
git commit -m "feat(engine): bcb controls and the control_spend_corr gate in EngineConfig"
```

---

### Task 2: `read_controls` e `PreparedData.controls_df`

**Files:**
- Modify: `engine/inputs.py`
- Modify: `engine/data_preprocessor.py:754-760, 782-786, 876-882`
- Modify: `engine/pipeline.py:156`
- Modify: `engine/__main__.py:33-35`
- Test: `tests/engine/test_inputs.py`, `tests/engine/test_data_preprocessor.py:1280-1292`, `tests/engine/test_elasticity_analysis.py:347-356`, `tests/engine/test_engine_cli.py`

- [ ] **Step 1: Write the failing tests**

Em `tests/engine/test_inputs.py`, acrescente `read_controls` ao import de `engine.inputs` e, no fim:

```python
def test_read_controls_keeps_the_requested_series_sorted_and_carried_forward(tmp_path):
    path = tmp_path / "bcb.csv"
    path.write_text(
        "Date,bcb_ipca,bcb_selic\n2024-02-01,0.8,\n2024-01-01,0.4,11.75\n2024-01-02,,11.75\n", encoding="utf-8"
    )

    frame = read_controls(path, ["bcb_ipca", "bcb_selic"])

    assert list(frame.columns) == ["Date", "bcb_ipca", "bcb_selic"]
    assert frame["Date"].is_monotonic_increasing
    by_date = frame.set_index("Date")
    assert by_date.loc["2024-01-02", "bcb_ipca"] == 0.4  # January's IPCA holds until February's
    assert by_date.loc["2024-02-01", "bcb_selic"] == 11.75
    assert list(read_controls(path, ["bcb_selic"]).columns) == ["Date", "bcb_selic"]


def test_no_controls_need_no_file():
    assert read_controls(None, []).empty


def test_a_requested_control_without_its_series_is_an_engine_error(tmp_path):
    with pytest.raises(EngineError, match="bcb_ipca"):
        read_controls(None, ["bcb_ipca"])
    path = tmp_path / "bcb.csv"
    path.write_text("Date,bcb_selic\n2024-01-01,11.75\n", encoding="utf-8")
    with pytest.raises(EngineError, match="bcb_ipca"):
        read_controls(path, ["bcb_ipca"])
```

Em `tests/engine/test_data_preprocessor.py`, substitua o teste `test_performance_file_is_read_once_and_kept_for_covariates` (linhas ~1280-1292) por:

```python
def test_performance_file_is_read_once(tmp_path, monkeypatch):
    import engine.inputs as module  # read_inputs owns the reads now

    config, paths = _daily_files(tmp_path, with_extra_column=True)
    reads = []
    real = module.read_csv_robust
    monkeypatch.setattr(module, "read_csv_robust", lambda path, **kw: reads.append(Path(path)) or real(path, **kw))

    prepared = _prepare(config, paths)

    assert reads.count(paths["performance_file"]) == 1
    assert prepared.controls_df.empty  # no bcb control asked


def test_bcb_controls_reach_the_prepared_data(tmp_path):
    config, paths = _daily_files(tmp_path)
    bcb = tmp_path / "bcb.csv"
    bcb.write_text("Date,bcb_ipca\n2024-12-01,0.4\n2025-01-01,0.5\n", encoding="utf-8")

    prepared = _prepare({**config, "controls": ["bcb_ipca"]}, {**paths, "bcb_file": bcb})

    assert list(prepared.controls_df.columns) == ["Date", "bcb_ipca"]
    assert prepared.controls_df["bcb_ipca"].tolist() == [0.4, 0.5]
```

Em `tests/engine/test_engine_cli.py`, no fim (`_load` lê o JSON de entrada; ajuste o import se o arquivo ainda não importa `_load`):

```python
def test_cli_passes_the_bcb_file(tmp_path):
    from engine.__main__ import _load

    run_json = tmp_path / "run.json"
    run_json.write_text('{"inputs": {"investment_file": "i.csv", "bcb_file": "bcb.csv"}}', encoding="utf-8")

    _, inputs = _load(run_json)

    assert inputs["bcb_file"] == Path("bcb.csv") and inputs["generic_trends_file"] is None
```

(adicione `from pathlib import Path` aos imports do arquivo se faltar).

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/engine/test_inputs.py tests/engine/test_data_preprocessor.py tests/engine/test_engine_cli.py -k "controls or read_once or bcb" -v`
Expected: FAIL (`ImportError: read_controls`, `AttributeError: controls_df`, `KeyError: 'bcb_file'`).

- [ ] **Step 3: Implement**

Em `engine/inputs.py`, no `RawInputs`, apague a linha `performance_df: pd.DataFrame  # the performance file as sent ...` e, no `return RawInputs(...)` de `_read_inputs`, apague `performance_df=performance_df,` (a variável local continua: os checks de duplicata a usam). Depois de `_empty_trends`, acrescente:

```python
def read_controls(path: Path | None, controls: list[str]) -> pd.DataFrame:
    """The platform's Banco Central file: Date plus one column per series, in a fixed format (not the user's, so no
    column_mapping). Each column carries its last value forward, so every row holds the latest number published."""
    if not controls:
        return pd.DataFrame({"Date": pd.Series(dtype="datetime64[ns]")})
    frame = pd.read_csv(path, parse_dates=["Date"]) if path else pd.DataFrame(columns=["Date"])
    missing = [name for name in controls if name not in frame.columns]
    if missing:
        raise EngineError(f"Controle do Banco Central pedido sem a série: {', '.join(missing)}.")
    return frame[["Date", *controls]].sort_values("Date").ffill().reset_index(drop=True)
```

Em `engine/data_preprocessor.py`:
- no `PreparedData`, troque `performance_df: pd.DataFrame  # raw performance file ...` por `controls_df: pd.DataFrame  # Date plus the bcb series asked in config["controls"] (empty without them)`;
- acrescente `read_controls,` ao import local de `engine.inputs` dentro de `load_and_prepare_data`;
- troque `performance_df = raw.performance_df` por `controls_df = read_controls(paths.get("bcb_file"), config["controls"])`;
- no `return PreparedData(...)`, troque `performance_df=performance_df,` por `controls_df=controls_df,`.

Em `engine/pipeline.py:156`, troque `prepared.performance_df,` por `prepared.controls_df,` (o parâmetro ainda se chama `performance_df` até a Task 3; com `controls_df` vazio, ou só com colunas `bcb_*`, o bloco antigo de covariáveis não acha nada).

Em `engine/__main__.py`, a tupla de chaves vira:

```python
        for key in ("investment_file", "performance_file", "generic_trends_file", "bcb_file")
```

Em `tests/engine/test_elasticity_analysis.py:353`, troque `performance_df=pd.DataFrame({"Date": dates}),` por `controls_df=pd.DataFrame({"Date": dates}),`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/engine/test_inputs.py tests/engine/test_data_preprocessor.py tests/engine/test_engine_cli.py tests/engine/test_elasticity_analysis.py tests/engine/test_pipeline_stages.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/inputs.py engine/data_preprocessor.py engine/pipeline.py engine/__main__.py tests/engine/test_inputs.py tests/engine/test_data_preprocessor.py tests/engine/test_engine_cli.py tests/engine/test_elasticity_analysis.py
git commit -m "feat(engine): read the platform's bcb file into PreparedData.controls_df"
```

---

### Task 3: causal sem covariáveis de mídia, com triagem e folds temporais

**Files:**
- Modify: `engine/analysis.py` (imports; helpers perto de `_select_variance_threshold_features`; `run_causal_impact_analysis`)
- Modify: `engine/logmessages.py`
- Test: `tests/engine/test_controls.py` (novo)

- [ ] **Step 1: Write the failing tests**

Crie `tests/engine/test_controls.py`:

```python
import numpy as np
import pandas as pd
import pytest

from engine.analysis import (
    lasso_folds,
    run_causal_impact_analysis,
    run_opportunity_projection,
    screen_controls,
    with_controls,
)
from engine.config import EngineConfig
from engine.pipeline import analyze_events, detect_events, load_inputs
from tests.engine.helpers import full_config
from tests.engine.synthetic_data import dataset_config, make_dataset

DAYS = pd.date_range("2024-01-01", periods=120, freq="D")
PRE, POST = ("2024-01-01", "2024-04-09"), ("2024-04-10", "2024-04-29")


def test_a_control_that_moves_with_the_spend_is_rejected():
    spend = pd.Series(np.arange(30, dtype=float), index=DAYS[:30])
    pre = pd.DataFrame({"Generic Searches": spend * 2 + 1, "bcb_ipca": np.tile([1.0, -1.0], 15)}, index=DAYS[:30])

    screened = screen_controls(pre, spend, 0.5)

    assert screened[0] == {"name": "trends", "corr": pytest.approx(1.0), "accepted": False}
    assert screened[1]["name"] == "bcb_ipca" and screened[1]["accepted"] is True


def test_a_constant_control_has_no_correlation_and_is_kept():
    spend = pd.Series(np.arange(10, dtype=float), index=DAYS[:10])
    pre = pd.DataFrame({"bcb_selic": 11.75}, index=DAYS[:10])

    assert screen_controls(pre, spend, 0.5) == [{"name": "bcb_selic", "corr": None, "accepted": True}]


def test_each_date_takes_the_last_value_published_up_to_it():
    model = pd.DataFrame({"Date": pd.date_range("2024-01-30", "2024-03-05", freq="D"), "kpi": 1.0})
    controls = pd.DataFrame({"Date": pd.to_datetime(["2024-01-01", "2024-02-01"]), "bcb_ipca": [0.4, 0.8]})

    merged = with_controls(model, controls).set_index("Date")

    assert merged.loc["2024-01-31", "bcb_ipca"] == 0.4
    assert merged.loc["2024-03-05", "bcb_ipca"] == 0.8  # after the last release, it still holds
    assert with_controls(model, pd.DataFrame()) is model


def test_lasso_folds_are_in_time_order_and_fit_a_short_pre_period():
    assert lasso_folds(8).n_splits == 2
    assert lasso_folds(400).n_splits == 5


def _event(control, controls_df=None, controls=()):
    rng = np.random.default_rng(3)
    spend = 100 + rng.normal(0, 15, len(DAYS))
    spend[100:] *= 2
    kpi = 50 + 8 * np.sqrt(spend) + rng.normal(0, 2, len(DAYS))
    investment = pd.DataFrame({"Date": DAYS, "Product Group": "TV", "investment": spend})
    kpi_df = pd.DataFrame({"Date": DAYS, "kpi": kpi})
    trends = pd.DataFrame({"Date": DAYS, "Generic Searches": control(spend, rng)})
    config = full_config({"controls": list(controls)})
    *_, params, _ = run_opportunity_projection(kpi_df, investment, trends, "TV", config)
    results, *_ = run_causal_impact_analysis(
        kpi_df,
        investment,
        trends,
        pd.DataFrame() if controls_df is None else controls_df,
        PRE,
        POST,
        "TV_2024-04-10",
        "TV",
        params,
        {**config, "period_days": 1},
    )
    assert results is not None, "run_causal_impact_analysis swallowed an exception; see the log"
    return results


def test_trends_that_follow_the_spend_leave_the_causal_model():
    results = _event(lambda spend, rng: spend + rng.normal(0, 1, len(spend)))

    [trends] = results["controls"]
    assert trends["name"] == "trends" and trends["accepted"] is False and trends["corr"] > 0.9


def test_independent_trends_and_a_bcb_series_are_screened_and_kept():
    monthly = pd.DataFrame({"Date": pd.date_range("2023-12-01", periods=6, freq="MS"), "bcb_ipca": [0.5, 0.4, 0.8, 0.2, 0.4, 0.3]})

    results = _event(lambda spend, rng: 50 + rng.normal(0, 5, len(spend)), monthly, ["bcb_ipca"])

    assert [(c["name"], c["accepted"]) for c in results["controls"]] == [("trends", True), ("bcb_ipca", True)]


def _outcomes(inputs):
    config = EngineConfig.from_input(dataset_config())
    prepared = load_inputs(inputs, config)
    cfg = {**config.to_legacy_dict(), "period_days": prepared.period_days}
    return analyze_events(prepared, detect_events(prepared, cfg), cfg)


def test_ad_metrics_in_the_performance_file_do_not_change_the_causal_result(tmp_path):
    plain = make_dataset(tmp_path / "plain", n_days=364)
    with_ads = make_dataset(tmp_path / "ads", n_days=364)
    performance = pd.read_csv(with_ads["performance_file"])
    # an ad metric that tracks the KPI: the prototype took it as a control and absorbed the effect
    performance["Clicks"] = performance["Sessions"] * 0.03
    performance["Impressions"] = performance["Sessions"] * 2
    performance.to_csv(with_ads["performance_file"], index=False)

    expected = [(o.event_id, o.results_data and o.results_data["absolute_lift"]) for o in _outcomes(plain)]
    actual = [(o.event_id, o.results_data and o.results_data["absolute_lift"]) for o in _outcomes(with_ads)]

    assert actual == expected
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/engine/test_controls.py -v`
Expected: FAIL (`ImportError: cannot import name 'lasso_folds'`). O teste do `Clicks` já passaria depois da Task 2 (o arquivo de performance deixou de chegar ao causal); ele fica como guarda contra a volta das covariáveis.

- [ ] **Step 3: Implement**

Em `engine/analysis.py`, imports: acrescente `from sklearn.model_selection import TimeSeriesSplit` (depois do `from sklearn.linear_model import LassoCV`) e `from engine.config import GATE_DEFAULTS` (junto dos outros imports de `engine.`; se não houver nenhum, depois do bloco do sklearn).

Logo **depois** de `_select_variance_threshold_features`, acrescente:

```python
TRENDS_COLUMN = "Generic Searches"
CALENDAR_FEATURES = ("is_weekend", "is_payday_period", "is_holiday")


def with_controls(model_data: pd.DataFrame, controls_df: pd.DataFrame) -> pd.DataFrame:
    """Each date takes the last value published on or before it: a monthly series holds until its next release."""
    if controls_df.empty:
        return model_data
    controls = controls_df.assign(Date=controls_df["Date"].astype(model_data["Date"].dtype)).sort_values("Date")
    return pd.merge_asof(model_data.sort_values("Date"), controls, on="Date")


def screen_controls(pre: pd.DataFrame, spend: pd.Series, limit: float) -> list[dict]:
    """A control that moves with the treated spend absorbs the effect being measured: |r| above `limit` rejects it.
    An undefined r (a constant series) has nothing to absorb."""
    screened = []
    for column in pre.columns:
        r = pre[column].corr(spend)
        corr = None if pd.isna(r) else float(r)
        name = "trends" if column == TRENDS_COLUMN else column
        screened.append({"name": name, "corr": corr, "accepted": corr is None or abs(corr) <= limit})
    return screened


def lasso_folds(n_rows: int) -> TimeSeriesSplit:
    """Folds in time order (a shuffled fold trains on the future); a short pre-period gets fewer of them."""
    return TimeSeriesSplit(n_splits=max(2, min(5, n_rows // 4)))
```

Em `run_causal_impact_analysis`:

1. Na assinatura, troque o parâmetro `performance_df` por `controls_df`.
2. Apague o bloco inteiro de `# --- Start of New Dynamic Code ---` até `# --- End of New Dynamic Code ---` (o `rename` do `performance_df`, o `possible_covariates`, o `found_covariates` e o merge) e ponha no lugar:

```python
        model_data = with_controls(model_data, controls_df)
```

3. Troque o trecho da seleção de variáveis:

```python
        log.info("   - Running automated feature selection for causal model...")
        potential_exog_vars = list(transformed_features.keys()) + [
            col
            for col in model_data.columns
            if "generic" in col.lower() or "day_" in col or col in ["is_weekend", "is_payday_period", "is_holiday"]
        ]

        # --- Add the dynamically found covariates to the list ---
        if found_covariates:
            potential_exog_vars.extend(found_covariates)
```

por:

```python
        log.info("   - Running automated feature selection for causal model...")
        candidates = [col for col in (TRENDS_COLUMN, *config.get("controls", [])) if col in model_data.columns]
        limit = config.get("control_spend_corr", GATE_DEFAULTS["control_spend_corr"])
        pre_spend = pre_data_for_model[event_channels].sum(axis=1)
        controls = screen_controls(pre_data_for_model[candidates], pre_spend, limit)
        accepted = []
        for column, control in zip(candidates, controls, strict=True):
            if control["accepted"]:
                accepted.append(column)
            else:
                log.warning(f"   - Control {control['name']} rejected: correlation {control['corr']:.2f} with the event's spend")
        # controls before the calendar, where the "generic" match used to put the trends column
        potential_exog_vars = (
            list(transformed_features.keys())
            + accepted
            + [col for col in model_data.columns if "day_" in col or col in CALENDAR_FEATURES]
        )
```

4. Troque `lasso = LassoCV(cv=5, random_state=0, max_iter=10000).fit(...)` por:

```python
            folds = lasso_folds(len(pre_data_for_model))
            lasso = LassoCV(cv=folds, random_state=0, max_iter=10000).fit(X_lasso_scaled, pre_data_for_model["kpi"])
```

5. No `results_dict`, depois de `"event_period_avg_investment": event_period_avg_investment,`, acrescente:

```python
            "controls": controls,
```

Em `engine/logmessages.py`:
- apague a regra `(r"No additional performance covariates found\. Proceeding without them\.", None)` (o log não existe mais);
- depois da regra `r"Selected features for causal model:\s*(.*)"`, acrescente:

```python
    (
        r"Control (\S+) rejected: correlation (\S+) with the event's spend",
        "   - Controle {0} descartado: correlação {1} com o investimento do evento.",
    ),
```

Se `tests/engine/test_logmessages.py` citar a regra apagada, apague só essa linha do teste.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/engine/test_controls.py tests/engine/test_analysis.py tests/engine/test_logmessages.py tests/engine/test_pipeline_stages.py -v`
Expected: PASS. Se `test_trends_that_follow_the_spend...` ou `test_independent...` derem `results is None`, leia o log da exceção engolida: o `_event` precisa de um pré-período com 100 linhas e um evento no dia 100 (spend ×2).

- [ ] **Step 5: Commit**

```bash
git add engine/analysis.py engine/logmessages.py tests/engine/test_controls.py tests/engine/test_logmessages.py
git commit -m "feat(engine): causal model drops ad-driven covariates, screens exogenous controls and uses time-ordered folds"
```

---

### Task 4: `controls` no `results.json` e paridade

**Files:**
- Modify: `engine/results_schema.py:132-147`
- Modify: `engine/results.py:11-33, 86-112`
- Modify: `tests/engine/test_parity.py`, `tests/engine/test_parity_real.py`
- Test: `tests/engine/test_results_build.py`

- [ ] **Step 1: Write the failing tests**

Em `tests/engine/test_results_build.py`, logo depois de `test_zero_lift_gives_null_cpa` (o arquivo tem um segundo bloco de imports mais abaixo; não escreva depois dele):

```python
def test_screened_controls_are_published_and_a_rejection_is_a_reason(synthetic_computed):
    data = _result_data(
        controls=[{"name": "trends", "corr": 0.93, "accepted": False}, {"name": "bcb_ipca", "corr": 0.1, "accepted": True}]
    )
    event = results._causal(with_events(synthetic_computed, [outcome(data=data)])).events[0]

    assert [(c.name, c.corr, c.accepted) for c in event.controls] == [("trends", 0.93, False), ("bcb_ipca", 0.1, True)]
    assert event.status == "published" and event.reasons == ["control_rejected"]


def test_an_event_without_controls_has_an_empty_list(synthetic_computed):
    event = results._causal(with_events(synthetic_computed, [outcome()])).events[0]
    assert event.controls == [] and event.reasons == []
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/engine/test_results_build.py -k controls -v`
Expected: FAIL (`AttributeError: 'CausalEvent' object has no attribute 'controls'`).

- [ ] **Step 3: Implement**

Em `engine/results_schema.py`, antes de `class CausalEvent`:

```python
class CausalControl(_Model):
    name: str  # trends, bcb_ipca, bcb_selic, bcb_ibc_br
    corr: float | None = None  # with the treated spend in the pre-period; None for a constant series
    accepted: bool
```

e em `CausalEvent`, depois de `placebo: Placebo | None = None`:

```python
    controls: list[CausalControl] = Field(default_factory=list)
```

Em `engine/results.py`, acrescente `CausalControl,` ao import de `engine.results_schema` (ordem alfabética, depois de `CausalEvent,`). Em `_event`, depois de `event.fit = Fit(...)`:

```python
    event.controls = [CausalControl(**control) for control in data.get("controls", [])]
    if any(not control.accepted for control in event.controls):
        event.reasons.append("control_rejected")  # the control left the model; the event still stands
```

Em `tests/engine/test_parity.py`, depois de `RTOL, ATOL = ...`:

```python
# A4 (06/nov/2026) changed the causal model on purpose: TimeSeriesSplit in the Lasso and the control screening move
# every model number (lift, p-value, fit, gates). Detection and the investment arithmetic still match the prototype.
MODEL_FREE = (
    "start_date",
    "end_date",
    "product_group",
    "investment_change_pct",
    "total_investment_post_period",
    "total_investment_pre_period",
    "event_period_avg_investment",
)


def model_free(events: list[dict]) -> list[dict]:
    return [
        {
            "event_id": e["event_id"],
            "product_group": e["product_group"],
            "intervention_date": e["intervention_date"],
            "results_data": {key: e["results_data"][key] for key in MODEL_FREE} if e["results_data"] else None,
        }
        for e in events
    ]
```

e, em `test_events_and_gates_match`, troque a última linha por:

```python
    assert_close(model_free(actual), model_free(snapshot["events"]), "events")
```

Em `tests/engine/test_parity_real.py`, troque o import para `from tests.engine.test_parity import assert_close, model_free` e o corpo do teste por:

```python
def test_gol_block_matches_the_prototype(block, actual, legacy):
    if block == "events":
        assert_close(model_free(actual[block]), model_free(legacy[block]), block)
    else:
        assert_close(actual[block], legacy[block], block)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/engine/test_results_build.py tests/engine/test_results_schema.py tests/engine/test_results_fixtures.py tests/engine/test_results_run.py -v`
Expected: PASS. `test_parity.py` é pulado no Windows; ele roda no CI (Linux). Se você estiver no Linux, rode também `mise run parity` e espere PASS.

- [ ] **Step 5: Run the whole engine suite**

Run: `uv run pytest tests/engine tests/llm -q`
Expected: PASS (com os skips de sempre: paridade fora do Linux, dados reais ausentes).

- [ ] **Step 6: Commit**

```bash
git add engine/results_schema.py engine/results.py tests/engine/test_results_build.py tests/engine/test_parity.py tests/engine/test_parity_real.py
git commit -m "feat(engine): results.json lists each event's screened controls; parity keeps only what a4 did not change"
```

---

### Task 5: `api/bcb.py`, busca na SGS

**Files:**
- Create: `api/bcb.py`
- Modify: `tests/conftest.py`
- Test: `tests/api/test_bcb.py` (novo)

- [ ] **Step 1: Write the failing tests**

Crie `tests/api/test_bcb.py`:

```python
from datetime import date
from typing import get_args

import httpx
import pytest

from api import bcb
from engine.config import BcbControl

ROWS = {
    433: [{"data": "01/01/2024", "valor": "0.42"}, {"data": "01/02/2024", "valor": "0.83"}],
    432: [{"data": "01/01/2024", "valor": "11.75"}, {"data": "02/01/2024", "valor": "11.75"}],
}


@pytest.fixture
def sgs(monkeypatch):
    calls = []

    def get(code, start, end):
        calls.append((code, start, end))
        return ROWS[code]

    monkeypatch.setattr(bcb, "get", get)
    return calls


def test_every_engine_control_has_an_sgs_code():
    assert set(bcb.SERIES) == set(get_args(BcbControl))


def test_fetch_joins_the_series_by_date_in_a_fixed_csv(sgs):
    content = bcb.fetch(["bcb_ipca", "bcb_selic"], today=date(2026, 11, 6))

    assert content.decode().splitlines() == [
        "Date,bcb_ipca,bcb_selic",
        "2024-01-01,0.42,11.75",
        "2024-01-02,,11.75",
        "2024-02-01,0.83,",
    ]
    assert [code for code, *_ in sgs] == [433, 432]
    assert sgs[0][1:] == (date(2016, 11, 8), date(2026, 11, 6))  # 3650 days: under the SGS's 10-year cap


@pytest.mark.parametrize(
    "failure",
    [httpx.ConnectTimeout("slow"), httpx.HTTPStatusError("503", request=None, response=None), ValueError("bad json")],
)
def test_a_failing_sgs_is_unavailable(monkeypatch, failure):
    def get(code, start, end):
        raise failure

    monkeypatch.setattr(bcb, "get", get)

    with pytest.raises(bcb.Unavailable):
        bcb.fetch(["bcb_ipca"])


def test_an_empty_series_is_unavailable(monkeypatch):
    monkeypatch.setattr(bcb, "get", lambda code, start, end: [])

    with pytest.raises(bcb.Unavailable):
        bcb.fetch(["bcb_ipca"])
```

Em `tests/conftest.py`, acrescente `bcb` ao `from api import ...` e, depois do fixture `no_gemini_key`:

```python
@pytest.fixture(autouse=True)
def no_bcb_network(monkeypatch):
    # tests never reach the SGS; the ones that need series replace bcb.get or bcb.fetch
    def get(code, start, end):
        raise AssertionError("a test tried to reach the Banco Central SGS")

    monkeypatch.setattr(bcb, "get", get)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/api/test_bcb.py -v`
Expected: FAIL (`ImportError: cannot import name 'bcb'`).

- [ ] **Step 3: Implement**

Crie `api/bcb.py`:

```python
"""Banco Central series for the causal model's controls, from the SGS (public, no key)."""

import csv
import io
import logging
from datetime import date, datetime, timedelta

import httpx

log = logging.getLogger(__name__)

# IPCA monthly change, Selic target (daily), IBC-Br seasonally adjusted (monthly): the model has only weekly seasonality
SERIES = {"bcb_ipca": 433, "bcb_selic": 432, "bcb_ibc_br": 24364}
URL = "https://api.bcb.gov.br/dados/serie/bcdata.sgs.{code}/dados"
TIMEOUT = 10
# ponytail: one call per series covers 10 years (the SGS caps a daily series there); older data needs chunked calls
WINDOW = timedelta(days=3650)
ERROR = "Não foi possível buscar as séries do Banco Central. Tente de novo ou desmarque os controles."


class Unavailable(Exception):
    pass


def get(code: int, start: date, end: date) -> list[dict]:
    params = {"formato": "json", "dataInicial": start.strftime("%d/%m/%Y"), "dataFinal": end.strftime("%d/%m/%Y")}
    response = httpx.get(URL.format(code=code), params=params, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def fetch(controls: list[str], today: date | None = None) -> bytes:
    """The engine's bcb_file: Date plus one column per control, a blank where a series has no value that day."""
    end = today or date.today()
    start = end - WINDOW
    series = {}
    for name in controls:
        try:
            rows = get(SERIES[name], start, end)
            values = {datetime.strptime(row["data"], "%d/%m/%Y").date(): float(row["valor"]) for row in rows}
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as e:
            log.warning("bcb.unavailable series=%s reason=%r", name, e)
            raise Unavailable(name) from e
        if not values:
            log.warning("bcb.unavailable series=%s reason=empty", name)
            raise Unavailable(name)
        series[name] = values

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["Date", *controls])
    for day in sorted(set().union(*series.values())):
        writer.writerow([day.isoformat(), *(series[name].get(day, "") for name in controls)])
    return out.getvalue().encode()
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/api/test_bcb.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add api/bcb.py tests/api/test_bcb.py tests/conftest.py
git commit -m "feat(api): fetch the banco central series from the sgs as the engine's bcb file"
```

---

### Task 6: o run guarda o `bcb_file` e devolve 502 sem a SGS

**Files:**
- Modify: `api/runs.py` (imports; função nova antes de `create`; começo de `create`)
- Modify: `api/routes/runs.py:32` (`InputKey`) e `create_run` (linhas ~89-96)
- Test: `tests/api/test_runs.py`

- [ ] **Step 1: Write the failing tests**

Em `tests/api/test_runs.py`, acrescente `bcb` ao `from api import ...` e, depois de `test_create_run_snapshots_config_and_inputs_and_launches`:

```python
BCB_CSV = b"Date,bcb_ipca\n2024-01-01,0.42\n"


def test_a_run_with_bcb_controls_snapshots_the_series(logged, ready, db, monkeypatch):
    asked = []
    monkeypatch.setattr(bcb, "fetch", lambda controls: asked.append(controls) or BCB_CSV)
    simulation = ready()
    simulations.save_params(db, simulation, {**PARAMS, "controls": ["bcb_ipca"]})

    r = post_run(logged, simulation)

    assert r.status_code == 201, r.text
    assert asked == [["bcb_ipca"]]
    run = db.get(Run, r.json()["id"])
    entry = run.inputs["bcb_file"]
    assert entry["filename"] == "bcb.csv"
    stored = storage.path(simulations.input_key(simulation.workspace_id, simulation.id, entry["sha256"]))
    assert stored.read_bytes() == BCB_CSV
    download = logged.get(f"/api/w/a/runs/{run.id}/inputs/bcb_file")
    assert download.status_code == 200 and download.content == BCB_CSV


def test_a_failing_sgs_blocks_the_run_with_502(logged, ready, db, monkeypatch):
    def fail(controls):
        raise bcb.Unavailable("bcb_ipca")

    monkeypatch.setattr(bcb, "fetch", fail)
    simulation = ready()
    simulations.save_params(db, simulation, {**PARAMS, "controls": ["bcb_ipca"]})

    r = post_run(logged, simulation)

    assert r.status_code == 502 and r.json()["detail"] == bcb.ERROR
    assert db.scalar(select(func.count()).select_from(Run)) == 0


def test_without_controls_the_sgs_is_not_called(logged, ready, monkeypatch):
    monkeypatch.setattr(bcb, "fetch", lambda controls: pytest.fail("fetched without controls"))

    r = post_run(logged, ready())

    assert r.status_code == 201 and "bcb_file" not in r.json()["inputs"]


def test_a_blocked_run_does_not_fetch(logged, ready, monkeypatch):
    monkeypatch.setattr(bcb, "fetch", lambda controls: pytest.fail("fetched for a blocked run"))
    simulation = ready(params=False)

    assert post_run(logged, simulation).status_code == 409
```

(O `ready(params=False)` não salva parâmetros, então o `create` bloqueia com 409 antes de buscar.)

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/api/test_runs.py -k "bcb or sgs or blocked_run" -v`
Expected: FAIL (`AttributeError: module 'api' has no attribute 'bcb'` no import, depois `KeyError: 'bcb_file'` e 201 no lugar do 502).

- [ ] **Step 3: Implement**

Em `api/runs.py`, imports:

```python
import hashlib
import logging
import tempfile
from datetime import timedelta
from pathlib import Path
```

e troque `from api import launcher, simulations` por `from api import bcb, launcher, simulations, storage`.

Antes de `def create(`, acrescente:

```python
def snapshot_bcb(simulation: Simulation) -> dict | None:
    """The Banco Central series the analyst asked for, stored like an upload; raises bcb.Unavailable."""
    controls = simulation.config.get("controls") or []
    if not controls:
        return None
    content = bcb.fetch(controls)
    sha256 = hashlib.sha256(content).hexdigest()
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / "bcb.csv"
        local.write_bytes(content)
        storage.put(simulations.input_key(simulation.workspace_id, simulation.id, sha256), local)
    return {"sha256": sha256, "filename": "bcb.csv"}
```

Em `create`, troque as linhas do começo até o `files = ...`:

```python
def create(db: Session, simulation: Simulation, confirmed: set[str], by: User) -> Run:
    # checked once before the network call so a blocked run never waits on the SGS, and again under the lock
    reason = block_reason(simulation, confirmed)
    if reason:
        raise Blocked(reason)
    bcb_file = snapshot_bcb(simulation)  # before the lock: no row lock held during the HTTP calls
    fail_stale(db, Run.simulation_id == simulation.id)
    simulations.lock(db, simulation)
    reason = block_reason(simulation, confirmed)
    if reason:
        raise Blocked(reason)
```

e, depois do `run = Run(...)` e antes do `db.add(run)`:

```python
    if bcb_file:
        run.inputs = {**run.inputs, "bcb_file": bcb_file}
```

Em `api/routes/runs.py`:
- `InputKey = Literal["investment_file", "performance_file", "generic_trends_file", "bcb_file"]`;
- acrescente `bcb` ao `from api import ...`;
- em `create_run`, depois do `except runs.Blocked as e: raise HTTPException(409, str(e))`:

```python
    except bcb.Unavailable:
        raise HTTPException(502, bcb.ERROR)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/api/test_runs.py tests/api/test_rbac.py tests/api/test_engine_swap.py -v`
Expected: PASS. Confira que `test_create_run_snapshots_config_and_inputs_and_launches` segue verde (sem controles, `inputs` não ganha a chave `bcb_file`).

- [ ] **Step 5: Commit**

```bash
git add api/runs.py api/routes/runs.py tests/api/test_runs.py
git commit -m "feat(api): a run with bcb controls snapshots the series, and a failing sgs answers 502"
```

---

### Task 7: checkboxes dos controles no formulário e entrada na página do run

**Files:**
- Modify: `web/src/lib/params.ts`
- Modify: `web/src/components/ParamsForm.tsx:157-244` (`ParamField`)
- Modify: `web/src/components/RunDetails.tsx:172-200` (`Inputs`)
- Test: `web/e2e/simulations.spec.ts`

- [ ] **Step 1: Write the failing E2E test**

Em `web/e2e/simulations.spec.ts`, depois de `test('a mistyped optional target is refused ...')`:

```ts
test('macro controls are saved with the parameters', async ({ page, browser }) => {
  const { slug, analystPage } = await analystOnNewWorkspace(page, browser)
  await createSimulation(analystPage, slug, 'Controles')
  await uploadTemplatesAndValidate(analystPage)

  await analystPage.getByLabel('IPCA').check()
  await expect(analystPage.getByText('Salve os parâmetros antes de rodar.')).toBeVisible()
  await analystPage.getByRole('button', { name: 'Salvar parâmetros' }).click()
  await expect(analystPage.getByRole('button', { name: 'Rodar' })).toBeEnabled()

  await analystPage.reload()
  await expect(analystPage.getByLabel('IPCA')).toBeChecked()
  await expect(analystPage.getByLabel('Selic')).not.toBeChecked()
  await expect(analystPage.getByRole('button', { name: 'Rodar' })).toBeEnabled()
})
```

O teste não clica em Rodar: o servidor do E2E chamaria a SGS de verdade.

- [ ] **Step 2: Run it to verify it fails**

Run: `mise run e2e -- -g "macro controls"`
Expected: FAIL (nenhum elemento com o rótulo "IPCA").

- [ ] **Step 3: Implement**

Em `web/src/lib/params.ts`:

No `FieldSchema`, troque a linha do `type` e acrescente `items`:

```ts
  type?: 'number' | 'integer' | 'boolean' | 'string' | 'object' | 'null' | 'array'
  items?: FieldSchema
```

Troque `export type FormValue = string | boolean` por:

```ts
export type FormValue = string | boolean | string[]
```

No grupo `'Causal'` do `FORM_LAYOUT`, depois de `{ path: 'require_model_fit', label: 'Exigir bom ajuste' },`:

```ts
      {
        path: 'controls',
        label: 'Controles macro (Banco Central)',
        help: 'Buscados na hora de rodar. Um controle que anda junto com o investimento do evento é descartado.',
      },
```

Troque o `ENUM_LABELS`:

```ts
export const ENUM_LABELS: Record<string, string> = {
  REVENUE: 'Receita',
  CONVERSIONS: 'Conversões',
  bcb_ipca: 'IPCA',
  bcb_selic: 'Selic',
  bcb_ibc_br: 'IBC-Br',
}
```

Em `displayValue`, depois de `if (value == null) return '—'`:

```ts
  if (Array.isArray(value)) return value.length ? value.map((v) => ENUM_LABELS[String(v)] ?? String(v)).join(', ') : 'Nenhum'
```

Troque `toForm` e `fromForm`:

```ts
const toForm = (field: FormField, value: unknown): FormValue => {
  if (field.schema.type === 'array') return Array.isArray(value) ? value.map(String) : []
  return field.schema.type === 'boolean' ? value === true : value == null ? '' : String(value)
}

function fromForm(field: FormField, value: FormValue): unknown {
  if (field.schema.type === 'boolean' || field.schema.enum || field.schema.type === 'array') return value
  return value === '' ? null : Number(value)
}
```

Troque `unsavedParams` (uma lista se compara pelo conteúdo, e uma simulação salva antes do A4 não tem `controls`, o que vale `[]`):

```ts
function changed(field: FormField, value: unknown, saved: unknown): boolean {
  if (field.schema.type === 'array') return JSON.stringify(value) !== JSON.stringify(saved ?? [])
  return value !== (saved ?? null)
}

// compared as the PUT body would carry it, so "0.20" on screen equals a saved 0.2
export const unsavedParams = (layout: FormGroup[], values: Record<string, FormValue>, config: Record<string, unknown>) =>
  allFields(layout).some((field) => changed(field, fromForm(field, values[field.path]), getPath(config, field.path)))
```

Em `web/src/components/ParamsForm.tsx`, no `ParamField`, logo depois de `const describedBy = ...`:

```tsx
  if (schema.type === 'array') {
    const selected = Array.isArray(value) ? value : []
    const options = schema.items?.enum ?? []
    return (
      <div className="space-y-1">
        <p id={id} className="text-sm font-medium">
          {field.label}
        </p>
        <div role="group" aria-labelledby={id} aria-describedby={describedBy} className="flex flex-wrap gap-4">
          {options.map((option) => (
            <div key={option} className="flex items-center gap-2">
              <Checkbox
                id={`${id}-${option}`}
                checked={selected.includes(option)}
                disabled={disabled}
                onCheckedChange={(on) =>
                  onChange(on === true ? options.filter((o) => o === option || selected.includes(o)) : selected.filter((o) => o !== option))
                }
              />
              <Label htmlFor={`${id}-${option}`}>{ENUM_LABELS[option] ?? option}</Label>
            </div>
          ))}
        </div>
        {note && (
          <p id={`${id}-note`} className="text-xs text-muted-foreground">
            {note}
          </p>
        )}
        {error && (
          <p id={`${id}-error`} role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
      </div>
    )
  }
```

(Marcar segue a ordem das opções, então `["bcb_ipca", "bcb_selic"]` sai igual qualquer que seja a ordem dos cliques.)

Em `web/src/components/RunDetails.tsx`, acima de `function Inputs`:

```tsx
// the uploads plus what the platform fetched for the run (A4)
const RUN_INPUTS = [...FILES, { key: 'bcb_file', label: 'Séries do Banco Central' }]
```

e, em `Inputs`, troque `{FILES.map((spec) => {` por `{RUN_INPUTS.map((spec) => {`.

- [ ] **Step 4: Build, lint and run the E2E**

Run: `cd web && bun run build && bun run lint && cd .. && mise run e2e -- -g "parameters|macro controls"`
Expected: PASS nos dois testes de parâmetros.

- [ ] **Step 5: Screenshot**

Com `docker compose up -d`, `mise run api` e `mise run web` no ar, abra uma simulação com parâmetros pelo MCP `playwright` e tire um screenshot do grupo "Causal" com os três checkboxes, nos temas claro e escuro. Abra também a página de um run e confira os parâmetros ("Controles macro (Banco Central)": "Nenhum" ou os rótulos).

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/params.ts web/src/components/ParamsForm.tsx web/src/components/RunDetails.tsx web/e2e/simulations.spec.ts
git commit -m "feat(web): bcb control checkboxes on the parameters form and the series on the run inputs"
```

---

### Task 8: docs

**Files:**
- Modify: `docs/decisoes/engine.md`, `docs/decisoes/infra-e-operacao.md`, `docs/m2/trilha-a-motor.md:113-131`, `CLAUDE.md`, `API-GUIDE.md:40`

- [ ] **Step 1: `docs/decisoes/engine.md`**

Acrescente uma seção `## A4 · Controles causais (06/nov/2026)` com:
- Leads/Clicks/Impressions do arquivo de performance não entram mais no causal; o `PreparedData.performance_df` virou `controls_df`.
- Controles candidatos: Trends (sempre que houver o arquivo) e `config.controls` (`bcb_ipca` = SGS 433, `bcb_selic` = 432, `bcb_ibc_br` = 24364, dessazonalizado porque o modelo só tem sazonalidade semanal). Triagem por evento: |r| com o spend dos canais do evento no pré-período > `gate_thresholds.control_spend_corr` (0.5) → descartado, `controls[].accepted=false` e `control_rejected` no `reasons` do evento, sem mudar o status. r indefinido (série constante) → aceito.
- Quem busca: a API, ao criar o run (`api/bcb.py`), grava `bcb.csv` no snapshot; o motor não acessa a rede. SGS fora do ar → 502, nenhum run. "Rodar de novo" busca de novo.
- Mensal → cadência do run: `merge_asof`, o último valor publicado até a data (não interpola; cobre os dias depois da última publicação).
- `LassoCV(cv=TimeSeriesSplit(max(2, min(5, n // 4))))`.
- Paridade: `test_events_and_gates_match` compara com o protótipo só a detecção e a aritmética de investimento (`MODEL_FREE`); os números do modelo causal mudaram de propósito. MMM e curva seguem idênticos. Diferença medida no Linux: (preencha com a saída de `mise run parity` antes e depois, ou do job `py` do CI). Pendente para a A10: calibrar o 0.5.
- Limite conhecido: dado com mais de 10 anos fica sem BCB nas datas antigas (a busca é de 3650 dias).

- [ ] **Step 2: `docs/decisoes/infra-e-operacao.md`**

Na parte do B11, uma linha: o servidor precisa de saída HTTPS para `api.bcb.gov.br` (controles do causal, A4); sem ela, todo run com controle do BCB dá 502.

- [ ] **Step 3: `docs/m2/trilha-a-motor.md`**

No item A4, depois de `- **Depende de:** A0.`, a linha de status:

```markdown
- **Status:** ✅ feito em 06/nov/2026. Covariáveis da mídia (Leads/Clicks/Impressions) fora do causal; controles exógenos (Trends e, marcadas pelo analista, IPCA/Selic/IBC-Br da SGS, buscadas pela API ao criar o run e gravadas no snapshot) triados por evento com `control_spend_corr` = 0.5 e publicados em `events[].controls`; `LassoCV` com `TimeSeriesSplit`. Verificado: `tests/engine/test_controls.py` (performance com Clicks/Impressions dá o mesmo lift; controle = spend + ruído descartado; controle independente e série do BCB aceitos; forward-fill por `merge_asof`; folds curtos), `tests/api/test_bcb.py`, `tests/api/test_runs.py` (snapshot, 502, sem controles não busca), `web/e2e/simulations.spec.ts`. A paridade compara com o protótipo só detecção e investimento (`MODEL_FREE`, registrado para a A10). Fora: séries além das três, cache da SGS, calibrar o 0.5 (A10). Spec: `docs/superpowers/specs/2026-11-06-a4-controles-causais-design.md`.
```

- [ ] **Step 4: `CLAUDE.md`**

- No mapa de `api/`, depois de `gemini.py`: `  bcb.py          séries do Banco Central (SGS) para os controles do causal; trocada por fake nos testes`.
- No "Estado atual", depois da frase do A5 (antes de "Pendência da Trilha A"): `**A4 (controles causais) concluído em 06/nov/2026**: sem Leads/Clicks/Impressions no causal; Trends e IPCA/Selic/IBC-Br (marcados pelo analista, buscados pela API na SGS ao criar o run, 502 se ela falhar) triados por evento (|r| com o spend > 0.5 → descartado, em `events[].controls`); `LassoCV` com `TimeSeriesSplit`; a paridade compara com o protótipo só detecção e investimento.` E em "Faltam:", troque `A4 e A6–A10` por `A6–A10`.

- [ ] **Step 5: `API-GUIDE.md`**

Na linha do `POST /api/w/{slug}/simulations/{simulation_id}/runs`, depois de "snapshot de `config` e do sha256 dos inputs": `; com \`controls\` nos parâmetros, busca as séries do BCB e grava \`inputs.bcb_file\`. 502 \`Não foi possível buscar as séries do Banco Central…\` se a SGS falhar (nenhum run criado)`. Na linha do `GET …/runs/{run_id}/inputs/{key}`, acrescente `bcb_file` às chaves aceitas.

- [ ] **Step 6: Full check and commit**

Run: `uv run ruff check . && uv run ruff format --check . && mise run test`
Expected: PASS.

```bash
git add docs/decisoes/engine.md docs/decisoes/infra-e-operacao.md docs/m2/trilha-a-motor.md CLAUDE.md API-GUIDE.md
git commit -m "docs(a4): causal controls, bcb fetch and the parity change"
```
