# A6 Suficiência e placebo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rejeitar eventos cujo "efeito" também aparece numa data falsa do pré-período (placebo) e marcar o run `inconclusive` quando os dados não sustentam publicar lift (suficiência).

**Architecture:** O placebo e o WMAPE fora da amostra vivem em `run_causal_impact_analysis` (mesmo modelo, ajustado em subconjuntos do pré) e entram em `results_data`. O gate `placebo_failed` entra em `_gate_reasons`. Um módulo novo `engine/sufficiency.py` (função pura) julga o run a partir dos eventos, do spend cru e de um flag `cv_out_of_sample` que o MMM passa a registrar. `pipeline.compute` aplica o resultado (eventos viram `insufficient_run`) e `results.py` publica `sufficiency`, `placebo`, `fit.wmape` e o status.

**Tech Stack:** Python 3.13, statsmodels `UnobservedComponents`, pydantic v2, pytest (`mise run test`).

**Spec:** `docs/superpowers/specs/2026-11-05-a6-suficiencia-placebo-design.md`

## Global Constraints

- `schema_version` continua 1; todo campo novo é opcional.
- Defaults só em `engine/config.py` (`GateThresholds`): `spend_cv_min` 0.10, `oos_wmape_max` 0.30, ambos `gt=0`, `strict=True`. A fração do holdout (0.2) é constante do código.
- O ajuste do evento real (lift, p, R², features, previsão) não muda; o golden causal do A4 só muda em quem passa nos gates. A matemática da elasticidade não muda (`cv_r2` e coeficientes idênticos).
- Ids estáveis: `placebo_failed`, `insufficient_run`, `no_validated_event`, `low_spend_variation`, `high_oos_wmape`, `cv_in_sample`.
- Sem flag `require_placebo`. Placebo que não roda: `placebo = {p_value: null, passed: null}`, aviso no log, evento não rejeitado, nada em `reasons`.
- Logs em pt-BR para a tela; nada de `print()`; nome de coluna nunca hardcoded.
- Ruff limpo; commits terminam com `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

- Pré curto: placebo não roda (`n // 2 < min_pre_periods` ou janela maior que a 2ª metade) e o holdout não calcula; nenhum dos dois derruba nem rejeita o evento.
- Denominador zero no WMAPE (`Σ|y| = 0`) e média de spend 0 no CV: viram `null`/CV 0, sem exceção.
- Evento `analysis_failed` (sem `results_data`) não entra em `validated_events`, no CV nem na mediana.
- Corte `max_events_to_analyze`: o placebo roda em todo candidato elegível, e `validated_events` conta antes do corte.
- Run sem MMM (falhou): a suficiência avalia só as partes causais, sem `cv_in_sample`.
- Evento demotado por `insufficient_run` não aparece como `selected` nem gera relatório/payload do Gemini com lift.

---

### Task 1: Limiares, schema e `sufficiency.assess`

**Files:**
- Modify: `engine/config.py` (`GateThresholds`), `engine/results_schema.py` (`Sufficiency`)
- Create: `engine/sufficiency.py`
- Test: `tests/engine/test_sufficiency.py`, `tests/engine/test_config.py`, `tests/engine/test_results_schema.py`

**Interfaces:**
- Produces: `GateThresholds.spend_cv_min`, `GateThresholds.oos_wmape_max`; `Sufficiency` ganha `reasons: list[str] = []` e `cv_out_of_sample: bool | None = None` (`spend_variation` passa a ser `{canal: cv}`).
- Produces: `spend_cv(investment_df: pd.DataFrame, channels: list[str]) -> dict[str, float]` (CV = `std(ddof=0)/mean` do spend por período nativo em `Product Group`, em todo o intervalo; média 0 → 0.0).
- Produces: `assess(validated: list[dict], investment_df: pd.DataFrame, cv_out_of_sample: bool | None, thresholds: GateThresholds) -> Sufficiency`, onde cada item de `validated` é `{"product_group": str, "oos_wmape": float | None}` dos eventos que passaram em todos os gates. Canais = os de `product_group.split(", ")` (união, ordem estável).
- Produces: `CAUSAL_REASONS = ("no_validated_event", "low_spend_variation", "high_oos_wmape")`.

