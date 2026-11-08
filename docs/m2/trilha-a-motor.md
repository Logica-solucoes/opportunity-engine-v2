# Trilha A — Motor, gates e auditoria (Dev A)

Dono: Dev A (perfil estatística/data science). Leia antes o [`README.md`](README.md), principalmente **O contrato A ↔ B**: tudo que a trilha A produz chega à trilha B por ele.

Princípio da trilha: **o motor decide o que é publicável**. Gate reprovado vira `status` + `reasons` no `results.json`. Nunca sai um número sem rótulo, e a camada de cima não refaz o julgamento.

Para cada item: **BRD** (seções a ler) · **Hoje** (estado do código em `bbad5af`) · **Fazer** · **Aceite** · **Em aberto**.

---

## A0 · Pacote `engine` e pipeline único — semana 1

- **Status:** ✅ feito em 04/nov/2026 (branch `feat/a0-engine-package`, no `main` em 05/nov/2026). Verificado: `compute()` idêntico ao protótipo congelado a `rtol=1e-9` no dataset sintético (`tests/engine/test_parity.py`, antes e depois da centralização dos defaults); `tests/engine` + `tests/llm` verdes; `ruff format/check` limpos; `grep -rn "os.getcwd\|sys.exit\|os._exit\|sys.path" engine/ llm/` vazio; `python -m engine` termina sozinho (sem `os._exit`). **Fora do A0:** o aceite "Streamlit continua rodando" (o repo antigo foi congelado como referência), o swap da API (feito em 05/nov/2026, `docs/decisoes/engine.md`), a paridade no servidor de produção e o `exemplo_csv/` (ausente no disco; o snapshot usa um dataset sintético). Acrescentou o módulo plugável `llm/` (só Gemini). Spec: `docs/superpowers/specs/2026-11-04-a0-pacote-engine-design.md`; decisões: `docs/decisoes/engine.md` e `llm.md`.
- **BRD:** Improvement Requests › Execution ("Cloud execution as jobs, no local code"); Capabilities › Processing engine.
- **Depende de:** nada. **Bloqueia:** tudo (B4 chama `engine.run`).
- **Hoje:**
  - `local_main.py` e `local_main-without-gemini.py` repetem ~90% do código e já divergiram: o sem-Gemini lê covariáveis com `pd.read_csv` cru (`:63-68`).
  - Bloqueios para rodar como worker:
    - imports por `sys.path` (`local_main.py:704`, `presentation.py:16-24` com `sys.exit`);
    - `exit(1)` e `os._exit(0)` (`:680-697`, `:743`);
    - caminhos via `os.getcwd()` (`local_main.py:98,297`, `gemini_report.py:577`, `elasticity_analysis.py:1180`);
    - `warnings.filterwarnings("ignore")` global (`:16`);
    - `config` mutado (`data_preprocessor.py:983` escreve `period_days`);
    - dados carregados duas vezes (`local_main.py:68` e `elasticity_analysis.py:293`).
  - Defaults inconsistentes: `investment_limit_factor` vale 2.0 (`analysis.py:871`), 3.0 (`elasticity_analysis.py:657,1049`) e 1.5 (`:974`).
- **Fazer:**
  - Mover os módulos do motor de `scripts/` para `engine/` com `git mv`, mantendo os nomes e trocando para imports de pacote. `streamlit_app.py` fica em `scripts/` até a remoção.
  - Criar `engine/pipeline.py` com `run(inputs, config, out_dir, on_log) -> dict`, que une os dois `local_main`. O Gemini é opcional: sem chave, cai no texto determinístico de `recommendations.py`.
  - Criar `engine/config.py` com o `EngineConfig` (pydantic), único lugar dos defaults; `investment_limit_factor=1.5` (BRD). A tabela de chaves está no mapeamento do `local_main` e em `CUSTOMIZATION.md`.
  - Criar `python -m engine --config x.json --out dir`, que o Streamlit passa a chamar no lugar dos dois scripts.
  - O motor só escreve dentro de `out_dir`, nunca chama `exit` e nunca mexe em filtros globais de warnings.
  - Carregar os dados uma vez e passar os DataFrames adiante.
