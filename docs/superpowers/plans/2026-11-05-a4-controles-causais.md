# A4 · Controles causais livres de contaminação — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O modelo causal deixa de usar Clicks/Impressions/Leads, os controles (a `Generic Searches` e as colunas de `config.controls` do arquivo de tendências) passam por uma triagem por evento contra o spend do canal tratado, o LassoCV usa folds temporais, e o resultado de cada evento registra controles usados e rejeitados.

**Architecture:** `engine/controls.py` tem a triagem como função pura. `read_inputs` lê as colunas de controle numa tabela separada (`controls_df`, para a elasticidade seguir lendo só a `Generic Searches`). `run_causal_impact_analysis` troca o parâmetro `performance_df` por `controls_df`, aplica a triagem depois de montar o pré-período e devolve `controls_used`/`controls_rejected` em `results`, que `results.py` publica em `CausalEvent.controls`.

**Tech Stack:** Python 3.13, pandas 3.0.3, numpy 2.5.0, scikit-learn 1.9.0 (`TimeSeriesSplit`, `LassoCV`), statsmodels 0.14.6, pydantic v2, pytest. Ruff, linha de 120, sem `print()`.

**Spec:** `docs/superpowers/specs/2026-11-05-a4-controles-causais-design.md` (a autoridade; em conflito, ela vence).

## Global Constraints