- [ ] **Step 1: Testes que falham.** `test_sufficiency.py`: (a) sem eventos → `passed False`, `reasons == ["no_validated_event"]`, `validated_events == 0`; (b) um evento com canal de CV alto e WMAPE 0.1 → `passed True`, `pre_wmape == 0.1`; (c) canal com spend constante (CV 0) → `low_spend_variation` e `spend_variation[canal] == 0.0`; (d) WMAPEs `[0.1, 0.5, 0.6]` → mediana 0.5 > 0.30 → `high_oos_wmape`; (e) nenhum `oos_wmape` calculável → `pre_wmape is None` e sem `high_oos_wmape`; (f) `cv_out_of_sample=False` → `cv_in_sample` e `passed False`, com os outros checks intactos; `None` não reprova; (g) `spend_cv_min=0.5` muda o resultado de (b); (h) `product_group` "A, B" avalia os dois canais. `test_config.py`: defaults 0.10 e 0.30; 0 e `"0.3"` (string) rejeitados. `test_results_schema.py`: `Sufficiency` aceita `reasons` e `cv_out_of_sample`.
- [ ] **Step 2: Rodar e ver falhar.** `uv run pytest tests/engine/test_sufficiency.py tests/engine/test_config.py tests/engine/test_results_schema.py -q`. Esperado: FAIL (módulo/campos inexistentes).
- [ ] **Step 3: Implementar** `GateThresholds` (comentário de uma linha por campo, como os vizinhos), os campos do `Sufficiency` e `engine/sufficiency.py`. `pre_wmape` = `statistics.median` dos `oos_wmape` não nulos.
- [ ] **Step 4: Rodar e ver passar**, mesmo comando. Esperado: PASS.
- [ ] **Step 5: Commit** `feat(engine): sufficiency rule and gate thresholds (a6)`.

### Task 2: Placebo e WMAPE fora da amostra no modelo causal

**Files:**
- Modify: `engine/analysis.py` (`run_causal_impact_analysis`), `engine/pipeline.py` (`_gate_reasons`), `engine/results.py` (`_event`)
- Test: `tests/engine/test_analysis.py`, `tests/engine/test_pipeline_stages.py`, `tests/engine/test_results_build.py`

**Interfaces:**
- Produces em `results_dict` de `run_causal_impact_analysis`: `placebo_p_value: float | None`, `placebo_ran: bool`, `oos_wmape: float | None`.
- Produces: `analysis.cumulative_p_value(abs_lift: float, forecast) -> tuple[float, float]` (devolve `(p_value, cum_se)`), usado pelo ajuste real e pelo placebo; o evento real continua dando o mesmo p-valor e o mesmo IC.
- Produces: `analysis.placebo_p_value(pre_data, selected_features, post_len, min_pre_periods) -> float | None` e `analysis.oos_wmape(pre_data, selected_features, min_pre_periods, holdout=0.2) -> float | None` (`None` = não rodou/não calculou).
- Consumes: `_gate_reasons(results, cfg)` ganha `placebo_failed` quando `placebo_ran` e `placebo_p_value < p_value_threshold`.
- Produces: `CausalEvent.placebo = Placebo(p_value, passed)` (`passed=None` quando não rodou) e `Fit.wmape`.

