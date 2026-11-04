# A0 — Pacote `engine` e módulo `llm/` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Criar o pacote `engine/` (pipeline único chamável como biblioteca, `EngineConfig`, CLI) e o módulo plugável `llm/` (só Gemini), movendo o motor do protótipo sem alterar nenhum número.

**Architecture:** Primeiro o snapshot de paridade é gerado com o código antigo (congelado). Depois o código é copiado para `engine/`, o acesso ao LLM passa por `llm/`, e `pipeline.py` divide o fluxo do `local_main` em estágios que devolvem dados em memória, com escritores legados (PNG/CSV/MD/HTML) chamados depois. A Fase 2 centraliza defaults e erros mantendo o snapshot verde.

**Tech Stack:** Python 3.13, `uv`, pandas/numpy/scipy/statsmodels/scikit-learn/holidays/matplotlib (versões fixadas), pydantic v2, `google-genai`, pytest, ruff.

**Spec:** `docs/superpowers/specs/2026-11-04-a0-pacote-engine-design.md` (contexto e conceitos: `docs/onboarding-trilha-a.md`). Código de origem, **somente leitura**: `/home/rodrigo/Sistemas/Dash/opportunity-engine/scripts/` (HEAD `6146b7f`); testes de origem em `.../opportunity-engine/tests/`.

## Global Constraints

