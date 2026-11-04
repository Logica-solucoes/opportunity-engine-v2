# A1 — `results.json` v1 e fixtures (design)

Item A1 da Trilha A (`docs/m2/trilha-a-motor.md`). Contrato de origem: `docs/m2/README.md` §3. Código de partida: `engine/pipeline.py` (`compute`, `run`), A0 concluído em 04/nov/2026 (`docs/decisoes/engine.md`).

## Intenção e por quê

Hoje `engine.run` calcula tudo, escreve CSV/PNG/HTML/MD e devolve só o cabeçalho do contrato (todas as seções `null`). O dashboard (B5), o histórico (B6) e o export (B7) precisam de **um documento único, tipado e versionado** com o resultado do run, em vez de remontar arquivos por glob e regex como o Streamlit faz. O A1 cria esse documento, grava em `out_dir/results.json` e entrega fixtures reais para o Dev B construir telas sem esperar o motor.

O A1 **não calcula nada novo**: transporta o que o `compute()` já produz (e a paridade de 1e-9 continua valendo). O que ainda não existe (A2 e A4–A9) tem lugar no schema e sai `null`.

## Metas

1. `engine/results_schema.py`: modelos pydantic (`extra="forbid"`) de **todo** o contrato §3, `schema_version = 1`, com `model_json_schema()` como contrato publicável para o front.
2. `engine/results.py`: `build_results(computed, engine_version) -> ResultsV1` a partir do `Computed`, sem recalcular estatística.
3. `engine.run` devolve o dict (`model_dump(mode="json")`) e grava o mesmo em `out_dir/results.json`.
4. JSON sem `NaN`/`Infinity` e sem sentinelas: valores não finitos viram `null`; `cpa_incremental` com lift zero vira `null`.
5. `status` do run derivado das seções (ver "Status"), com `reasons` em cada seção.
6. Fixtures em `tests/fixtures/results/` gerados da **Gol anonimizada**, mais o script de anonimização e um teste de guarda.

## Não-metas

- `validation`, `sufficiency`, `experiment_design`, `reports`, placebo, identificabilidade, IC das curvas, `extrapolated`, guardrails e `engine.scenario` (A2, A3, A5–A9): saem `null`. O schema já os tipa para que esses itens só passem a preenchê-los.
- Trocar `api/worker.py`, `api/engine_run.py` ou o front (Dev B). O worker continua gravando seu próprio `results.json` até o swap; como `run` devolve o mesmo dict já seguro, os dois arquivos são idênticos.
- Parar de gerar PNG/HTML do matplotlib (decisão em aberto do item): **continuam sendo gerados** no M2 até o B5 estar em paridade.
- Mudar qualquer número, gate ou limiar. Um número diferente do `compute()` é falha.

## Anti-metas

- `NaN`, `Infinity` ou `999999` no JSON.
- Campo que o front precise recalcular (curva, CPA, ponto ótimo): a matemática fica só em Python.
- Dado real de cliente (nome de canal, valor, caminho de arquivo) em qualquer fixture versionado.

## Restrições

- Contrato §3: nomes do README são o ponto de partida; este documento fecha o formato das seções que o A1 preenche.
- `CODE-STYLE.md`: sem `print()`, pt-BR nas mensagens que chegam à tela, `ruff` (linha 120), nome de coluna nunca hardcoded (o `Computed` já usa nomes internos).
- Paridade: `tests/engine/test_parity.py` e `test_parity_real.py` continuam passando sem mudança.
- Dados reais só com 1 thread de BLAS (`docs/decisoes/engine.md`); os testes que rodam a Gol fixam isso.

## Abordagens consideradas

