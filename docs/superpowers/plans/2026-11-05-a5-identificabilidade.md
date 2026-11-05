# A5 · Identificabilidade por canal — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O motor mede, por canal, se o coeficiente do MMM é separável de zero e estável (IC de bootstrap), marca `identifiable` com motivo e não publica curva, contribuição nem mix individual do que não se sustenta; o `results.json` e o payload do Gemini mostram só os canais identificáveis mais um balde `nao_identificavel`.

**Architecture:** `engine/identifiability.py` é uma função pura sobre a matriz de bootstrap. O MMM passa a guardar a matriz (a média usada pelo modelo não muda). `compute` avalia a identificabilidade depois do MMM, porque só ele tem o relatório de validação (canais colineares do A3). A publicação (`results.py`) e os cenários que vão ao Gemini (`outputs.py`) filtram usando essa avaliação; a matemática não muda.

**Tech Stack:** Python 3.13, numpy 2.5.0, scikit-learn 1.9.0 (Ridge), pydantic v2, pytest. Ruff, linha de 120, sem `print()`.

**Spec:** `docs/superpowers/specs/2026-11-05-a5-identificabilidade-design.md` (a autoridade; em conflito, ela vence).

## Global Constraints

- Regra: `identifiable` sse `lo > 0` **e** `(hi − lo) ≤ width_ratio × |ponto|`; `lo`/`hi` = percentis 2.5/97.5 das reamostras; `ponto` = média das reamostras. Motivos na ordem: `ci_crosses_zero` (`lo ≤ 0`), `ci_too_wide`; mais `collinearity` para canal sinalizado pelo gate do A3 (que fica `identifiable=false` mesmo passando no IC). Ponto zero nunca é identificável.
- `gate_thresholds.identifiability_width_ratio`: float > 0, estrito, default 1.0, declarado em `GateThresholds` (`engine/config.py`).
- Bootstrap: 200 reamostras, seed 42, Ridge(alpha=1.0, positive=True, fit_intercept=False), exatamente como hoje; `bootstrap_average_coefficients` devolve o mesmo vetor de antes.
- Balde: constante `UNIDENTIFIED_KEY = "nao_identificavel"`. A soma de cada linha do mix e do split dos cenários não muda.
- Canal não identificável: `hill`, `adstock`, `curve`, `contribution_pct` nulos/vazios no `results.json`; `coef_ci`, `identifiable`, `reasons` e `observed_spend_range` ficam.
- `status` do `elasticity` continua `ok`; sem nenhum canal identificável, `reasons` ganha `no_identifiable_channel`. `schema_version` continua 1.
- Arquivos legados por canal em `out_dir` (PNG/CSV de curva individual) ficam completos; `SATURATION_CURVE.md` (entrada do Gemini) e os cenários passam a usar os nomes publicados.
- `mmm`, curva agregada, pontos e mix seguem idênticos ao protótipo (`rtol=1e-9`) no sintético e na Gol.
- Nenhuma chave nova lida de `config[...]` fora de `EngineConfig` (o `test_config` varre isso).
- Suíte completa leva ~11–14 min: durante a tarefa rode só os testes afetados; suíte inteira e `mise run parity-real` nas Tasks 2 e 3 (em background, lendo o fim do log). Commits terminam com `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

- **Limite inferior exatamente 0** (Ridge positivo zera o canal em >2.5% das reamostras): não é identificável (teste na Task 1).
- **Nenhum canal identificável** (o caso real hoje: Gol 0 de 12, sintético 0 de 5): o total e a curva agregada seguem publicados, `unidentified` lista todos, `reasons` tem `no_identifiable_channel` (teste na Task 2).
- **Soma das linhas do mix** igual antes e depois do filtro; canal com `/` ou espaço no nome (`GOOGLE DISPLAY/VIDEO`) funciona (teste na Task 2).
- **`block_per_channel` + par colinear:** canal sinalizado sai `identifiable=false` com `collinearity`; sem relatório de validação (`compute` direto), nenhum canal é marcado por colinearidade (testes nas Tasks 1 e 2).
- **Payload do LLM** não contém o nome do canal oculto, nem no `SATURATION_CURVE.md` nem no prompt (teste na Task 2).
- **Aceite do item** com um sintético de efeito forte: canal com efeito real `true`, canal sem efeito `false` (Task 3).

---

### Task 1: Regra, matriz de bootstrap e config

**Files:**
- Modify: `engine/config.py` (`GateThresholds.identifiability_width_ratio`)
- Create: `engine/identifiability.py`
- Modify: `engine/elasticity_analysis.py` (`bootstrap_coefficients`, `bootstrap_average_coefficients`, dicionário `mmm`)
- Modify: `engine/pipeline.py` (`Computed.identifiability`, avaliação em `compute`)
- Test: `tests/engine/test_identifiability.py` (novo), `tests/engine/test_elasticity_analysis.py`, `tests/engine/test_config.py`, `tests/engine/test_pipeline_stages.py`

**Interfaces:**
- Consumes: `grouping.thresholds` (retorna `(collinearity_r, vif_max)`), `ValidationReport.collinearity` (A3), `mmm["spend_cols"]`.
- Produces:
  - `GateThresholds.identifiability_width_ratio: float = 1.0`.
  - `engine.identifiability.UNIDENTIFIED_KEY = "nao_identificavel"`.
  - `engine.identifiability.assess(coefs: np.ndarray, columns: list[str], width_ratio: float, collinear_channels: set[str]) -> dict[str, dict]` → `{canal: {"identifiable": bool, "reasons": list[str], "coef_ci": (lo, hi), "point": float}}`.
  - `engine.identifiability.collinear_channels(validation, vif_max: float) -> set[str]` → canais em `validation.collinearity.pairs` ou com VIF acima de `vif_max`/`None`; `validation is None` ou `collinearity` vazio → conjunto vazio.
  - `elasticity_analysis.bootstrap_coefficients(X, y, n_bootstrap=200, seed=42) -> np.ndarray` (n_bootstrap × k); `bootstrap_average_coefficients` devolve `bootstrap_coefficients(...).mean(axis=0)`.
  - `mmm["bootstrap_coefs"]` (a matriz, em memória; nunca serializada).
  - `Computed.identifiability: dict[str, dict] | None = None`, preenchido em `compute` quando há `mmm`, com `assess(mmm["bootstrap_coefs"], mmm["spend_cols"], width_ratio, collinear_channels(validation, vif_max))`; `width_ratio` e `vif_max` vêm do `cfg["gate_thresholds"]` com os defaults de `GateThresholds`.

- [ ] **Step 1: Escrever os testes que falham.**
  `tests/engine/test_identifiability.py` (matrizes feitas à mão com `numpy`):
  - `test_positive_narrow_ci_is_identifiable`: coluna com valores ~10 ± 1 → `identifiable`, `reasons == []`, `coef_ci` = percentis, `point` = média.
  - `test_ci_crossing_zero_is_not_identifiable`: coluna com valores de −5 a 15 → `reasons == ["ci_crosses_zero"]`.
  - `test_lower_bound_exactly_zero_is_not_identifiable`: coluna com 5% de zeros e o resto positivo → `ci_crosses_zero`.
  - `test_wide_positive_ci_is_too_wide`: IC positivo com largura > ponto → `reasons == ["ci_too_wide"]`; com `width_ratio=2.0` o mesmo canal passa.
  - `test_zero_point_is_never_identifiable`: coluna toda zero → `ci_crosses_zero`.
  - `test_collinear_channel_is_never_identifiable`: IC bom mas canal em `collinear_channels` → `identifiable False`, `reasons == ["collinearity"]`; IC ruim + colinear → ambos os motivos, na ordem IC primeiro.
  - `test_invariant_to_column_order_and_names`.
  - `test_collinear_channels_from_the_report`: com `ValidationReport` cujo `collinearity` tem um par (A, B) e VIF `C: None`, `D: 12.0`, `E: 3.0`, `vif_max=10` → `{"A","B","C","D"}`; `None` e relatório vazio → `set()`.
  `tests/engine/test_elasticity_analysis.py`: `bootstrap_coefficients` devolve forma `(n_bootstrap, k)`; `bootstrap_average_coefficients(X, y, ...)` é **exatamente** `bootstrap_coefficients(...).mean(axis=0)` (`assert_array_equal`) e igual ao cálculo antigo reproduzido no teste (laço original com `default_rng(seed)`).
  `tests/engine/test_config.py`: `identifiability_width_ratio` default 1.0 no JSON Schema de `GateThresholds`; `0`, `-1`, `True`, `"x"` → `EngineError` citando `gate_thresholds`.
  `tests/engine/test_pipeline_stages.py`: `compute` direto sobre o sintético tem `Computed.identifiability` com uma entrada por canal de `mmm["spend_cols"]`; `mmm["bootstrap_coefs"].shape == (200, len(spend_cols))`.

- [ ] **Step 2: Rodar e ver falhar:** `uv run pytest tests/engine/test_identifiability.py tests/engine/test_elasticity_analysis.py tests/engine/test_config.py tests/engine/test_pipeline_stages.py -q -k "identif or bootstrap or width_ratio"` — Expected: FAIL (módulo e funções ausentes).

- [ ] **Step 3: Implementar** conforme as Interfaces. `bootstrap_coefficients` é o corpo atual de `bootstrap_average_coefficients` devolvendo `coefs` em vez de `coefs.mean(axis=0)` (mesma ordem de `rng.integers`, para a média sair idêntica). Em `run_mmm_engine`, guardar `bootstrap_coefs` no dicionário devolvido chamando `bootstrap_coefficients` **uma vez** e usando `.mean(axis=0)` para `mkt_model.coef_` (sem refazer o bootstrap). `assess` usa `np.percentile(coefs, [2.5, 97.5], axis=0)`; ordem dos motivos: IC antes de `collinearity`. `compute` monta `width_ratio`/`vif_max` com `GateThresholds.model_validate(cfg.get("gate_thresholds") or {})`.

- [ ] **Step 4: Rodar e ver passar:** o comando do Step 2 sem `-k` nos quatro arquivos, mais `uv run pytest tests/engine/test_parity.py -q` — Expected: PASS (a paridade sintética continua idêntica).

- [ ] **Step 5: Commit**

```bash
uv run ruff check engine tests/engine && uv run ruff format engine tests/engine
git add engine tests
git commit -m "feat(engine): bootstrap matrix, identifiability rule and config (a5)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Publicação filtrada

