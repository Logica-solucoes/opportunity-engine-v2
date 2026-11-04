# A1 — `results.json` v1 e fixtures — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `engine.run` devolve e grava um `results.json` tipado e versionado (todo o contrato §3), sem `NaN`/`Infinity`, mais fixtures da Gol anonimizada.

**Architecture:** modelos pydantic fechados em `engine/results_schema.py`; `engine/results.py` monta o modelo a partir do `Computed` (só transporte, nenhum cálculo novo), sanitiza e grava; `run()` chama no fim. Seções de A2/A4–A9 existem no schema e saem `null`.

**Tech Stack:** Python 3.13, pydantic 2, pandas, pytest, uv, ruff.

**Spec:** `docs/superpowers/specs/2026-11-04-a1-results-json-design.md` (a spec vence este plano em qualquer conflito).

## Global Constraints

- Todos os modelos `extra="forbid"`; `schema_version: Literal[1]`.
- JSON final: `json.dumps(..., ensure_ascii=False, allow_nan=False)`; `NaN`/`inf`/`-inf` → `null` em qualquer profundidade.
- Nenhum número muda: `tests/engine/test_parity.py` e `test_parity_real.py` passam sem edição; nada de arredondar.
- Nome de canal/coluna nunca hardcoded; pt-BR em mensagens de tela; sem `print()`; `ruff format` + `ruff check` (linha 120).
- Dados reais só com 1 thread de BLAS (`threadpool_limits(limits=1)` nos testes que usam a Gol).
- Fixtures versionados: canais só `CANAL_NN`, sem caminhos, sem `exemplo_csv`; fatores de escala em `tests/fixtures/results/.private/` (git-ignorado).
- Commits terminam com `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`. Nada de merge nem push.
- Não tocar `api/`, `Dockerfile`, o protótipo, nem `tests/fixtures/parity/snapshot.json`.

## Review Focus

- Evento com `analysis_failed` (`results_data` nulo, DataFrames nulos): sai com `lift`, `fit`, `series` `None` e `reasons=["analysis_failed"]`, sem exceção.
- Ponto com `inf`/`NaN` (ex.: `Incremental_ROI = inf` em `strategic_reallocation`, `iCPA = NaN`): vira `null`, o JSON abre com `parse_constant` que falha.
- `cpa_incremental` com `absolute_lift == 0` (hoje 0 como sentinela): `null`.
- Nomes de canal com espaço, barra ou acento (`"RTB HOUSE"`, `"GOOGLE DISPLAY/VIDEO"`) nas chaves de `mix`, `by_channel` e nos ids: preservados exatamente.
- Cadência semanal (`period_days=7`) e dataset sem trends: `results.json` válido, `baseline.monthly` coerente, sem `NaN`.
- Rodar `run` duas vezes no mesmo `out_dir`: o `results.json` sai idêntico byte a byte.

---

### Task 1: Schema `ResultsV1` e `sanitize`

**Files:**
- Create: `engine/results_schema.py`, `engine/results.py` (só `sanitize` por ora), `tests/engine/test_results_schema.py`

**Interfaces:**
- Produces: `SCHEMA_VERSION = 1`; `ResultsV1` e submodelos (nomes do spec: `Causal`, `EventDetected`, `CausalEvent`, `Lift`, `Fit`, `Placebo`, `EventSeries`, `Elasticity`, `ElasticityMetrics`, `ChannelFit`, `Hill`, `CurvePoint`, `Group`, `ResponseRow`, `Scenario`, `Baseline`, `MonthlyBaseline`, `ValidationReport`, `Check`, `Sufficiency`, `Reports`, `Grounding`); `ExperimentDesign = dict[str, Any]`; `Elasticity.metrics: ElasticityMetrics | None` (nulo quando o MMM falha); `Reports.global_` com alias `"global"`; `sanitize(obj: Any) -> Any` em `engine/results.py`.

