# A0 — Pacote `engine` e pipeline único (design)

Item A0 da Trilha A (`docs/m2/trilha-a-motor.md`). Contexto e conceitos: `docs/onboarding-trilha-a.md`. Código de origem: repo do protótipo em `/home/rodrigo/Sistemas/Dash/opportunity-engine/` (HEAD `6146b7f`), **congelado** a partir de agora.

## Intenção e por quê

Hoje o motor é um conjunto de scripts do protótipo: cada execução lê caminhos de um JSON, escreve em `outputs/` relativo ao diretório atual, imprime no stdout, chama `exit` e `os._exit`, e tem dois pontos de entrada (`local_main.py`, `local_main-without-gemini.py`) que já divergiram. A plataforma (worker do B4) precisa chamar o motor como biblioteca: `run(inputs, config, out_dir, on_log) -> dict`. Sem isso, a API segue com o motor falso (`api/engine_run.py`) e nenhum dos itens A1–A10 pode ser construído sobre uma base testável.

O A0 entrega essa base **sem mudar nenhum número** (Fase 1) e depois centraliza config e limpeza (Fase 2). A divisão existe para que, se um número mudar, se saiba qual fase causou.

## Metas

1. Pacote `engine/` importável (`from engine import run, EngineConfig`), com as dependências analíticas no `pyproject.toml`/`uv.lock`.
2. `engine.pipeline.run` único, unindo os dois `local_main`, com LLM opcional.
3. Módulo `llm/` plugável (interface, erros, fábrica) com **um único provedor implementado: Gemini**. Trocar de provedor no futuro é escrever um adaptador e registrá-lo, sem tocar no motor nem na API.
4. `engine.config.EngineConfig` (pydantic) como única fonte de parâmetros e defaults.
5. O motor só lê de `inputs`, só escreve em `out_dir`, reporta por `on_log`, nunca encerra o processo e nunca mexe em filtros globais de warnings nem em `sys.path`.
6. Dados lidos e preparados **uma vez** por run; a config recebida não é mutada.
7. **Snapshot de paridade** (`tests/fixtures/parity/`) provando que a Fase 1 não mudou números (tolerância 1e-9 relativa).
8. `python -m engine` para rodar o motor na linha de comando.
9. Os testes do protótipo que pertencem ao motor passam no novo local.

## Não-metas

- `results.json`, schema e fixtures de resultado (A1). `run` devolve só o dict mínimo do contrato (ver "Retorno").
- `validate` (A2) e qualquer gate novo (A3–A9). A API continua com o `validate` falso.
- Trocar `api/engine_run.py`, `api/engine_config.py` ou o `Dockerfile` (ver "Entrega ao Dev B"; é um passo seguinte, combinado, não parte do A0).
- Unificar as convenções de adstock ou as duas versões de `hill_transform` / `create_calendar_features` (achado F10, decisão da A10). **Elas não são idênticas**; unir muda números.
- Reescrever prompts, payload restrito, `response_schema` nos relatórios e o grounding (A9). O A0 só troca o transporte do Gemini pelo módulo `llm/` (ver "Módulo LLM"); os prompts ficam como estão, inclusive a persona "Google marketing strategist", que é conteúdo da A9.
- Adaptadores para outros provedores (Claude etc.). A interface é desenhada para recebê-los; **nenhum é escrito agora**.
- Migrar `api/gemini.py` e as sugestões do B3 para o módulo `llm/` (Dev B, passo seguinte) e renomear rota, `source: "gemini"` e botão da tela.
- Conectores de dados do Google (BigQuery, Ads, GA4): fora do escopo por ora. Os dados entram só por CSV. O motor nunca consultou o Google para métricas; nada muda no A0.
- Streamlit: fica no repo antigo, congelado, como referência de paridade e plano B de demo. O aceite "Streamlit roda" **sai do A0**.
- `dashboard_charts.py` e seus testes (A8 e B5), `streamlit_app.py`, `db.py`, `google_api.py`.
- Preservar histórico git dos arquivos (decisão: copiar).

## Anti-metas (falha mesmo que "funcione")