- **Opção 1 (escolhida, 04/nov): modelos fechados para todo o contrato.** Seções dos itens futuros existem no schema, opcionais e `null`. O front gera tipos de uma fonte só; A5–A9 só preenchem. Custo: o A1 fixa nomes que os outros itens podem querer ajustar (ajuste aditivo não muda `schema_version`; remoção ou renomeação muda).
- Opção 2: modelos fechados só para `causal` e `elasticity`, seções futuras `dict | None`. Descartada: o B5 ficaria sem tipos para o que vem depois e cada item redefiniria o contrato.

## Schema

Todos os modelos `extra="forbid"`. Floats são finitos ou `None`. Datas em `YYYY-MM-DD`.

**Raiz `ResultsV1`:** `schema_version: Literal[1]`, `engine_version: str`, `status: "succeeded"|"inconclusive"|"failed"`, `validation: ValidationReport | None`, `sufficiency: Sufficiency | None`, `causal: Causal | None`, `elasticity: Elasticity | None`, `experiment_design: ExperimentDesign | None`, `reports: Reports | None`, `baseline: Baseline | None`.

**Tipos do futuro, só o formato do README** (o item dono aperta os campos livres): `ValidationReport` (A2, §2: `ok`, `cadence`, `period_days`, `date_range`, `channels`, `checks[{id, level, message, details}]`, `collinearity`), `Sufficiency` (A6: `passed`, `spend_variation: dict`, `validated_events`, `pre_wmape`), `ExperimentDesign` (A7: `dict`), `Reports` (A9: `events: dict[str, dict]`, `global_: dict | None` serializado como `global`, `grounding: {status, issues}`). No A1 todos saem `null`.

**`Causal`:** `status`, `reasons: list[str]`, `events_detected`, `events`.
- `events_detected[]`: `date` (data da intervenção), `channels: list[str]`, `investment_change_pct: float | None`, `eligible: bool`. Vem de **todos** os candidatos do `detect_events`.
- `events[]` (só os analisados, ou seja, elegíveis): `id`, `channels`, `start`, `end` (janela efetivamente medida, `results_data.start_date/end_date`), `status: "published"|"rejected"`, `reasons` (os `EventOutcome.reasons`, mais `not_selected` se passou mas ficou fora de `max_events_to_analyze`), `selected: bool`, `lift {abs, ci: [lo, hi], rel_pct}`, `p_value`, `investment_change_pct`, `incremental_investment` (= `total_investment_post_period`), `cpa_incremental` (`None` se `absolute_lift == 0`), `fit {r2, mae, mape, wmape: None}`, `placebo: None`, `series {line, accuracy, investment, kpi}`.
- `status` de evento: `published` se `passed` **e** `selected`. Passou mas não selecionado = `rejected` com `not_selected`. O front não interpreta gate; só lê `status` e `reasons`.
- `series` são listas de registros dos quatro DataFrames do `EventOutcome`: `line` (`date, actual_kpi, forecasted_kpi, investment`), `accuracy` (`date, kpi, predicted`, mais `mae` no registro como hoje), `investment` (`period, investment`), `kpi` (`category, kpi`). Nomes em `snake_case`, `NaN` → `None`. Eventos que falharam na análise (`results_data` nulo) saem com `lift`, `fit` e `series` `None` e `reasons=["analysis_failed"]`.