- Mensagens na tela em pt-BR, sem caminhos nem dados do cliente.
- Ids novos e estáveis, ambos `error`: `control_missing`, `control_name_clash`.
- `gate_thresholds.control_spend_corr` default 0.5, número em (0, 1], estrito (sem bool nem texto), declarado em `GateThresholds` (`engine/config.py`) para o default sair no JSON Schema.
- Triagem: correlação de Pearson no pré-período do evento entre o controle e o spend cru do canal tratado (soma, se o evento tem vários canais, `product_group` separado por vírgula); rejeita se `abs(r) > control_spend_corr` (estrito, sinal ignorado); correlação indefinida (NaN) não rejeita.
- Rejeitar um controle **não** põe nada em `reasons` nem reprova o evento; o registro é `CausalEvent.controls` (`used`, `rejected`).
- `schema_version` continua 1; o campo novo é opcional.
- A elasticidade (MMM) e o `run_opportunity_projection` seguem lendo só a `Generic Searches` de `trends_df`, sem triagem.
- Covariáveis `Leads`, `Clicks`, `Impressions` do arquivo de performance nunca entram no modelo causal.
- Blocos `period_days`, `mmm`, `response_curve`, `points`, `optimized_mix` seguem idênticos ao protótipo (`rtol=1e-9`); só os números do resultado causal por evento mudam, contra um golden gerado pelo motor.
- Suíte completa leva ~10–14 min: durante a tarefa rode só os testes afetados; suíte inteira e `mise run parity-real` nas Tasks 3 e 4 (em background, lendo o fim do log). Commits terminam com `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

- **Gol:** se a `Generic Searches` da Gol passar de 0.5 de correlação com o canal de algum evento, ela é rejeitada e o número causal muda. Teste/registro: a Task 4 gera o golden da Gol, lista por evento o que mudou e confere que `event_id`, `product_group` e `intervention_date` seguem iguais ao protótipo.
- **Evento com vários canais tratados:** a triagem usa a soma dos spends (teste na Task 3).
- **Pré-período no mínimo permitido:** o `TimeSeriesSplit` encolhe os folds em vez de levantar (teste na Task 3).
- **Controle com datas faltando:** o `fillna(0)` que já existe zera os buracos antes da triagem; o run não quebra (teste na Task 3; o efeito sobre a correlação vira item adiado se se confirmar).
- **Nome em `controls` com caixa/espaços diferentes do cabeçalho** (`" Selic "` × `Selic`): resolve pelo cabeçalho sem espaços nas pontas, comparação exata de caixa não é exigida (teste na Task 2).
- **Controle repetido em `controls`, ou igual à coluna de tendência mapeada:** vale uma vez só (teste na Task 2).
- **Arquivo de performance com `Clicks`, `Impressions`, `Leads`:** resultado causal idêntico ao do mesmo arquivo sem elas (teste na Task 3).

---

### Task 1: Config, triagem e schema

**Files:**
- Modify: `engine/config.py` (`GateThresholds.control_spend_corr`; validação de `controls`)
- Create: `engine/controls.py`
- Modify: `engine/results_schema.py` (`RejectedControl`, `EventControls`, `CausalEvent.controls`)
- Test: `tests/engine/test_controls.py` (novo), `tests/engine/test_config.py`, `tests/engine/test_results_schema.py`

**Interfaces:**
- Consumes: `GateThresholds` existente.
- Produces:
  - `GateThresholds.control_spend_corr: float = 0.5`.
  - `EngineConfig.controls: list[str]` agora normalizado: cada nome com `strip()`, sem vazios, sem repetidos (ordem preservada); vazio ou não-texto → `EngineError` de config que cita `controls`.
  - `engine.controls.screen_controls(pre_data: pd.DataFrame, candidates: list[str], treated_channels: list[str], threshold: float) -> tuple[list[str], list[dict]]` → `(aceitos em ordem alfabética, rejeitados como {"name": str, "r": float} ordenados por abs(r) decrescente e nome)`; `r` arredondado a 4 casas; candidatos que não são colunas de `pre_data` são ignorados; canais tratados que não são colunas de `pre_data` → `ValueError`.
  - `engine.results_schema.RejectedControl(name: str, r: float)`, `EventControls(used: list[str] = [], rejected: list[RejectedControl] = [])`, `CausalEvent.controls: EventControls | None = None`.

- [ ] **Step 1: Escrever os testes que falham.**
  `tests/engine/test_controls.py` (séries com `numpy.random.default_rng(1)`, índice de datas):
  - `test_control_equal_to_spend_plus_noise_is_rejected`: controle = spend + ruído pequeno → em `rejected`, `abs(r) > 0.9`; `accepted == []`.
  - `test_independent_control_is_accepted`.
  - `test_sign_does_not_matter`: controle = −spend + ruído → rejeitado, `r < 0`.
  - `test_threshold_is_strict`: com `threshold` igual a `abs(r)` calculado (`numpy.corrcoef`) → aceito.
  - `test_several_treated_channels_use_the_summed_spend`: canais A e B, controle ≈ A + B mas pouco correlacionado com cada um sozinho → rejeitado ao tratar `["A","B"]`, aceito ao tratar `["A"]`.
  - `test_constant_control_is_not_rejected`: controle constante → aceito (correlação indefinida não rejeita), sem exceção nem warning escapando.
  - `test_unknown_candidate_is_ignored_and_unknown_treated_channel_raises`.
  - `test_order`: aceitos em ordem alfabética; rejeitados por `abs(r)` decrescente.
  Em `tests/engine/test_config.py`: `GateThresholds` default `control_spend_corr == 0.5` e está em `EngineConfig.model_json_schema()["$defs"]["GateThresholds"]["properties"]`; valores `0`, `1.5`, `True`, `"x"` → `EngineError` citando `gate_thresholds`; `controls=[" Selic ", "Selic", "IPCA"]` → `["Selic", "IPCA"]`; `controls=[""]` e `controls=[3]` → `EngineError` citando `controls`.
  Em `tests/engine/test_results_schema.py`: `CausalEvent(...)` sem `controls` continua válido e `controls is None`; com `EventControls(used=["a"], rejected=[RejectedControl(name="b", r=0.7)])` faz round-trip em JSON.

- [ ] **Step 2: Rodar e ver falhar:** `uv run pytest tests/engine/test_controls.py tests/engine/test_config.py tests/engine/test_results_schema.py -q` — Expected: FAIL (módulo e campos ausentes).

- [ ] **Step 3: Implementar** conforme as Interfaces. `screen_controls`: `spend = pre_data[treated_channels].sum(axis=1)`; correlação via `pd.Series.corr` dentro de `numpy.errstate` (NaN → aceita); o `r` registrado é o assinado. `controls` validado por `field_validator` em `EngineConfig` (mensagem pt-BR que cita o campo). Os campos novos do schema seguem o estilo `_Model` do arquivo.

- [ ] **Step 4: Rodar e ver passar** o comando do Step 2 mais `uv run pytest tests/engine/test_results_build.py -q` — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff check engine tests/engine && uv run ruff format engine tests/engine
git add engine tests
git commit -m "feat(engine): control screening, config and event controls schema (a4)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Leitura dos controles e checks

**Files:**
- Modify: `engine/inputs.py` (`RawInputs.controls_df`, leitura das colunas de controle, checks)
- Modify: `engine/data_preprocessor.py` (`PreparedData.controls_df`, `load_and_prepare_data` repassa)
- Test: `tests/engine/test_inputs.py`, `tests/engine/test_validate_checks.py`, `tests/engine/test_data_preprocessor.py`, `tests/engine/csv_factory.py` (opção `trends_columns`)

**Interfaces:**
- Consumes: `EngineConfig.controls` normalizado (Task 1); `RawInputs`, `_column`, `robust_numeric_parsing`, `_not_numeric` existentes.
- Produces:
  - `RawInputs.controls_df: pd.DataFrame` — `Date` mais uma coluna por controle (nome do cabeçalho do arquivo), ordenado por data; sem controles, só a coluna `Date` vazia. `trends_df` NÃO ganha colunas.
  - `PreparedData.controls_df: pd.DataFrame` (campo no fim, com default de tabela vazia só com `Date`) copiado de `RawInputs`.
  - Checks `error`: `control_missing` (nome de `controls` ausente do arquivo de tendências, ou sem arquivo de tendências; `details["controls"]` lista os nomes), `control_name_clash` (nome igual a um canal do investimento já lido, a `Date`, `kpi` ou `Generic Searches`; `details["controls"]`); controle com mais de 50% não numérico usa `value_not_numeric` (mesma mensagem dos demais, citando a coluna).
  - Resolução do nome: cabeçalho do arquivo comparado sem espaços nas pontas e sem diferenciar caixa; o nome já mapeado como coluna de tendência (`trends_col`) e repetidos valem uma vez só (ignorados).
  - `csv_factory.write_inputs(..., trends_columns: dict[str, list] | None = None)`: colunas extras do arquivo de tendências (mesmo comprimento das linhas de `trends`).

- [ ] **Step 1: Escrever os testes que falham.**
  - `test_inputs.py`: `test_controls_are_read_from_the_trends_file` (2 controles → `controls_df.columns == ["Date","Selic","IPCA"]`, valores numéricos, `trends_df.columns == ["Date","Generic Searches"]`); `test_control_header_matches_ignoring_case_and_edge_spaces` (`" selic "` resolve `Selic`); `test_repeated_and_primary_trends_column_count_once`; `test_no_controls_gives_an_empty_controls_df`.
  - `test_validate_checks.py`: `control_missing` com nome inexistente; `control_missing` sem arquivo de tendências; `control_name_clash` com um nome de canal e com `kpi`; `value_not_numeric` para controle de texto; `ok` quando os controles existem e são numéricos; todos com `validate` e com `load_and_prepare_data` levantando o mesmo `check_id` (acordo `validate` × loader).
  - `test_data_preprocessor.py`: `PreparedData.controls_df` traz os controles e `trends_df` continua só com `Generic Searches`.

- [ ] **Step 2: Rodar e ver falhar:** `uv run pytest tests/engine/test_inputs.py tests/engine/test_validate_checks.py tests/engine/test_data_preprocessor.py -q -k "control"` — Expected: FAIL.

- [ ] **Step 3: Implementar.** Em `_read_inputs`, ler as colunas de controle do quadro bruto do arquivo de tendências antes do `rename` da data; numérico com `robust_numeric_parsing`; datas pelo mesmo formato da tendência; acumular os checks e abortar como os demais erros de leitura. Em `load_and_prepare_data`, `raw.controls_df` vai para `PreparedData`. O `trends_df` e todos os consumidores atuais não mudam.

- [ ] **Step 4: Rodar e ver passar:** o comando do Step 2 sem `-k`, mais `uv run pytest tests/engine/test_validate_collinearity.py tests/engine/test_run.py -q -k "not twin and not group"` — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff check engine tests/engine && uv run ruff format engine tests/engine
git add engine tests
git commit -m "feat(engine): read user controls from the trends file with validate checks (a4)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Modelo causal sem contaminação

**Files:**
- Modify: `engine/analysis.py` (`run_causal_impact_analysis`)
- Modify: `engine/pipeline.py` (chamada passa `prepared.controls_df`)
- Modify: `engine/results.py` (`_event` publica `controls`)
- Test: `tests/engine/test_analysis.py`, `tests/engine/test_run.py`, `tests/engine/test_results_build.py`

**Interfaces:**
- Consumes: `screen_controls`, `EventControls`, `RejectedControl` (Task 1); `PreparedData.controls_df` (Task 2).
- Produces:
  - `run_causal_impact_analysis(kpi_df, daily_investment_df, market_trends_df, controls_df, pre_period, post_period, event_name, product_group, model_params, config)` — o 4º parâmetro passa de `performance_df` para `controls_df`; o dicionário `results` ganha `controls_used: list[str]` e `controls_rejected: list[dict]`.
  - `CausalEvent.controls` preenchido quando há `results_data` (mesmo com listas vazias); `None` quando a análise falhou.
  - O Lasso usa `TimeSeriesSplit(n_splits=min(5, linhas_do_pré_período − 1))`.

- [ ] **Step 1: Escrever os testes que falham.**
  `tests/engine/test_analysis.py` (monte com os helpers do arquivo; adapte a chamada existente em `:325` ao novo parâmetro):
  - `test_clicks_impressions_leads_do_not_change_the_result`: o mesmo evento rodado com um `controls_df` vazio e com colunas `Clicks`, `Impressions`, `Leads` presentes só no arquivo de performance (que o modelo nem recebe mais) → `results` idêntico (`==` nos floats).
  - `test_control_equal_to_spend_plus_noise_is_rejected_and_reported`: `controls_df` com `Spend_like` ≈ spend do canal tratado → `results["controls_rejected"][0]["name"] == "Spend_like"` e fora do modelo; um controle independente em `controls_used`.
  - `test_triage_is_per_event`: o mesmo controle é rejeitado num evento do canal A e aceito num evento do canal B.
  - `test_multi_channel_event_uses_the_summed_spend`.
  - `test_generic_searches_is_screened_like_any_control`: `Generic Searches` ≈ spend → em `controls_rejected`.
  - `test_all_controls_rejected_still_runs`: `controls_used == []` e `results` completo.
  - `test_short_pre_period_does_not_break_the_lasso`: pré-período no mínimo permitido roda sem exceção.
  - `test_lasso_uses_time_series_folds`: espiona `LassoCV` (monkeypatch em `engine.analysis.LassoCV`) e confere que o `cv` recebido é um `TimeSeriesSplit` com `n_splits == min(5, n − 1)`.
  - `test_control_with_missing_dates_runs`: `controls_df` com buracos de datas roda sem exceção.
  `tests/engine/test_results_build.py`: um `EventOutcome` com `results_data` contendo `controls_used`/`controls_rejected` vira `CausalEvent.controls` com os mesmos nomes e `r`; `reasons` do evento não muda; sem `results_data`, `controls is None`.
  `tests/engine/test_run.py`: `test_rejected_control_does_not_fail_the_event` — run completo com um controle ≈ spend declarado em `controls` (arquivo de tendências com a coluna extra): o evento correspondente tem o controle em `controls.rejected` e `reasons` sem nada de controle.

- [ ] **Step 2: Rodar e ver falhar:** `uv run pytest tests/engine/test_analysis.py tests/engine/test_results_build.py tests/engine/test_run.py -q -k "control or lasso or clicks or triage or generic or short_pre or missing_dates"` — Expected: FAIL.

- [ ] **Step 3: Implementar.** Em `run_causal_impact_analysis`: remover o bloco "New Dynamic Code" (`perf_df_renamed`, `found_covariates`) e o `extend(found_covariates)`; depois do merge com `market_trends_df`, `left`-merge de `controls_df` em `Date` (se tiver colunas além de `Date`); depois de `pre_data_for_model` e da checagem de linhas mínimas, chamar `screen_controls` com candidatos `["Generic Searches"]` (se for coluna) mais as colunas de `controls_df`, canais tratados `[c.strip() for c in product_group.split(",")]` e `config.get("gate_thresholds", {}).get("control_spend_corr", 0.5)`; os aceitos entram em `potential_exog_vars` por nome (a regra `"generic" in col.lower()` deixa de existir); `results["controls_used"]`/`["controls_rejected"]`; Lasso com `cv=TimeSeriesSplit(n_splits=...)`. `pipeline.py` passa `prepared.controls_df`. `results._event` monta `EventControls` quando há `results_data`. Registrar no log os controles rejeitados (pt-BR via `logmessages` se houver tradução por padrão de mensagem).

- [ ] **Step 4: Rodar e ver passar** o comando do Step 2 sem `-k`, mais `uv run pytest tests/engine/test_pipeline_stages.py tests/engine/test_results_run.py tests/engine/test_hygiene.py -q` — Expected: PASS. Se algum teste existente comparar números causais contra o protótipo (`test_parity*`), ele é tratado na Task 4, não aqui.

- [ ] **Step 5: Commit**

```bash
uv run ruff check engine tests/engine && uv run ruff format engine tests/engine
git add engine tests
git commit -m "feat(engine): causal model drops ad-driven covariates, screens controls and uses temporal lasso folds (a4)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Paridade com golden, fixtures e documentação