- [ ] **Step 1: Write the failing tests** in `tests/engine/test_results_schema.py`:
  - `test_minimal_results_validates`: `ResultsV1(schema_version=1, engine_version="x", status="failed")` valida e todas as seções são `None`.
  - `test_unknown_field_is_rejected`: campo extra na raiz e em `CausalEvent` levanta `ValidationError`.
  - `test_schema_version_must_be_1`.
  - `test_status_values`: só `succeeded|inconclusive|failed`; `CausalEvent.status` só `published|rejected`.
  - `test_reports_global_alias`: `Reports(**{"events": {}, "global": {"a": 1}, "grounding": None}).model_dump(by_alias=True)` tem a chave `"global"`.
  - `test_json_schema_is_exportable`: `ResultsV1.model_json_schema()` contém `"properties"` com as 10 chaves da raiz.
  - `test_sanitize_replaces_non_finite_at_any_depth`: `sanitize({"a": [float("nan"), {"b": float("inf")}], "c": -float("inf"), "d": 1.5})` → `{"a": [None, {"b": None}], "c": None, "d": 1.5}`; `sanitize` não muta a entrada e deixa `bool`/`int`/`str` intactos.

- [ ] **Step 2: Run** `uv run pytest tests/engine/test_results_schema.py -q` — Expected: FAIL (módulo inexistente).

- [ ] **Step 3: Implement** `engine/results_schema.py` com os modelos do spec (seção "Schema"): campos float são `float | None`, `lift.ci` é `tuple[float | None, float | None] | None`, `CurvePoint(x, y, lo, hi, extrapolated)` com `lo/hi/extrapolated` opcionais, `Scenario.name` `Literal["current","max_efficiency","strategic_limit","diminishing_return","saturation","strategic_reallocation"]`. Seções com `status: Literal["ok","inconclusive","failed"]` e `reasons: list[str]` em `Causal` e `Elasticity`. `Baseline.monthly[] = {month, kpi, investment, by_channel: dict[str, float]}`. E `sanitize` em `engine/results.py` (recursivo sobre `dict`/`list`/`tuple`, `float` não finito → `None`).

- [ ] **Step 4: Run** o mesmo comando — Expected: PASS. `uv run ruff format engine tests && uv run ruff check engine tests`.

- [ ] **Step 5: Commit** `feat(engine): results.json v1 schema and sanitize (a1)`.

### Task 2: Dados que o `Computed` ainda não guarda

**Files:**
- Modify: `engine/pipeline.py` (`Computed`, `detect_events`, `run_elasticity`, `compute`), `engine/elasticity_analysis.py` (`generate_individual_response_curves`)
- Test: `tests/engine/test_pipeline_stages.py` (estender), `tests/engine/conftest.py` (criar, ver abaixo)

**Interfaces:**
- Consumes: Task 1 não é usada aqui.
- Produces: `Computed.candidates: pd.DataFrame` (saída do `detect_events`, todas as linhas, inclusive `eligible=False`); `Computed.individual_curves_df: pd.DataFrame | None` (colunas `Channel, Channel_Spend, Projected_Total_KPIs, Historical_Avg, Recommended`); `detect_events` ganha a coluna `investment_change_pct` (de `percentage_change`); `generate_individual_response_curves(...)` devolve o DataFrame (sempre, com ou sem `output_dir`); fixture de sessão `synthetic_computed` em `tests/engine/conftest.py` (roda `compute` no dataset sintético uma vez, `full_config`/`dataset_config`, 1 thread) e `synthetic_prepared`.

- [ ] **Step 1: Write failing tests** em `test_pipeline_stages.py`:
  - `test_detect_events_keeps_the_investment_change`: coluna `investment_change_pct` presente, numérica, sinal positivo para aumento; `columns` do DataFrame vazio também a inclui.
  - `test_compute_keeps_the_candidates`: `computed.candidates` tem tantas linhas quanto `detect_events` e a coluna `eligible`.
  - `test_compute_keeps_the_individual_curves`: `computed.individual_curves_df` tem 100 linhas por canal de `mmm["spend_cols"]`.
  - `test_individual_curves_function_returns_the_frame`: chamada direta com `output_dir=None` devolve o DataFrame (hoje devolve `None`).