- [ ] **Step 1: Testes que falham.** (a) `cumulative_p_value` reproduz o p-valor e o IC do evento num caso fixo (compare com o resultado antes da extração, com `==`); (b) série sintética com efeito injetado na 2ª metade do pré (degrau ≥ 10σ) → `placebo_p_value < 0.05` e `_gate_reasons` devolve `placebo_failed`; (c) série limpa (nível + sazonalidade + ruído) → placebo não reprova em 3 sementes; (d) pré com menos linhas que `2 × min_pre_periods` → `placebo_p_value is None`, `placebo_ran False`, sem `placebo_failed`; (e) janela do pós maior que a 2ª metade → não roda; (f) `oos_wmape` de uma série quase determinística fica < 0.05; denominador `Σ|y| = 0` → `None`; holdout < 7 linhas → `None`; (g) falha do ajuste (monkeypatch levantando) → `None` + aviso, evento segue; (h) `_event` publica `placebo` e `fit.wmape`, com `passed=None` quando não rodou.
- [ ] **Step 2: Rodar e ver falhar.** Esperado: FAIL.
- [ ] **Step 3: Implementar.** Extrair `cumulative_p_value` sem mudar a conta. Placebo: ajusta o mesmo `UnobservedComponents(kpi, "llevel", trend=True, seasonal=7, exog=selected_features)` em `pre_data.iloc[: n // 2]`, prevê `post_len` linhas seguintes com os exógenos reais e usa `cumulative_p_value` (impacto = soma de `kpi − previsto`). WMAPE: treino nos primeiros 80%, `Σ|y−ŷ| / Σ|y|` no holdout. Qualquer exceção → `None` + `log.warning` em pt-BR. Guardar `placebo_ran`, `placebo_p_value`, `oos_wmape` em `results_dict`. Mensagens novas em `logmessages.py` se o padrão do arquivo exigir.
- [ ] **Step 4: Rodar** os três arquivos de teste e `uv run pytest tests/engine/test_parity.py -q`. Esperado: PASS; o ajuste real idêntico ao snapshot.
- [ ] **Step 5: Commit** `feat(engine): placebo gate and out-of-sample wmape per event (a6)`.

### Task 3: O MMM registra se o CV foi fora da amostra

**Files:**
- Modify: `engine/elasticity_analysis.py` (`walk_forward_cv_score`, `run_mmm_engine`)
- Test: `tests/engine/test_elasticity_analysis.py`

**Interfaces:**
- Produces: `cv_is_out_of_sample(n_rows: int, n_splits: int = 3) -> bool` (`min(n_splits, max(1, n_rows // 20)) >= 2`), usada por `walk_forward_cv_score` no lugar da conta inline; `run_mmm_engine` devolve `"cv_out_of_sample": bool` no dicionário `mmm`.

- [ ] **Step 1: Testes que falham.** `cv_is_out_of_sample(39) is False`, `(40) is True`; `run_mmm_engine` num dataset de < 40 linhas de lift traz `cv_out_of_sample False`, e num dataset longo `True`; `cv_r_squared` e `bootstrap_coefs` iguais aos de antes (valores fixados do código atual).
- [ ] **Step 2: Rodar e ver falhar.** Esperado: FAIL.
- [ ] **Step 3: Implementar** sem alterar a aritmética.
- [ ] **Step 4: Rodar** `uv run pytest tests/engine/test_elasticity_analysis.py tests/engine/test_parity.py -q`. Esperado: PASS.
- [ ] **Step 5: Commit** `feat(engine): record whether the elasticity cv was out of sample (a6)`.

### Task 4: Pipeline e resultado publicam a suficiência

**Files:**
- Modify: `engine/pipeline.py` (`Computed.sufficiency`, `compute`), `engine/results.py` (`build_results`, `_causal`, `_elasticity`, `run_status`), `engine/results_schema.py` (`ResultsV1.sufficiency` já existe), `engine/logmessages.py`
- Test: `tests/engine/test_pipeline_stages.py`, `tests/engine/test_results_build.py`, `tests/engine/test_run.py`

**Interfaces:**
- Consumes: `sufficiency.assess`, `CAUSAL_REASONS` (Task 1); `results_data["oos_wmape"]` (Task 2); `mmm["cv_out_of_sample"]` (Task 3).
- Produces: `Computed.sufficiency: Sufficiency | None`; em `compute`, depois de analisar os eventos e a elasticidade: `validated` = outcomes com `passed`, antes do corte; se `assess` devolver algum motivo de `CAUSAL_REASONS`, cada outcome com `passed` ganha `insufficient_run` em `reasons` e fica `passed=False, selected=False`.
- Produces: `run_status` devolve `inconclusive` sempre que `sufficiency` existe e `passed is False`, nunca `succeeded`; `_causal` põe os motivos causais da suficiência em `causal.reasons` (sem duplicar `no_event_passed_gates`/`no_validated_event`) e status `inconclusive`; `_elasticity` acrescenta `cv_in_sample` a `reasons` (informativo, status segue `ok`).

