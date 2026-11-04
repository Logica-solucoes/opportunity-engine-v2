# A2 · Validação de upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `engine.validate(inputs, config) -> ValidationReport` com o catálogo de checks do spec, e `run`/`load_and_prepare_data` obedecendo ao mesmo veredito (sem média/soma silenciosa).

**Architecture:** `engine/inputs.py` lê e normaliza os três CSV e acumula `Check`s (extraído de `load_and_prepare_data`); `engine/validation.py` roda os checks sobre as tabelas lidas e monta o `ValidationReport`; `load_and_prepare_data` consome `read_inputs` e levanta `EngineError(check_id)`; `run()` valida antes de calcular e grava o relatório em `results.json`.

**Tech Stack:** Python 3.13, pandas 3.0.3, numpy 2.5.0, pydantic, pytest, `uv`, `mise`.

**Spec:** `docs/superpowers/specs/2026-11-04-a2-validacao-upload-design.md`

## Global Constraints

- ruff line length 120; sem `print()`; mensagens mostradas na tela em pt-BR, sem caminhos nem dados do cliente (exemplos de valor inválido: no máximo 3, como hoje).
- Nome de coluna nunca hardcoded: vem do `column_mapping`.
- `EngineConfig` é só lido; `validate` não escreve arquivo nem altera o CWD.
- Dados limpos: resultado do `run` idêntico ao de antes (paridade sintética e `mise run parity-real` a rtol 1e-9, BLAS em 1 thread).
- Ids de check estáveis (tabela do spec): `file_unreadable`, `column_missing`, `date_unparseable`, `value_not_numeric`, `no_valid_rows`, `duplicate_date_channel`, `kpi_duplicate_dates`, `kpi_not_single_source`, `cadence_mismatch`, `insufficient_after_partial`, `missing_dates`, `outliers`, `partial_period_dropped`, `dv360_cm360_overlap`.
- `ok` é `true` se e somente se não há check `error`. `collinearity` sai vazia (A3 preenche).
- TDD: teste primeiro, vê-lo falhar, depois o código. Rodar a suíte inteira (`mise run test`) ao fim de cada task.

## Review Focus

- Arquivo de performance com `;` e decimal vírgula, sem canal (layout VW `_br`) → `ok`, sem `kpi_not_single_source`.
- Performance com data repetida **e** coluna de texto que varia na mesma data (Tcross) → só `kpi_not_single_source`, sem `kpi_duplicate_dates` duplicado.
- Série de investimento com canal que tem investimento 0 em todo o período (variância zero) → o `dv360_cm360_overlap` não pode dar `NaN`/divisão por zero.
- Trends ausente (`None`) ou vazio → sem erro.
- Rodapé de BI no fim do CSV continua sendo descartado (não vira `date_unparseable`).
- Cadência semanal (PMAX): `missing_dates` usa a grade semanal, não a diária.

---

### Task 1: `EngineError.check_id`, fábrica de CSV de teste e `read_inputs` (sem checks novos)

Extrai a leitura sem mudar comportamento; é a base de tudo.

**Files:**
- Modify: `engine/errors.py`
- Create: `engine/inputs.py`
- Modify: `engine/data_preprocessor.py:759-910` (leitura vira chamada a `read_inputs`)
- Create: `tests/engine/csv_factory.py`
- Test: `tests/engine/test_inputs.py`

**Interfaces:**
- Produces:
  - `EngineError(message: str, check_id: str | None = None)`; atributo `.check_id`.
  - `engine.inputs.RawInputs` (dataclass): `kpi_df` (`Date`, `kpi`), `investment_df` (`Date`, `Product Group`, `investment`), `trends_df` (`Date`, `Generic Searches`), `performance_df` (cru, coluna de data renomeada `Date`), `checks: list[Check]`.
  - `engine.inputs.read_inputs(config: dict, paths: dict[str, Path | None]) -> RawInputs`: `config` no formato legado (`column_mapping`, `date_formats`, `performance_kpi_column`). Lança `EngineError(msg, check_id)` quando não dá para continuar lendo (`file_unreadable`, `column_missing`, `date_unparseable`); `value_not_numeric` e `no_valid_rows` entram em `checks` como `error` e o `load_and_prepare_data` os levanta.
  - `tests/engine/csv_factory.py`: `write_inputs(tmp_path, investment: list[tuple], kpi: list[tuple], *, trends=None, sep=",", inv_header=("dates","product_group","total_revenue"), kpi_header=("date","Sessions"), extra_kpi_cols=None) -> dict[str, Path | None]` e `legacy_config() -> dict` (o `dataset_config()` de `synthetic_data.py`, importado).