- [ ] **Step 2: Run** `uv run pytest tests/engine/test_pipeline_stages.py -q` — Expected: FAIL nos quatro.
- [ ] **Step 3: Implement** as quatro mudanças. `run_elasticity` guarda o retorno de `generate_individual_response_curves` em `individual_curves_df` — hoje a função só é chamada quando `global_dir is not None`; passe a chamá-la sempre (com `output_dir=global_dir`, que pode ser `None`) para o dado existir mesmo sem exportar. Nenhuma linha de cálculo muda.
- [ ] **Step 4: Run** `uv run pytest tests/engine -q -k "not parity"` e depois `uv run pytest tests/engine/test_parity.py -q` — Expected: PASS (paridade intacta).
- [ ] **Step 5: Commit** `refactor(engine): keep candidates and individual curves in Computed (a1)`.

### Task 3: `build_results` — seção `causal`

**Files:**
- Modify: `engine/results.py`
- Test: `tests/engine/test_results_build.py`

**Interfaces:**
- Consumes: `Computed.events: list[EventOutcome]`, `Computed.candidates`, schema da Task 1.
- Produces: `build_causal(computed: "Computed") -> Causal | None` (privado `_causal` aceitável). Regras: `events_detected` de **todos** os `candidates` (`date` = `intervention_date`, `channels` = `product_group` dividido em `", "`, `investment_change_pct`, `eligible`); `events` de `computed.events`; `CausalEvent.id` = `event_id`; `status="published"` se `passed and selected`, senão `"rejected"`; `reasons` = `outcome.reasons`, mais `"not_selected"` se `passed and not selected`; `start/end` de `results_data["start_date"/"end_date"]`; `lift {abs, ci [lower, upper], rel_pct}`; `incremental_investment` = `total_investment_post_period`; `cpa_incremental` `None` se `absolute_lift == 0`; `fit {r2, mae, mape, wmape=None}`; `placebo=None`; `series` dos quatro DataFrames (`line`: `date, actual_kpi, investment, forecasted_kpi`; `accuracy`: `date, kpi, predicted` e `mae` em cada registro; `investment`: `period, investment`; `kpi`: `category, kpi`). Seção `status`: `ok` se ≥1 evento `published`; senão `inconclusive` com reason `no_events_detected` (sem candidatos), `no_eligible_events` (candidatos, nenhum elegível) ou `no_event_passed_gates`. Retorna sempre um `Causal` (nunca `None`) para o motor ter o motivo.

- [ ] **Step 1: Write failing tests** em `tests/engine/test_results_build.py` (usa `synthetic_computed`):
  - `test_causal_events_follow_the_outcomes`: um `CausalEvent` por `EventOutcome`; `id`s iguais; `published` ⇔ `passed and selected`.
  - `test_passed_but_not_selected_is_rejected_with_reason`: construindo `EventOutcome` à mão com `passed=True, selected=False`.
  - `test_series_have_the_four_named_blocks`: chaves `line/accuracy/investment/kpi`, registros com os nomes `snake_case` do contrato, sem `NaN`.
  - `test_analysis_failed_event_has_no_lift_fit_or_series`: `EventOutcome(..., results_data=None, reasons=["analysis_failed"])` → `lift/fit/series is None`, sem exceção.
  - `test_zero_lift_gives_null_cpa`: `results_data` com `absolute_lift=0, cpa_incremental=0` → `cpa_incremental is None`.
  - `test_events_detected_lists_every_candidate_including_ineligible`.
  - `test_causal_status_reasons`: três casos (sem candidatos, nenhum elegível, nenhum passou) → `inconclusive` com o reason certo; ≥1 publicado → `ok`.
  - `test_channel_names_with_spaces_and_slashes_are_kept`: `product_group="GOOGLE DISPLAY/VIDEO, RTB HOUSE"` → `channels == ["GOOGLE DISPLAY/VIDEO", "RTB HOUSE"]`.