- Contrato: `run(inputs: dict[str, Path | None], config: dict | EngineConfig, out_dir: Path, on_log: Callable[[str, str], None]) -> dict`; `inputs` com as chaves `investment_file`, `performance_file`, `generic_trends_file`; `on_log(level, message)` com `level ∈ {"info","warning","error"}` e mensagem em pt-BR; `status ∈ {"succeeded","inconclusive","failed"}`; o dict devolvido tem `schema_version=1`, `engine_version`, `status` e as demais seções `null`; nunca `NaN`/`Infinity`.
- Versões fixadas com `==`: numpy 2.5.0, pandas 3.0.3, scipy 1.18.0, statsmodels 0.14.6, scikit-learn 1.9.0, holidays 0.99, matplotlib 3.11.0.
- Paridade: `numpy.testing.assert_allclose(rtol=1e-9)` contra `tests/fixtures/parity/snapshot.json`, com `LLM_PROVIDER=none`. Se oscilar, medir e documentar a menor tolerância estável (não afrouxar sem registrar).
- O repo do protótipo **nunca** é modificado.
- Sem `print()`; `log = logging.getLogger(__name__)`; nunca hardcode de nome de coluna; `ruff format` (linha 120) e `ruff check` verdes em `engine/`, `llm/`, `tests/engine/`, `tests/llm/`.
- `grep -rn "os.getcwd\|sys.exit\|os._exit\|sys.path" engine/ llm/` vazio; o motor só escreve dentro de `out_dir` e nunca muta a config recebida.
- `llm/` não importa `engine/` nem `api/`. Provedor/modelo por ambiente: `LLM_PROVIDER` (default `gemini`; `none` desliga), `LLM_MODEL` (default `gemini-flash-latest`); chave `GEMINI_API_KEY`. Temperatura/esforço/seed ficam **dentro** do adaptador, nunca na interface.
- Hospedagem: servidor próprio x86-64. Não alterar `api/`, `Dockerfile` nem `docs/m2/` (swap é passo combinado com o Dev B).
- Commits: conventional, minúsculos, em inglês (`feat(engine): …`), terminando com a linha `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Textos para o usuário (mensagens de `on_log`, `EngineError`, checks) em pt-BR; identificadores em inglês.

## Review Focus

Entradas que o spec implica mas que nenhum aceite cobre; cada uma tem teste na tarefa dona:

1. **Cadência semanal** (`period_days=7`): o run completo termina sem erro. → Task 11.
2. **Sem arquivo de trends** (`generic_trends_file=None`): o run completo termina. → Task 9.
3. **Nenhum evento detectado** (investimento plano): `succeeded`, MMM roda, lista de eventos vazia, sem exceção. → Task 9.
4. **Config com chave desconhecida** (ex.: `require_significance`, nome provisório que a API salva hoje): `EngineError` em pt-BR citando o campo, e não traceback de pydantic. → Task 7.
5. **Um relatório LLM falha com `LLMError` comum**: só aquele relatório cai no texto determinístico; os demais continuam. → Task 11.

---

### Task 1: Dependências fixadas e esqueleto dos pacotes

**Files:**
- Modify: `pyproject.toml`, `uv.lock`
- Create: `engine/__init__.py` (vazio por ora), `llm/__init__.py` (vazio por ora)
- Create: `tests/engine/test_deps.py`

**Interfaces:**
- Produces: pacotes `engine` e `llm` importáveis; as sete bibliotecas nas versões fixadas.

- [ ] **Step 1: Write the failing test** `tests/engine/test_deps.py::test_numeric_libs_are_pinned` — importa as sete bibliotecas e afirma `numpy.__version__ == "2.5.0"`, `pandas.__version__ == "3.0.3"`, `scipy.__version__ == "1.18.0"`, `statsmodels.__version__ == "0.14.6"`, `sklearn.__version__ == "1.9.0"`, `holidays.__version__ == "0.99"`, `matplotlib.__version__ == "3.11.0"`. Mais `test_packages_import`: `import engine, llm`.
- [ ] **Step 2: Run** `uv run pytest tests/engine/test_deps.py -v` → FAIL (`ModuleNotFoundError`).
- [ ] **Step 3: Implement** `uv add "numpy==2.5.0" "pandas==3.0.3" "scipy==1.18.0" "statsmodels==0.14.6" "scikit-learn==1.9.0" "holidays==0.99" "matplotlib==3.11.0"`; criar os dois `__init__.py` vazios. Conferir `uv sync --frozen` e que `uv.lock` foi commitado.
- [ ] **Step 4: Run** `uv run pytest tests/engine/test_deps.py -v` → PASS.
- [ ] **Step 5: Commit** `feat(engine): pin numeric deps and add engine and llm package skeletons`.

---

### Task 2: Dataset sintético e snapshot de paridade do código antigo

**Files:**
- Create: `tests/engine/synthetic_data.py`
- Create: `tests/fixtures/parity/generate_legacy_snapshot.py`, `tests/fixtures/parity/snapshot.json`, `tests/fixtures/parity/README.md`
- Test: `tests/engine/test_synthetic_data.py`

**Interfaces:**
- Produces (consumido pelas Tasks 8, 9, 11, 12):
  - `make_dataset(out_dir: Path, *, seed: int = 7, cadence_days: int = 1, with_trends: bool = True, flat_spend: bool = False) -> dict[str, Path | None]` — grava `investment.csv` (colunas `dates,product_group,total_revenue`), `performance.csv` (`date,Sessions`), `trends.csv` (`Day,Ad Opportunities`) e devolve `{"investment_file","performance_file","generic_trends_file"}`.
  - `dataset_config() -> dict` — config no formato **do protótipo** com `column_mapping`, `investment_limit_factor: 1.5`, `optimization_target: "CONVERSIONS"`, `post_event_days: 14`, `max_events_to_analyze: 5`, `min_pre_period_days: 14`, `p_value_threshold: 0.1`, `r_squared_threshold: 0.3`, `increase_threshold_percent: 50`, `decrease_threshold_percent: 30`, `require_*: True`, `kpi_is_monetary: False`, `treat_outliers: False`, `advertiser_name: "synthetic"`, `financial_targets` com as quatro metas definidas. Usa os nomes de coluna acima.

- [ ] **Step 1: Write the failing tests** em `test_synthetic_data.py`: `test_dataset_is_deterministic` (duas chamadas com mesmo seed → bytes idênticos dos três arquivos); `test_dataset_has_detectable_events` (730 dias, ≥ 5 canais; calcular em pandas, por canal e por semana `W-MON`, a razão contra a média móvel de 12 semanas anteriores e afirmar que ≥ 2 semanas passam de 1,5 ou ficam abaixo de 0,7); `test_flat_spend_has_no_events` (mesma conta com `flat_spend=True` → nenhuma semana fora dos limiares); `test_weekly_cadence` (`cadence_days=7` → datas espaçadas em 7 dias nos três arquivos).
- [ ] **Step 2: Run** `uv run pytest tests/engine/test_synthetic_data.py -v` → FAIL.
- [ ] **Step 3: Implement `make_dataset` e `dataset_config`**: KPI = nível + sazonalidade semanal + efeito de saturação dos gastos + ruído, tudo de `numpy.random.default_rng(seed)`; dois degraus de investimento em canais diferentes e semanas diferentes.
- [ ] **Step 4: Run** os testes → PASS.
- [ ] **Step 5: Implement `generate_legacy_snapshot.py`** (script de ferramenta, não de produção): `python generate_legacy_snapshot.py --legacy-repo PATH --out snapshot.json`. Gera o dataset em diretório temporário com `make_dataset`, adiciona `PATH/scripts` ao `sys.path` (permitido: é ferramenta), monta o config do protótipo (`dataset_config()` + caminhos dos arquivos + `output_directory` temporário) e chama diretamente `data_preprocessor.load_and_prepare_data`, `analysis.find_events`, `analysis.run_opportunity_projection`, `analysis.run_causal_impact_analysis` (um por candidato, replicando o loop de `local_main.py:139-200`), a fórmula dos três gates de `local_main.py:229-250`, `elasticity_analysis.run_mmm_engine`, `generate_aggregated_response_curve`. Grava JSON com: `versions` (numpy/pandas/scipy/statsmodels/sklearn), `period_days`, `events` (por candidato: `event_id`, `product_group`, `intervention_date`, `results_data` completo, `passed`, `reasons`), `mmm` (`contribution_pct`, `r_squared`, `cv_r_squared`, `optimal_params`, `marketing_contribution_of_kpi_pct`), `response_curve` (colunas → listas) e os seis pontos notáveis. Rodar sem gerar arquivos de saída permanentes.
- [ ] **Step 6: Gerar o snapshot** com o ambiente do repo antigo: `cd /home/rodrigo/Sistemas/Dash/opportunity-engine && uv run python <caminho>/generate_legacy_snapshot.py --legacy-repo . --out <caminho>/snapshot.json`. Rodar **duas vezes** e `diff` dos dois JSON: devem ser idênticos (se não, registrar a oscilação no `README.md` e parar para decidir tolerância). Conferir que as `versions` do snapshot batem com as da Task 1.
- [ ] **Step 7: Escrever `tests/fixtures/parity/README.md`** (como regenerar, que o repo antigo é congelado, as versões, a regra de nunca regenerar sem aprovação).
- [ ] **Step 8: Commit** `test(engine): add synthetic dataset and legacy parity snapshot`.

---

### Task 3: Módulo `llm/` (interface, erros, fábrica, adaptador Gemini)

**Files:**
- Create: `llm/base.py`, `llm/gemini.py`; Modify: `llm/__init__.py`, `.env.example`
- Create: `tests/fakes/llm.py`, `tests/llm/test_contract.py`, `tests/llm/test_gemini.py`, `tests/llm/test_factory.py`

**Interfaces:**
- Produces (consumido pelas Tasks 6, 11):
  - `llm.base`: `class LLM(Protocol)` com `provider: str`, `model: str`, `generate_text(self, prompt: str, *, timeout_s: float | None = None) -> str`, `generate_json(self, prompt: str, schema: dict, *, timeout_s: float | None = None) -> Any`; `class LLMError(Exception)`; `class LLMUnavailable(LLMError)` com `__init__(self, reason: str)` e atributo `reason` (`str(e) == reason`); `class LLMRefused(LLMError)`; `class LLMBadOutput(LLMError)`.
  - `llm.__init__`: reexporta tudo acima; `PROVIDERS: dict[str, type]` (`{"gemini": GeminiLLM}`); `get_llm(provider: str | None = None, model: str | None = None) -> LLM | None` — `provider` default `os.environ.get("LLM_PROVIDER", "gemini")`; `"none"` → `None`; provedor fora de `PROVIDERS` → `ValueError`; sem `GEMINI_API_KEY` → `None`; `model` default `os.environ.get("LLM_MODEL", "gemini-flash-latest")`.
  - `llm.gemini.GeminiLLM(model: str, api_key: str)` e função de módulo `_client(api_key: str, timeout_s: float | None)` (ponto de substituição nos testes) que importa `google.genai` dentro da função.
  - `tests/fakes/llm.py`: `class FakeLLM` com `provider = "fake"`, `model = "fake"`, `__init__(self, replies: list[str | Exception])` (consumidas em ordem; `Exception` é levantada), `calls: list[str]` (prompts recebidos), `timeouts: list[float | None]` (um por chamada), e os dois métodos da interface (`generate_json` faz `json.loads` do texto, `LLMBadOutput` se inválido).
  - `tests/llm/test_contract.py`: `run_provider_contract(make_llm_with_replies)` — função reutilizável que valida: texto devolvido, JSON válido devolvido já parseado, JSON inválido → `LLMBadOutput`, falha transitória → `LLMUnavailable`.

- [ ] **Step 1: Write the failing tests.** `test_factory.py`: `test_none_provider_returns_none`; `test_missing_key_returns_none` (monkeypatch `delenv("GEMINI_API_KEY")`); `test_unknown_provider_raises_value_error`; `test_default_model_and_provider_from_env` (setenv `LLM_MODEL`, `GEMINI_API_KEY`; `get_llm().model == valor`, `.provider == "gemini"`). `test_gemini.py` (substituindo `llm.gemini._client` por um cliente falso, sem rede): `test_generate_text_returns_text`; `test_generate_json_parses_and_strips_code_fence`; `test_http_429_and_503_map_to_unavailable` (parametrizado: 429, 500, 503, 504 → `LLMUnavailable` com `reason` não vazio); `test_400_maps_to_llm_error_not_unavailable`; `test_timeout_maps_to_unavailable`; `test_empty_text_is_bad_output`; `test_blocked_prompt_is_refused`; `test_fake_llm_passes_contract` e `test_gemini_passes_contract` usando `run_provider_contract`. Usar `google.genai.errors.APIError` (atributo `code`) para os erros HTTP do cliente falso.
- [ ] **Step 2: Run** `uv run pytest tests/llm -v` → FAIL.
- [ ] **Step 3: Implement** `llm/base.py`, `llm/gemini.py`, `llm/__init__.py` e `FakeLLM`. `generate_text`: `client.models.generate_content(model=..., contents=prompt)`; `generate_json`: o mesmo com `response_mime_type="application/json"` e `response_json_schema=schema` (como `api/gemini.py:25-31`), `json.loads` após remover *code fence*. Sem `temperature` explícito. Timeout via `HttpOptions(timeout=<ms>)`. Mapeamento de erros conforme o spec, seção "Módulo LLM".
- [ ] **Step 4: Atualizar `.env.example`** (comentários, estilo do arquivo): `# LLM_PROVIDER=gemini  (gemini | none)` e `# LLM_MODEL=gemini-flash-latest`.
- [ ] **Step 5: Run** `uv run pytest tests/llm -v` → PASS; `uv run ruff format --check llm tests/llm tests/fakes && uv run ruff check llm tests/llm tests/fakes` limpos.
- [ ] **Step 6: Commit** `feat(llm): add pluggable llm module with gemini adapter`.

