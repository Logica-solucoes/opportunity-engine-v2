# Motor (`engine/`)

Decisões do A0, 04/nov/2026. Spec: `docs/superpowers/specs/2026-11-04-a0-pacote-engine-design.md`; plano: `docs/superpowers/plans/2026-11-04-a0-pacote-engine.md`. O código veio do protótipo (`opportunity-engine`, HEAD `6146b7f`, **congelado**: referência de paridade e plano B de demo).

## O que o A0 entregou

`engine.run(inputs, config, out_dir, on_log) -> dict` (contrato §3), `EngineConfig`, `EngineError` e `python -m engine`. Com o A1 e o A2, `run` grava e devolve o `results.json` v1 e `engine.validate` existe (seções abaixo). A branch entrou no `main` em 05/nov/2026. O swap da API para o motor real foi feito no mesmo dia (passos abaixo); só o `run` falso sobrou, atrás de `ENGINE_FAKE=1`.

## Pipeline em estágios, sem mexer na matemática

`engine/pipeline.py` divide o fluxo do `local_main` em `load_inputs → detect_events → analyze_events → run_elasticity` (agrupados em `compute()`), que devolvem dados em memória (`Computed`, `EventOutcome` com `passed` e `reasons`); `engine/outputs.py` escreve os arquivos de sempre (PNG, CSV, Markdown, HTML) a partir do `Computed`. **Por quê:** o A1 troca os escritores por um montador de `results.json` sem desmontar o fluxo, e a paridade se prova no `compute()`, sem arquivos no meio.

- Os módulos analíticos (`analysis`, `elasticity_analysis`, `data_preprocessor`, `presentation`, `recommendations`) são cópias; só mudaram imports, caminhos, a leitura única dos dados (`PreparedData`), a remoção de `exit`/`os._exit`/`getcwd`/`sys.path`, e os defaults (Fase 2).
- Os dados são lidos **uma vez**; antes, `local_main` e `run_mmm_engine` liam e preparavam duas vezes, e o arquivo de performance uma terceira.
- Um evento que falha não derruba o run. Os três gates (`require_statistical_significance`, `require_logical_direction`, `require_model_fit`) registram `reasons` (`not_significant`, `illogical_direction`, `poor_fit`, `analysis_failed`) em memória; hoje isso não chega ao `results.json` (A1).
- `status`: `succeeded`, ou `failed` quando o MMM não produz resultado e nenhum evento passa. `inconclusive` é da A6.
- Saída em `out_dir`: `<canais>/<data>/…` (nomes com tudo fora de `[\w-]` trocado por `_`, porque canal e anunciante vêm do dado do cliente e um `../` escrevia fora do `out_dir`; corrigido na revisão de 05/nov) por evento selecionado e `global_saturation_analysis/`. O nível `<advertiser>` e o `output_directory` do protótipo sumiram (nada lê esses caminhos). O relatório do evento é `report_<canais>_<data>.html` (era `gemini_report_*.html`). A falha ou a ausência do LLM cai em `RECOMMENDATIONS.md` (texto determinístico).

## `EngineConfig`

Pydantic, `extra="forbid"`, `allow_inf_nan=False`. Os módulos continuam lendo um dict; `EngineConfig.to_legacy_dict()` entrega todas as chaves (os `config.get(chave, default)` espalhados foram removidos, e um teste varre o código para não voltarem). Detalhes que não se leem no código:

- **`None` em `financial_targets` vira chave ausente.** O motor já lia `financial_targets.get("target_cpa", inf)` (e `0` para ROAS, `minimum_acceptable_iroi` para iROAS): ausente é exatamente "sem meta". Sentinelas como `999999` não existem mais.
- `optimization_target` tem default `CONVERSIONS` (o protótipo usa `REVENUE`, que não valida sem `average_ticket`); `REVENUE` exige `average_ticket > 0`.
- `performance_kpi_column` é derivado de `column_mapping.performance_file.kpi_col`; `*_file_path` e `output_directory` não existem (viram `inputs` e `out_dir`); `period_days` não é entrada, é o resultado da cadência detectada (`PreparedData.period_days`) e o `run` o põe numa **cópia** do dict.
- Provedor e modelo de LLM **não** são config de run: variáveis de ambiente (`docs/decisoes/llm.md`).
- Chave desconhecida ou valor fora do limite → `EngineError("Configuração inválida: …")` citando o campo.