- Um número diferente do protótipo na Fase 1, mesmo que "melhor".
- Corrigir bug estatístico de passagem (isso é A4–A10, e cada mudança de número precisa ser registrada para a auditoria).
- Mudar a assinatura de `run` do contrato.

## Restrições

- Contrato A↔B (`docs/m2/README.md` §1 e §3): `run(inputs, config, out_dir, on_log) -> dict`; `inputs = {"investment_file": Path, "performance_file": Path, "generic_trends_file": Path | None}`; `on_log(level, message)` com `level ∈ info|warning|error` e `message` em pt-BR; `status ∈ succeeded|inconclusive|failed`; sem `NaN`/`Infinity` no que for devolvido.
- O worker (`api/worker.py`) exige `results["status"]` e `results["engine_version"]`, grava `json.dumps(results)` sem `allow_nan=False` e esconde toda exceção do usuário.
- `CODE-STYLE.md`: sem `print()`, `logging.getLogger(__name__)`, nunca hardcode de coluna (resolver por `column_mapping`), `ruff format` (linha 120) e `ruff check`.
- Python 3.13, `uv`. **Paridade numérica exige as mesmas versões do protótipo**: o `uv.lock` dele fixa numpy 2.5.0, pandas 3.0.3, scipy 1.18.0, statsmodels 0.14.6, scikit-learn 1.9.0, holidays 0.99, matplotlib 3.11.0. O `uv.lock` de v2 não tem nenhuma delas; elas entram **fixadas nessas versões** (`==`) e a decisão de atualizá-las é posterior à A10.
- O repo do protótipo não é modificado.
- **Hospedagem: servidor próprio x86-64** (Docker, sem GCP/Cloud Run). O worker é um processo separado (hoje `api/launcher.py` por subprocess). Não há limite de 15 min de Job; o único limite é o `STALE_AFTER` de 20 min em `api/runs.py` (Dev B). Chaves de API por variável de ambiente, sem Secret Manager.

## Decisões já tomadas na conversa

- Copiar os arquivos (sem histórico).
- Repo antigo congelado como referência; `engine/` daqui evolui sozinho.
- Duas fases: mover sem mudar números, depois centralizar.
- Pipeline em estágios sem mexer na matemática (opção 3 abaixo).
- Módulo `llm/` plugável, com **só o Gemini implementado** (04/nov).
- Hospedagem em servidor próprio x86-64, sem GCP; sem integração de dados com o Google por ora (04/nov).

## Abordagens consideradas

| | O que é | Prós | Contras |
|---|---|---|---|
| 1. Casca fina | `pipeline.py` = corpo do `local_main` adaptado; continua gravando arquivos; devolve dict mínimo | menor risco de paridade | o A1 precisa desmontar o fluxo depois para obter os dados em memória |
| 2. Pipeline em estágios puros | estágios devolvem dados; escritores separados; módulos refatorados | melhor base para o A1 | muda muito de uma vez; difícil achar quem mudou um número |
| **3. Estágios sem mexer na matemática (escolhida)** | `pipeline.py` em funções de estágio que devolvem dados em memória; escritores legados chamados depois, com o mesmo conteúdo; módulos analíticos só mudam em imports, caminhos, `exit`/`getcwd`/warnings e na leitura única | paridade preservada; o A1 troca os escritores por um montador de JSON | um pouco mais de trabalho que a 1 |

## Design

### Layout

```
engine/
  __init__.py        exporta run, EngineConfig, EngineError
  __main__.py        CLI (python -m engine)
  config.py          EngineConfig + conversão para o dict "legado"
  errors.py          EngineError (mensagem em pt-BR, segura para a tela)
  pipeline.py        run() e os estágios
  data_preprocessor.py  analysis.py  elasticity_analysis.py
  reports.py         (ex-gemini_report.py, neutro)  presentation.py  recommendations.py
  logmessages.py     regras de tradução pt-BR (copiadas de logger.py) + handler do on_log
llm/                 módulo plugável compartilhado por engine/ e api/ (ver "Módulo LLM")
  __init__.py        LLM, erros, get_llm()
  base.py            Protocol LLM + LLMError/LLMUnavailable/LLMRefused/LLMBadOutput
  gemini.py          GeminiLLM (único provedor)
tests/engine/        testes migrados + paridade
tests/llm/           contrato do módulo + adaptador Gemini com cliente falso
tests/fixtures/parity/
```