**Files:**
- Modify: `engine/results_schema.py` (`ChannelFit.reasons`, `Unidentified`, `Elasticity.unidentified`)
- Modify: `engine/results.py` (`_channel_fits`, `_response_rows`, `_elasticity`)
- Modify: `engine/outputs.py` (`_scenario`, razão de contribuição em `_write_global`)
- Test: `tests/engine/test_results_build.py`, `tests/engine/test_results_schema.py`, `tests/engine/test_outputs.py` (novo ou o arquivo existente que cobre `outputs`), `tests/engine/test_run.py`

**Interfaces:**
- Consumes: `Computed.identifiability`, `UNIDENTIFIED_KEY` (Task 1).
- Produces:
  - `ChannelFit.reasons: list[str] = []`; `Unidentified(channels: list[str] = [], contribution_pct: float | None = None)`; `Elasticity.unidentified: Unidentified | None = None`.
  - `results._channel_fits`: todo canal ativo traz `identifiable`, `coef_ci` (tupla `(lo, hi)`) e `reasons`; se `identifiable` é falso, `contribution_pct`, `hill`, `adstock` e `curve` ficam nulos/vazios.
  - `results._response_rows`: no `mix` de cada variante, canais identificáveis com a própria chave, os demais somados em `UNIDENTIFIED_KEY` (chave só presente se há ao menos um canal oculto).
  - `results._elasticity`: `unidentified` preenchido (nomes e soma de `contribution_pct`) quando há canal oculto, `reasons` com `no_identifiable_channel` se nenhum é identificável; sem `Computed.identifiability` (`None`), nada é filtrado (comportamento anterior).
  - `outputs._scenario`/`ratio`: os splits e a razão usam os canais identificáveis mais `UNIDENTIFIED_KEY`; sem `identifiability`, nada muda.