- [ ] **Step 1: Write the failing tests** em `tests/engine/test_inputs.py`:
  - `test_read_inputs_clean_returns_normalized_tables`: 10 dias × 2 canais → `kpi_df.columns == ["Date","kpi"]`, `investment_df` com `Product Group`, `checks == []`.
  - `test_missing_file_is_file_unreadable`: arquivo vazio → `EngineError` com `check_id == "file_unreadable"`.
  - `test_missing_column_is_column_missing`: `column_mapping.investment_file.investment_col = "inexistente"` → `check_id == "column_missing"`.
  - `test_unparseable_dates`: datas `"abc"` → `check_id == "date_unparseable"`.
  - `test_mostly_non_numeric_kpi_is_value_not_numeric`: 60% do KPI = `"x"` → `read_inputs` devolve um check `value_not_numeric` com `level == "error"` (não levanta).
  - `test_engine_error_keeps_check_id`: `EngineError("m", "c").check_id == "c"`; `EngineError("m").check_id is None`.
- [ ] **Step 2: Run** `uv run pytest tests/engine/test_inputs.py -q`. Expected: FAIL (módulo inexistente).
- [ ] **Step 3: Implement** `EngineError.__init__(message, check_id=None)`; `read_inputs` movendo o trecho de leitura/resolução/parse/limpeza (linhas ~766–910 do `load_and_prepare_data`) para `engine/inputs.py`, trocando cada `raise ValueError` pelo `EngineError`/`Check` com o id certo; mensagens pt-BR atuais preservadas. `FileNotFoundError` e leitura vazia → `file_unreadable`. Sem checks novos nesta task. Use os mesmos helpers (`read_csv_robust`, `resolve_column`, `robust_*`, `parse_investment_columns`, `drop_bi_export_footer_rows`), importados de `engine.data_preprocessor`; evite import circular movendo para `engine/inputs.py` só o fluxo, não os helpers.
- [ ] **Step 4: Rewire** `load_and_prepare_data`: chama `read_inputs`, levanta `EngineError(check.message, check.id)` para o primeiro `error` em `checks`, depois segue com a seção "Aggregate Performance File Rows…" em diante (ainda soma duplicatas: muda na Task 2). Remove a conversão genérica `ValueError → EngineError` apenas dos trechos movidos.
- [ ] **Step 5: Run** `mise run test`. Expected: tudo verde, incluindo `tests/engine/test_parity.py` e `tests/engine/test_data_preprocessor.py` sem alteração de expectativas (se algum teste antigo checa texto de mensagem, a mensagem não pode mudar).
- [ ] **Step 6: Commit** `refactor(engine): read_inputs extracted from load_and_prepare_data (a2)`.

---

### Task 2: checks de duplicata e fonte única (e o fim da média/soma silenciosa)

**Files:**
- Modify: `engine/inputs.py`, `engine/data_preprocessor.py` (remove o `groupby().sum()` do KPI)
- Test: `tests/engine/test_inputs.py` (acrescenta), `tests/engine/test_data_preprocessor.py` (ajusta o que dependia da soma)