Copiados sem mudança de matemática: `data_preprocessor`, `analysis`, `elasticity_analysis`, `presentation`, `recommendations` e `gemini_report` (renomeado `reports.py`, com os parâmetros `gemini_client` → `llm`; ver "Módulo LLM"). **Removidos**: `saturation_curve.py` (código morto), `generate_elasticity_budget_scenarios` e `generate_historical_split_scenarios` (sem chamadores), o bloco `if __name__ == "__main__"` de `elasticity_analysis.py` (CLI própria, usa `getcwd`). **Não copiados**: `streamlit_app`, `db`, `google_api`, `dashboard_charts`, `local_main*` (viram o pipeline), `logger.py` (só as regras de tradução e `translate_line` vão para `logmessages.py`; o resto é infraestrutura de arquivo/stdout do Streamlit).

### API pública

```python
def run(inputs: dict[str, Path | None], config: dict | EngineConfig, out_dir: Path,
        on_log: Callable[[str, str], None]) -> dict
```

`config` aceito como dict (o snapshot salvo na simulação) ou `EngineConfig`; dict é validado por `EngineConfig.model_validate`, completando defaults. **Não** muta a entrada.

### `EngineConfig`

Pydantic, `extra="forbid"`, `allow_inf_nan=False`. Parte dos nomes e defaults do protótipo, com `investment_limit_factor=1.5` (BRD) e `optimization_target="CONVERSIONS"` (o código do protótipo usa `REVENUE`, que não validaria sem `average_ticket`; o validador do modelo exige o ticket quando o alvo é `REVENUE`):

- **Formulário** (superconjunto do `ParamsIn` atual da API): `optimization_target`, `kpi_is_monetary`, `average_ticket`, `conversion_rate_from_kpi_to_bo`, `financial_targets` (`None` = sem meta), `investment_limit_factor`, `max_budget_step`, `p_value_threshold`, `min_pre_period_days`, `r_squared_threshold`, `increase_threshold_percent`, `decrease_threshold_percent`, `post_event_days`, `max_events_to_analyze`, `treat_outliers`, e os três gates `require_statistical_significance`, `require_logical_direction`, `require_model_fit`.
- **Preenchidos pelo sistema**: `column_mapping`, `date_formats`, `channel_groups`, `controls`, `gate_thresholds`, `product_group_filter`, `min_intervention_date` (era argumento de CLI), `country_code`, `per_channel_investment_limit_factor`, `max_channel_mix_share`, `minimum_acceptable_iroi`, `min_marketing_contribution`, `reallocation_min_cv_r2` (confirmar nome na implementação). O modelo e o provedor de LLM **não** são config de run: são config de implantação (`LLM_PROVIDER`, `LLM_MODEL`; ver "Módulo LLM"), e `gemini_model` sai do `EngineConfig`.
- **Metadados de relatório**: `advertiser_name`, `client_industry`, `client_business_goal`, `primary_business_metric_name` (opcionais, com default neutro; a API hoje não os tem).
- **Removidos**: `*_file_path` e `output_directory` (viram `inputs` e `out_dir`); `performance_kpi_column` (derivado de `column_mapping.performance_file.kpi_col`); `average_ticket_value` (alias antigo).
- `period_days` **não é entrada**: é resultado da detecção de cadência e vive no objeto de dados preparados.

**Compatibilidade com os módulos copiados.** Os módulos continuam lendo `config.get("chave", default)`. O `EngineConfig` expõe `to_legacy_dict()`, que devolve um dict com **todas** as chaves preenchidas (os `default` espalhados no código viram código morto, e passam a ser removidos na Fase 2). `None` em `financial_targets` vira **chave ausente** na conversão: o código já lê `financial_targets.get("target_cpa", float("inf"))`, `"target_roas", 0` e `"target_iroas", minimum_acceptable_iroi`, então ausência é exatamente "sem meta" (verificado em `analysis.py:1005-1012` e `elasticity_analysis.py:926-930`); sentinelas como `999999` nunca aparecem em `EngineConfig` nem no que `run` devolve. O dict efetivo de cada run é uma cópia com `period_days` preenchido após a leitura.

