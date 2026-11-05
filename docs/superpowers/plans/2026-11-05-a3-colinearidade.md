# A3 · Gate de colinearidade — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `validate` mede colinearidade (correlação par a par e VIF do spend cru), sugere grupos e bloqueia o run enquanto o analista não agrupar (`channel_groups`) ou aceitar (`block_per_channel`); o agrupamento soma o spend antes de modelar.

**Architecture:** Um passo `apply_groups` (`engine/grouping.py`) roda logo depois de `read_inputs`, compartilhado por `validate` e `load_and_prepare_data`. `engine/collinearity.py` é uma função pura sobre a tabela larga `Date × canal`. O gate é avaliado no conjunto efetivo de canais dentro do `validate`; o `run` já valida primeiro e aborta com `EngineError.check_id`.

**Tech Stack:** Python 3.13, pandas 3.0.3, numpy 2.5.0, statsmodels 0.14.6 (`variance_inflation_factor`), pydantic v2, pytest. Lint: ruff, linha de 120, sem `print()`.

**Spec:** `docs/superpowers/specs/2026-11-05-a3-colinearidade-design.md` (a autoridade; em conflito, ela vence).

## Global Constraints

- Mensagens na tela em pt-BR, sem caminhos nem dados do cliente além de nomes de canal e números agregados.
- Ids dos checks estáveis: `collinearity_unresolved` (error), `collinearity_blocked` (warning), `group_unknown_channel`, `group_overlap`, `group_too_small` (todos error).
- `gate_thresholds`: `collinearity_r` default 0.85, número em (0, 1]; `vif_max` default 10, número ≥ 1. Valor inválido numa chave conhecida → `EngineError` de config; chave desconhecida é ignorada.
- `channel_groups` continua `list[list[str]]`; nome do grupo = `" + ".join(membros)` (membros em maiúsculas, ordem do config). Membros comparados em maiúsculas e sem espaços nas pontas.
- Colinearidade usa o **spend cru** sem os períodos parciais descartados (o mesmo conjunto de `check_channel_overlap`); par sinalizado se `abs(r) > collinearity_r`; canais constantes ou de soma zero ficam fora.
- Sem `channel_groups` e sem colinearidade, nada muda: paridade sintética e `parity-real` idênticas.
- Suíte completa leva ~9,5 min: rode só os testes afetados durante a tarefa e a suíte inteira nas Tasks 3 e 4 (em background, lendo o final do log).
- Matemática só em Python; nome de coluna nunca hardcoded; commits terminam com `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.

## Review Focus

- **Gol no limite:** a Gol consolidada tem um par (`GOOGLE DISPLAY/VIDEO` × `KAYAK`) com \|r\| = 0.8501 (medido antes do corte de períodos parciais), logo acima do default 0.85. Com o gate ligado o `parity-real` falharia por `collinearity_unresolved`. Teste: o `GOL_CONFIG` do parity passa `block_per_channel=True` (não muda número nenhum no A3) e `test_validate_real.py` registra o resultado da Gol sem e com o bloqueio.
- Ruído de ponto flutuante no limiar: \|r\| exatamente igual ao limiar não sinaliza (`>` estrito); teste com limiar igual a r calculado.
- Menos linhas que canais + 1: VIF vira dicionário vazio, sem exceção, e os pares ainda são avaliados.
- Grupo com todos os canais: sobra um canal, nenhuma colinearidade, o run segue com 1 canal.
- Nomes de grupo com caixa e espaços diferentes (`" search "`) resolvem para o mesmo canal.
- Cadência semanal: agrupar e medir colinearidade funcionam com uma linha por semana.

---

### Task 1: Config e passo de agrupamento

**Files:**
- Modify: `engine/config.py` (campo `block_per_channel`, validação de `gate_thresholds`)
- Create: `engine/grouping.py`
- Modify: `engine/results.py:239` (usar `group_name`)
- Test: `tests/engine/test_grouping.py` (novo), `tests/engine/test_config.py`

**Interfaces:**
- Consumes: `Check` (`engine/results_schema.py`); investimento longo `Date`, `Product Group`, `investment` (saída de `read_inputs`).
- Produces:
  - `EngineConfig.block_per_channel: bool = False`.
  - `engine.grouping.group_name(members: list[str]) -> str` → `" + ".join` dos membros normalizados (maiúsculas, `strip`).
  - `engine.grouping.apply_groups(investment_df: pd.DataFrame, groups: list[list[str]]) -> tuple[pd.DataFrame, list[Check]]`. Sem erro devolve o investimento agrupado (mesmas colunas, uma linha por (Date, canal)) e `[]`; com erro devolve o DataFrame **inalterado** e os checks `error`.
  - `engine.grouping.thresholds(config: dict) -> tuple[float, float]` → `(collinearity_r, vif_max)` lendo `gate_thresholds` do dict legado, com os defaults.

- [ ] **Step 1: Escrever os testes que falham** em `tests/engine/test_grouping.py`:
  - `test_group_name_normalizes_and_keeps_config_order`: `group_name([" search", "pmax "]) == "SEARCH + PMAX"`.
  - `test_apply_groups_sums_members_per_date`: 2 datas × canais A, B, C; `apply_groups(df, [["a", "b"]])` devolve canais `{"A + B", "C"}`, com `A + B` = soma por data; as demais linhas intactas; `Product Group` normalizado.
  - `test_missing_member_row_sums_what_exists`: A tem a data D1, B não → `A + B` em D1 = valor de A.
  - `test_unknown_channel`: grupo com `"X"` inexistente → check `group_unknown_channel` (error), `details["channels"] == ["X"]`, DataFrame devolvido igual ao de entrada.
  - `test_overlap`: `[["A","B"],["B","C"]]` → `group_overlap`, `details["channels"] == ["B"]`.
  - `test_too_small`: `[["A"]]` → `group_too_small`; também `[["A","a"]]` (mesmo canal duas vezes) → `group_too_small`.
  - `test_all_channels_in_one_group_leaves_one_channel`.
  - `test_no_groups_returns_input_unchanged`: `[]` devolve o mesmo conteúdo, sem checks.
  - Em `tests/engine/test_config.py`: `block_per_channel` default `False`; `gate_thresholds={"collinearity_r": 1.5}` e `{"vif_max": 0.5}` e `{"vif_max": "x"}` → `EngineError` cuja mensagem cita `gate_thresholds`; `{"outra_chave": 1}` aceita.

- [ ] **Step 2: Rodar e ver falhar:** `uv run pytest tests/engine/test_grouping.py tests/engine/test_config.py -q` — Expected: FAIL (módulo `engine.grouping` inexistente / campo ausente).

- [ ] **Step 3: Implementar** `engine/grouping.py` conforme as Interfaces. `apply_groups` valida na ordem unknown → overlap → too_small, acumulando os três tipos; só agrupa se não houver erro; soma com `groupby(["Date", "Product Group"], as_index=False)["investment"].sum()` depois de renomear os membros para `group_name`. `thresholds` tolera `gate_thresholds` ausente ou `None`. Em `engine/config.py`: campo `block_per_channel: bool = False` (na seção "filled by the system"), e um `field_validator("gate_thresholds")` que valida `collinearity_r` (0 < v ≤ 1) e `vif_max` (v ≥ 1), número real e não-bool, com mensagem pt-BR que cita o campo (o `_describe` já prefixa `campo 'gate_thresholds'`). Em `engine/results.py:239` trocar o `" + ".join(members)` por `group_name(members)` (e `members=` pelos normalizados).

- [ ] **Step 4: Rodar e ver passar:** mesmo comando do Step 2 mais `uv run pytest tests/engine/test_results_build.py -q` — Expected: PASS (o teste de `groups` em `test_results_build.py:237` continua verde).

- [ ] **Step 5: Commit**

```bash
uv run ruff check engine tests/engine && uv run ruff format engine tests/engine
git add engine/config.py engine/grouping.py engine/results.py tests/engine/test_grouping.py tests/engine/test_config.py
git commit -m "feat(engine): channel group step and block_per_channel config (a3)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Análise de colinearidade