- [ ] **Step 1: Escrever os testes que falham.**
  `test_results_build.py` (com o `synthetic_computed` e uma `identifiability` montada à mão, setando `computed.identifiability`):
  - `test_unidentified_channel_loses_curve_hill_adstock_and_contribution`: o canal marcado falso tem `hill is None`, `adstock is None`, `curve == []`, `contribution_pct is None`, `identifiable is False`, `reasons == ["ci_crosses_zero"]`, `coef_ci` preenchido; o identificável mantém tudo.
  - `test_mix_pools_hidden_channels_and_keeps_the_row_sum`: para cada linha e variante, o nome do canal oculto não é chave, `UNIDENTIFIED_KEY` está presente e `sum(mix.values())` é igual ao valor antes do filtro (`pytest.approx`).
  - `test_unidentified_section_lists_names_and_summed_contribution`.
  - `test_no_identifiable_channel_still_publishes_the_total`: todos falsos → `elasticity.status == "ok"`, `reasons == ["no_identifiable_channel"]`, `response_curve` e `scenarios` não vazios, todos os canais em `unidentified.channels`.
  - `test_special_characters_in_channel_names`: um canal chamado `GOOGLE DISPLAY/VIDEO` oculto não aparece em nenhuma chave de `mix`.
  - `test_without_identifiability_nothing_is_filtered`: `computed.identifiability = None` → resultado igual ao atual (nenhum campo novo preenchido além de defaults).
  `test_results_schema.py`: `ChannelFit` sem `reasons` e `Elasticity` sem `unidentified` continuam válidos; round-trip em JSON.
  `tests/engine/test_outputs.py` (ou o arquivo existente): com `identifiability` marcando `SEARCH` como oculto, `written.scenarios` não tem `SEARCH` em nenhum split, tem `UNIDENTIFIED_KEY`, e a soma de cada split é igual à do split sem filtro; `SATURATION_CURVE.md` não contém `SEARCH`; o prompt recebido por um `FakeLLM` em `generate_reports` não contém o nome do canal oculto.