**Divergência com a API** (lista a entregar ao Dev B, ver abaixo): a API não tem `post_event_days`, `max_events_to_analyze`, `require_logical_direction` e outros; usa `require_significance`/`require_good_fit` onde o motor tem três gates; e os defaults de `r_squared_threshold` (0,5 × 0,3), `min_pre_period_days` (28 × 14) e dos limiares de evento (20/20 × 50/30 no exemplo) diferem. O A0 adota os do protótipo e **não altera a API**.

### Estágios do `pipeline.py`

1. `load_inputs` → `PreparedData` (dataclass): `kpi_df`, `investment_df`, `trends_df`, `performance_df` (a leitura crua usada para covariáveis, hoje relida), `correlation_matrix`, `period_days`. Uma leitura só; `run_mmm_engine` passa a receber o `PreparedData` em vez de recarregar. Mudança de assinatura em `load_and_prepare_data` e `run_mmm_engine`; os testes migrados são ajustados.
2. `detect_events` → candidatos (`find_events` + filtro `product_group_filter`/`min_intervention_date`).
3. `analyze_events` → pré-treina o modelo de resposta, roda `run_causal_impact_analysis` por candidato, aplica os três gates e devolve **todos** os eventos com `passed` e `reasons` (hoje só log), ordena os aprovados por |lift| e corta em `max_events_to_analyze`.
4. `run_elasticity` → MMM, curva agregada, curvas individuais, cenários.
5. `write_legacy_outputs` e `generate_reports` → PNG, CSV, MD e HTML com o conteúdo de hoje, sob `out_dir` (`<canais>/<data>/…` por evento e `global_saturation_analysis/`; o nível `<advertiser>` e `output_directory` somem — escolha minha, o repo antigo está congelado e nada lê esses caminhos). Com LLM: relatório por evento e global; sem LLM, sem chave ou em indisponibilidade (`LLMUnavailable`): `recommendations.generate_basic_recommendations_file` por evento e sem narrativa global (comportamento do `local_main-without-gemini`). A indisponibilidade vista uma vez no run desliga as chamadas seguintes (substitui `is_gemini_outage_error`).

Erro de um evento ou relatório não derruba o run (como hoje). `generate_global_gemini_report` (renomeada `generate_global_report`) deixa de calcular o diretório por `getcwd` e recebe o caminho.

### Retorno

Dict mínimo do contrato: `schema_version=1`, `engine_version` (git sha se disponível, senão versão do pacote), `status`, e as demais seções `null`. `status`: `succeeded` normalmente; `failed` se o MMM não produziu resultado e nenhum evento foi aprovado. `inconclusive` é da A6. As estruturas em memória dos estágios (eventos com `passed`/`reasons`, `mmm_results`, curvas) ficam acessíveis ao A1, mas **não** entram no dict no A0.

### Erros

`EngineError(Exception)` com mensagem pt-BR segura para a tela. As `ValueError`/`FileNotFoundError` de `data_preprocessor` que já têm texto pt-BR e útil são relançadas como `EngineError`; qualquer outra exceção sobe como está. O worker hoje descarta a mensagem de qualquer exceção por segurança; adotar `EngineError` lá é decisão do Dev B (responde à pergunta em aberto do contrato §3).

### `on_log`

Um `logging.Handler` instalado na árvore de loggers do motor durante o `run` (e removido no `finally`) encaminha registros de nível `INFO+` para `on_log`, passando a mensagem por `translate_line` (regras pt-BR copiadas de `logger.py`; `None` descarta ruído; linha sem regra passa como está). `WARNING → "warning"`, `ERROR/CRITICAL → "error"`, `INFO → "info"`. Não escreve em stdout nem em arquivo.

### Warnings e `sys.path`