**Interfaces:**
- Consumes: `read_inputs`, `Check`, `csv_factory.write_inputs`.
- Produces: `read_inputs` passa a acrescentar em `checks`:
  - `duplicate_date_channel` (error): `details = {"count": int, "examples": [{"date": "YYYY-MM-DD", "channel": str}, ...≤5]}`.
  - `kpi_duplicate_dates` (error): `details = {"count": int, "dates": [≤10 datas ISO]}`.
  - `kpi_not_single_source` (error): `details = {"columns": [nomes das colunas que variam], "dates": [≤5]}`.
  - Regra: depois de normalizar, se o KPI tem data repetida **e** alguma coluna não numérica de `performance_df` (fora data e KPI) assume ≥2 valores distintos dentro de uma mesma data → só `kpi_not_single_source`; se há data repetida sem tal coluna → só `kpi_duplicate_dates`.

- [ ] **Step 1: Write the failing tests** (CSV mínimo via `write_inputs`):
  - `test_duplicate_date_channel_flags_error`: duas linhas (2024-01-02, SEARCH) → check com `level == "error"`, `details["count"] == 1`.
  - `test_kpi_duplicate_dates_without_channel_column`: KPI com a mesma data duas vezes e sem coluna extra → só `kpi_duplicate_dates`.
  - `test_kpi_not_single_source_with_channel_column`: KPI `Data;Canal;Leads` com a mesma data para `A` e `B` (`extra_kpi_cols={"Canal": [...]}`) → só `kpi_not_single_source`, `details["columns"] == ["Canal"]`, **sem** `kpi_duplicate_dates`.
  - `test_single_kpi_with_numeric_extra_column_is_ok`: KPI com data única e uma segunda coluna numérica → sem checks.
  - `test_semicolon_decimal_comma_performance_is_ok` (VW `_br`): `sep=";"`, valores `"1.234,56"` → sem checks.
  - `test_load_and_prepare_data_raises_with_check_id`: investimento duplicado → `EngineError.check_id == "duplicate_date_channel"`; KPI duplicado → `"kpi_duplicate_dates"`; `Canal` → `"kpi_not_single_source"`.
- [ ] **Step 2: Run** os testes novos. Expected: FAIL.
- [ ] **Step 3: Implement** os três checks em `read_inputs` (antes do `dropna` final que remove linhas, mas depois do parse de data, para o `date` ser comparável). Remover o `groupby().sum()` do KPI em `load_and_prepare_data`. Mensagens pt-BR (ex.: "O arquivo de performance tem conversões reportadas por canal. Envie o total por data."; "Há N linhas repetidas para a mesma data e canal no arquivo de investimento. Remova ou consolide as duplicatas.").
- [ ] **Step 4: Run** `mise run test`. Testes antigos que esperavam média/soma devem ser reescritos para esperar o erro (ledger: ruling por teste alterado). `mise run parity-real` (se `exemplo_csv/` existir): Gol idêntico; se Gol tiver duplicata real, registre como achado em vez de enfraquecer o check.
- [ ] **Step 5: Commit** `feat(engine): duplicate and single-source checks replace silent mean and sum (a2)`.

---

### Task 3: `validate` e os checks sobre a série

**Files:**
- Create: `engine/validation.py`
- Modify: `engine/__init__.py` (exporta `validate`, `ValidationReport`)
- Test: `tests/engine/test_validate_checks.py`

**Interfaces:**
- Consumes: `read_inputs`, `detect_cadence`, `drop_partial_periods`, `treat_outliers`'s regra IQR (extrair `iqr_bounds(series) -> tuple[float, float]` em `data_preprocessor.py` e fazer `treat_outliers` usá-la; comportamento idêntico).
- Produces: `validate(inputs: dict[str, Path | None], config: dict | EngineConfig) -> ValidationReport` (pydantic de `engine.results_schema`). Funções puras, cada uma `RawInputs/tabelas -> list[Check]`:
  - `check_cadence(raw) -> tuple[list[Check], int | None]`: `cadence_mismatch` (error) se `abs(inv - kpi) > 2`; devolve `period_days`.
  - `check_partial_and_sufficiency(raw, period_days)`: `partial_period_dropped` (info, `details={"investment": n, "performance": n}`) e `insufficient_after_partial` (error).
  - `check_missing_dates(raw, period_days)`: `missing_dates` (warning, `details={"count": int, "dates": [≤50 ISO]}`) comparando as datas do KPI com a grade `period_days` entre mínimo e máximo.
  - `check_outliers(raw)`: `outliers` (info, `details={"count": int, "dates": [≤50]}`) nos pontos do KPI fora de `iqr_bounds`.
  - `check_channel_overlap(raw)`: `dv360_cm360_overlap` (warning, `details={"channels": [a, b], "correlation": float, "sum_ratio": float}`) para cada par de canais com correlação diária > 0.95 **e** razão `sum(a)/sum(b)` em [0.9, 1.1]; canais com variância zero ou soma zero são ignorados (sem NaN).