**Files:**
- Create: `tests/fixtures/parity/make_a4_golden.py`, `tests/fixtures/parity/snapshot_a4_events.json` (versionado), tarefa `parity-real-a4` em `mise.toml`
- Modify: `tests/engine/test_parity.py`, `tests/engine/test_parity_real.py`, `tests/engine/real_data.py` (caminho do golden da Gol), `tests/fixtures/parity/README.md`
- Modify: `tests/fixtures/results/generate_fixtures.py` e os 3 JSON, `tests/engine/test_validate_real.py` (controles na Gol)
- Modify: `docs/decisoes/engine.md`, `docs/m2/trilha-a-motor.md` (Status do A4), `docs/m2/README.md` (§3: campo `controls` por evento), `CLAUDE.md` (mapa e "Estado atual")

**Interfaces:**
- Consumes: tudo das Tasks 1–3.
- Produces: `make_a4_golden.py [--real]` grava os números causais por evento (`results_data` e `passed`/`reasons`/`selected`) gerados pelo motor; `test_events_and_gates_match` compara identidade (`event_id`, `product_group`, `intervention_date`) com o protótipo e o resto com o golden; mesma estrutura em `test_parity_real.py` com `real/gol_a4_events.json` (git-ignorado).

- [ ] **Step 1: Medir o impacto.** Rodar o `parity` atual (`uv run pytest tests/engine/test_parity.py -q`) — Expected: o teste de eventos pode falhar (números causais mudaram); os demais blocos continuam passando. Anotar, por evento, o que mudou (`mise run parity-real` para a Gol) e se a `Generic Searches` foi rejeitada em algum evento.