- **Aceite:**
  - `mise run test` verde.
  - **Snapshot de paridade:** rodar `exemplo_csv/` antes e depois do refactor dá os mesmos números (lift, p-value, curva) com tolerância 1e-9. Guardar o snapshot em `tests/fixtures/parity/`, porque ele também serve à A10.
  - `grep -rn "os.getcwd\|sys.exit\|os._exit\|sys.path" engine/` vazio.
  - Streamlit continua rodando fim-a-fim.
- **Em aberto:** remover já `saturation_curve.py` (código morto: `generate_event_saturation_curves` e `run_global_saturation_analysis` nunca são chamados) e as funções mortas de `recommendations.py`? Sugestão: sim, nesse mesmo item.

## A1 · `results.json` v1 + fixtures — semana 1

- **Status:** ✅ feito em 04/nov/2026 (branch `feat/a0-engine-package`, no `main` em 05/nov/2026). `engine.run` devolve e grava `results.json` v1 (`engine/results_schema.py`, `engine/results.py`; spec `docs/superpowers/specs/2026-11-04-a1-results-json-design.md`). Verificado: nenhum `NaN`/`Infinity` (parse com `parse_constant` que falha); números do arquivo batem com `compute()` a `rtol=1e-9`; paridade sintética e com a Gol intactas; fixtures em `tests/fixtures/results/` (Gol anonimizada e sintético; regenerados em 06/nov/2026: três `inconclusive` e um `failed`, nenhum `succeeded`, ver o `README.md` da pasta). Seções de A2 e A5–A9 existem no schema e saem `null`. **Muda o A0 em um caso:** MMM ok sem evento aprovado agora é `inconclusive`. O worker grava o dict que o `run` devolve (decisão do swap, 05/nov/2026).
- **BRD:** Capabilities › Simulation history ("every run saved with inputs, parameters, version and outputs").
- **Depende de:** A0. **Bloqueia:** B5, B6, B7.
- **Hoje:**
  - O resultado está espalhado em CSV, PNG, HTML, MD e JSON sob `outputs/<adv>/...`.
  - O Streamlit remonta tudo por glob (`streamlit_app.py:1652-1657`), regex sobre HTML (`:113`) e chega a reprocessar os dados (`:1933-1978`).
- **Fazer:**
  - `run()` retorna o dict do contrato (README › contrato §3) e também o grava em `out_dir/results.json`.
  - Seções cujo item ainda não existe (A5–A9) saem com valores neutros e `status` correto, ex.: `experiment_design: null`, `placebo: null`.
  - Séries dos gráficos entram como listas de registros, pelo conteúdo hoje salvo por `presentation.save_causal_chart_data`.
  - `baseline` mensal de investimento e KPI vai dentro do JSON, para o dashboard não recarregar os dados.
  - Gerar fixtures de `exemplo_csv/` em `tests/fixtures/results/`: um run bom e um com evento rejeitado.
- **Aceite:**
  - JSON válido contra um schema versionado (`engine/results_schema.py`, modelos pydantic com `model_json_schema()`).
  - Fixtures commitados até **sexta 23/out**.
  - Nenhum `NaN`/`Infinity` no JSON: vira `null` (hoje `target_cpa=999999` e `inf` circulam como sentinela).
- **Em aberto:** manter os PNG/HTML do matplotlib no M2? Sugestão: parar de gerar no worker assim que B5 estiver em paridade; o export PDF vem do front (B7).

## A2 · Validação de upload e deduplicação — semana 2

