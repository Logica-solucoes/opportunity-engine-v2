# Motor (`engine/`)

Decisões do A0, 04/nov/2026. Spec: `docs/superpowers/specs/2026-11-04-a0-pacote-engine-design.md`; plano: `docs/superpowers/plans/2026-11-04-a0-pacote-engine.md`. O código veio do protótipo (`opportunity-engine`, HEAD `6146b7f`, **congelado**: referência de paridade e plano B de demo).

## O que o A0 entregou

`engine.run(inputs, config, out_dir, on_log) -> dict` (contrato §3), `EngineConfig`, `EngineError` e `python -m engine`. Com o A1 e o A2, `run` grava e devolve o `results.json` v1 e `engine.validate` existe (seções abaixo). A branch entrou no `main` em 05/nov/2026; a API ainda usa os falsos (`api/engine_run.py`, `api/validation.py`, `api/engine_config.py`) até o swap do Dev B.

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

### Divergências com `api/engine_config.py` (resolver no swap)

| | `ParamsIn` da API | `EngineConfig` |
|---|---|---|
| gates | `require_significance`, `require_good_fit` | `require_statistical_significance`, `require_logical_direction`, `require_model_fit` |
| `r_squared_threshold` | 0,5 | 0,3 |
| `min_pre_period_days` | 28 | 14 (e há piso interno de 8 períodos) |
| `increase/decrease_threshold_percent` | 20 / 20 | 50 / 30 |
| campos que a API não tem | — | `post_event_days` (14), `max_events_to_analyze` (5), `treat_outliers`, `require_logical_direction` e os preenchidos pelo sistema (`country_code`, `date_formats`, `max_channel_mix_share`…) |

Os defaults do motor vêm do protótipo; **os definitivos são da Data Science**.

## Erros e `on_log`

- `EngineError` leva mensagem em pt-BR **segura para a tela**: sem caminho de arquivo (o motor só vê o caminho do storage) e sem dado do cliente. `data_preprocessor` converte seus `ValueError`/`FileNotFoundError` nele. Qualquer outra exceção sobe como está. O worker hoje esconde toda exceção; adotar `EngineError` ali é decisão do Dev B (é a pergunta em aberto do contrato §3).
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

Os modelos são pequenos: o BLAS multithread só gera disputa de threads. **Recomendação para o ambiente do worker: fixar essas três variáveis em 1** (e então o tamanho do servidor importa pouco: um run usa ~1 núcleo). O `response_curve_data.csv` saiu idêntico byte a byte nas duas medições. Não fixei isso no código do motor (`threadpoolctl`) porque muda o comportamento do processo; é decisão de implantação (Dev B), mas agora também é questão de reprodutibilidade (acima). O limite do run (`STALE_AFTER`, 20 min em `api/runs.py`) é do Dev B; com 1 núcleo, o dataset sintético leva bem menos que isso.

## `results.json` v1 (A1, 04/nov/2026)

Spec: `docs/superpowers/specs/2026-11-04-a1-results-json-design.md`. `engine/results_schema.py` define o contrato inteiro (pydantic, `extra=forbid`, `schema_version=1`); `engine/results.py` monta o documento a partir do `Computed` **sem calcular nada** e `run()` o grava em `out_dir/results.json` e o devolve.

- **Todo o §3 está tipado, mas só `causal`, `elasticity` e `baseline` são preenchidos.** `validation`, `sufficiency`, `experiment_design` e `reports` (A2, A5–A9), e dentro das seções `placebo`, `identifiable`, `coef_ci`, `lo/hi` das curvas, `extrapolated`, `cpa/roas/ramp` dos cenários, saem `null`. Quando o item dono chegar, só preenche. Campo opcional novo não muda `schema_version`; remover ou renomear muda. **Por quê:** o front gera tipos de uma fonte só e nenhum item futuro redefine o contrato.
- **Status.** Cada seção tem `status` (`ok|inconclusive|failed`) e `reasons`. O run é `succeeded` se `causal` e `elasticity` estão `ok`, `failed` se nenhuma está, `inconclusive` nos demais. **Muda o A0 num caso:** MMM ok sem nenhum evento aprovado era `succeeded`. Evento é `published` só se passou nos gates **e** está entre os `max_events_to_analyze`; o resto é `rejected`, com `not_selected` para quem passou e ficou de fora. O front só lê `status` e `reasons`.
- **Sem sentinelas.** `NaN`/`inf` viram `null` em qualquer profundidade (`sanitize`), o documento é validado de novo e gravado com `allow_nan=False`. `cpa_incremental` com lift zero (era `0`) vira `null`.
- **Curva e cenários.** `mix` da curva tem três variantes (`historical`, `optimized`, `strategic`) porque a curva agregada calcula as três. `scenarios` empacota os seis pontos notáveis; o A8 os refina. `iroas` é `Incremental_ROI` (receita incremental / investimento incremental) e `revenue` é `Projected_Revenue`, **só em modo receita** (`kpi_is_monetary` ou alvo `REVENUE`); fora dele valem 0 por construção e saem `null`. `iroas` também é `null` com investimento incremental 0 (o motor escreve 0 para 0/0), e `icpa` é `null` sem investimento ou sem KPI incremental (o motor escreve 0). Um 0 nesses campos nunca é valor real.
- **PNG/HTML do matplotlib continuam sendo gerados** até o B5 estar em paridade.
- **Fixtures** (`tests/fixtures/results/`): Gol **anonimizada** (canais `CANAL_NN`, investimento e KPI multiplicados por fatores privados em `.private/factors.json`, git-ignorado; **datas reais**, risco aceito: o formato da série ainda é reconhecível por quem conhece a Gol). Teste de CI garante só nomes anônimos e nenhum caminho; teste local confirma que nenhum nome ou valor original aparece. Regenerar exige `exemplo_csv/` e o mesmo arquivo de fatores (`generate_fixtures.py`, ~6 min).
- **Para o Dev B:** `api/worker.py` hoje faz `json.dumps(results)` e grava; como `run` já devolve o dict seguro, os dois arquivos saem iguais. No swap, o worker pode só enviar o `results.json` que o `run` gravou.