### Divergências que a API tinha (resolvidas em 05/nov/2026)

| | `ParamsIn` da API | `EngineConfig` |
|---|---|---|
| gates | `require_significance`, `require_good_fit` | `require_statistical_significance`, `require_logical_direction`, `require_model_fit` |
| `r_squared_threshold` | 0,5 | 0,3 |
| `min_pre_period_days` | 28 | 14 (e há piso interno de 8 períodos) |
| `increase/decrease_threshold_percent` | 20 / 20 | 50 / 30 |
| campos que a API não tem | — | `post_event_days` (14), `max_events_to_analyze` (5), `treat_outliers`, `require_logical_direction` e os preenchidos pelo sistema (`country_code`, `date_formats`, `max_channel_mix_share`…) |

Os defaults do motor vêm do protótipo; **os definitivos são da Data Science**.

## Erros e `on_log`

- `EngineError` leva mensagem em pt-BR **segura para a tela**: sem caminho de arquivo (o motor só vê o caminho do storage) e sem dado do cliente. `data_preprocessor` converte seus `ValueError`/`FileNotFoundError` nele. Qualquer outra exceção sobe como está. O worker mostra a mensagem do `EngineError` na tela do run e esconde qualquer outra exceção (passo 7 do swap, 05/nov/2026).
- `on_log(level, message)`: um handler nos loggers `engine` e `llm` (INFO+, restaurado no `finally`) passa cada registro por `translate_line` (regras pt-BR do `logger.py` do protótipo; `None` descarta ruído; **linha sem regra passa como está**, então ainda aparecem mensagens em inglês). `WARNING→warning`, `ERROR/CRITICAL→error`.
- O `run` não escreve em stdout, não muda o cwd e restaura os filtros de warnings (`catch_warnings`).

## Paridade

`tests/engine/test_parity.py` compara `compute()` com `tests/fixtures/parity/snapshot.json` (`rtol=1e-9`), gerado **uma vez** pelo código do protótipo sobre o dataset sintético de `tests/engine/synthetic_data.py` (`tests/fixtures/parity/README.md`). Vale só com as mesmas versões das bibliotecas numéricas, fixadas no `pyproject.toml`: numpy 2.5.0, pandas 3.0.3, scipy 1.18.0, statsmodels 0.14.6, scikit-learn 1.9.0, holidays 0.99, matplotlib 3.11.0. `mise run parity` roda só ela (~95 s).

- Verificado na máquina de desenvolvimento (x86-64): idêntico a 1e-9, antes (Fase 1) e depois (Fase 2) da centralização dos defaults.
- **Falta rodar no servidor de produção** (x86-64, outra CPU): CPUs diferentes podem escolher kernels de BLAS diferentes. Se passar de 1e-9, registre aqui a tolerância medida.
- **No Windows o MMM cai em outro ótimo (05/nov/2026).** Com as mesmas versões das bibliotecas (o OpenBLAS do wheel de Windows), os eventos causais batem até ~1e-6, mas a contribuição por canal muda muito (SOCIAL 70% contra 51,6%, DISPLAY 4,5% contra 7,0%) e a curva de resposta acompanha. Fixar o BLAS em 1 thread não muda nada. Por isso `test_parity.py` só roda no Linux, que é a plataforma do snapshot, do CI e da produção. **O que isso diz sobre o motor:** o ajuste do adstock/Hill é mal condicionado, e um ruído de última casa decimal troca o mix recomendado. É herança do protótipo e é assunto da A10 (auditoria matemática), não do refactor.
- O dataset sintético prova o refactor, não a estatística. Em `require_model_fit=False` porque o R² dentro da amostra do modelo causal é negativo nesse dado.
- **Paridade com dado real (Gol, 04/nov/2026):** `tests/engine/test_parity_real.py` compara o `compute()` com o protótipo sobre `exemplo_csv/Gol` (53 eventos, 15 passam, 5 selecionados; MMM R² 0,27, CV 0,22), os seis blocos a `rtol=1e-9`: **passa**. `exemplo_csv/` e os números do protótipo (`tests/fixtures/parity/real/gol.json`) são confidenciais e ignorados pelo git, então o teste é pulado onde não existem. Para gerar e rodar: `mise run parity-real` (~5 min; usa `LEGACY_REPO`, padrão `../opportunity-engine`).
- **A paridade com dado real só vale com BLAS de 1 thread.** Com todas as threads a curva de resposta e seus pontos se afastaram até ~7,5e-4 (relativo) do protótipo; com 1 thread, idênticos. O teste real fixa 1 thread com `threadpoolctl`; o sintético não mostrou essa sensibilidade. Reforça a recomendação de fixar as variáveis abaixo no worker: sem isso, o mesmo input pode dar curvas ligeiramente diferentes entre execuções e máquinas.