- **BRD:** Technical Details §4 (deduplicação); Capabilities › Data upload & validation; Improvement Requests › Data quality.
- **Status:** ✅ feito em 04/nov/2026 (branch `feat/a0-engine-package`, no `main` em 05/nov/2026). `engine.validate` (`engine/validation.py`, `engine/inputs.py`; spec `docs/superpowers/specs/2026-11-04-a2-validacao-upload-design.md`) com 14 checks; `run` valida antes e grava o relatório em `results.json`. Verificado: um teste por check; `validate` < 10 s em 730 × 15; `validate` e `load_and_prepare_data` concordam no primeiro erro; paridade sintética e da Gol (`parity-real`) intactas. **Nos dados reais (`exemplo_csv/`):** a Gol **como enviada é rejeitada** (`duplicate_date_channel`: GOOGLE aparece 5 vezes por dia, 1580 linhas; o protótipo tirava a média sem avisar); Tcross (Leads por canal) falha com `kpi_not_single_source`; PMAX semanal (um canal só) passa; VW (faturamento total) passa com `missing_dates` e `outliers`. Colinearidade segue vazia (A3). Falta: dados reais das Core, nomes DV360/CM360 e templates oficiais (Data Analytics). O swap da API foi feito em 05/nov/2026.
- **Depende de:** A0. **Bloqueia:** B2.
- **Hoje (antes do A2):**
  - Já existe em `data_preprocessor.py`: encoding/delimitador, rodapé de BI (`:82`), datas e números BR/US (`:128`, `:560`), >50% NaN (`:863,902`), cadência divergente (`:960`), períodos parciais (`:971`), outliers IQR (`:14`, só aplica, não reporta).
  - Faltam ou estão errados:
    - duplicatas de (data, canal) no **investimento** viram média silenciosa no `pivot_table`;
    - duplicatas de data no KPI são **somadas** com warning (`:948-955`);
    - não há regra de KPI single-source nem checagem DV360/CM360;
    - não há relatório de datas faltantes;
    - todo erro é re-embrulhado em `Exception` genérica (`:1075-1080`), o que perde a mensagem para o usuário.
  - Transformação oculta: canal com correlação negativa com o KPI recebe adstock no próprio investimento (`:1043-1058`). Entra na A10.
- **Fazer:**
  - `engine.validate(inputs, config) -> ValidationReport` (README › contrato §2): síncrona, sem rodar modelo, ids estáveis, mensagens pt-BR.
  - Checks:
    - `duplicate_date_channel` — erro;
    - `kpi_duplicate_dates` — erro (fim da soma silenciosa);
    - `kpi_not_single_source` — erro: arquivo de performance com coluna de canal ou KPI repetido por data, isto é, conversão reportada por plataforma;
    - `missing_dates` — warning, com as datas;
    - `outliers` — info, com contagem e datas;
    - `dv360_cm360_overlap` — warning: duas séries de canal com correlação diária > 0.95 **e** razão de soma entre 0.9 e 1.1; o analista precisa escolher uma;
    - mais os checks atuais convertidos em entradas do relatório.
  - `load_and_prepare_data` levanta exceções com o `id` do check, e não `Exception` genérica.
  - Colinearidade fica na A3, que roda dentro do mesmo `validate`.
- **Aceite:**
  - Um teste por check, com CSV mínimo em `tests/`.
  - `validate` < 10 s em 730 dias × 15 canais.
  - Rodar sobre os dados reais das Core assim que chegarem e registrar o resultado.
- **Em aberto:**
  - Os nomes de canal DV360/CM360 vêm do arquivo do cliente; o check é por similaridade de série, não por nome. Confirmar com Data Analytics.
  - Os templates CSV padrão (dono: Data Analytics) já existem?

## A3 · Gate de colinearidade — semana 2