Sem `filterwarnings` em nível de módulo. O `run` executa dentro de `warnings.catch_warnings()` com os mesmos filtros de hoje, restaurados na saída (o contrato "nunca mexe em filtros globais" vale porque o estado é restaurado; `catch_warnings` não é thread-safe, o que não importa num worker de processo único). Sem `sys.path`; `presentation.py` importa `analysis` por import normal do pacote.

### Módulo LLM (`llm/`)

**Por quê.** Hoje há duas chamadas de LLM acopladas ao SDK do Google (`gemini_report.py`, 2 pontos; `api/gemini.py`, 1 ponto). A decisão é implementar só Gemini, mas de modo que a troca futura seja escrever um arquivo.

**Pacote de topo**, não dentro de `engine/`, para a API poder usá-lo sem importar o motor. Quem cria é o A0; quem migra o `api/gemini.py` é o Dev B.

```python
# llm/base.py
class LLM(Protocol):
    provider: str                 # "gemini"
    model: str
    def generate_text(self, prompt: str, *, timeout_s: float | None = None) -> str: ...
    def generate_json(self, prompt: str, schema: dict, *, timeout_s: float | None = None) -> Any: ...
        # JSON já parseado; o chamador valida com pydantic

class LLMError(Exception): ...               # base
class LLMUnavailable(LLMError):              # sem chave, rede, timeout, cota, 5xx: tente de novo depois / use o texto determinístico
    reason: str                              # código curto e estável para log ("no_key", "rate_limited", "timeout"…)
class LLMRefused(LLMError): ...              # o provedor recusou por política
class LLMBadOutput(LLMError): ...            # resposta não é JSON válido / não bate com o schema pedido

# llm/__init__.py
def get_llm(provider: str | None = None, model: str | None = None) -> LLM | None
```

- **Seleção por implantação:** `LLM_PROVIDER` (default `gemini`; `none` desliga) e `LLM_MODEL` (default `gemini-flash-latest`, o alias que o B3 usa hoje). Chaves ficam com o adaptador: `GEMINI_API_KEY`. `get_llm()` devolve `None` quando o provedor é `none` ou não há chave (o chamador cai no texto determinístico); provedor desconhecido levanta `ValueError` (erro de configuração, não de run). As variáveis entram no `.env.example`.
- **Registro:** `PROVIDERS = {"gemini": GeminiLLM}` em `llm/__init__.py`. Adicionar Claude no futuro = `llm/claude.py` + uma linha no dicionário + a dependência.
- **O que a interface não expõe:** temperatura, esforço de raciocínio, penalidades, seed. São detalhes de cada provedor e ficam **dentro** do adaptador (alguns modelos nem aceitam). Determinismo e segurança vêm do grounding da A9 e da validação pydantic de quem chama, que valem para qualquer provedor. `timeout_s` fica na interface porque é geral e as chamadas têm limites diferentes (60 s nos relatórios, 20 s nas sugestões).
- **`GeminiLLM`** usa `google-genai` (já dependência; import dentro do adaptador, para o pacote importar sem o SDK). `generate_text`: `models.generate_content`. `generate_json`: `response_mime_type="application/json"` + `response_json_schema`, como `api/gemini.py` faz; tolera *code fence* antes do `json.loads`. Sem `temperature` explícito (comportamento atual dos relatórios). Mapeamento de erros: sem chave, `429`, `500/503/504`, timeout e falha de conexão → `LLMUnavailable(reason)`; recusa por segurança → `LLMRefused`; JSON inválido → `LLMBadOutput`; qualquer outro erro do SDK → `LLMError`.
- **`reports.py`** troca as duas chamadas `gemini_client.generate_content(prompt, request_options=…)` + `.text` por `llm.generate_text(prompt, timeout_s=60)`; o parsing do JSON da narrativa continua no lugar (remover fica para a A9, que usará `generate_json`). `LLMUnavailable` passa **sem ser embrulhado** em `RuntimeError`; o pipeline a captura, marca "LLM indisponível neste run" e pula as chamadas restantes (o que `is_gemini_outage_error` fazia por casamento de texto). Qualquer outro `LLMError` falha só aquele relatório, como hoje.
- **`os._exit(0)`:** o SDK antigo (`google-generativeai`) deixava um thread gRPC que travava o processo. O A0 não o adiciona; `google-genai` não tem o problema (confirmar no teste da CLI: o processo termina sozinho).
- **Parity:** o teste roda com `LLM_PROVIDER=none`, então nenhuma chamada de rede acontece e a presença de `GEMINI_API_KEY` no `.env` do desenvolvedor não altera nada.