## Tempo de execução

Run completo (`python -m engine`) no dataset sintético de 2 anos diários × 5 canais (6 eventos candidatos), medido em 04/nov/2026 na máquina de desenvolvimento (8 threads):

| Threads de BLAS | Relógio | CPU |
|---|---|---|
| padrão (todos os núcleos) | ~99 s | ~10 min |
| `OMP_NUM_THREADS=OPENBLAS_NUM_THREADS=MKL_NUM_THREADS=1` | **~40 s** | ~40 s |

Os modelos são pequenos: o BLAS multithread só gera disputa de threads. **O ambiente do worker fixa essas três variáveis em 1** (`api/launcher.py`, desde 05/nov/2026) (e então o tamanho do servidor importa pouco: um run usa ~1 núcleo). O `response_curve_data.csv` saiu idêntico byte a byte nas duas medições. Não fixei isso no código do motor (`threadpoolctl`) porque muda o comportamento do processo; é decisão de implantação (Dev B), mas agora também é questão de reprodutibilidade (acima). O limite do run (`STALE_AFTER`, 20 min em `api/runs.py`) é do Dev B; com 1 núcleo, o dataset sintético leva bem menos que isso.

## `results.json` v1 (A1, 04/nov/2026)

Spec: `docs/superpowers/specs/2026-11-04-a1-results-json-design.md`. `engine/results_schema.py` define o contrato inteiro (pydantic, `extra=forbid`, `schema_version=1`); `engine/results.py` monta o documento a partir do `Computed` **sem calcular nada** e `run()` o grava em `out_dir/results.json` e o devolve.