- Relatório: `cadence` ∈ {"diária","semanal","mensal"} (1/7/30, senão `f"{n} dias"`), `period_days`, `date_range=[min, max]` ISO do investimento, `channels` ordenados, `collinearity=Collinearity()`; `ok = not any(c.level == "error")`. Erros que impedem ler (`EngineError` de `read_inputs`) viram um relatório `ok=False` com esse único check e demais campos vazios/`None` — `validate` nunca levanta por problema de dado.

- [ ] **Step 1: Write the failing tests** (um por check, CSV mínimo; `legacy_config()` do factory):
  - `test_clean_dataset_is_ok_without_checks` usando `make_dataset(n_days=364)` → `ok`, `checks == []` exceto o que o dado sintético legitimamente gerar (se gerar `outliers` info, assertar que nenhum é `error`/`warning`), `cadence == "diária"`, `channels == sorted(CHANNELS)`.
  - `test_cadence_mismatch`: investimento diário × KPI semanal → `cadence_mismatch`, `ok is False`.
  - `test_partial_period_dropped_is_info_with_counts`.
  - `test_insufficient_after_partial`.
  - `test_missing_dates_lists_dates`: remover 3 dias do KPI → warning com `details["count"] == 3`; semanal: remover 1 semana → `count == 1`.
  - `test_outliers_reports_count_and_dates`: um pico de 1e6 → info, `count >= 1`, a data do pico em `dates`.
  - `test_dv360_cm360_overlap_by_series_not_name`: canais `"A"` e `"B"` quase iguais (B = A × 1.02 + ruído pequeno) → warning; trocar os nomes para `"DV360"`/`"X"` não muda; `B = A × 3` (correlação alta, razão fora de 0.9–1.1) → sem warning; canal constante → sem warning e sem exceção.
  - `test_validate_returns_error_report_instead_of_raising`: arquivo vazio → `ok False`, check `file_unreadable`.
  - `test_validate_agrees_with_load_and_prepare_data`: parametrizado com os CSV dos testes das Tasks 1–2 e cadência/parcial: `ok False` ⇔ `load_and_prepare_data` levanta, com o mesmo `check_id` do primeiro erro.
  - `test_validate_under_10s_730_days_15_channels`: sintético 730 × 15, `time.perf_counter() < 10`.