---

### Task 4: Copiar os módulos do motor e migrar os testes (comportamento idêntico)

**Files:**
- Create (cópias de `/home/rodrigo/Sistemas/Dash/opportunity-engine/scripts/`): `engine/data_preprocessor.py`, `engine/analysis.py`, `engine/elasticity_analysis.py`, `engine/presentation.py`, `engine/recommendations.py`, `engine/reports.py` (de `gemini_report.py`)
- Create (testes de origem em `.../opportunity-engine/tests/`): `tests/engine/test_analysis.py`, `test_elasticity_analysis.py`, `test_data_preprocessor.py`, `test_presentation.py`

**Interfaces:**
- Produces: módulos importáveis como `engine.analysis` etc.; `engine/reports.py` ainda com o código do Gemini antigo (adaptado na Task 6).

- [ ] **Step 1: Copiar** os seis arquivos com `cp` (sem `saturation_curve.py`, `google_api.py`, `dashboard_charts.py`, `streamlit_app.py`, `db.py`, `local_main*`). Copiar os quatro arquivos de teste.
- [ ] **Step 2: Remover o que o spec manda** em `engine/`: o bloco `if __name__ == "__main__":` de `elasticity_analysis.py` (a partir do `argparse`, linhas ~1170-1196) e o `import argparse`; as funções `generate_elasticity_budget_scenarios` e `generate_historical_split_scenarios` de `recommendations.py` (conferir com `grep` que nada as chama).
- [ ] **Step 3: Trocar imports internos por imports de pacote**: `import data_preprocessor` → `from engine import data_preprocessor` (`elasticity_analysis`); `import analysis` (`presentation`, hoje dentro de `try/except` com `sys.exit`) → `from engine import analysis`, **sem** `try/except`; `from presentation import format_number` → `from engine.presentation import format_number` (`recommendations`, `reports`); `import presentation` → `from engine import presentation`. Nos testes: remover os blocos `sys.path.append(...)` e usar `from engine.<modulo> import …`.
- [ ] **Step 4: Run** `uv run pytest tests/engine -v --ignore=tests/engine/test_deps.py --ignore=tests/engine/test_synthetic_data.py` e levar tudo ao verde **sem mudar comportamento** (só imports/caminhos nos testes). Os testes de `data_preprocessor`/`presentation` que referenciam `Streamlit` ou `logger` ficam de fora e são listados no corpo do commit.
- [ ] **Step 5: Commit** `feat(engine): copy prototype modules and migrate their tests`.