- **Todo o §3 está tipado, mas só `causal`, `elasticity` e `baseline` são preenchidos.** `validation`, `sufficiency`, `experiment_design` e `reports` (A2, A5–A9), e dentro das seções `placebo`, `identifiable`, `coef_ci`, `lo/hi` das curvas, `extrapolated`, `cpa/roas/ramp` dos cenários, saem `null`. Quando o item dono chegar, só preenche. Campo opcional novo não muda `schema_version`; remover ou renomear muda. **Por quê:** o front gera tipos de uma fonte só e nenhum item futuro redefine o contrato.
- **Status.** Cada seção tem `status` (`ok|inconclusive|failed`) e `reasons`. O run é `succeeded` se `causal` e `elasticity` estão `ok`, `failed` se nenhuma está, `inconclusive` nos demais. **Muda o A0 num caso:** MMM ok sem nenhum evento aprovado era `succeeded`. Evento é `published` só se passou nos gates **e** está entre os `max_events_to_analyze`; o resto é `rejected`, com `not_selected` para quem passou e ficou de fora. O front só lê `status` e `reasons`.
- **Sem sentinelas.** `NaN`/`inf` viram `null` em qualquer profundidade (`sanitize`), o documento é validado de novo e gravado com `allow_nan=False`. `cpa_incremental` com lift zero (era `0`) vira `null`.
- **Curva e cenários.** `mix` da curva tem três variantes (`historical`, `optimized`, `strategic`) porque a curva agregada calcula as três. `scenarios` empacota os seis pontos notáveis; o A8 os refina. `iroas` é `Incremental_ROI` (receita incremental / investimento incremental) e `revenue` é `Projected_Revenue`, **só em modo receita** (`kpi_is_monetary` ou alvo `REVENUE`); fora dele valem 0 por construção e saem `null`. `iroas` também é `null` com investimento incremental 0 (o motor escreve 0 para 0/0), e `icpa` é `null` sem investimento ou sem KPI incremental (o motor escreve 0). Um 0 nesses campos nunca é valor real.
- **PNG/HTML do matplotlib continuam sendo gerados** até o B5 estar em paridade.
- **Fixtures** (`tests/fixtures/results/`): Gol **anonimizada** (canais `CANAL_NN`, investimento e KPI multiplicados por fatores privados em `.private/factors.json`, git-ignorado; **datas reais**, risco aceito: o formato da série ainda é reconhecível por quem conhece a Gol). Teste de CI garante só nomes anônimos e nenhum caminho; teste local confirma que nenhum nome ou valor original aparece. Regenerar exige `exemplo_csv/` e o mesmo arquivo de fatores (`generate_fixtures.py`, ~6 min).
- **Para o Dev B:** `api/worker.py` faz `json.dumps(results)` e grava; como `run` já devolve o dict seguro, os dois arquivos saem iguais. Mantido assim no swap (passo 10).

## `validate` (A2, 04/nov/2026)

Spec: `docs/superpowers/specs/2026-11-04-a2-validacao-upload-design.md`. `engine.validate(inputs, config) -> ValidationReport` é síncrono, não roda modelo e **nunca levanta por problema de dado**: o problema vira um check (só uma configuração inválida levanta `EngineError`). `engine/inputs.py` (`read_inputs`) lê e normaliza os três CSV e é usado por `validate` **e** por `load_and_prepare_data`; por isso o que o `validate` aprova o `run` lê igual.

- **Catálogo (ids estáveis):** erros `file_unreadable`, `column_missing`, `column_unusable` (o parser quebrou com o formato da coluna, ex. canal numérico ou cabeçalhos repetidos), `date_unparseable`, `value_not_numeric`, `no_valid_rows`, `duplicate_date_channel`, `kpi_duplicate_dates`, `kpi_not_single_source`, `cadence_mismatch`, `insufficient_after_partial`, `collinearity_unresolved` e `channel_group_unknown` (A3); avisos `missing_dates`, `dv360_cm360_overlap`; infos `outliers`, `partial_period_dropped`, `collinearity_not_assessed` (A3). `details` leva os dados estruturados (datas até 50, contagens, canais) para a tela.
- **Fim da correção silenciosa.** Duplicata de (data, canal) no investimento (era média) e data repetida no KPI (era soma) são **erro**. `run()` valida primeiro e para no primeiro erro com `EngineError.check_id`; avisos e infos vão para o `results.json` (`validation`) e para o log.
- **`kpi_not_single_source`:** o KPI repete data **e** uma coluna de texto do arquivo de performance muda entre linhas da mesma data (canal, plataforma). Colunas de texto que na verdade são números em formato local (`1.234,56`) não contam. Data repetida sem tal coluna é `kpi_duplicate_dates`.
- **`dv360_cm360_overlap`:** por série, nunca por nome: correlação diária > 0.95 e razão de soma (menor/maior, simétrica) ≥ 0.9, isto é, entre 0.9 e ~1.11 para qualquer ordem dos nomes; canal constante ou de soma zero é ignorado.
- **`missing_dates`** olha lacunas por série (intervalo / cadência arredondado), tolerando o ±1 dia de re-ancoramento semanal que `detect_cadence` já aceita.
- **Achado nos dados reais:** `exemplo_csv/Gol/investment.csv` tem GOOGLE 5 vezes por dia (valores diferentes, provavelmente subcampanhas) e o protótipo tirava a **média**. Agora a Gol como enviada é rejeitada. Se o certo é **somar** e não tirar a média (a média subestima o investimento do canal), isso é decisão de negócio com a Data Analytics; hoje o analista precisa consolidar o arquivo. `parity-real` compara protótipo e motor numa cópia da Gol com a média aplicada **no teste** (`tests/engine/real_data.py`); sobre o arquivo original os dois já não concordam (o adstock do protótipo rodava nas linhas repetidas antes do `pivot_table`).
- **Para o Dev B (swap):** `api/validation.py` vira `from engine import validate`; o `config` pode ir como veio (dict ou `EngineConfig`). A tela do B2 deve tratar os novos ids (`details` por id) e o nível `info`. Ausência de `generic_trends_file` é `None`.
- **Fora do A2:** templates CSV oficiais e nomes DV360/CM360 (Data Analytics).