**Files:**
- Create: `engine/collinearity.py`
- Test: `tests/engine/test_collinearity.py` (novo)

**Interfaces:**
- Consumes: `Collinearity` (`engine/results_schema.py`: `pairs: list[dict]`, `vif: dict[str, float | None]`, `suggested_groups: list[list[str]]`).
- Produces: `engine.collinearity.analyze(wide: pd.DataFrame, r_max: float, vif_max: float) -> Collinearity`, e `engine.collinearity.flagged(result: Collinearity, vif_max: float) -> tuple[list[dict], list[str]]` → `(pairs, canais com VIF acima do limiar ou null)`. `wide` é a tabela `Date × canal` já sem parciais e com 0 onde falta.

- [ ] **Step 1: Escrever os testes que falham** em `tests/engine/test_collinearity.py` (séries com `numpy.random.default_rng(1)`):
  - `test_pair_above_threshold_is_flagged_with_signed_r`: B = A·1.1 + ruído pequeno → `pairs == [{"a":"A","b":"B","r":<~0.99>}]`, `a < b`, `r` com 4 casas.
  - `test_negative_correlation_counts`: B = −A + constante + ruído → par sinalizado com `r < 0`.
  - `test_threshold_is_strict`: com `r_max` igual ao \|r\| calculado do par (use o valor retornado por `numpy.corrcoef`), o par **não** é sinalizado.
  - `test_vif_matches_manual_regression`: 3 canais pequenos (30 linhas); VIF de cada um comparado a `1 / (1 - R²)` calculado no teste com `numpy.linalg.lstsq` (intercepto incluído), `pytest.approx(rel=1e-6)`.
  - `test_independent_channels_have_low_vif_and_no_groups`: `pairs == []`, `suggested_groups == []`, VIFs < 1.5.
  - `test_perfect_collinearity_gives_null_vif`: B = 2·A → `vif["A"] is None and vif["B"] is None`; `flagged` os devolve.
  - `test_constant_and_zero_channels_are_ignored`: coluna constante e coluna só de zeros ficam fora de `pairs` e `vif`, sem exceção.
  - `test_fewer_rows_than_channels_has_empty_vif_but_still_pairs`: 3 linhas, 4 canais → `vif == {}`; pares ainda calculados.
  - `test_single_channel`: `analyze` com 1 canal → tudo vazio.
  - `test_suggested_groups_are_connected_components`: pares (A,B) e (B,C) → `[["A","B","C"]]`; D isolado não aparece; grupos e membros ordenados.
  - `test_vif_only_channel_joins_its_most_correlated_partner`: três canais com C ≈ A + B (nenhum par acima de 0.85, VIF de C > 10) → C aparece num grupo com o canal de maior \|r\| com ele.
  - `test_invariant_to_column_order_and_names`: embaralhar colunas e renomear com prefixo preserva pares, VIF e grupos (módulo o rename).