## `validate` (A2, 04/nov/2026)

Spec: `docs/superpowers/specs/2026-11-04-a2-validacao-upload-design.md`. `engine.validate(inputs, config) -> ValidationReport` é síncrono, não roda modelo e **nunca levanta por problema de dado**: o problema vira um check (só uma configuração inválida levanta `EngineError`). `engine/inputs.py` (`read_inputs`) lê e normaliza os três CSV e é usado por `validate` **e** por `load_and_prepare_data`; por isso o que o `validate` aprova o `run` lê igual.

- **Catálogo (ids estáveis):** erros `file_unreadable`, `column_missing`, `column_unusable` (o parser quebrou com o formato da coluna, ex. canal numérico ou cabeçalhos repetidos), `date_unparseable`, `value_not_numeric`, `no_valid_rows`, `duplicate_date_channel`, `kpi_duplicate_dates`, `kpi_not_single_source`, `cadence_mismatch`, `insufficient_after_partial`; avisos `missing_dates`, `dv360_cm360_overlap`; infos `outliers`, `partial_period_dropped`. `details` leva os dados estruturados (datas até 50, contagens, canais) para a tela.
- **Fim da correção silenciosa.** Duplicata de (data, canal) no investimento (era média) e data repetida no KPI (era soma) são **erro**. `run()` valida primeiro e para no primeiro erro com `EngineError.check_id`; avisos e infos vão para o `results.json` (`validation`) e para o log.
- **`kpi_not_single_source`:** o KPI repete data **e** uma coluna de texto do arquivo de performance muda entre linhas da mesma data (canal, plataforma). Colunas de texto que na verdade são números em formato local (`1.234,56`) não contam. Data repetida sem tal coluna é `kpi_duplicate_dates`.
- **`dv360_cm360_overlap`:** por série, nunca por nome: correlação diária > 0.95 e razão de soma (menor/maior, simétrica) ≥ 0.9, isto é, entre 0.9 e ~1.11 para qualquer ordem dos nomes; canal constante ou de soma zero é ignorado.
- **`missing_dates`** olha lacunas por série (intervalo / cadência arredondado), tolerando o ±1 dia de re-ancoramento semanal que `detect_cadence` já aceita.
- **Achado nos dados reais:** `exemplo_csv/Gol/investment.csv` tem GOOGLE 5 vezes por dia (valores diferentes, provavelmente subcampanhas) e o protótipo tirava a **média**. Agora a Gol como enviada é rejeitada. Se o certo é **somar** e não tirar a média (a média subestima o investimento do canal), isso é decisão de negócio com a Data Analytics; hoje o analista precisa consolidar o arquivo. `parity-real` compara protótipo e motor numa cópia da Gol com a média aplicada **no teste** (`tests/engine/real_data.py`); sobre o arquivo original os dois já não concordam (o adstock do protótipo rodava nas linhas repetidas antes do `pivot_table`).
- **Para o Dev B (swap):** `api/validation.py` vira `from engine import validate`; o `config` pode ir como veio (dict ou `EngineConfig`). A tela do B2 deve tratar os novos ids (`details` por id) e o nível `info`. Ausência de `generic_trends_file` é `None`.
- **Fora do A2:** colinearidade (`collinearity` sai vazia, A3), templates CSV oficiais e nomes DV360/CM360 (Data Analytics).