## Colinearidade (A3, 05/nov/2026)

Roda dentro do `validate`, sobre o spend **sem os períodos parciais** (o mesmo recorte do overlap e do modelo; uma semana parcial é baixa em todos os canais ao mesmo tempo e inflaria o |r|). Matriz data × canal (canal constante sai), Pearson par a par; par com |r| > `gate_thresholds.collinearity_r` (default 0.85, `GATE_DEFAULTS` em `engine/config.py`; valor fora de (0, 1) é config inválida) entra em `collinearity.pairs` (`a`, `b`, `r`). O relatório `collinearity` é do spend **cru** (sem `channel_groups`): mostra a colinearidade real mesmo depois de agrupar.

- **VIF só reporta.** Por canal (`variance_inflation_factor` do statsmodels), `None` quando infinito, negativo ou > 1e6. O limite `collinearity_vif` vem com o A5, quando o VIF passa a decidir algo.
- **`suggested_groups`** são os componentes conexos dos pares sinalizados, sem os pares de `dv360_cm360_overlap`.
- **Gate sobre o spend agrupado.** `collinearity_unresolved` (erro) se, depois de somar os grupos de `channel_groups`, ainda houver par acima do limite: par dentro de um grupo some, e um grupo que ficou colinear com um terceiro canal continua bloqueando. `details.pairs` são esses pares abertos (podem ter nome de grupo, `"A + B"`); `details.suggested_groups` e a sugestão da mensagem são os componentes conexos deles, com o grupo expandido nos membros. Passa sem pares abertos ou com `block_per_channel=true`; o efeito deste último no resultado é do A5. `channel_group_unknown` (erro) se um grupo cita canal que não está no arquivo de investimento.
- **Overlap não bloqueia.** Par de `dv360_cm360_overlap` (mesma mídia reportada duas vezes) fica em `pairs`, mas não entra no gate nem nas sugestões: agrupar somaria a mesma fonte duas vezes. O aviso de overlap já pede para escolher qual manter.
- **`channel_groups`** (lista de listas de canal; nomes com strip/upper e sem repetição, cada grupo com 2+ canais distintos, nenhum canal em dois grupos) soma o spend por data logo após `read_inputs`, antes dos períodos parciais e do adstock de correlação negativa. O canal do grupo se chama `"A + B"`, na ordem do config. `product_group_filter` com o nome de um membro vale para o grupo inteiro.
- **Abaixo de 30 períodos não avalia** (`collinearity_not_assessed`, info, só com 2+ canais que variam; `collinearity` vazia): com poucas datas dois canais correlacionam perto de ±1 por acaso (com 2 datas, ±1 exato). Conta os períodos completos. O histórico mínimo é do A6 e a calibração do A10.
- **Consequência:** a API não manda `channel_groups` nem `block_per_channel` (não estão em `ParamsIn`), então dataset colinear com 30+ períodos não roda pela plataforma até a tela do B2 existir. Quando o B2 mandar esses campos, salvar os parâmetros precisa revalidar (hoje `save_params` não revalida, porque nada do que ele grava muda o relatório).
- **Verificado:** `tests/engine/test_collinearity.py`; o dataset da paridade não dispara o gate (|r| máximo 0.066) e, sem `channel_groups`, a leitura não muda; o teste de paridade em si só roda no Linux.