- [ ] **Step 2: Rodar e ver falhar:** `uv run pytest tests/engine/test_collinearity.py -q` — Expected: FAIL (módulo inexistente).

- [ ] **Step 3: Implementar** `analyze`: remover colunas com `std() == 0` ou soma ≤ 0; pares via `DataFrame.corr()` sobre as colunas restantes (ordenar nomes; `a < b`; ordenar por \|r\| decrescente e depois por nome); VIF com `statsmodels.stats.outliers_influence.variance_inflation_factor` sobre a matriz com constante (`statsmodels.api.add_constant`), só se `n_linhas > n_canais + 1` e `n_canais ≥ 2`; resultado infinito ou NaN → `None`; arredondar `r` e VIF a 4 casas. Grupos sugeridos: componentes conexos com `networkx`-free (DFS/union-find simples); canais com VIF > `vif_max` (ou `None`) e fora de qualquer par ganham uma aresta para o canal de maior \|r\|. Suprimir os `RuntimeWarning` de divisão por zero do statsmodels com `numpy.errstate`. `flagged` aplica a mesma regra.

- [ ] **Step 4: Rodar e ver passar:** `uv run pytest tests/engine/test_collinearity.py -q` — Expected: PASS.

- [ ] **Step 5: Commit**

```bash
uv run ruff check engine tests/engine && uv run ruff format engine tests/engine
git add engine/collinearity.py tests/engine/test_collinearity.py
git commit -m "feat(engine): pairwise correlation, vif and suggested groups (a3)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Gate no `validate`, agrupamento no loader e no `run`

**Files:**
- Modify: `engine/validation.py` (`validate`, novo `check_collinearity`)
- Modify: `engine/data_preprocessor.py` (`load_and_prepare_data`, logo depois de `read_inputs`)
- Modify: `tests/engine/csv_factory.py` (helpers `correlated_rows`, `with_twin`)
- Modify: `tests/engine/real_data.py` (`GOL_CONFIG` ganha `"block_per_channel": True`)
- Test: `tests/engine/test_validate_collinearity.py` (novo), `tests/engine/test_run.py`

**Interfaces:**
- Consumes: `apply_groups`, `thresholds` (Task 1); `analyze`, `flagged` (Task 2); `_series_checks`, `check_partial` existentes.
- Produces: `validate` preenche `report.collinearity` e `report.channels` com o conjunto efetivo e emite os checks da tabela do spec. `engine.validation.check_collinearity(investment_df, config: dict, groups_applied: bool) -> tuple[Collinearity, list[Check]]` onde `investment_df` é o investimento efetivo sem parciais. `load_and_prepare_data` levanta `EngineError(check.message, check.id)` para erro de grupo e entrega o investimento agrupado.
- Helpers de teste: `correlated_rows(n, r_noise=0.02) -> (investment_rows, kpi_rows)` com canais `A`, `B` (≈ A) e `C` (independente) para `write_inputs`; `with_twin(paths, source="SEARCH", twin="SEARCH2", noise=0.02) -> paths` reescreve `investment.csv` do `make_dataset` adicionando o canal gêmeo (spend = fonte × (1 + ruído)).

- [ ] **Step 1: Escrever os testes que falham.**
  `tests/engine/test_validate_collinearity.py`:
  - `test_flagged_pair_blocks_with_suggestion`: `correlated_rows` → `ok is False`, check `collinearity_unresolved` (error) com `details` contendo `pairs`, `vif_channels` e `suggested_groups == [["A","B"]]`; `report.collinearity.pairs[0]["a"] == "A"`.
  - `test_group_resolves_and_becomes_one_channel`: mesmo dado com `channel_groups=[["A","B"]]` → `ok`, `report.channels == ["A + B", "C"]`, `collinearity.pairs == []`.
  - `test_block_per_channel_turns_error_into_warning`: `block_per_channel=True` → `ok`, check `collinearity_blocked` (warning), sem `collinearity_unresolved`.
  - `test_group_still_colliding_with_another_channel_stays_unresolved`: três canais A, B, D com D ≈ A (B ≈ A também); agrupar só A+B ainda colide com D → `collinearity_unresolved`.
  - `test_group_errors_skip_the_gate`: grupo desconhecido → `group_unknown_channel`, `ok=False`, e nenhum `collinearity_unresolved` no relatório; idem `group_overlap` e `group_too_small`.
  - `test_group_names_are_matched_case_and_space_insensitively`: `[[" a ", "b"]]` resolve.
  - `test_thresholds_come_from_gate_thresholds`: `gate_thresholds={"collinearity_r": 0.999}` com r ≈ 0.99 → sem erro; `{"vif_max": 1000}` idem se só o VIF sinalizava.
  - `test_weekly_cadence_groups_and_gates`: dataset semanal via `make_dataset(cadence_days=7)` + `with_twin` → erro sem grupo, ok com grupo.
  - `test_loader_agrees_with_validate_on_group_errors`: para `group_unknown_channel`, `group_overlap`, `group_too_small`, `load_and_prepare_data(legacy_config com os grupos, paths)` levanta `EngineError` com `check_id` igual ao do primeiro erro de `validate`.
  - `test_loader_returns_grouped_investment`: com grupo válido o `PreparedData` tem a coluna do grupo e não as dos membros.
  - `test_validate_stays_fast_with_collinearity`: 730 dias × 15 canais < 10 s.
  Em `tests/engine/test_run.py`:
  - `test_run_stops_on_unresolved_collinearity`: `with_twin` sem grupo → `EngineError.check_id == "collinearity_unresolved"`, nenhuma saída de modelo gravada.
  - `test_run_with_group_publishes_only_the_group` (aceite do item): `with_twin` + `channel_groups=[["SEARCH","SEARCH2"]]` → run conclui; o `results.json` tem o canal `SEARCH + SEARCH2` e **nenhum** canal `SEARCH` ou `SEARCH2` isolado em `elasticity.channels`; `elasticity.groups` lista o grupo; `validation.collinearity.pairs == []`.
  - `test_run_with_block_per_channel_runs`: `with_twin` + `block_per_channel=True` → conclui, `validation` traz `collinearity_blocked`.

- [ ] **Step 2: Rodar e ver falhar:** `uv run pytest tests/engine/test_validate_collinearity.py tests/engine/test_run.py -q -k "collinearity or group or block_per or twin or unresolved"` — Expected: FAIL (colinearidade vazia, grupos sem efeito).

- [ ] **Step 3: Implementar.** `validate`: depois do `read_inputs`, `groups = config.channel_groups`; `investment, group_checks = apply_groups(raw.investment_df, groups)`; se houver erro de grupo, devolve o relatório com `raw.checks + group_checks`, `collinearity=Collinearity()`, `ok=False` e **sem** rodar o resto da colinearidade (as demais checagens de série rodam sobre o investimento cru). Sem erro, rodar `_series_checks` sobre uma cópia de `raw` com o investimento efetivo, depois `check_collinearity` sobre o investimento efetivo sem parciais (reaproveite `check_partial`), e preencher `channels` com os nomes efetivos. `check_collinearity` pivota (`pivot_table(...).fillna(0)`), chama `analyze` com `thresholds(config)`, e emite `collinearity_unresolved` (error) ou `collinearity_blocked` (warning) com mensagem pt-BR que cita os canais e `details = {"pairs", "vif_channels", "suggested_groups"}`. `load_and_prepare_data`: logo depois do laço de `raw.checks`, `daily_investment_df, group_checks = apply_groups(raw.investment_df, config.get("channel_groups") or [])` e levantar o primeiro erro com `check_id`; o resto do corpo usa o investimento agrupado. Ajustar `tests/engine/real_data.py` conforme Review Focus. Se o import de `engine.grouping` em `data_preprocessor` criar ciclo, importar localmente como já é feito com `engine.inputs`.

- [ ] **Step 4: Rodar e ver passar** o comando do Step 2 sem `-k` nos dois arquivos, mais `uv run pytest tests/engine/test_validate_checks.py tests/engine/test_data_preprocessor.py tests/engine/test_results_run.py -q` — Expected: PASS (nada existente muda; os datasets limpos têm \|r\| ≤ 0.18).

- [ ] **Step 5: Suíte completa e paridade.** Em background, `mise run test > <log> 2>&1`, ler o final do log — Expected: tudo verde (esperado ~800 passed, 3 skipped). Depois `mise run parity-real` — Expected: 6 passed (Gol com `block_per_channel=True`, números idênticos).

- [ ] **Step 6: Commit**

```bash
uv run ruff check engine tests && uv run ruff format engine tests
git add engine tests
git commit -m "feat(engine): validate gates collinearity and run groups channels before modelling (a3)

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Dados reais, fixtures e documentação