- [ ] **Step 2: Rodar e ver falhar:** `uv run pytest tests/engine/test_results_build.py tests/engine/test_results_schema.py tests/engine/test_outputs.py -q -k "unidentified or identif or pools or hidden or special_characters or without_identifiability"` — Expected: FAIL.

- [ ] **Step 3: Implementar.** Um helper em `engine/identifiability.py`, `pool(mapping: dict[str, float], hidden: set[str]) -> dict[str, float]`, soma os ocultos em `UNIDENTIFIED_KEY` (sem criar a chave se `hidden` é vazio) e é usado por `results._response_rows` e `outputs._scenario`/razão de contribuição, para um só lugar decidir o balde. `_channel_fits`: `identifiable`/`reasons`/`coef_ci` vêm de `computed.identifiability[nome]`. `_elasticity` calcula `unidentified` e o motivo informativo. Arquivos legados por canal (`generate_individual_response_curves`) não mudam.

- [ ] **Step 4: Rodar e ver passar** o comando do Step 2 sem `-k`, mais `uv run pytest tests/engine/test_results_run.py tests/engine/test_results_fixtures.py tests/engine/test_hygiene.py -q`. As fixtures de `results.json` ainda não foram regeneradas: se `test_results_fixtures.py` falhar só pelos campos novos, é tratado na Task 3. Expected: PASS nos demais.

- [ ] **Step 5: Suíte completa e paridade.** Em background, `mise run test > <log> 2>&1`, ler o fim do log, e `mise run parity-real` — Expected: verde, exceto, se for o caso, os testes de fixtures da Task 3; paridade da Gol e do sintético idêntica.

- [ ] **Step 6: Commit**