## Identificabilidade (A5, 05/nov/2026)

- **Só publicação.** O canal não identificável continua no ajuste e no otimizador; o `results.json` e o payload do Gemini é que o escondem. **Por quê:** congelar ou tirar do modelo muda números que a A10 ainda audita, e a paridade fica intacta.
- **IC em unidade do KPI.** `coef_b × Σ X_scaled` por reamostragem, p2.5/p97.5. O coeficiente da Ridge vive no espaço MinMax e não significa nada fora do modelo.
- **"Cruza zero" é p2.5 ≤ 0.** A Ridge tem `positive=True`; zero exato é o canal zerado em ≥ 2,5% das reamostragens. Largura > ponto também reprova. Regra fixa, sem `gate_thresholds`.
- **Bucket `"Não identificados"`.** O spend dos canais escondidos é somado nessa chave no mix da curva, dos cenários e do `.md`/HTML global; os totais não mudam.
- **Nenhum identificável → `inconclusive`, não `failed`.** A curva total e os cenários saem; o `run_status` conta elasticidade `inconclusive` como "publicou algo".
- **Estrito nos dados atuais.** No sintético da paridade (spend com ~3% de ruído) todo canal reprova; com spend lognormal σ = 0,5 o canal forte passa. A Gol deve reprovar toda. Calibrar com a Data Science na A10.
- **O IC é condicional aos hiperparâmetros** (adstock, Hill) do ajuste final: o bootstrap só reamostra a Ridge, então é mais estreito que o verdadeiro. Para a A10.

## Passos do swap (Dev B)

1. Feito: o `pyproject.toml` tem as dependências e o `Dockerfile` copia `engine/` e `llm/` e recebe `ENGINE_VERSION` (`docs/decisoes/infra-e-operacao.md`). Falta medir o tamanho da imagem.
2. **Feito em 05/nov/2026.** `api/engine_run.py` chama `engine.run`. `api/engine_config.py` só tem `ANALYST_FIELDS` (17 nomes) e o `ParamsIn`, criado com `create_model` copiando tipo, default e limites de cada campo do `EngineConfig` do motor (`extra="forbid"`); o `EngineConfig` provisório saiu. `treat_outliers` fica fora do formulário (recebe lista de canais, que o formulário gerado não desenha) e mantém o default do motor. Campos novos no formulário: `post_event_days`, `max_events_to_analyze`, `require_logical_direction`. `PUT …/params` com `REVENUE` sem `average_ticket` dá 422 em `["body", "average_ticket"]` (`revenue_needs_ticket`), checado na rota (um `model_validator` daria `loc ["body"]`, que o formulário não liga a um campo).
3. **Feito em 05/nov/2026.** Migration `0006_rename_require_params`: renomeia `require_significance` → `require_statistical_significance` e `require_good_fit` → `require_model_fit` em `simulations.config` **e** `runs.config`, mantendo os valores (um `false` salvo pode ser escolha do analista); o `downgrade` inverte.
4. **Feito em 05/nov/2026.** `block_reason` e `runBlockReason` não mudaram. `api/validation.py` chama `engine.validate(inputs, config).model_dump(mode="json")` **sempre**, também nos testes e no E2E (o `validate` falso saiu). Problema de dado é check, nunca exceção; só config que o motor recusa levanta `EngineError`, que o `save_mapping` (`api/simulations.py`) transforma em 422 com a mensagem do motor. O caminho `csvfile.Unreadable` → 422 saiu: valor ilegível vira o check `value_not_numeric`, e arquivo sem linha legível ganha também `no_valid_rows`.
5. **Feito em 05/nov/2026.** O falso ficou só para o `run`, atrás de `ENGINE_FAKE=1` (`fake_run` em `api/engine_run.py`, que só emite as linhas de log). Quem liga: o E2E (`web/e2e/env.ts`) e a suíte da API (fixture autouse `fast_engine` em `tests/conftest.py`). `FAKE_ENGINE_STEP_SECONDS` e `FAKE_ENGINE_FAIL` só valem com o falso. Nunca em produção. `tests/api/test_engine_swap.py` sobe CSV sintético, valida e roda no motor real.
6. `run` roda um run inteiro dentro do processo do worker: nenhum subprocess, nenhuma thread gRPC pendurada (o adaptador do Gemini usa `google-genai`).
7. **Feito em 05/nov/2026.** **`EngineError` no worker.** `api/worker.py` tem `except EngineError` antes do `except Exception`: o run falha com a mensagem do próprio motor (pt-BR, segura para a tela por contrato) em `runs.error` e no log, e registra o `check_id`. Qualquer outra exceção segue com a mensagem genérica.
8. **Custo de import.** `from engine import validate` executa o `engine/__init__`, que carrega `pipeline`, statsmodels, sklearn e matplotlib: ~2,2 s e bem mais memória no processo da API (no boot e a cada reload da API). Medir no swap; se pesar, tornar os exports do `__init__` preguiçosos.
9. **Relatórios do LLM.** O `run` chama o Gemini por evento e mais uma vez no global (até 60 s cada) para gerar os HTML legados, mas `reports` sai `null` no `results.json` (A9) e o worker apaga o diretório. Até o A9, o `api/launcher.py` sobe o worker com `LLM_PROVIDER=none` (feito em 05/nov/2026): o custo, a latência e o envio de agregados do cliente não serviam para nada. Tirar isso do launcher quando o A9 preencher `reports`.
10. O `run` já grava o `results.json` no `out_dir`, mas **o worker continua guardando o dict que o `run` devolve** (`json.dumps`), decidido em 05/nov/2026. Enviar o arquivo quebraria os testes que trocam o `run` por uma lambda, e o ganho é nulo: o dict é o mesmo documento.