- [ ] **Step 2: Run** `uv run pytest tests/engine/test_validate_checks.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** `engine/validation.py` e a extração `iqr_bounds`. Em `load_and_prepare_data`, os `raise ValueError` de cadência e de "sem linhas após parciais" viram `EngineError(msg, "cadence_mismatch" | "insufficient_after_partial")`, com a mesma mensagem usada pelo check (uma única constante de texto por id, em `inputs.py` ou `validation.py`, importada pelos dois).
- [ ] **Step 4: Run** `mise run test`. Expected: verde. `ruff` limpo: `uv run ruff check engine tests && uv run ruff format --check engine tests`.
- [ ] **Step 5: Commit** `feat(engine): validate with cadence, missing dates, outliers and channel overlap checks (a2)`.

---

### Task 4: `run` valida antes e grava `validation` no `results.json`

**Files:**
- Modify: `engine/pipeline.py` (`run`, `compute`), `engine/results.py` (`build_results`), `tests/fixtures/results/generate_fixtures.py` (+ fixtures regenerados)
- Test: `tests/engine/test_results_run.py`, `tests/engine/test_run.py`, `tests/engine/test_results_fixtures.py`

**Interfaces:**
- Consumes: `validate`.
- Produces:
  - `run()` chama `validate` logo após resolver o LLM e antes de `compute`; se `ok` for falso → `EngineError(primeiro erro.message, primeiro erro.id)` sem escrever `results.json` de sucesso; logs do relatório via `log` (warnings/infos em pt-BR).
  - `Computed` ganha `validation: ValidationReport | None = None`; `compute()` aceita `validation=` opcional e o repassa; `build_results` preenche `ResultsV1.validation`.
  - `run()` devolve o documento com `validation` não nulo.

- [ ] **Step 1: Write the failing tests:**
  - `test_run_results_contains_validation_report`: `run` no sintético (364 dias) → `doc["validation"]["ok"] is True`, `doc["validation"]["channels"]` = canais sintéticos, e `ResultsV1.model_validate(doc)` passa.
  - `test_run_aborts_on_validation_error_with_check_id`: investimento duplicado → `EngineError` com `check_id == "duplicate_date_channel"`; `out_dir` sem `results.json`.
  - `test_run_keeps_warnings_in_results`: KPI com buracos → `validation.checks` contém `missing_dates` e o `status` do run não é `failed` por causa disso.
  - Fixtures: `test_results_fixtures` passa a exigir `validation` nos três JSON versionados.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** as mudanças acima. Regenerar fixtures: `PYTHONPATH=. uv run python tests/fixtures/results/generate_fixtures.py` (ver `tests/fixtures/results/README.md` para o fluxo com `.private/`); `falha.json` mantém `status failed` com `validation` preenchido. Atualizar o README dos fixtures se o passo mudar.
- [ ] **Step 4: Run** `mise run test` e `mise run parity-real` (se `exemplo_csv/` existir). Expected: verde; paridade idêntica a 1e-9.
- [ ] **Step 5: Commit** `feat(engine): run validates first and writes the report to results.json (a2)`.

---

### Task 5: dados reais, desempenho e documentação

**Files:**
- Modify: `docs/decisoes/engine.md`, `docs/m2/trilha-a-motor.md` (Status do A2), `CLAUDE.md` (parágrafo "Estado atual" e mapa `engine/`), `docs/decisoes/upload-e-storage.md` (nota do swap do `validate`)
- Create: `tests/engine/test_validate_real.py` (pula sem `exemplo_csv/`)

- [ ] **Step 1: Write** `test_validate_real.py`: roda `validate` em cada pasta de `exemplo_csv/` com o mapeamento do layout (reaproveitar `tests/engine/real_data.py` para Gol) e assere: Gol `ok is True`; PMAX/Tcross (performance por canal) `ok is False` com `kpi_not_single_source`. Pastas VW: não assertar `ok`; imprimir (via `-s`, sem `print()` no código do projeto — use `capsys`/`log`) os ids obtidos e registrá-los na seção de resultados do spec.
- [ ] **Step 2: Run** `uv run pytest tests/engine/test_validate_real.py -q`. Expected: PASS ou SKIP; registrar os ids reais de VW no spec (seção "Resultado nos dados reais").
- [ ] **Step 3: Docs:**
  - `engine.md`: seção "validate (A2)" com catálogo, a regra do `kpi_not_single_source`, o efeito no `run` (duplicatas viram erro) e os passos do swap do Dev B (`from engine import validate`; a tela do B2 deve tratar os novos ids; `column_mapping` chega ao `validate` já no formato legado via `EngineConfig`).
  - `trilha-a-motor.md` A2: `Status: concluído em 04/nov/2026` + o que foi verificado; `CLAUDE.md`: estado atual (A2 concluído; seções restantes A3–A10) e linha `validation.py`/`inputs.py` no mapa.
- [ ] **Step 4: Run** `mise run test` e `uv run ruff check . && uv run ruff format --check .`. Expected: verde.
- [ ] **Step 5: Commit** `docs: mark a2 done and record validate decisions`.