### CLI

`python -m engine --config run.json --out DIR`. `run.json` = campos do `EngineConfig` + chave `inputs` com os três caminhos. Logs vão para o stderr no formato `[nível] mensagem`. Código de saída 0 em `succeeded`, 1 em `failed` ou `EngineError`. Existe para desenvolvimento e para gerar/conferir o snapshot, não para a plataforma.

### Testes e paridade

- **Migrados** para `tests/engine/` (sem `sys.path`): `test_analysis`, `test_elasticity_analysis`, `test_data_preprocessor`, `test_presentation`, `test_gemini_report` (renomeado `test_reports`; o teste de `is_gemini_outage_error` vira teste do tratamento de `LLMUnavailable`), e as regras de `test_logger` que cobrem `translate_line`. **Não migrados**: `test_db`, `test_google_api`, `test_streamlit_throttle`, `test_filter_columns` (lógica da sidebar do Streamlit) e `test_dashboard_charts` (A8).
- **`tests/llm/`**: um conjunto de testes de **contrato** reutilizável (`run_provider_contract(llm)`) que qualquer adaptador futuro deve passar: texto, JSON válido, JSON inválido → `LLMBadOutput`, indisponibilidade → `LLMUnavailable`. Para o Gemini roda com um cliente `genai` falso (sem rede): mapeamento de erros (429/503/timeout → `Unavailable`; 400 → `LLMError`), ausência de chave, `get_llm()` com `none`/provedor desconhecido. Um teste vivo opcional (pulado sem `GEMINI_API_KEY`). Um `FakeLLM` em `tests/fakes/llm.py` serve ao motor e à API.
- **Dataset**: `exemplo_csv/` não existe no disco. Gerador sintético determinístico em `tests/engine/synthetic_data.py` (seed fixa; 2 anos diários, ~5 canais, ao menos 2 degraus de investimento detectáveis, sazonalidade semanal, ruído, arquivo de trends). Vira o germe do gerador da A10. Se o `exemplo_csv/` aparecer, entra como segundo caso.
- **Snapshot**: `tests/fixtures/parity/generate_legacy_snapshot.py` roda o código **do repo antigo, sem modificá-lo** (caminho em `LEGACY_REPO`, usando o `uv.lock` dele) sobre o dataset e grava `snapshot.json` com: por candidato de evento, o `results_data` completo e o resultado dos gates; `contribution_pct`, `r_squared`, `cv_r_squared`, `optimal_params` e `marketing_contribution_of_kpi_pct` do MMM; `response_curve_df` e os seis pontos notáveis; os cenários. O script chama as funções do código antigo diretamente (`find_events`, `run_opportunity_projection`, `run_causal_impact_analysis`, `run_mmm_engine`, `generate_aggregated_response_curve`), não o `local_main`, que só produz arquivos; os três gates são reavaliados no script com a mesma fórmula de `local_main.py:229-250`. O snapshot é gerado **uma vez**, antes de qualquer mudança, e commitado. Config do dataset com `investment_limit_factor` explícito (os defaults divergentes do código ficam fora do caminho da Fase 1).
- **Teste de paridade**: roda `engine.run` no mesmo dataset e compara com `numpy.testing.assert_allclose(rtol=1e-9)`. LLM desligado (`LLM_PROVIDER=none`). Antes de exigir 1e-9, medir: rodar o protótipo duas vezes e `engine` duas vezes; se houver oscilação, registrar a menor tolerância estável e documentar.

### Fases