**`Elasticity`:** `status`, `reasons`, `metrics`, `channels`, `groups`, `response_curve`, `scenarios`.
- `metrics`: `cv_r2`, `r2`, `media_contribution_pct` (= `marketing_contribution_of_kpi_pct`), `low_confidence: None`, `reallocation_suppressed: None` (A5/A8).
- `channels[]`: `name`, `contribution_pct`, `identifiable: None`, `coef_ci: None`, `hill {K, n}` (de `ks`, `ss`), `adstock` (de `alphas`), `observed_spend_range [min, max]` do gasto diário observado, `curve [{x, y, lo: None, hi: None, extrapolated: None}]` (curva individual: o `generate_individual_response_curves` passa a **devolver** o DataFrame além de exportar o CSV; números intactos).
- `groups[]`: `name` (membros unidos por " + "), `members`, de `channel_groups` da config.
- `response_curve[]` (uma linha por ponto da curva agregada): `investment` ← `Daily_Investment`, `kpi` ← `Projected_Total_KPIs`, `kpi_lo/kpi_hi: None`, `revenue` ← `Projected_Revenue`, `icpa` ← `iCPA`, `iroas` ← `Incremental_ROI` **se for receita incremental sobre investimento; se for outra coisa, `None` e a divergência vai para o ledger**, `incremental_investment`, `incremental_kpi`, `extrapolated: None`, `mix: {historical, optimized, strategic}` (cada um `{canal: gasto}` a partir das colunas `Spend_<canal>_<Historical|Optimized|Strategic>`).
- `scenarios[]`: os pontos notáveis não nulos do `Computed`, com `name` em `current` (baseline), `max_efficiency`, `strategic_limit`, `diminishing_return`, `saturation`, `strategic_reallocation`; cada um com `investment`, `kpi`, `icpa`, `incremental_investment`, `incremental_kpi` quando existirem no ponto, `cpa: None`, `roas: None`, `kpi_lo/kpi_hi: None`, `extrapolated: None`, `ramp: None`. O A8 redefine/amplia; o A1 só empacota.

**`Baseline`** (para o dashboard não recarregar dados): `monthly [{month: "YYYY-MM", kpi, investment, by_channel: {canal: investimento}}]`, somas mensais do `PreparedData`.

### Status

Cada seção ganha `status` ∈ `ok | inconclusive | failed` e `reasons`:

| Seção | `ok` | `inconclusive` (reasons) | `failed` |
|---|---|---|---|
| `causal` | ≥ 1 evento `published` | `no_events_detected`, `no_eligible_events`, `no_event_passed_gates` | — |
| `elasticity` | MMM e curva produzidos | — | `model_failed` (MMM nulo) |

Status do run: `succeeded` se as duas seções `ok`; `failed` se nenhuma `ok`; `inconclusive` nos demais casos. Isto **muda** o A0 num caso: MMM ok sem nenhum evento aprovado era `succeeded` e passa a `inconclusive`. O worker já trata `inconclusive` como final (`FINAL_STATUSES`). Seção não produzida sai `null` (não um objeto vazio).

## Mudanças no código existente (sem alterar números)

- `Computed` ganha `candidates: pd.DataFrame` (hoje o `compute()` descarta o resultado do `detect_events`) e `individual_curves_df: pd.DataFrame | None`.
- `detect_events` passa a manter `percentage_change` como coluna `investment_change_pct` (o `find_events` já a calcula e descarta).
- `generate_individual_response_curves` devolve o DataFrame (hoje só exporta); chamadores atuais ignoram o retorno.
- `outputs.py` e a ordem das gravações ficam como estão; `run()` acrescenta `results.json` ao final.

## Serialização

`build_results` monta o modelo; `run` chama `model_dump(mode="json")`, passa por um `sanitize` que troca `float('nan')`, `inf` e `-inf` por `None` em qualquer profundidade, valida de novo contra o modelo e grava com `json.dumps(..., ensure_ascii=False, allow_nan=False)`. O mesmo dict é o retorno de `run`. `numpy` e `pandas` nunca vazam para o JSON (tipos escalares convertidos antes).

## Fixtures e anonimização

