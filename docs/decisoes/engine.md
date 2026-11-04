# Motor (`engine/`)

Decisões do A0, 04/nov/2026. Spec: `docs/superpowers/specs/2026-11-04-a0-pacote-engine-design.md`; plano: `docs/superpowers/plans/2026-11-04-a0-pacote-engine.md`. O código veio do protótipo (`opportunity-engine`, HEAD `6146b7f`, **congelado**: referência de paridade e plano B de demo).

## O que o A0 entregou

`engine.run(inputs, config, out_dir, on_log) -> dict` (contrato §3), `EngineConfig`, `EngineError` e `python -m engine`. O `run` devolve só o mínimo do contrato (`schema_version`, `engine_version`, `status`, demais seções `null`); o `results.json` é o A1. `validate` (A2) continua sendo o falso de `api/validation.py`.

## Pipeline em estágios, sem mexer na matemática

`engine/pipeline.py` divide o fluxo do `local_main` em `load_inputs → detect_events → analyze_events → run_elasticity` (agrupados em `compute()`), que devolvem dados em memória (`Computed`, `EventOutcome` com `passed` e `reasons`); `engine/outputs.py` escreve os arquivos de sempre (PNG, CSV, Markdown, HTML) a partir do `Computed`. **Por quê:** o A1 troca os escritores por um montador de `results.json` sem desmontar o fluxo, e a paridade se prova no `compute()`, sem arquivos no meio.

- Os módulos analíticos (`analysis`, `elasticity_analysis`, `data_preprocessor`, `presentation`, `recommendations`) são cópias; só mudaram imports, caminhos, a leitura única dos dados (`PreparedData`), a remoção de `exit`/`os._exit`/`getcwd`/`sys.path`, e os defaults (Fase 2).
- Os dados são lidos **uma vez**; antes, `local_main` e `run_mmm_engine` liam e preparavam duas vezes, e o arquivo de performance uma terceira.
- Um evento que falha não derruba o run. Os três gates (`require_statistical_significance`, `require_logical_direction`, `require_model_fit`) registram `reasons` (`not_significant`, `illogical_direction`, `poor_fit`, `analysis_failed`) em memória; hoje isso não chega ao `results.json` (A1).
- `status`: `succeeded`, ou `failed` quando o MMM não produz resultado e nenhum evento passa. `inconclusive` é da A6.
- Saída em `out_dir`: `<canais>/<data>/…` por evento selecionado e `global_saturation_analysis/`. O nível `<advertiser>` e o `output_directory` do protótipo sumiram (nada lê esses caminhos). O relatório do evento é `report_<canais>_<data>.html` (era `gemini_report_*.html`). A falha ou a ausência do LLM cai em `RECOMMENDATIONS.md` (texto determinístico).

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
- **Curva e cenários.** `mix` da curva tem três variantes (`historical`, `optimized`, `strategic`) porque a curva agregada calcula as três. `scenarios` empacota os seis pontos notáveis; o A8 os refina. `iroas` é `Incremental_ROI` (receita incremental / investimento incremental).
- **PNG/HTML do matplotlib continuam sendo gerados** até o B5 estar em paridade.
- **Fixtures** (`tests/fixtures/results/`): Gol **anonimizada** (canais `CANAL_NN`, investimento e KPI multiplicados por fatores privados em `.private/factors.json`, git-ignorado; **datas reais**, risco aceito: o formato da série ainda é reconhecível por quem conhece a Gol). Teste de CI garante só nomes anônimos e nenhum caminho; teste local confirma que nenhum nome ou valor original aparece. Regenerar exige `exemplo_csv/` e o mesmo arquivo de fatores (`generate_fixtures.py`, ~6 min).
- **Para o Dev B:** `api/worker.py` hoje faz `json.dumps(results)` e grava; como `run` já devolve o dict seguro, os dois arquivos saem iguais. No swap, o worker pode só enviar o `results.json` que o `run` gravou.

## Passos do swap (Dev B)

1. `pyproject.toml` já tem as dependências; o `Dockerfile` precisa de `COPY engine/ ./engine/` e `COPY llm/ ./llm/` (medir o tamanho da imagem antes/depois).
2. `api/engine_run.py` vira `from engine import run`; `api/engine_config.py` passa a derivar do `EngineConfig` (formulário e `/api/engine/config-schema` vêm de `EngineConfig.model_json_schema()`; decidir o layout dos campos novos e o que fica "avançado").
3. **Configs já salvas** têm as chaves provisórias (`require_significance`, `require_good_fit`): o `EngineConfig` as recusa com `EngineError`. Migrar `simulations.config` e decidir o que fazer com `runs.config` antigos ("Rodar de novo" já filtra pelo schema).
4. `block_reason` (gate do Rodar) e `runBlockReason` da tela não mudam. O `validate` continua o falso até o A2.
5. Testes: `tests/conftest.py` (`fast_engine`) e `tests/api/test_runs.py` usam `FAKE_ENGINE_*`; trocar por um motor falso injetado, ou manter o falso atrás de uma variável de ambiente nos testes.
6. `run` roda um run inteiro dentro do processo do worker: nenhum subprocess, nenhuma thread gRPC pendurada (o adaptador do Gemini usa `google-genai`).

## Limitações conhecidas

- Mensagens do motor ainda misturam inglês (as que não têm regra em `logmessages.py`) e a `reports.py` mantém os prompts em inglês/pt-BR do protótipo (A9).
- `ruff`: o código copiado tem exceções por arquivo em `pyproject.toml` (`# legacy prototype style`); revisar na A10.
- Duas versões de `hill_transform`, de `create_calendar_features` e três convenções de adstock continuam (achado F10, decisão da A10).
- `period_days` ainda tem `config.get("period_days", 1)` nos helpers (chave de runtime).