---

### Task 5: Conformidade com ruff (format, autofix e ignores explícitos)

**Files:**
- Modify: `engine/*.py`, `tests/engine/*.py`, `pyproject.toml`

- [ ] **Step 1: Run** `uv run ruff format engine tests/engine` e, em seguida, os testes da Task 4: continuam verdes (só formatação).
- [ ] **Step 2: Run** `uv run ruff check engine tests/engine --fix` (aplica só correções seguras: `I001`, `UP009`, `F401`, `F541`, `RUF019`); conferir com `git diff` que nenhuma importação removida era usada por efeito colateral; testes verdes.
- [ ] **Step 3: Para o que sobrar** (`BLE001`, `G201`, `SIM118`, `C408`, `C414`, `C401`, `RUF046`, `RUF059`, `TRY002` em `engine/`; o equivalente em `tests/engine/`), adicionar em `pyproject.toml` `[tool.ruff.lint.per-file-ignores]` para `"engine/*"` e `"tests/engine/*"`, com o comentário `# legacy prototype style; revisit in the A10 audit pass`. Não reescrever lógica nesta fase.
- [ ] **Step 4: Run** `uv run ruff format --check . && uv run ruff check .` → limpos no repo todo; `uv run pytest tests/engine tests/llm -q` verde.
- [ ] **Step 5: Commit** `style(engine): format and lint the copied prototype modules`.

---

### Task 6: `reports.py` sobre o módulo `llm/`

**Files:**
- Modify: `engine/reports.py`
- Create: `tests/engine/test_reports.py` (a partir de `tests/test_gemini_report.py` do protótipo — só os testes que importam de `gemini_report`; os que importam `streamlit_app` ficam de fora)

**Interfaces:**
- Consumes: Task 3 (`LLM`, `LLMUnavailable`, `LLMError`).
- Produces (consumido pela Task 11): `generate_html_report(llm: LLM, results_data, config, image_paths, output_filename, market_analysis_df, line_chart_df, csv_output_filename=None, correlation_matrix=None)`; `generate_global_report(llm: LLM, config, scenarios=None, total_investment=None, kpi_projections=None, *, global_output_dir: Path)`; os parâmetros `gemini_client` viram `llm`; `is_gemini_outage_error` e `_get_image_as_base64` mantidos só se ainda usados (apagar o primeiro).

- [ ] **Step 1: Write the failing tests** em `test_reports.py`: `test_event_narrative_uses_generate_text_with_60s_timeout` (FakeLLM com resposta JSON válida da narrativa; afirma `calls` com um prompt e `timeout_s=60` registrado — estender `FakeLLM` para guardar `timeouts`); `test_llm_unavailable_propagates_unwrapped` (FakeLLM levanta `LLMUnavailable("timeout")` → `generate_html_report` levanta `LLMUnavailable`, não `RuntimeError`); `test_other_llm_error_is_wrapped_and_writes_nothing` (FakeLLM levanta `LLMBadOutput` → `RuntimeError`, nenhum arquivo criado); `test_global_report_writes_into_given_dir` (usa `global_output_dir=tmp_path`, sem `os.getcwd`); `test_no_llm_raises_value_error` (llm `None`). Reaproveitar do protótipo `test_api_error_raises_and_writes_nothing`.
- [ ] **Step 2: Run** `uv run pytest tests/engine/test_reports.py -v` → FAIL.
- [ ] **Step 3: Implement** em `reports.py`: nos dois pontos (`gemini_report.py` linhas ~214 e ~660 do original) trocar `gemini_client.generate_content(prompt, request_options=GEMINI_REQUEST_OPTIONS)` + `.text` por `llm.generate_text(prompt, timeout_s=60)`; manter a remoção de *code fence* e `json.loads` onde estão; `except LLMUnavailable: raise` antes do `except Exception` que embrulha em `RuntimeError`; `generate_global_report` recebe `global_output_dir` em vez de montar o caminho com `os.getcwd()` e `config["output_directory"]`; apagar `is_gemini_outage_error`, `GEMINI_REQUEST_OPTIONS` e as constantes de texto de outage. Textos de prompt **inalterados**.
- [ ] **Step 4: Run** os testes de `test_reports.py` → PASS; `uv run ruff format engine tests/engine`.
- [ ] **Step 5: Commit** `refactor(engine): route report generation through the llm module`.

---

### Task 7: `EngineConfig`, `to_legacy_dict` e `EngineError`

**Files:**
- Create: `engine/config.py`, `engine/errors.py`
- Test: `tests/engine/test_config.py`