**Files:**
- Modify: `tests/engine/test_validate_real.py`
- Modify: `tests/fixtures/results/generate_fixtures.py` e os 3 JSON, só se mudarem de conteúdo
- Modify: `docs/decisoes/engine.md`, `docs/m2/trilha-a-motor.md` (Status do A3), `docs/decisoes/upload-e-storage.md`, `CLAUDE.md` (mapa e "Estado atual"), `engine/__init__.py` (nada a exportar; conferir)

**Interfaces:**
- Consumes: tudo das Tasks 1–3.
- Produces: registro dos resultados nos dados reais e a nota de swap para o Dev B.

- [ ] **Step 1: Smoke nos dados reais.** Em `test_validate_real.py` (pulado sem `exemplo_csv/`) adicionar:
  - `test_gol_consolidated_flags_google_display_video_and_kayak`: `validate` da Gol consolidada com `block_per_channel=False` → `collinearity_unresolved` citando o par `GOOGLE DISPLAY/VIDEO` × `KAYAK` (ou, se o corte de períodos parciais o levar a 0.85 ou menos, registrar o valor real no teste e na nota e ajustar a asserção para o que o dado mostra, **sem** afrouxar o limiar); com `block_per_channel=True` → `ok` e `collinearity_blocked`.
  - PMAX semanal (um canal só) → sem checks de colinearidade; VW (faturamento total) idem.
  Rodar: `uv run pytest tests/engine/test_validate_real.py -q` — Expected: PASS; anotar os números reais para a documentação.