- **BRD:** Technical Details §2; Capabilities › Model validation & publication gates.
- **Status:** ✅ feito em 05/nov/2026. `validate` preenche `collinearity` (pares |r| > 0.85 no spend cru, VIF por canal, `suggested_groups`) e dá `collinearity_unresolved` até o config trazer `channel_groups` (somados na leitura) ou `block_per_channel`; abaixo de 30 períodos não avalia. Verificado: `tests/engine/test_collinearity.py`; o dataset da paridade não dispara o gate (|r| máximo 0.066) e, sem `channel_groups`, a leitura não muda; falta rodar a paridade no Linux. Atualizado em 06/nov/2026: o VIF > `vif_max` (10) também bloqueia, canal só de VIF entra na sugestão, `collinearity.unresolved` e `channel_group_name_taken`. Verificado: `tests/engine/test_collinearity.py` (26 passed; VIF sem par, semanal, overlap não bloqueia pelo VIF). Falta medir o VIF na Gol e nas Core. Falta: rodar sobre a Gol e os datasets das Core; limites ajustáveis pelo Admin são da Trilha B. Decisões em `docs/decisoes/engine.md`.
- **Depende de:** A2. **Bloqueia:** A5, B2 (tela de agrupamento).
- **Hoje:** não há VIF. A única correlação calculada é a matriz de Pearson (`data_preprocessor.py:1041,1069`), usada no hack de adstock e enviada ao Gemini.
- **Fazer:**
  - Em `validate`: correlação par a par e VIF (`statsmodels.stats.outliers_influence.variance_inflation_factor`) do spend por canal.
  - Thresholds em `config.gate_thresholds` (default |r| > 0.85, VIF > 10, ajustáveis por Admin do workspace via B1).
  - `suggested_groups` = componentes conexos dos pares sinalizados.
  - O analista escolhe uma de duas saídas:
    - `config.channel_groups = {"PMAX + SEARCH": ["PMAX","SEARCH"]}`, que soma o spend antes de modelar;
    - `config.block_per_channel = true`, em que o modelo roda mas resultado por canal sai `identifiable=false` (A5).
  - Run com colinearidade não resolvida → erro de validação.
- **Aceite:**
  - Teste sintético: dois canais com r = 0.95 são sinalizados, agrupados viram um canal, e o resultado sai só no nível de grupo.
  - O VIF bate com cálculo manual em um caso pequeno.
- **Em aberto:** ~~VIF só sobre spend, ou spend após adstock?~~ Decidido em 05/nov/2026: spend cru (o BRD diz "channel spend").

## A4 · Controles causais livres de contaminação — semana 2

- **BRD:** Technical Details §7; Improvement Requests › Causal controls.
- **Depende de:** A0.
- **Status:** ✅ feito em 06/nov/2026. Covariáveis da mídia (Leads/Clicks/Impressions) fora do causal; controles exógenos (Trends e, marcadas pelo analista, IPCA/Selic/IBC-Br da SGS, buscadas pela API ao criar o run e gravadas no snapshot) triados por evento com `control_spend_corr` = 0.5 e publicados em `events[].controls`; `LassoCV` com `TimeSeriesSplit`. Verificado: `tests/engine/test_controls.py` (performance com Clicks/Impressions dá o mesmo lift; controle = spend + ruído descartado; controle independente e série do BCB aceitos; forward-fill por `merge_asof`; folds curtos), `tests/api/test_bcb.py`, `tests/api/test_runs.py` (snapshot, 502, sem controles não busca), `web/e2e/simulations.spec.ts` (sem clicar Rodar). Paridade causal completa no sintético de novo (06/nov/2026; no Windows o teste é pulado, mesmas decisões e diferença máxima 5e-5 medidas à mão, Linux pendente); a Gol compara com o golden do motor (`mise run parity-a4-golden`, pendente de rodar com os dados). Colunas de calendário por nome exato. Decisão 2: `control_rejected` fica em `reasons` e a aba Causal o mostra como observação (ramo b). Fora: séries além das três, cache da SGS, calibrar o 0.5 (A10). Spec: `docs/superpowers/specs/2026-11-06-a4-controles-causais-design.md`.
- **Hoje:**
  - Covariáveis hardcoded `Leads`, `Clicks`, `Impressions` (`analysis.py:307-320`), com case exato e fora do `column_mapping`.
  - `.replace(".", "")` em string (`:328`) quebra decimal US.
  - LassoCV com folds não temporais (`:433-453`).