## Limitações conhecidas

- **`incremental_investment` dos eventos é o investimento total do pós-período** (`total_investment_post_period`), não o incremental (pós − base, que `reports.py` calcula). O `cpa_incremental` usa o mesmo total. Está no spec do A1, mas o nome engana, e o front não pode recalcular. Decidir (renomear ou calcular o incremental no Python) antes de o B5 consumir o campo. Achado da revisão de 05/nov/2026, dono: Trilha A.
- Fallbacks de nome de coluna fixos no código (`inputs.py`: `"Start Date"`, `"Ad Opportunities"`, `"dates"`, `"product_group"`, `"total_revenue"`; `config.py`: `"Sessions"`), contra o CODE-STYLE. Uma coluna mapeada que não existe é trocada por outra com só um `log.warning`, que dentro do `validate` não chega a lugar nenhum. Deveria virar check. Dono: Trilha A.
- **A `message` de `value_not_numeric` (e dos checks que mostram exemplos) leva o valor bruto da coluna, sem limite de tamanho.** Um campo de 200 KB vira uma mensagem de 200 KB no banco e na tela, e o valor é dado do cliente. Truncar os exemplos é da Trilha A.
- `investment_change_pct = 0` com pré-período zerado (`analysis.py`) é sentinela e chega ao `results.json`.
- Em `pipeline.py`, `write_legacy_outputs`, `generate_reports` e `build_results` ficam fora do `try`: uma exceção ali sobe crua em vez de `EngineError`. O `log.error` de "análise não produziu resultados" roda depois do `forward_logs` e não chega ao `on_log`.

- Mensagens do motor ainda misturam inglês (as que não têm regra em `logmessages.py`) e a `reports.py` mantém os prompts em inglês/pt-BR do protótipo (A9).
- `ruff`: o código copiado tem exceções por arquivo em `pyproject.toml` (`# legacy prototype style`); revisar na A10.
- Duas versões de `hill_transform`, de `create_calendar_features` e três convenções de adstock continuam (achado F10, decisão da A10).
- `period_days` ainda tem `config.get("period_days", 1)` nos helpers (chave de runtime).