- [ ] **Step 2: Fixtures.** `uv run python tests/fixtures/results/generate_fixtures.py` e `git diff --stat tests/fixtures/results`. Se mudou algo além de `validation.collinearity`, investigar antes de seguir; rodar `uv run pytest tests/engine/test_results_fixtures.py tests/engine/test_results_contract.py -q` — Expected: PASS.

- [ ] **Step 3: Documentação.** `docs/decisoes/engine.md`: seção "Colinearidade (A3)" com o porquê (spend cru, conjunto efetivo, spec A=passo compartilhado), os ids, as chaves de `gate_thresholds`, `block_per_channel`, o achado da Gol no limiar e a nota de swap do Dev B (campo `block_per_channel` no `EngineConfig` provisório da API; `channel_groups` em dict gravado por um teste do B3 não passa no modelo estrito; tela de agrupamento do B2 com os ids novos). `docs/m2/trilha-a-motor.md`: linha `Status` do A3 com data e o que foi verificado (inclui o resultado da Gol). `docs/decisoes/upload-e-storage.md`: nota de que o `validate` real traz `collinearity`. `CLAUDE.md`: mapa (`grouping.py`, `collinearity.py`) e parágrafo "Estado atual" com o A3.

- [ ] **Step 4: Verificação final.** `uv run ruff check . && uv run ruff format --check .`; suíte completa em background — Expected: verde.

- [ ] **Step 5: Commit**

```bash
git add tests docs CLAUDE.md engine
git commit -m "docs: mark a3 done and record collinearity decisions

Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>"
```