**Interfaces:**
- Produces (consumido pelas Tasks 9, 11, 12, 13):
  - `engine.errors.EngineError(Exception)` — mensagem em pt-BR segura para a tela.
  - `engine.config.FinancialTargets(BaseModel)` com `target_cpa`, `target_icpa`, `target_roas`, `target_iroas`: `float | None = None`, `gt=0`.
  - `engine.config.EngineConfig(BaseModel)` (`extra="forbid"`, `allow_inf_nan=False`) com os campos e defaults do spec (seção "EngineConfig"). Defaults: `optimization_target="CONVERSIONS"` (**desvio do protótipo, cujo default no código é `REVENUE`**: com `REVENUE` o default não validaria sem `average_ticket`; coincide com o default da API) e um validador que exige `average_ticket > 0` quando `optimization_target == "REVENUE"`, `kpi_is_monetary=False`, `average_ticket=None`, `conversion_rate_from_kpi_to_bo=1.0`, `investment_limit_factor=1.5`, `max_budget_step=0.2`, `p_value_threshold=0.05`, `min_pre_period_days=14`, `r_squared_threshold=0.3`, `increase_threshold_percent=50`, `decrease_threshold_percent=30`, `post_event_days=14`, `max_events_to_analyze=5`, `treat_outliers=False`, `require_statistical_significance=True`, `require_logical_direction=True`, `require_model_fit=True`, `country_code="BR"`, `per_channel_investment_limit_factor=3.0`, `max_channel_mix_share=0.4`, `minimum_acceptable_iroi=0`, `min_marketing_contribution=0.05`, `column_mapping: dict = {}`, `date_formats: dict = {}`, `channel_groups=[]`, `controls=[]`, `gate_thresholds={}`, `product_group_filter=None`, `min_intervention_date=None`, `advertiser_name="default_advertiser"`, `client_industry=None`, `client_business_goal=None`, `primary_business_metric_name="KPIs"`. (Conferir o nome e o default de `reallocation_min_cv_r2` e demais chaves lidas com `grep -n 'config.get\|config\[' engine/*.py`.)
  - `EngineConfig.from_input(config: dict | EngineConfig) -> EngineConfig` — valida sem mutar a entrada; `ValidationError` do pydantic vira `EngineError("Configuração inválida: campo 'x' …")` listando os campos.
  - `EngineConfig.to_legacy_dict(self) -> dict` — dict novo com **todas** as chaves que os módulos leem; `financial_targets` só com as metas definidas (**chave ausente = sem meta**: o código lê `.get("target_cpa", float("inf"))`, `"target_roas", 0`, `"target_iroas", minimum_acceptable_iroi`); `performance_kpi_column` derivado de `column_mapping["performance_file"]["kpi_col"]` (default `"Sessions"`); `generic_trends_file_path`/`*_file_path`/`output_directory` **não** entram.

- [ ] **Step 1: Write the failing tests** em `test_config.py`: `test_defaults_match_spec` (a tabela acima); `test_extra_key_is_engine_error_naming_field` (`{"require_significance": True}` → `EngineError` cuja mensagem contém `require_significance`) — Review Focus 4; `test_from_input_does_not_mutate` (deepcopy antes/depois); `test_to_legacy_dict_omits_unset_targets` (sem metas → `"financial_targets" == {}`; com `target_cpa=25` → `{"target_cpa": 25.0}`); `test_to_legacy_dict_derives_kpi_column`; `test_inf_is_rejected` (`average_ticket=float("inf")`); `test_revenue_requires_average_ticket` (`REVENUE` sem ticket → `EngineError` pt-BR citando `average_ticket`); `test_legacy_dict_covers_every_key_the_modules_read` — varre `engine/*.py` com regex por `config.get\("(\w+)"` e `config\["(\w+)"\]`, e afirma que cada chave está em `to_legacy_dict()` ou em `{"period_days"}` (chaves em runtime).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `config.py` e `errors.py`.
- [ ] **Step 4: Run** `uv run pytest tests/engine/test_config.py -v` → PASS (se o teste de cobertura de chaves achar chaves não previstas, acrescentá-las ao modelo, não ao teste).
- [ ] **Step 5: Commit** `feat(engine): add EngineConfig, legacy config adapter and EngineError`.

---

### Task 8: Leitura única dos dados (`PreparedData`)

**Files:**
- Modify: `engine/data_preprocessor.py`, `engine/elasticity_analysis.py`, `engine/analysis.py` (só se necessário), `tests/engine/test_data_preprocessor.py`, `tests/engine/test_elasticity_analysis.py`

**Interfaces:**
- Consumes: Task 7 (`to_legacy_dict`).
- Produces (consumido pelas Tasks 9, 11):
  - `@dataclass class PreparedData` em `engine/data_preprocessor.py`: `kpi_df`, `investment_df`, `trends_df`, `performance_df` (leitura crua do arquivo de performance com a coluna de data renomeada para `Date`, hoje relida em `local_main.py:73-83`), `correlation_matrix`, `period_days: int`.
  - `load_and_prepare_data(config: dict, paths: dict[str, Path | None]) -> PreparedData` — `paths` são os `inputs` do contrato; **não** escreve em `config` (o `config["period_days"] = …` de `data_preprocessor.py:983` vira o campo `period_days`).
  - `run_mmm_engine(config: dict, prepared: PreparedData) -> dict | None` — não recarrega dados.

- [ ] **Step 1: Write the failing tests**: em `test_data_preprocessor.py`, adaptar os testes existentes de `load_and_prepare_data` à nova assinatura e acrescentar `test_load_does_not_mutate_config` (deepcopy antes/depois, e `prepared.period_days == 1` para o dataset diário) e `test_performance_df_is_returned_without_rereading` (monkeypatch de `read_csv_robust` contando chamadas: o arquivo de performance é lido **uma vez**); em `test_elasticity_analysis.py`, adaptar as chamadas de `run_mmm_engine` e acrescentar `test_run_mmm_engine_does_not_read_files` (monkeypatch de `read_csv_robust` levantando erro).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** a nova assinatura: usar `paths[...]` no lugar de `config["performance_file_path"]` etc.; mover para `load_and_prepare_data` a leitura/renomeação da coluna de data do arquivo de performance feita em `local_main`; manter todos os `ValueError` com seus textos. Em `run_mmm_engine`, remover o bloco de carga (`elasticity_analysis.py:293-326`) usando `prepared.kpi_df`, `prepared.investment_df`, `prepared.trends_df`. Onde o resto do módulo lê `config.get("period_days", 1)`, o chamador passa um dict efetivo com `period_days` preenchido (decidido na Task 9).
- [ ] **Step 4: Run** `uv run pytest tests/engine -q` → PASS.
- [ ] **Step 5: Commit** `refactor(engine): load and prepare the inputs once per run`.