- **Fazer:**
  - Remover as covariáveis ad-driven. Clicks, impressions, branded search e conversões de plataforma nunca entram como controle.
  - Controles do usuário vêm de `config.controls` (colunas do arquivo de trends ou séries pré-empacotadas). Cada um é triado: correlação com o spend do canal tratado no pré-período > `gate_thresholds.control_spend_corr` (default 0.5) → rejeitado e listado em `reasons`.
  - Séries pré-empacotadas: Google Trends já chega via upload. **BCB** (SGS: IPCA, Selic, IBC-Br) é o primeiro item da ordem de corte; se entrar, buscar e cachear por data, interpolando mensal para a cadência do run.
  - LassoCV com `TimeSeriesSplit`.
- **Aceite:**
  - Arquivo de performance com coluna `Clicks` não muda o resultado.
  - Controle sintético igual a spend + ruído é rejeitado.
  - O snapshot de paridade muda só no que foi intencional, registrado para a A10.
- **Em aberto:** threshold de correlação do controle (0.5 é chute); calibrar na A10.

## A5 · Identificabilidade por canal — semana 3

- **Status:** ✅ feito em 05/nov/2026. `channels[].coef_ci` é o p2.5/p97.5 da contribuição do canal no período (unidade do KPI) sobre as 200 reamostragens; `identifiable=false` quando p2.5 ≤ 0 (a Ridge é positiva) ou a largura passa do ponto; o canal sai sem contribuição, Hill, adstock e curva, e o spend dele entra em `"Não identificados"` no mix da curva, dos cenários e do payload do Gemini. Só publicação: modelo e otimizador iguais, paridade intacta. Nenhum canal identificável → `elasticity` `inconclusive` (`no_identifiable_channel`), com a curva total publicada. Verificado: `tests/engine/test_identifiability.py` (sintético com `STRONG` identificável e `NOEFFECT` não), `test_results_build.py`, `test_outputs.py`; suíte inteira 827 passed, 21 skipped no Windows; a matriz fica em `mmm["coef_samples"]` para o A8. **Medido:** no sintético da paridade todo canal sai não identificável (spend quase constante), então os runs dele ficam `inconclusive`. Falta: rodar na Gol e nas Core, regenerar os fixtures do A1 (precisa da Gol) e a paridade no Linux. Spec: `docs/superpowers/specs/2026-11-05-a5-identificabilidade-design.md`. Atualizado em 06/nov/2026: canal colinear com `block_per_channel` sai `identifiable=false` (`collinearity`); a realocação sai com qualquer canal escondido (`reallocation_suppressed`); aceite `STRONG`/`NOEFFECT` passa nas sementes 7, 11 e 23; run sem canal identificável segue `inconclusive` (decisão 1).

- **BRD:** Technical Details §2 (segunda metade); Capabilities › gates.
- **Depende de:** A3.
- **Hoje:** o bootstrap (n=200, seed 42, `elasticity_analysis.py:256-280`) calcula a matriz de coeficientes, mas **só a média sobrevive** (`:439`). Não há intervalo em lugar nenhum.
- **Fazer:**
  - Expor percentis 2.5/97.5 por canal em `channels[].coef_ci`.
  - `identifiable=false` quando o IC cruza zero ou a largura é maior que o |ponto|.
  - Canal não identificável sai de curva individual, mix, cenários e payload do Gemini. Só o grupo (ou o total) é publicado, com o motivo.
  - Guardar a matriz de bootstrap: a A8 usa para as bandas.
- **Aceite:**
  - Sintético: um canal sem efeito real sai `identifiable=false`; um com efeito forte sai `true`.
  - O JSON de um run com canal não identificável não contém curva nem mix desse canal.

## A6 · Suficiência de dados e placebo — semana 3