- [ ] **Step 2: Run** `uv run pytest tests/engine/test_results_build.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** `_causal` em `engine/results.py` (helpers para converter DataFrame em lista de registros: `Timestamp` → `YYYY-MM-DD`, escalares numpy → Python, `NaN` fica para o `sanitize`).
- [ ] **Step 4: Run** o mesmo comando — Expected: PASS; `ruff`.
- [ ] **Step 5: Commit** `feat(engine): build the causal section of results.json (a1)`.

### Task 4: `build_results` — elasticidade, baseline e status

**Files:**
- Modify: `engine/results.py`
- Test: `tests/engine/test_results_build.py` (estender)

**Interfaces:**
- Consumes: Task 3 (`_causal`), `Computed.mmm`, `response_curve_df`, os seis `*_point`, `individual_curves_df`, `effective_config["channel_groups"]`, `prepared.kpi_df` (`Date, kpi`), `prepared.investment_df` (`Date, Product Group, investment`).
- Produces: `build_results(computed: "Computed", engine_version: str) -> ResultsV1`; `run_status(causal: Causal, elasticity: Elasticity | None) -> str` (spec, tabela "Status"). Elasticidade: `metrics {cv_r2, r2, media_contribution_pct=marketing_contribution_of_kpi_pct, low_confidence=None, reallocation_suppressed=None}`; `channels[]` por `spend_cols` com `contribution_pct`, `hill {K: ks[i], n: ss[i]}`, `adstock: alphas[i]`, `observed_spend_range [min, max]` da coluna do canal em `mmm["dataframe"]`, `curve` de `individual_curves_df` (`x=Channel_Spend`, `y=Projected_Total_KPIs`), `identifiable/coef_ci=None`; `groups[]` de `channel_groups` (`name=" + ".join(members)`); `response_curve[]` com o mapeamento do spec (`iroas ← Incremental_ROI`, que o código confirma ser `Incremental_Revenue / Incremental_Investment`; `mix` com as três variantes lidas das colunas `Spend_<canal>_<Historical|Optimized|Strategic>`); `scenarios[]` dos pontos não nulos (`icpa ← point.get("iCPA")`, `projected_kpis` descartado). Se `mmm is None`: `elasticity = Elasticity(status="failed", reasons=["model_failed"], ...vazios)` — decisão: a seção existe com `status` e listas vazias, `metrics=None`. `baseline.monthly`: soma mensal de `kpi` e de `investment` e por canal.

- [ ] **Step 1: Write failing tests**:
  - `test_elasticity_metrics_and_channels`: `cv_r2`, `r2` iguais ao `mmm`; um `ChannelFit` por `spend_cols`, `hill.K` = `ks[i]`; `observed_spend_range[0] <= [1]`; `curve` com 100 pontos.
  - `test_response_curve_rows_map_the_columns`: `len == len(response_curve_df)`; primeira linha: `investment == Daily_Investment`, `kpi == Projected_Total_KPIs`, `mix` com as 3 chaves e um valor por canal.
  - `test_non_finite_curve_values_are_null_after_dump`: força `Incremental_ROI = inf` e `iCPA = NaN` numa cópia do `Computed` e confirma `None` depois de `dump_results` (Task 5 não é necessária: use `sanitize(results.model_dump(mode="json", by_alias=True))`).
  - `test_scenarios_use_the_known_names_and_skip_missing_points`.
  - `test_groups_from_config`: `channel_groups=[["PMAX","SEARCH"]]` → `{"name": "PMAX + SEARCH", "members": [...]}`.
  - `test_baseline_monthly_sums_match_the_prepared_data`: soma de `kpi` por mês e `by_channel` somando ao `investment`.
  - `test_run_status_matrix`: (ok,ok)→`succeeded`; (inconclusive,ok)→`inconclusive`; (ok,failed)→`inconclusive`; (inconclusive,failed)→`failed`.
  - `test_failed_model_yields_a_failed_elasticity_section`: `Computed(..., mmm=None)`.
  - `test_build_results_validates_and_has_no_future_sections`: `validation/sufficiency/experiment_design/reports is None`; `ResultsV1.model_validate(results.model_dump(by_alias=True))` passa.
  - `test_weekly_cadence_dataset`: `make_dataset(cadence_days=7)` + `compute` → `build_results` válido (marcar `slow` não é necessário; reutilize o custo do dataset curto).
  - `test_dataset_without_trends_builds`: `with_trends=False`.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement** `_elasticity`, `_baseline`, `run_status`, `build_results`.
- [ ] **Step 4: Run** `uv run pytest tests/engine/test_results_build.py tests/engine/test_results_schema.py -q` — Expected: PASS; `ruff`.
- [ ] **Step 5: Commit** `feat(engine): build elasticity, baseline and status of results.json (a1)`.

### Task 5: `run()` grava e devolve o `results.json`

**Files:**
- Modify: `engine/results.py` (`dump_results`, `write_results`), `engine/pipeline.py` (`run`), `engine/__init__.py` (exportar `ResultsV1`)
- Test: `tests/engine/test_results_run.py`; ajustar `tests/engine/test_run.py` onde esperava `succeeded`/seções `None`

**Interfaces:**
- Consumes: `build_results`, `sanitize`.
- Produces: `dump_results(results: ResultsV1) -> dict` (`model_dump(mode="json", by_alias=True)` → `sanitize` → `ResultsV1.model_validate` de novo → devolve o dict); `write_results(data: dict, path: Path) -> None` (`json.dumps(..., ensure_ascii=False, allow_nan=False)`); `run()` retorna o dict e grava `out_dir/results.json`. O status vem de `run_status` (o `failed = mmm is None and not any(passed)` do A0 sai).

- [ ] **Step 1: Write failing tests** (`test_results_run.py`, `run` no dataset sintético, `LLM_PROVIDER=none`):
  - `test_run_writes_results_json_equal_to_the_return`: `json.loads(file) == returned`.
  - `test_results_json_has_no_non_finite_numbers`: `json.loads(text, parse_constant=_boom)` não dispara.
  - `test_run_result_validates_against_the_schema`.
  - `test_run_twice_gives_identical_files`: duas execuções em `out_dir` diferentes e a segunda no mesmo `out_dir`: bytes iguais (compare ignorando `engine_version` só se a sha mudar durante o teste — não muda).
  - `test_status_inconclusive_when_no_event_is_eligible`: `min_intervention_date` depois do último dado → `inconclusive`, `causal.status == "inconclusive"`, `elasticity.status == "ok"`.
  - `test_numbers_in_results_match_compute`: lift de um evento e `cv_r2` lidos do arquivo batem com `compute()` a `rtol=1e-9`.
  - `test_run_still_returns_failed_status_when_nothing_works`: reaproveite o caso de `test_run.py` que força falha e confirme `status == "failed"` e `causal`/`elasticity` presentes com `failed`/`inconclusive`.
- [ ] **Step 2: Run** `uv run pytest tests/engine/test_results_run.py tests/engine/test_run.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement.** O `results.json` é escrito depois dos escritores legados e dos relatórios (não muda a ordem existente). `engine_version()` continua vindo de `engine/version.py`.
- [ ] **Step 4: Run** `uv run pytest tests/engine -q -k "not parity"` — Expected: PASS; depois `uv run pytest tests/engine/test_parity.py -q` — PASS.
- [ ] **Step 5: Commit** `feat(engine): run writes and returns results.json (a1)`.