---

### Task 9: Estágios do pipeline em memória e teste de paridade

**Files:**
- Create: `engine/pipeline.py` (estágios, sem `run` ainda), `tests/engine/test_parity.py`, `tests/engine/test_pipeline_stages.py`

**Interfaces:**
- Consumes: Tasks 2, 7, 8.
- Produces (consumido pelas Tasks 10, 11): em `engine/pipeline.py`:
  - `@dataclass class EventOutcome`: `event_id: str`, `product_group: str`, `intervention_date: str`, `results_data: dict | None`, `line_df`, `inv_bar_df`, `sessions_bar_df`, `accuracy_df` (DataFrames ou `None`), `passed: bool`, `reasons: list[str]` (`"not_significant"`, `"illogical_direction"`, `"poor_fit"`, `"analysis_failed"`), `selected: bool` (entre os `max_events_to_analyze` melhores aprovados).
  - `@dataclass class Computed`: `prepared: PreparedData`, `effective_config: dict`, `events: list[EventOutcome]`, `mmm: dict | None`, `response_curve_df`, `baseline_point`, `max_efficiency_point`, `strategic_limit_point`, `diminishing_return_point`, `saturation_point`, `strategic_reallocation_point`, `optimized_mix: dict`, `current_split: dict`.
  - `compute(inputs: dict[str, Path | None], config: EngineConfig, *, individual_curves_dir: Path | None = None) -> Computed` — estágios `load_inputs` → `detect_events` → `analyze_events` → `run_elasticity`; `effective_config = {**config.to_legacy_dict(), "period_days": prepared.period_days}`; não escreve arquivos (o parâmetro `individual_curves_dir` existe porque `generate_individual_response_curves` grava; `None` pula essa chamada).
  - Funções de estágio com assinaturas `load_inputs(inputs, config) -> PreparedData`, `detect_events(prepared, cfg: dict) -> pandas.DataFrame`, `analyze_events(prepared, candidates, cfg: dict) -> list[EventOutcome]`, `run_elasticity(prepared, cfg: dict) -> dict` (usam o dict legado).

- [ ] **Step 1: Write the failing test** `tests/engine/test_parity.py::test_compute_matches_legacy_snapshot`: `monkeypatch.setenv("LLM_PROVIDER","none")`; gera o dataset (Task 2) em `tmp_path`; monta `EngineConfig` a partir de `dataset_config()` (convertendo os campos para o modelo novo); `compute(...)`; compara com `snapshot.json`: versões (`numpy`, `pandas`, `scipy`, `statsmodels`, `sklearn`) iguais às do snapshot (mensagem explicando que paridade exige as mesmas versões); eventos (ids, `passed`, `reasons`, todos os campos numéricos de `results_data`), `mmm` e a curva de resposta com `assert_allclose(rtol=1e-9)`. Mais, em `test_pipeline_stages.py`: `test_no_events_flat_spend` (`flat_spend=True`: `events == []`, `mmm` não `None`) — Review Focus 3; `test_without_trends_file` (`generic_trends_file=None`: completa) — Review Focus 2; `test_gates_record_reasons` (config com `p_value_threshold=1e-9`: eventos com `passed=False` e `"not_significant" in reasons`); `test_selected_limited_by_max_events` (`max_events_to_analyze=1` → no máximo um `selected`); `test_input_config_not_mutated`.
- [ ] **Step 2: Run** `uv run pytest tests/engine/test_parity.py tests/engine/test_pipeline_stages.py -v` → FAIL.
- [ ] **Step 3: Implement** `pipeline.py` espelhando o fluxo de `local_main.py:55-197` e `460-514` **sem** escrita de arquivo: filtro `product_group_filter`/`min_intervention_date`; candidatos com `event_id = f"{advertiser}_{canais_com_underscore}_{data}"`, `start_date` = primeira data do KPI, `end_date` = intervenção + `post_event_span` (`analysis.periods_to_days`); pré-treino com `run_opportunity_projection` sobre todos os canais com evento; gates como em `local_main.py:229-250`, registrando `reasons`; ordenar aprovados por |lift|; MMM com `prepared`; curva agregada com `optimized_mix = analysis.find_optimal_historical_mix(...) or {}` e `current_split` pelo investimento total por canal. **Falha de um evento não derruba o run**: `analysis_failed` em `reasons`, log de aviso.
- [ ] **Step 4: Run** os testes → PASS. Se a paridade falhar, **parar e diagnosticar** (qual campo, quanto); não afrouxar a tolerância sem registrar a medição.
- [ ] **Step 5: Commit** `feat(engine): split the pipeline into in-memory stages with parity coverage`.

---

### Task 10: `on_log` e tradução pt-BR

**Files:**
- Create: `engine/logmessages.py`, `tests/engine/test_logmessages.py`

**Interfaces:**
- Produces (consumido pela Task 11): `translate_line(line: str) -> str | None` (cópia fiel de `logger.py:361-370` + a lista `_RULES`, `_banner`, `_divider` de que ela depende; `None` = descartar); `class OnLogHandler(logging.Handler)` com `__init__(self, on_log: Callable[[str, str], None])`; `contextmanager forward_logs(on_log) -> Iterator[None]` que instala o handler na árvore de loggers `engine` e `llm` (nível `INFO`) e o remove no `finally`. Mapeamento: `WARNING → "warning"`, `ERROR`/`CRITICAL → "error"`, `INFO → "info"`; `DEBUG` não é encaminhado; mensagem passa por `translate_line` e é descartada se `None`.