- **Status:** ✅ feito em 06/nov/2026. Placebo no meio do pré (`placebo_failed`), WMAPE fora da amostra, `sufficiency` do run (`spend_cv_min` 0.10, `oos_wmape_max` 0.30, provisórios), eventos `insufficient_run` sem lift, `cv_in_sample` deixando a elasticidade `inconclusive` e o gate de robustez `model_dependent` (decisão 3, escolhida pelo dono: reajuste sem as features de mídia, `events[].robustness`). Verificado em container Linux: `test_placebo.py`, `test_sufficiency.py` e `test_placebo_acceptance.py` passam, ruído branco nas 3 sementes sem evento publicado (a 1 publicava 2, agora `model_dependent`), pulso injetado → `placebo_failed`, efeito real limpo publicado; paridade 5/5 a 1e-9 contra snapshot da mesma CPU; Gol (`test_parity_real.py` 7/7, golden `gol_a4_events.json` gerado), fixtures do A1 regenerados. Na Gol `model_dependent` dispara em 0 eventos e o run termina `inconclusive` (nenhum canal identificável). Falta calibrar os limiares (A10). Detalhe em `docs/decisoes/engine.md`.
- **BRD:** Technical Details §3 e §7 (placebo); Capabilities › gates.
- **Depende de:** A0.
- **Hoje:**
  - O evento é pulado se o pré-período é curto.
  - O `mape` em `analysis.py:467-472` é MAE/média×100 (na prática WMAPE), mas **in-sample**.
  - O CV walk-forward da elasticidade cai para in-sample com < 40 linhas (`elasticity_analysis.py:169-206`), sem avisar.
- **Fazer:**
  - **Suficiência** (`results.sufficiency`):
    - variação de spend por canal analisado (coeficiente de variação ≥ threshold);
    - nº de eventos validados ≥ 1;
    - **WMAPE fora da amostra** do contrafactual: segurar o último 20% do pré-período.
  - Falhou → `status: "inconclusive"`, sem lift publicado, e a A7 entra.
  - CV com poucas linhas também reprova a suficiência (deixa de cair calado para in-sample).
  - **Placebo por evento:** intervenção falsa no meio do pré-período, mesmo modelo. p < `p_value_threshold` → evento `rejected` com `reasons: ["placebo_failed"]`.
- **Aceite:**
  - **White noise:** KPI = ruído puro → nenhum evento publicado e run `inconclusive`. É o caso de "16% de efeito no ruído" citado no BRD.
  - Placebo com efeito injetado no pré-período reprova.
- **Em aberto:** thresholds de spend variation e WMAPE; propor valores e calibrar na A10.

## A7 · Experiment designer — semana 3

- **BRD:** Technical Details §3 (MDE, duração, budget at risk, calibração); Capabilities › Experiment designer.
- **Depende de:** A6.
- **Hoje:** nada.
- **Fazer:** quando `status == "inconclusive"`, preencher `experiment_design`:
  - `test_type`: on/off, step-up de orçamento, ou geo split se houver dimensão geográfica (hoje não há; deixar fora);
  - `mde`: a 95% de confiança e 80% de poder, a partir da volatilidade residual do pré-período. Ponto de partida: MDE_abs ≈ (1.96 + 0.84) · σ · √T para T períodos, corrigindo autocorrelação com fator de variância AR(1) dos resíduos;
  - `duration_days`: menor T em que o MDE fica abaixo do efeito plausível (lift relativo alvo, default 5%);
  - `budget_at_risk`: spend da célula de teste × T;
  - `assumptions` em texto.
  - Calibração: endpoint de upload do resultado do experimento (B2 guarda); no M2 o motor só **exibe** a referência no run seguinte (uso como prior fica no pós-launch).
- **Aceite:** com σ e T conhecidos, o MDE confere com cálculo manual; e simulação Monte Carlo com efeito = MDE detecta ≈ 80% das vezes (tolerância ±5 p.p.).
- **Em aberto:** fórmula final validada pela Data Science, que é dona da metodologia.

## A8 · Guardrails do planner e `engine.scenario` — semana 3