**Fase 1 (nenhum número muda).** Copiar; imports de pacote; `pipeline.py` em estágios; leitura única; `to_legacy_dict`; `on_log`; remoção de `exit`/`os._exit`/`getcwd`/`sys.path`/warnings globais; módulo `llm/`; renomear `gemini_report` → `reports`; código morto; migração dos testes; snapshot verde.
**Fase 2 (números do snapshot continuam iguais).** Remover os `.get(chave, default)` redundantes dos módulos (defaults só no `EngineConfig`); `investment_limit_factor` deixa de ter três defaults (agora um, 1,5); `EngineError`; docstring/limpeza; teste de que o dict padrão gera o mesmo run que o snapshot quando os valores explícitos coincidem com os defaults do `EngineConfig`.

### Entrega ao Dev B (no mesmo PR ou imediatamente depois)

Nota curta em `docs/decisoes/` (arquivo `engine.md`, índice atualizado) com: lista de campos do `EngineConfig` e divergências com `ParamsIn`; semântica de `on_log` e de `status`; `EngineError`; passos do swap (`api/engine_config.py` → `from engine.config import …`, `api/engine_run.py` → `from engine import run`, o `Dockerfile` com `COPY engine/ ./engine/`, substituição das variáveis `FAKE_ENGINE_*` nos testes de `tests/api/test_runs.py` e `tests/conftest.py`) e o impacto no tamanho da imagem (medir antes/depois). Nota também `docs/decisoes/llm.md`: por que plugável, como adicionar um provedor, o que fica dentro do adaptador, e os passos para o Dev B migrar `api/gemini.py` para `llm.get_llm().generate_json(...)` (mantendo o `Unavailable` → `LLMUnavailable`) e, depois, renomear a rota, `source: "gemini"` e o botão da tela. O swap em si é um passo combinado com o Dev B, porque a config muda o formulário e as configs já salvas.

## Aceite (cada linha vira verificação)

| Aceite da spec | Verificação |
|---|---|
| `mise run test` verde | suíte completa de `tests/` (API + engine) passa |
| Snapshot de paridade (1e-9) | `tests/engine/test_parity.py` contra `tests/fixtures/parity/snapshot.json` |
| `grep -rn "os.getcwd\|sys.exit\|os._exit\|sys.path" engine/` vazio | passo no CI/`mise` e teste que roda o grep |
| Streamlit roda | **removido do A0** (repo antigo congelado) |
| (novo) motor chamável como biblioteca | teste que chama `run` com `inputs`/`out_dir` temporários e confere `status`, `engine_version`, arquivos só dentro de `out_dir` |
| (novo) config não mutada | teste que compara o dict de entrada antes/depois |
| (novo) `on_log` | teste que captura chamadas, confere níveis, pt-BR e que nada vai ao stdout |
| (novo) sem LLM | run com `LLM_PROVIDER=none` (ou sem chave) termina e grava o relatório determinístico |
| (novo) LLM indisponível | `FakeLLM` que levanta `LLMUnavailable` na 1ª chamada: o run termina, as chamadas seguintes não acontecem e o relatório determinístico é gravado |
| (novo) módulo `llm/` | `tests/llm/` verde (contrato + adaptador Gemini com cliente falso); `llm/` não importa `engine/` nem `api/` |
| (novo) CLI | teste que roda `python -m engine` num diretório temporário e confere código de saída |
| (novo) `ruff format --check` e `ruff check` em `engine/`, `llm/`, `tests/engine/` e `tests/llm/` | CI |

## Riscos