- [ ] **Step 1: Write the failing tests**: migrar de `test_logger.py` do protótipo os testes de `translate_line` (`test_translate_line_individual_curve_plot`, `_suppressed_patterns`, `_gemini_global_reports`, `_additional_patterns`) adaptados a `engine.logmessages`; `test_handler_maps_levels` (logger `engine.x` emite info/warning/error/critical/debug → `on_log` recebe `("info"|"warning"|"error"|"error", …)` e nada para debug); `test_noise_lines_are_dropped`; `test_handler_removed_after_context` (após o `with`, novas mensagens não chegam; `logging.getLogger("engine").handlers` volta ao estado anterior); `test_nothing_written_to_stdout` (capfd).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `logmessages.py`: copiar apenas as regras e `translate_line`; **não** trazer `setup_logging`, `LogContext`, `_StreamToLogger` (infra do Streamlit).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(engine): forward engine logs to on_log with pt-BR translation`.

---

### Task 11: Escritores legados, relatórios e `run`

**Files:**
- Modify: `engine/pipeline.py`, `engine/__init__.py`
- Test: `tests/engine/test_run.py`

**Interfaces:**
- Consumes: Tasks 3, 6, 7, 9, 10.
- Produces (consumido pela Task 12): `engine.run(inputs, config, out_dir, on_log) -> dict` (contrato exato); `engine/__init__.py` exporta `run`, `EngineConfig`, `EngineError`. Em `pipeline.py`: `write_legacy_outputs(computed: Computed, out_dir: Path) -> dict` (gera PNG/CSV/MD sob `out_dir/<canais>/<data>/` por evento selecionado e `out_dir/global_saturation_analysis/`; devolve `{"event_dirs": {event_id: Path}, "global_dir": Path}`) e `generate_reports(computed, written, out_dir, llm: LLM | None) -> None`.

- [ ] **Step 1: Write the failing tests** em `test_run.py` (dataset sintético, `LLM_PROVIDER=none` salvo indicação):
  - `test_run_returns_contract_dict`: `status == "succeeded"`, `schema_version == 1`, `engine_version` string não vazia, `validation is None` e as demais seções `None`.
  - `test_writes_only_inside_out_dir`: lista de arquivos antes/depois em `tmp_path`; nada fora de `out_dir`; `out_dir` criado se não existir; existem `global_saturation_analysis/response_curve_data.csv` e ao menos um diretório de evento selecionado.
  - `test_input_config_and_cwd_untouched`: dict de config igual antes/depois; `os.getcwd()` igual.
  - `test_on_log_receives_portuguese_levels`: chamadas só com níveis válidos, ao menos uma mensagem `info`, nada em stdout/stderr (capfd).
  - `test_without_llm_writes_deterministic_recommendations`: existe o arquivo gerado por `recommendations.generate_basic_recommendations_file` por evento.
  - `test_llm_unavailable_stops_further_calls`: `FakeLLM(["…", LLMUnavailable("timeout")])`, injetado com `monkeypatch.setattr("engine.pipeline.get_llm", lambda *a, **k: fake)`; após a indisponibilidade, `len(fake.calls)` não cresce e o run termina `succeeded` com fallback determinístico.
  - `test_other_llm_error_only_fails_that_report` (Review Focus 5): `FakeLLM([LLMBadOutput(...), <JSON válido>, ...])` com ≥ 2 eventos selecionados; o primeiro relatório cai no fallback e o seguinte é gerado.
  - `test_weekly_cadence_run_completes` (Review Focus 1): `make_dataset(cadence_days=7)` → `succeeded`.
  - `test_failed_when_mmm_fails_and_no_event_passes`: dataset degenerado (KPI constante) → `status == "failed"`, sem exceção.
  - `test_warning_filters_restored`: `warnings.filters` igual antes/depois do `run`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `run`: `EngineConfig.from_input`; `out_dir.mkdir(parents=True, exist_ok=True)`; `with forward_logs(on_log), warnings.catch_warnings():` com `simplefilter("ignore")`; `compute(..., individual_curves_dir=<global_dir>)`; `write_legacy_outputs`; `llm = get_llm()` (importado em `pipeline` para o monkeypatch); `generate_reports` captura `LLMUnavailable` (marca indisponível e pula o resto, com `on_log` de aviso em pt-BR) e `LLMError` genérico por relatório; `recommendations.generate_basic_recommendations_file` como fallback por evento; relatório global só com LLM disponível; retorno mínimo com `engine_version` = git sha via `git rev-parse --short HEAD` se `.git` existir, senão `importlib.metadata.version("opportunity-engine-v2")`. `status`: `"failed"` só se `computed.mmm is None` e nenhum evento passou. Escritores: portar o miolo de `local_main.py:306-449` e `522-648` chamando `presentation.save_*`, `create_presentation_dataframe`, `create_comparative_saturation_md`, `save_opportunity_curve_plot` com `out_dir` como raiz.
- [ ] **Step 4: Run** `uv run pytest tests/engine -q` → PASS.
- [ ] **Step 5: Commit** `feat(engine): add run() with legacy writers, llm reports and on_log`.

---

### Task 12: CLI `python -m engine`

**Files:**
- Create: `engine/__main__.py`, `tests/engine/test_cli.py`

**Interfaces:**
- Consumes: Task 11. Produces: `python -m engine --config run.json --out DIR` (`run.json` = campos do `EngineConfig` + chave `"inputs"` com os três caminhos); stderr no formato `[nível] mensagem`; saída 0 em `succeeded`/`inconclusive`, 1 em `failed` ou `EngineError`, 2 para argumento/arquivo de config inválido.

- [ ] **Step 1: Write the failing tests** (`subprocess.run([sys.executable, "-m", "engine", ...], env com LLM_PROVIDER=none, timeout)`): `test_cli_runs_and_exits_zero` (dataset sintético; saída 0; arquivos em `--out`; **o processo termina sozinho**, sem `os._exit`); `test_cli_failed_run_exits_one` (KPI constante); `test_cli_bad_config_exits_two_with_message` (chave desconhecida → mensagem pt-BR no stderr, saída 1 ou 2 conforme a regra acima).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `__main__.py` com `argparse`; sem `sys.exit` fora de `if __name__ == "__main__": raise SystemExit(main())` (o `grep` de aceite procura `sys.exit`, não `SystemExit`).
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `feat(engine): add python -m engine command line`.

---

### Task 13: Fase 2 — defaults únicos e limpeza

**Files:**
- Modify: `engine/analysis.py`, `engine/elasticity_analysis.py`, `engine/data_preprocessor.py`, `engine/presentation.py`, `engine/reports.py`, `engine/pipeline.py`, `engine/errors.py`
- Test: `tests/engine/test_defaults.py`, `tests/engine/test_hygiene.py`

**Interfaces:**
- Consumes: todas as anteriores. Produces: nenhum `config.get(chave, default)` com default no motor (todas as chaves vêm de `to_legacy_dict()`); `data_preprocessor` levanta `EngineError` (pt-BR) nos `ValueError`/`FileNotFoundError` que já tinham texto útil; `pipeline.run` deixa `EngineError` subir e relança outras exceções sem embrulhar.

- [ ] **Step 1: Write the failing tests**: `test_defaults.py::test_no_inline_defaults_remain` — varre `engine/*.py` com regex por `config\.get\("\w+",\s*[^)]` e afirma lista vazia (exceto `financial_targets` dicts internos, que são de outro dict); `test_investment_limit_factor_single_default` (run com a chave ausente usa 1,5 em todos os pontos: comparar com o run do snapshot cujo valor explícito é 1,5 → resultados iguais com `assert_allclose`); `test_data_prep_errors_are_engine_errors` (arquivo de KPI com >50% não numérico → `EngineError` com o texto pt-BR existente). `test_hygiene.py::test_forbidden_calls_absent` — roda o `grep` do aceite (`os.getcwd|sys.exit|os._exit|sys.path`) sobre `engine/` e `llm/` e afirma vazio; `test_llm_does_not_import_engine_or_api` (leitura de `llm/*.py`).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** as remoções dos defaults inline (um módulo por vez, rodando `uv run pytest tests/engine -q` a cada um — o `test_parity` precisa continuar verde), a troca dos `raise ValueError/FileNotFoundError` por `EngineError` e a remoção dos `except Exception` que apenas re-embrulham.
- [ ] **Step 4: Run** `uv run pytest tests/engine tests/llm -q` → PASS, com `test_parity` verde.
- [ ] **Step 5: Commit** `refactor(engine): single source for defaults and engine errors`.

---

### Task 14: Documentação, entrega ao Dev B e verificação final

**Files:**
- Create: `docs/decisoes/engine.md`, `docs/decisoes/llm.md`
- Modify: `docs/decisoes/README.md`, `CLAUDE.md` (Estrutura e "Estado atual"), `docs/m2/trilha-a-motor.md` (linha `Status` do A0), `CODE-STYLE.md` (menção ao `llm/`, se couber), `mise.toml` (task `parity`: `uv run pytest tests/engine/test_parity.py -q`)

- [ ] **Step 1: Escrever `docs/decisoes/engine.md`**: por que o pipeline é em estágios; `to_legacy_dict` e por que `None` = chave ausente (corrige o spec, que falava em sentinela 999999); lista de campos do `EngineConfig` e **divergências com `api/engine_config.py`** (`require_significance`/`require_good_fit` ≠ três gates; `post_event_days`, `max_events_to_analyze`, `require_logical_direction` ausentes na API; defaults de `r_squared_threshold`, `min_pre_period_days` e limiares de evento); `EngineError`; semântica de `status` e `on_log`; passos do swap para o Dev B (`api/engine_config.py` → `from engine.config import …`, `api/engine_run.py` → `from engine import run`, `Dockerfile` `COPY engine/ llm/` (e medir o tamanho da imagem antes/depois), trocar `FAKE_ENGINE_*` em `tests/conftest.py` e `tests/api/test_runs.py`, ajustar o gate de `block_reason` e o formulário ao novo schema, atenção às configs já salvas com as chaves provisórias).
- [ ] **Step 2: Escrever `docs/decisoes/llm.md`**: por que plugável; a interface e o que ela **não** expõe; como adicionar um provedor (arquivo + `PROVIDERS` + dependência + `run_provider_contract`); passos para o Dev B migrar `api/gemini.py` para `get_llm().generate_json(...)` mapeando `LLMUnavailable`; renomear rota, `source: "gemini"` e botão. Atualizar `docs/decisoes/README.md`.
- [ ] **Step 3: Atualizar `CLAUDE.md`** (Estrutura: `engine/` e `llm/`; "Estado atual": A0 concluído com a data e o que foi verificado), `trilha-a-motor.md` (Status do A0, data, verificações) e `mise.toml`.
- [ ] **Step 4: Verificação final** — `uv run ruff format --check . && uv run ruff check . && uv run pytest -q` (suíte inteira, com Postgres no ar) verdes; `grep -rn "os.getcwd\|sys.exit\|os._exit\|sys.path" engine/ llm/` vazio; `uv run python -m engine --help` funciona; registrar o tempo do run completo no dataset sintético (`time uv run python -m engine …`).
- [ ] **Step 5: Verificação no servidor (manual, feita por quem tem o acesso)** — rodar `mise run parity` (ou `uv run pytest tests/engine/test_parity.py`) no servidor x86-64 e anotar o resultado e o tempo em `docs/decisoes/engine.md`; se passar de 1e-9, registrar a tolerância medida.
- [ ] **Step 6: Commit** `docs: record the engine package and llm module decisions (a0)`.