### Task 6: Anonimização, fixtures e guardas

**Files:**
- Create: `tests/fixtures/results/anonymize_gol.py`, `tests/fixtures/results/generate_fixtures.py`, `tests/fixtures/results/README.md`, `tests/fixtures/results/{gol_anonimizada,gol_inconclusiva,falha}.json`, `tests/engine/test_results_fixtures.py`
- Modify: `.gitignore` (`tests/fixtures/results/.private/`)

**Interfaces:**
- Consumes: `tests.engine.real_data.GOL_CONFIG`, `run`, `build_results`/`dump_results`/`write_results`, `ResultsV1`.
- Produces: `anonymize_gol.anonymize(src_dir: Path, out_dir: Path, factors_file: Path) -> dict[str, str]` (mapa real→`CANAL_NN`; o mapa **não** é gravado em disco versionado); `generate_fixtures.py` (CLI `uv run python tests/fixtures/results/generate_fixtures.py`): anonimiza num diretório temporário, roda `run` com `threadpool_limits(1)` e `LLM_PROVIDER=none`, grava `gol_anonimizada.json` e `gol_inconclusiva.json` (`min_intervention_date` = dia seguinte ao último dado), e `falha.json` (um `Computed` do dataset sintético com `events=[]`, `mmm=None`, `candidates` vazio → `build_results`). Fatores: `factors.json` com `{"investment": f1, "kpi": f2}`, criado com valores aleatórios em `[0.3, 3.0]` se não existir; o script **não** contém nomes reais; datas e trends preservados; valores arredondados a 2 casas.