- [ ] **Step 2: Gerar os goldens** com `make_a4_golden.py` (sintético, versionado; Gol, local, com BLAS em 1 thread como o parity real). Reescrever os testes de paridade conforme as Interfaces; blocos `period_days`, `mmm`, `response_curve`, `points`, `optimized_mix` continuam contra o protótipo.
  Run: `uv run pytest tests/engine/test_parity.py -q` e `mise run parity-real` — Expected: PASS (6 passed na Gol).

- [ ] **Step 3: Gol e fixtures.** Adicionar em `test_validate_real.py` um teste que registra a Gol com um controle declarado ausente (`control_missing`) e sem controles (`ok`). Regenerar os 3 JSON de `tests/fixtures/results/` e conferir `git diff --stat`: devem mudar o campo `controls` por evento e, se os números causais mudaram, os números. Run: `uv run pytest tests/engine/test_results_fixtures.py tests/engine/test_results_run.py tests/engine/test_validate_real.py -q` — Expected: PASS.

- [ ] **Step 4: Documentação.** `docs/decisoes/engine.md`: seção "Controles causais (A4)" com o porquê (`Clicks` etc. são efeito do spend; triagem por evento; `controls` fora de `reasons`; `controls_df` separado para o MMM seguir igual), a lista por evento do que mudou na paridade (insumo da A10) e o que o Dev B precisa (`control_spend_corr` em `gate_thresholds`, colunas de controle na tela, `controls` por evento no B5). `docs/m2/trilha-a-motor.md`: `Status` do A4 com data e o que foi verificado. `docs/m2/README.md` §3: o campo `controls`. `CLAUDE.md`: mapa (`controls.py`) e "Estado atual" com o A4.

- [ ] **Step 5: Verificação final.** `uv run ruff check . && uv run ruff format --check .`; suíte completa em background e `mise run parity-real` — Expected: tudo verde.

- [ ] **Step 6: Commit**

```bash
git add -A tests docs CLAUDE.md mise.toml
git commit -m "docs: mark a4 done, pin causal numbers to an engine golden and record the parity deltas

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```