- **Paridade entre máquinas**: o ajuste do `UnobservedComponents` e o L-BFGS-B são numéricos; sem as mesmas versões e a mesma plataforma, a 1e-9 pode oscilar. Mitigação: versões fixadas, medição antes de exigir a tolerância.
- **Dataset sintético ≠ dado real**: a paridade valida o refactor, não a estatística. Os dados reais das Core e o `exemplo_csv/` continuam pendentes.
- **Paridade entre máquinas x86-64.** O desenvolvimento e o servidor próprio são x86-64, mas CPUs diferentes podem fazer o OpenBLAS escolher kernels diferentes (AVX2 × AVX-512), e o `UnobservedComponents` e o L-BFGS-B são sensíveis a isso. Mitigação: rodar a suíte de paridade **uma vez no servidor**; se passar de 1e-9, medir e documentar a tolerância por máquina (esperado: 1e-8 ou menos), sem mascarar mudança real. Conferido em 04/nov: as sete versões fixadas têm wheels binários para `x86_64` (e também `aarch64`, caso o alvo mude), Python 3.13, então o `docker build` não compila nada.
- **Tamanho da imagem e tempo de partida** com pandas/scipy/statsmodels/sklearn/matplotlib; medir e informar o Dev B.
- **Tempo de execução** do run completo (reinícios do otimizador com validação cruzada e 200 reamostragens de bootstrap). Medir no servidor com o dataset sintético e registrar; se passar de 20 min (`STALE_AFTER`), o Dev B ajusta o limite.
- **LLM só Gemini, interface especulativa.** Uma interface desenhada com um único provedor pode vazar detalhes dele. Mitigação: manter a interface mínima (duas funções, `timeout_s`), nenhum parâmetro de amostragem, e o teste de contrato que um segundo provedor terá de passar; revisar a interface quando o segundo adaptador for escrito.
- **`translate_line`** deixa passar linhas em inglês sem regra; a tela pode mostrar mensagens mistas até as mensagens serem reescritas (fora do A0).

## Calls minhas para você conferir

1. Estrutura de saída em `out_dir` sem o nível `<advertiser>`.
2. Módulo `llm/` de topo (compartilhado com a API), só com o adaptador Gemini sobre `google-genai`; `gemini_report.py` renomeado `reports.py`; as chamadas editadas direto, sem camada de compatibilidade.
3. Modelo/provedor como variáveis de implantação (`LLM_PROVIDER`, `LLM_MODEL`), fora do `EngineConfig`.
4. `warnings.catch_warnings()` no nível do run.
5. Swap da API e migração do `api/gemini.py` **fora** do A0.
6. Não migrar `test_filter_columns`, `test_db`, `test_google_api`, `test_streamlit_throttle`, `test_dashboard_charts`.
7. `status = failed` apenas quando o MMM falha e nenhum evento passa.
8. Pinagem das bibliotecas numéricas nas versões do protótipo.

## O que fica para quem implementa

Nomes exatos de cada campo do `EngineConfig` além dos listados (conferir com um `grep` de `config.get`/`config[...]` nos módulos); formato interno do snapshot; como detectar o git sha em ambiente sem `.git`; quais regras de `_RULES` migrar (todas, a menos que dependam do Streamlit); o texto exato das mensagens de `reason` de `LLMUnavailable`; se o `FakeLLM` precisa de scripts de resposta por prompt.

## Desvios na implementação (04/nov/2026)

Registrados no ledger do plano; nenhum muda número nem contrato.

- Escritores e relatórios em `engine/outputs.py` (dataclass `Written`), `run` e os estágios em `engine/pipeline.py`; `engine/version.py` para o `engine_version`.
- `compute()` recebe `global_dir` (as funções de curva exportam seus próprios arquivos ali) em vez de `individual_curves_dir`; `detect_events` devolve todos os eventos filtrados com a coluna `eligible`, para o pré-treino enxergar todos os canais com evento como no `local_main`.
- `GeminiLLM.from_env` guarda a chave e o modelo padrão do provedor; `get_llm` fica neutro. `run_provider_contract` e as narrativas de teste vivem em `tests/fakes/llm.py`.
- O relatório de evento passou a se chamar `report_<canais>_<data>.html`.
- Mensagens de erro da preparação de dados não levam mais caminho de arquivo (só "arquivo de performance/investimento").
- `period_days` mantém um `config.get("period_days", 1)` nos helpers (chave de runtime, não campo do `EngineConfig`).
- O snapshot sintético usa `require_model_fit=False` (o R² dentro da amostra do modelo causal é negativo nesse dado; com o gate ligado nenhum evento passa).
- Achado de implantação (fora do escopo): com `OMP_NUM_THREADS=1` o run completo leva ~40 s contra ~99 s com todas as threads, e o resultado foi idêntico; recomendação em `docs/decisoes/engine.md`.