- [ ] **Step 1: Testes que falham.** (a) `Computed` com 2 eventos passados e mediana de WMAPE 0.6 → ambos `rejected` com `insufficient_run`, `selected False`, sem lift em `causal` publicado, `causal.status inconclusive`, run `inconclusive`; (b) suficiência ok → nada muda e `results.sufficiency.passed True` com `validated_events`; (c) `cv_out_of_sample False` → run `inconclusive`, `elasticity.status ok`, `cv_in_sample` em `elasticity.reasons`, curva publicada; (d) sem MMM → sem `cv_in_sample` e a suficiência avalia só o causal; (e) `analysis_failed` fica fora da contagem; (f) evento demotado não gera relatório/payload com lift (o LLM falso em `tests/fakes/llm` não recebe o evento); (g) `run_status` com `sufficiency.passed False` e as duas análises `ok` → `inconclusive`.
- [ ] **Step 2: Rodar e ver falhar.** Esperado: FAIL.
- [ ] **Step 3: Implementar.** Limiares via `GateThresholds.model_validate(cfg.get("gate_thresholds") or {})`, como o A5. Log pt-BR do veredito (uma linha com os motivos). `build_results` passa `sufficiency=computed.sufficiency`.
- [ ] **Step 4: Rodar** os três arquivos. Esperado: PASS.
- [ ] **Step 5: Commit** `feat(engine): publish sufficiency and demote events of an insufficient run (a6)`.

### Task 5: Aceite sintético, golden, fixtures, medição e docs

**Files:**
- Modify: `tests/engine/synthetic_data.py` (`make_noise_dataset`), `tests/fixtures/parity/make_a4_golden.py` + `snapshot_a4_events.json` (regenerar), `tests/fixtures/results/*.json` (regenerar), `docs/m2/README.md`, `docs/m2/trilha-a-motor.md`, `docs/decisoes/engine.md`, `CLAUDE.md`
- Test: `tests/engine/test_run.py`, `tests/engine/test_sufficiency_real.py` (novo, pula sem `exemplo_csv/Gol`)

**Interfaces:**
- Produces: `make_noise_dataset(out_dir, *, seed=3) -> dict[str, Path | None]`: mesmos spends do sintético padrão (com os picos), KPI = ruído puro (gaussiano em torno de um nível constante, sem resposta à mídia).

- [ ] **Step 1: Testes que falham.** Em `test_run.py`: **ruído puro** (`make_noise_dataset`, 3 sementes) → nenhum evento `published`, `status == "inconclusive"`, `sufficiency.passed False`; o sintético padrão com efeito (`make_strong_effect_dataset`) segue sem regressão em `status` e `sufficiency`; efeito injetado no pré reprova no placebo ponta a ponta. `test_sufficiency_real.py`: roda a Gol e registra (assert de formato, números documentados como medição para o A10) quantos eventos passam, quantos reprovam no placebo, o WMAPE mediano e o `status`.
- [ ] **Step 2: Rodar e ver falhar.** Esperado: FAIL (helper inexistente).
- [ ] **Step 3: Implementar** o helper; regenerar o golden (`mise run parity-a4-golden`, com o BLAS fixado em 1 thread como o README de paridade manda) e as fixtures de `results.json`; conferir no diff que só mudam `sufficiency`, `placebo`, `fit.wmape` e os eventos que mudaram de gate.
- [ ] **Step 4: Docs.** `docs/m2/README.md`: `sufficiency` com `reasons`/`cv_out_of_sample`, `placebo.passed = null` = não rodou, `fit.wmape` fora da amostra, os ids novos. `docs/decisoes/engine.md`: seção A6 (placebo A vs B e o vazamento do Lasso, suficiência no nível do run, canais analisados, limiares 0.10/0.30 com a medição da Gol, lista para o Dev B: `spend_cv_min`, `oos_wmape_max`). `docs/m2/trilha-a-motor.md`: Status ✅ do A6 com a data. `CLAUDE.md`: linha do mapa e "Estado atual".
- [ ] **Step 5: Suíte completa** em background (`mise run test`, ~15 min, apague o `.done` antigo antes) mais `mise run parity-real` e `uv run ruff check . && uv run ruff format --check .`. Esperado: tudo verde; uma falha é reportada pelo nome.
- [ ] **Step 6: Commit** `feat(engine): sufficiency and placebo acceptance, golden and docs (a6)`.