- **Status:** ✅ feito em 06/nov/2026. Banda p5/p95 das 200 reamostragens da Ridge (Hill, adstock e scaler fixos: banda otimista, para a A10) e `extrapolated` (total ou canal fora do `[min, max]` histórico) em toda linha da curva, cenário e ponto de curva individual; curvas individuais sempre dentro do cap; `ramp` em degraus compostos de `max_budget_step` e `notes` tCPA/tROAS nos cenários. `engine.scenario(results, filters, max_budget_step)` puro sobre o `results.json`, com os filtros do Streamlit e saída mensal, exposto em `GET /api/w/{slug}/runs/{run_id}/scenario`. Learning/budget-limited cortado (conector fora do escopo). Verificado: `tests/engine/test_ramp.py`, `test_guardrails.py`, `test_scenario.py` (paridade com o filtro e o `find_saturation_point` do Streamlit em 8 combinações sobre a Gol; < 300 ms), `tests/api/test_scenario_route.py`; suíte inteira 885 passed, 21 skipped no Windows. Falta: paridade no Linux e regenerar os fixtures do A1 com banda (precisa da Gol). Spec: `docs/superpowers/specs/2026-11-06-a8-guardrails-scenario-design.md`.

- **BRD:** Technical Details §5; Capabilities › Scenarios & recommendations; Journey 2 (slider).
- **Depende de:** A1, A5.
- **Hoje:**
  - Guardrails financeiros em `elasticity_analysis.py:923-971` e cap de extrapolação por canal (`:667-679`). As curvas individuais **pulam o cap** (`:1070-1072`).
  - A filtragem interativa e o ponto ótimo vivem no Streamlit (`streamlit_app.py:2208-2366`) e em `dashboard_charts.py:15-78`.
  - Não há bandas nem passo máximo.
- **Fazer:**
  - **Bandas:** propagar a matriz de bootstrap (A5) pela curva → `kpi_lo`/`kpi_hi` (p5/p95) em todo ponto e cenário.
  - **Extrapolação:** `extrapolated=true` em ponto ou cenário fora da faixa histórica de spend (por canal e total); as curvas individuais passam a respeitar o cap.
  - **Passo máximo:** `config.max_budget_step` (0.20). Mudança maior que isso vira `ramp`, uma lista de degraus de no máximo 20%.
  - Notas tCPA/tROAS em texto fixo nos cenários.
  - Learning/budget-limited do Google Ads fica **cortável**, porque depende do OAuth (B8).
  - `engine.scenario(results, filters)` reúne a lógica de filtro, ponto ótimo e saturação hoje no Streamlit e em `dashboard_charts`. Portar com os testes de `test_dashboard_charts.py`.
- **Aceite:**
  - Mesmos filtros dão mesmo ponto ótimo que o Streamlit atual (teste de paridade).
  - Nenhum ponto sem banda.
  - Cenário +50% com passo de 20% gera 3 degraus.
  - `scenario` < 300 ms (slider).

## A9 · Grounding do Gemini — semana 3

- **BRD:** Technical Details §6; Improvement Requests › Gemini reports; Risks › Gemini output quality.
- **Depende de:** A5, A6 (status entram no payload).
- **Hoje:**
  - SDK `google-generativeai` sem `generation_config`: sem temperature e sem schema; o JSON é parseado após tirar code fence (`gemini_report.py:26`).
  - Payload do evento: `gemini_report.py:67`. O global anexa `SATURATION_CURVE.md` e diz que há imagem, mas não manda (`:564`).
  - `low_confidence` **não** chega ao prompt (achado F17 da auditoria de julho).
  - A narrativa entra **sem escape** no HTML (só o título é escapado).
  - Já existe tratamento de outage (`:43`, `local_main.py:414-441`).
- **Fazer:**
  - Migrar para `google-genai`, com `temperature=0`, `response_mime_type="application/json"` e `response_schema`.
  - Payload restrito ao do BRD: lift, p-values, R², WMAPE, K, ótimo, status de guardrails e gates.
  - Canal não identificável ou run inconclusivo → o prompt recebe o status e só pode explicar o porquê.
  - **Checagem pós-geração:**
    - extrair todo número do texto (formatos pt-BR: `R$ 3,4M`, `89,7%`, `-0,17x`, `4,64M`) e casar com algum valor do payload, com tolerância de arredondamento;
    - todo nome de canal citado tem que estar no conjunto publicado.
  - Falhou → regenera 1x → falhou de novo → `grounding.status="blocked"`, e a UI mostra o texto determinístico de `engine/narratives.py`.
  - Remover a menção a imagem inexistente.