- **Fonte:** `exemplo_csv/Gol` (53 eventos candidatos, 15 aprovados, 5 selecionados): um único run traz eventos `published` e `rejected`.
- **Script** `tests/fixtures/results/anonymize_gol.py` (sem nomes reais dentro): lê a Gol, troca os canais por `CANAL_01…NN` (ordem alfabética do nome real, calculada em tempo de execução), multiplica investimento e KPI por **fatores distintos** guardados em `tests/fixtures/results/.private/factors.json` (ignorado pelo git; o script o cria com valores aleatórios se não existir, e quem regenera precisa do mesmo arquivo), **mantém as datas reais** (decisão de 04/nov, risco aceito: o formato da série continua reconhecível por quem conhece a Gol) e não escala os trends (índice).
- **Gerados** (config da Gol de `tests/engine/real_data.py`, `LLM_PROVIDER=none`, 1 thread): `gol_anonimizada.json` (`succeeded`), `gol_inconclusiva.json` (mesmos dados com `min_intervention_date` depois do último dado: sem evento elegível, `inconclusive`) e `falha.json` (montado pelo builder a partir de um `Computed` sintético sem MMM nem eventos, `failed`).
- **Guarda** (roda em CI, sem os dados): todo nome de canal em qualquer fixture casa `^CANAL_\d{2}$`, nenhum campo contém `/` de caminho nem `exemplo_csv`, e cada fixture valida contra `ResultsV1`. **Guarda local** (pula sem `exemplo_csv/`): nenhum nome de canal nem valor de investimento/KPI original aparece nos fixtures.
- `tests/fixtures/results/README.md` explica como regenerar e o que o B5 pode assumir.

## Aceite

- `ResultsV1.model_json_schema()` válido; os três fixtures validam; `status` e `reasons` coerentes com a tabela.
- Nenhum `NaN`/`Infinity` em `results.json` (carregado com `parse_constant` que falha) nem em qualquer fixture.
- `compute()` idêntico ao anterior: `test_parity.py` e `test_parity_real.py` passam; o conteúdo numérico do `results.json` da Gol bate com o `compute()` (valores lidos de volta do arquivo, `rtol=1e-9`).
- `run` na Gol anonimizada devolve o mesmo dict que grava.
- Fixtures commitados; `ruff format/check` limpos; suíte inteira verde.
- Docs: `docs/decisoes/engine.md` (seção do `results.json`), linha `Status` do A1 em `trilha-a-motor.md`, "Estado atual" e a estrutura em `CLAUDE.md`.

## Testes

Unitários do schema (`extra=forbid`, rejeita não finito); `sanitize` em profundidade; `build_results` sobre o dataset sintético (todas as seções, `series` com os quatro nomes, `published` vs `rejected` vs `not_selected`, `analysis_failed`); os três casos de status; `cpa_incremental` nulo com lift zero; `run` grava arquivo idêntico ao retorno; idempotência (rodar duas vezes dá o mesmo JSON); relação com a paridade real (local, pulado sem dados).

## Decisões minhas (a confirmar na leitura)

1. `status` por seção e regra de status do run (acima); muda o A0 em um caso.
2. `mix` da curva como três mixes (`historical/optimized/strategic`) em vez de um só, porque a curva agregada calcula os três.
3. `scenarios` com os seis pontos notáveis e `cpa/roas/ramp/extrapolated` nulos; A8 refina.
4. `extrapolated` e IC das curvas ficam `null` (A5/A8 definem uma vez só).
5. `published` exige estar entre os `max_events_to_analyze` selecionados; os demais aprovados saem `rejected: not_selected`.
6. Fatores de escala fora do repositório; fixtures só regeneráveis por quem os tem.
7. Fixture `inconclusive` derivada dos mesmos dados; `falha` montado sinteticamente.

## Deixado ao construtor

Nomes internos das funções auxiliares, organização dos modelos em submódulos, a conversão exata de cada coluna (`Date` → `date`), e o limite de casas decimais (nenhum arredondamento: o JSON carrega o float como está).

## Desvios na implementação

- `generate_individual_response_curves` já devolvia o DataFrame (a spec supunha que só exportava): nenhuma mudança nessa função; `run_elasticity` passou a chamá-la sempre, também sem `global_dir`, para as curvas existirem em memória.
- O teste de idempotência roda `run` duas vezes no mesmo `out_dir` (em vez de três execuções separadas).
- Geração dos fixtures levou ~6,5 min (a spec estimava 2–4).