- [ ] **Step 1: Write failing tests** em `test_results_fixtures.py`:
  - `test_anonymize_renames_and_scales_but_keeps_dates` (sobre o dataset sintético copiado para `tmp_path`): canais viram `CANAL_01…`, colunas de data idênticas, razão investimento_novo/antigo é constante e ≠ 1, trends idênticos.
  - `test_anonymize_is_deterministic_for_the_same_factors_file`.
  - `test_fixtures_validate_and_cover_the_three_statuses`: carrega os três, `ResultsV1.model_validate`, status `succeeded`/`inconclusive`/`failed`; a Gol tem ≥1 evento `published` e ≥1 `rejected`.
  - `test_fixtures_contain_no_non_finite_numbers`.
  - `test_fixtures_only_use_anonymous_channel_names`: todo nome de canal (em `channels`, `elasticity.channels[].name`, chaves de `mix`/`by_channel`, membros de grupos, `events_detected`) casa `^CANAL_\d{2}$`; nenhuma string do JSON contém `exemplo_csv` nem `/`.
  - `test_fixtures_hide_the_original_data` (**local**, `skipif` sem `exemplo_csv/Gol`): nenhum nome de canal real e nenhum valor original de `investment` aparece como número no texto dos fixtures.
- [ ] **Step 2: Run** `uv run pytest tests/engine/test_results_fixtures.py -q` — Expected: FAIL.
- [ ] **Step 3: Implement** os dois scripts (importáveis como módulo: `tests.fixtures.results.anonymize_gol`), gerar os fixtures (`uv run python tests/fixtures/results/generate_fixtures.py`, ~2–4 min), inspecionar tamanho (`ls -la`; esperado < 1 MB cada) e abrir `gol_anonimizada.json` para conferir que não há nome real (`grep` pelos nomes reais saídos de `exemplo_csv/Gol/investment.csv` deve retornar vazio). README: como regenerar, o arquivo de fatores, o que o B5 pode assumir (`status`, `reasons`, séries).
- [ ] **Step 4: Run** `uv run pytest tests/engine/test_results_fixtures.py -q` — Expected: PASS.
- [ ] **Step 5: Commit** `test(engine): anonymized gol fixtures for results.json (a1)`.

### Task 7: Documentação e verificação final

**Files:**
- Modify: `docs/decisoes/engine.md` (seção do `results.json`: formato, status, o que ficou `null` por item, anonimização, a mudança de status do A0), `docs/m2/trilha-a-motor.md` (linha `Status` do A1 com data e verificação), `CLAUDE.md` ("Estado atual" e o mapa `engine/`: `results_schema.py`, `results.py`), `docs/superpowers/specs/2026-11-04-a1-results-json-design.md` (seção "Desvios na implementação", se houver)

- [ ] **Step 1:** Escrever as quatro atualizações acima (pt-BR, no estilo dos arquivos).
- [ ] **Step 2: Verificar:** `uv run ruff format --check . && uv run ruff check .`; `uv run pytest -q -p no:warnings` (suíte inteira) — Expected: tudo verde, anotando N passed/skipped; `mise run parity-real` — Expected: 6 passed; `grep -rn "NaN\|Infinity" tests/fixtures/results/*.json` — Expected: vazio.
- [ ] **Step 3: Commit** `docs: record results.json v1 decisions and mark a1 done`.