```bash
uv run ruff check engine tests/engine && uv run ruff format engine tests/engine
git add engine tests
git commit -m "feat(engine): publish only identifiable channels and pool the rest in results and the llm payload (a5)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Aceite com efeito forte, dados reais, fixtures e documentação

**Files:**
- Modify: `tests/engine/synthetic_data.py` (opção para um dataset de efeito forte, sem alterar o `make_dataset` atual), `tests/engine/test_run.py`
- Modify: `tests/engine/test_validate_real.py` ou novo `tests/engine/test_identifiability_real.py` (Gol)
- Modify: `tests/fixtures/results/generate_fixtures.py` e os JSON, se mudarem
- Modify: `docs/decisoes/engine.md`, `docs/m2/trilha-a-motor.md` (Status do A5), `docs/m2/README.md` (§3: `identifiable`, `unidentified`), `CLAUDE.md` (mapa e "Estado atual"), `docs/decisoes/upload-e-storage.md` não muda

**Interfaces:**
- Consumes: tudo das Tasks 1–2.
- Produces: `synthetic_data.make_strong_effect_dataset(out_dir, *, seed=7, n_days=...) -> dict[str, Path | None]` com um canal de efeito real forte (`STRONG`), um canal sem efeito (`NULL`) e os demais pequenos, e as constantes `STRONG`/`NULL`.

- [ ] **Step 1: Escrever os testes que falham.**
  - `test_strong_effect_channel_is_identifiable_and_null_channel_is_not` (em `test_run.py`, run completo com `make_strong_effect_dataset` e `LLM_PROVIDER=none`): `channels[STRONG].identifiable is True` e tem `curve`/`hill`; `channels[NULL].identifiable is False`, sem `curve`/`hill`.
  - `test_run_with_a_hidden_channel_has_no_curve_or_mix_for_it`: no mesmo run, o JSON serializado do canal `NULL` não aparece como chave de nenhum `mix`, não tem curva individual, e a chave `nao_identificavel` aparece; a soma de cada linha do mix bate com a do mesmo run lido sem filtro (via `computed`).
  - Gol (pulado sem `exemplo_csv/`): registra quantos canais passam (hoje 0 de 12) e que `unidentified.channels` lista os 12; o total (`response_curve`) continua publicado.
  - `block_per_channel` + canais colineares: com o dataset de `with_twin` do A3 e `block_per_channel=True`, o canal gêmeo sai `identifiable=false` com `collinearity` no `results.json`.

- [ ] **Step 2: Rodar e ver falhar:** `uv run pytest tests/engine/test_run.py -q -k "strong_effect or hidden_channel or block_per_channel"` — Expected: FAIL (helper e comportamento ausentes).

- [ ] **Step 3: Implementar o helper e ajustar o dataset** até o aceite ser estável: canal `STRONG` com resposta clara e variação grande de spend, `NULL` sem relação com o KPI; **sem afrouxar a regra nem o limiar** para fazer passar. Se o efeito forte não ficar identificável com a regra literal, o resultado vai na documentação e a pergunta volta para o dono.

- [ ] **Step 4: Fixtures e Gol.** Regenerar os JSON de `tests/fixtures/results/` (`uv run python tests/fixtures/results/generate_fixtures.py`, em background) e conferir `git diff --stat`: devem mudar `elasticity.channels` (campos de identificabilidade), `unidentified`, `mix` e `reasons`. Rodar `uv run pytest tests/engine/test_results_fixtures.py tests/engine/test_results_run.py -q` — Expected: PASS.

- [ ] **Step 5: Documentação.** `docs/decisoes/engine.md`: seção "Identificabilidade (A5)" com o porquê (bootstrap do Ridge positivo; regra literal; bootstrap sem restrição descartado por dar sinais errados), a medição (Gol 0 de 12, sintético 0 de 5), o balde `nao_identificavel`, o limite (a parcela do balde ainda vem de coeficientes não identificados; A8), os arquivos legados e o que o Dev B precisa. `docs/m2/trilha-a-motor.md`: `Status` do A5 com data e o que foi verificado. `docs/m2/README.md` §3: `identifiable`, `reasons`, `unidentified`. `CLAUDE.md`: mapa (`identifiability.py`) e "Estado atual".

- [ ] **Step 6: Verificação final.** `uv run ruff check . && uv run ruff format --check .`; suíte completa em background e `mise run parity-real` — Expected: tudo verde.

- [ ] **Step 7: Commit**

```bash
git add -A tests docs CLAUDE.md
git commit -m "docs: mark a5 done and record the identifiability decisions

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```