## Passos do swap (Dev B)

1. Feito: o `pyproject.toml` tem as dependências e o `Dockerfile` copia `engine/` e `llm/` e recebe `ENGINE_VERSION` (`docs/decisoes/infra-e-operacao.md`). Falta medir o tamanho da imagem.
2. `api/engine_run.py` vira `from engine import run`; `api/engine_config.py` passa a derivar do `EngineConfig` (formulário e `/api/engine/config-schema` vêm de `EngineConfig.model_json_schema()`; decidir o layout dos campos novos e o que fica "avançado").
3. **Configs já salvas** têm as chaves provisórias (`require_significance`, `require_good_fit`): o `EngineConfig` as recusa com `EngineError`. Migrar `simulations.config` e decidir o que fazer com `runs.config` antigos ("Rodar de novo" já filtra pelo schema).
4. `block_reason` (gate do Rodar) e `runBlockReason` da tela não mudam. O `validate` falso vira `from engine import validate`, **mas o real devolve um `ValidationReport` (pydantic), não dict**: `api/simulations.py` faz `report["ok"]` e grava em JSONB, e `api/runs.py` itera `validation["checks"]`. Use `validate(...).model_dump(mode="json")`. O `validate` também levanta `EngineError` com config inválido, e o `save_mapping` passa o `simulation.config` com os parâmetros já salvos (passo 3): sem migrar nem capturar, vira 500.
5. Testes: `tests/conftest.py` (`fast_engine`) e `tests/api/test_runs.py` usam `FAKE_ENGINE_*`; trocar por um motor falso injetado, ou manter o falso atrás de uma variável de ambiente nos testes.
6. `run` roda um run inteiro dentro do processo do worker: nenhum subprocess, nenhuma thread gRPC pendurada (o adaptador do Gemini usa `google-genai`).
7. **`EngineError` no worker.** `api/worker.py` captura `Exception` e grava uma mensagem genérica. Com o A2, o `run` para no primeiro check de erro com `EngineError` (mensagem pt-BR, `check_id`); sem um `except EngineError as e: message = str(e)`, essa mensagem nunca chega à tela do run.
8. **Custo de import.** `from engine import validate` executa o `engine/__init__`, que carrega `pipeline`, statsmodels, sklearn e matplotlib: ~2,2 s e bem mais memória no processo da API (no boot e a cada reload da API). Medir no swap; se pesar, tornar os exports do `__init__` preguiçosos.
9. **Relatórios do LLM.** O `run` chama o Gemini por evento e mais uma vez no global (até 60 s cada) para gerar os HTML legados, mas `reports` sai `null` no `results.json` (A9) e o worker apaga o diretório. Até o A9, rode o worker com `LLM_PROVIDER=none`: o custo, a latência e o envio de agregados do cliente não servem para nada.
10. O `run` já grava o `results.json` no `out_dir`; o worker pode enviar esse arquivo em vez de regravar o dict.

## Limitações conhecidas

- **`incremental_investment` dos eventos é o investimento total do pós-período** (`total_investment_post_period`), não o incremental (pós − base, que `reports.py` calcula). O `cpa_incremental` usa o mesmo total. Está no spec do A1, mas o nome engana, e o front não pode recalcular. Decidir (renomear ou calcular o incremental no Python) antes de o B5 consumir o campo. Achado da revisão de 05/nov/2026, dono: Trilha A.
- Fallbacks de nome de coluna fixos no código (`inputs.py`: `"Start Date"`, `"Ad Opportunities"`, `"dates"`, `"product_group"`, `"total_revenue"`; `config.py`: `"Sessions"`), contra o CODE-STYLE. Uma coluna mapeada que não existe é trocada por outra com só um `log.warning`, que dentro do `validate` não chega a lugar nenhum. Deveria virar check. Dono: Trilha A.
- `investment_change_pct = 0` com pré-período zerado (`analysis.py`) é sentinela e chega ao `results.json`.
- Em `pipeline.py`, `write_legacy_outputs`, `generate_reports` e `build_results` ficam fora do `try`: uma exceção ali sobe crua em vez de `EngineError`. O `log.error` de "análise não produziu resultados" roda depois do `forward_logs` e não chega ao `on_log`.

- Mensagens do motor ainda misturam inglês (as que não têm regra em `logmessages.py`) e a `reports.py` mantém os prompts em inglês/pt-BR do protótipo (A9).
- `ruff`: o código copiado tem exceções por arquivo em `pyproject.toml` (`# legacy prototype style`); revisar na A10.
- Duas versões de `hill_transform`, de `create_calendar_features` e três convenções de adstock continuam (achado F10, decisão da A10).
- `period_days` ainda tem `config.get("period_days", 1)` nos helpers (chave de runtime).