- **Aceite:**
  - Testes do checador com textos fabricados: número inventado reprova, canal rejeitado reprova, arredondamento legítimo passa.
  - Sem chave de API, o run termina com relatório determinístico.
- **Decidido em 04/nov/2026:** API key por variável de ambiente, pelo módulo `llm/`. Vertex AI saiu junto com o GCP (`docs/decisoes/infra-e-operacao.md`).
- **Status:** ✅ feito em 08/nov/2026. `engine/grounding.py` (checador de números pt-BR, datas e canais) e `engine/narratives.py` (uma narrativa por evento publicado e uma global, `generate_json` com schema pydantic e `temperature=0`, uma regeneração, texto determinístico em `blocked`); `reports` no `results.json`; `reports.py` e `recommendations.py` apagados. Verificado: testes do checador com textos fabricados (números inventados e canais reprovam, arredondamento legítimo passa, datas por extenso), run sem chave com relatório determinístico e `grounding: null`, `ruff` limpo, pytest completo 1098 passed, 23 skipped, com 1 falha de corrida entre processos paralelos no mesmo Postgres (`test_admin.py::test_list_users`, passa sozinho e no rerun); E2E 36/36 no run do fixtures-dev; dois reruns do consolidator, com outros testes rodando na mesma máquina e no mesmo banco, falharam no timeout de 15 s de `helpers.runToCompletion` (worker falso, fora do caminho do A9). Desvios documentados em `docs/decisoes/engine.md` › A9 (datas por extenso; "28 dias" bloqueado; inteiro até 12 e canal inventado não pegos). Falta rodar com chave real do Gemini.

## A10 · Auditoria matemática — semana 4 (9–13/nov)

- **BRD:** Technical Details (todas); Phase 2 Week 4; Capabilities › Mathematical audit; Improvement Requests › Calculation memory.
- **Depende de:** A2–A9.
- **Hoje:** auditoria interna de julho em `docs/superpowers/plans/2026-07-08-statistical-audit-findings.md`: F1–F7, F11–F13 e F15 corrigidos; F9 parcial; F8 e F10 adiados; F14, F16 e F17 anotados. O original é `upstream/main` (`rafahm-google/opportunity-engine`).
- **Fazer:**
  - **Gerador sintético** (`tests/synthetic.py`): KPI = baseline (calendário + trend) + Σ Hill(adstock(spend)) + ruído, com lift e K conhecidos. Rodar o motor e medir a recuperação.
  - **Controle white noise:** nenhum efeito publicado.
  - **Paridade com `upstream/main`** no `exemplo_csv` onde for intencional. Toda diferença tem que mapear para uma correção documentada (F1… e as novas das A2–A9).
  - **Revisar e decidir**, documentando cada um:
    - `seasonal=7` fixo mesmo com cadência semanal (`analysis.py:456`);
    - `cum_se` assumindo independência (`:508-518`);
    - adstock oculto em canal com correlação negativa (`data_preprocessor.py:1043-1058`);
    - três convenções de adstock (F10);
    - fallback in-sample do CV.
  - Calibrar os thresholds dos gates e o **histórico mínimo** de dados (o BRD pede para confirmar na semana 4).
  - Relatório em `docs/audit/2026-11-auditoria-matematica-m2.md`: método, datasets, critérios, resultado e lista de correções com evidência.
- **Aceite:** critérios numéricos definidos **antes** de rodar, por exemplo "lift recuperado dentro do IC 95% em ≥ 90% dos cenários sintéticos" e "0 eventos publicados no white noise em 50 seeds". Todos aprovados ou desvio justificado no relatório.
- **Em aberto:** os critérios numéricos (dono: Data Science). Cobrar antes de 9/nov.

---

## Contribuições da trilha A para B

- **Guia do usuário v1** (entrega do M2): seção "como interpretar os resultados", com lift, IC, identificabilidade, bandas e experiment design.
- **Textos pt-BR** de cada `check.id` e `reason`, que a UI exibe tal como vierem.
