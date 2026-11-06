# Marketing GEM

Plataforma multi-marca de análise de investimento em mídia (projeto Omnicom / AlmapBBDO). Um **motor** estatístico (Trilha A, `engine/`) roda duas análises — causal por evento e saturação/elasticidade com guardrails de CPA/ROAS — e uma **plataforma** (Trilha B: `api/` + `web/`) cuida de auth, upload, jobs assíncronos, dashboards, histórico e export. Sucessor do protótipo Streamlit (Max Impact Engine, repo `opportunity-engine`, sem acesso para este time).

Spec canônica: `docs/m2/README.md` (decisões, arquitetura alvo, contrato A↔B, calendário), com o detalhe por item em `docs/m2/trilha-a-motor.md` e `docs/m2/trilha-b-plataforma.md`. Requisitos do cliente: o BRD `[Omnicom - AlmapBBDO] BRD - Marketing GEM - 2026 v2.docx` na raiz (**não versionado**, confidencial; peça ao time). Em dúvida de escopo, contrato ou schema, o `docs/m2/README.md` vence; ele por sua vez responde ao BRD.

Antes de escrever spec, plano ou código de qualquer item `A*`/`B*`, leia `docs/m2/README.md` e o arquivo da sua trilha.

Mapa do código (arquitetura, endpoints, schema, fluxos): `docs/CODEBASE_MAP.md` — ainda não gerado; rodar o cartographer quando houver mais código (B1+). Ele diz **onde**; `docs/decisoes/` diz **por quê**.

## Estrutura

```
api/              Python 3.13 + FastAPI + SQLAlchemy 2 + Alembic + psycopg 3 (uv)
  main.py         create_app(): middleware de Origin, routers e SPA com fallback para index.html
  db.py           DATABASE_URL, engine, SessionLocal, Base, get_db, ping()
  models.py       User, Workspace, Membership, UserSession, Simulation, SimulationFile, Run, RunLog
  passwords.py    scrypt
  auth.py         sessão, login, bloqueio, dependências de escopo (require_role…)
  logs.py         logs JSON no stdout com user_id/workspace_id/run_id do contexto da request
  accounts.py     regra de negócio de contas, membros e workspaces
  simulations.py  regra de negócio de simulações: upload, sugestão de mapeamento, validação
  runs.py         regra de negócio de runs: gate, criação, run morto, visibilidade
  usage.py        uso por workspace × usuário × mês (view `usage`) e o CSV
  launcher.py     dispara o worker por subprocess (também em produção)
  engine_config.py `ParamsIn` recortado do `EngineConfig` do motor (`ANALYST_FIELDS`)
  suggestions.py  sugestões de parâmetros: regras dos dados, resumo e validação do Gemini
  gemini.py       chamada ao Gemini (GEMINI_API_KEY); trocada por fake nos testes
  bcb.py          séries do Banco Central (SGS) para os controles do causal; trocada por fake nos testes
  bigquery.py     query no BigQuery (ADC), com teto de bytes e timeout; trocada por fake nos testes (conector fora do escopo por ora)
  google_import.py conector Google: config por workspace, SQL do DTS/GA4, CSV canônicos e import
  storage.py      put/path sobre STORAGE_DIR (disco local, também em produção)
  csvfile.py      encoding, delimitador e cabeçalho de CSV
  validation.py   chama `engine.validate`
  engine_run.py   chama `engine.run`; fake com `ENGINE_FAKE=1` (E2E e testes)
  routes/         routers finos (auth, members, admin, simulations, runs, engine)
  cli.py          python -m api.cli create-admin
  worker.py       executa um run (`python -m api.worker <run_id>`)
  alembic.ini     config do Alembic (rodar sempre com -c api/alembic.ini)
  migrations/     revisões Alembic (env.py lê DATABASE_URL de api/db.py)
web/              Vite + React 19 + TypeScript + TanStack Router/Query (bun)
  src/routes/     rotas file-based; routeTree.gen.ts é gerado mas versionado
  src/lib/        api.ts (fetch + ApiError), auth.ts (meQuery, erros pt-BR), theme.ts, simulations.ts (tipos e regras de tela da simulação), params.ts (layout e estado do formulário de parâmetros), runs.ts (tipos, queries, filtros do histórico e useRunLog do SSE), results.ts (tipos do results.json, query e formatação pt-BR)
  src/components/ ui/ é do shadcn (gerado por `bunx shadcn@latest add`); o resto é nosso
  e2e/            Playwright contra a app real (banco app_e2e)
engine/           Trilha A: motor estatístico (A0, 04/nov/2026)
  __init__.py     exporta run, validate, scenario, ScenarioFilters, EngineConfig, EngineError
  __main__.py     python -m engine --config run.json --out DIR
  config.py       EngineConfig (pydantic) e to_legacy_dict(); única fonte dos defaults
  pipeline.py     run() e os estágios em memória (load_inputs, detect_events, analyze_events, run_elasticity, compute)
  inputs.py, validation.py  leitura dos CSV e `validate` (A2): checks com id estável, `EngineError.check_id`
  results_schema.py  contrato do results.json v1 (pydantic, extra=forbid); results.py monta, sanitiza (NaN→null) e grava
  outputs.py      escritores legados (PNG/CSV/MD/HTML) e relatórios por LLM, a partir do Computed
  analysis.py, elasticity_analysis.py, data_preprocessor.py, presentation.py, recommendations.py, reports.py   cópias do protótipo
  logmessages.py  tradução pt-BR dos logs e a ponte para o on_log
  errors.py       EngineError (mensagem pt-BR segura para a tela)
  scenario.py     `ramp`, notas tCPA/tROAS e `scenario()` (A8): filtros do planner sobre o results.json, mensal
llm/              acesso plugável a LLM (get_llm, LLM, LLMUnavailable…); só o adaptador Gemini existe
tests/            pytest; tests/api/ plataforma, tests/engine/ motor (inclui paridade), tests/llm/, tests/fakes/ e tests/fixtures/parity/
docs/m2/          plano do M2 · docs/superpowers/ specs e planos · docs/decisoes/ porquês
```

## Rodando o projeto

1. `docker compose up -d` — Postgres 16 em `:5432` (usuário/senha/banco `app`). Variáveis em `.env.example`; o mise carrega o `.env` se existir, e sem ele valem os defaults.
2. `mise run db-migrate` — aplica as migrations.
3. `mise run create-admin voce@exemplo.com "Seu Nome"` — cria o primeiro platform admin e imprime a senha temporária (troca obrigatória no 1º login).
4. `mise run api` — API em `:8000` com reload.
5. `mise run web` — SPA em `:5173`, `/api` faz proxy para `:8000`. Abra `http://localhost:5173`: deve abrir a tela de login.

```bash
mise run test                                       # uv run pytest
mise run e2e                                        # Playwright: build do web + uvicorn em :8001 + banco app_e2e
mise run worker                                     # python -m api.worker
mise run parity                                     # paridade do motor com o snapshot do protótipo (só Linux, ~95 s)
uv run python -m engine --config run.json --out DIR  # roda o motor sem a plataforma
uv run alembic -c api/alembic.ini revision -m "…"   # nova migration
cd web && bun run build                             # tsc -b + vite build
cd web && bun run lint                              # oxlint
```

Depois de criar arquivo novo em `web/src/routes/`, rode `cd web && bunx vite build` uma vez antes do `bun run build`: o `tsc -b` roda antes de o plugin do Vite regenerar o `routeTree.gen.ts`.

Use `uv` e `bun` — não pip, poetry, npm ou yarn. Se a porta 5432 estiver ocupada por outro Postgres local, o `docker compose up` falha: libere a porta ou troque o mapeamento no compose.

## Deploy

Uma imagem só (`Dockerfile`): API (padrão), SPA (`web/dist` servido pelo FastAPI) e worker (`python -m api.worker`, outro comando na mesma imagem). **Alvo (decidido em 04/nov/2026): servidor próprio x86-64 com Docker, sem GCP.** Nada de Cloud Run, Cloud SQL, GCS, Secret Manager nem Vertex. O Postgres roda em Docker no próprio servidor, os arquivos ficam em disco (`STORAGE_DIR`), os segredos vêm do `.env` do servidor e o worker é subprocess da API. O conector Google (BigQuery) está **fora do escopo por ora**: o dado entra só por CSV. O porquê e o que o B11 precisa cobrir (proxy com TLS e limite de corpo, backup) estão em `docs/decisoes/infra-e-operacao.md`. Passo a passo de deploy: `docs/deploy.md` (a criar no B11). A imagem copia `api/`, `engine/` e `llm/`; o build passa `--build-arg ENGINE_VERSION=$(git rev-parse --short HEAD)` para o `results.json` levar a versão do motor.

## Convenções

As regras moram em quatro arquivos na raiz — leia o do ramo que a tarefa toca antes de codar:

- `CODE-STYLE.md` — qualquer código: ferramentas, idioma, dinheiro, erro, testes, commits, regras do motor.
- `DATABASE.md` — model, migration, query, schema.
- `API-GUIDE.md` — rota REST, status de erro, tabela de endpoints.
- `SECURITY.md` — auth, sessão, workspaces, segredos; e como reportar vulnerabilidade.

A skill `project-conventions` carrega esse índice sozinha. Resumo: **toda rota e query é escopada por workspace** (recurso de outro workspace = 404, nunca 403); **a matemática fica só em Python** (o front nunca recalcula curva, CPA ou ponto ótimo); nada de `print()`; nome de coluna nunca hardcoded (vem do `column_mapping`).

## Design

`PRODUCT.md` e `DESIGN.md` ainda não existem. O visual deve seguir o design system do Almap Metrics (B10); enquanto os tokens não chegam, usa-se tema próprio. Sugestão: rodar `/impeccable teach` quando o B10 começar.

### Verificar mudanças no frontend

Com o MCP `playwright` conectado (registrado em `.mcp.json`; aprove com `/mcp` se aparecer como pendente), depois de qualquer mudança visual abra a rota afetada com `mise run web` no ar e tire um screenshot antes de reportar como concluída. `tsc -b`/`vite build` passando não pega regressão visual nem rota que renderizou vazia.

**Cuidado ao escrever em `web/src/routes/**` com o dev server rodando.** O gerador do TanStack Router reescreve o arquivo com um placeholder (`Hello "/rota"!`) se ler conteúdo vazio. Um heredoc de shell trunca o arquivo antes de escrever e pode perder a escrita; prefira `Write`/`Edit` e confira com um screenshot.

## UI stack

Tone: Dense system — ferramenta interna de análise, densa e sóbria.
- Blocks: shadcn (estilo `radix-nova`) para primitivos; blocks.so (`@blocks-so`) para telas de app (o `FileDrop` vem do `file-upload-04`)
- Motion: nenhum por ora
- Icons: lucide (o padrão do shadcn), até o B10
- Theme: tema próprio do protótipo em `web/src/index.css`, até o B10 trazer os tokens do Almap Metrics
- Fonts: Inter, até o B10
- Showpiece: nenhum
- Extras: —

Pick UI from this stack only. At the start of a UI task, offer once to scout the `ui-sources` catalog for components that fit this tone; load that skill for the scouting pass or when the stack can't cover a need. Ícones, tema e fontes são trocados juntos no B10, não peça a peça.

## Estado atual

**B0 (esqueleto) concluído em 21/out/2026**: API com `/api/health`, SPA servida com fallback, worker stub, Postgres no compose, imagem única, CI (`py` com Postgres + `web`). **B1a (auth backend) concluído em 21/out/2026**: tabelas `users`/`workspaces`/`memberships`/`sessions` (migration `0001`), sessão por cookie opaco com expiração deslizante, bloqueio por falhas, troca de senha obrigatória, RBAC por workspace (`require_role`, 404 entre workspaces), rotas de membros e de platform admin, CLI `create-admin`. **B1b (telas) concluído em 22/out/2026**: login, troca de senha obrigatória, seletor de workspace por slug na URL, membros, admin de workspaces e usuários, tema claro/escuro do protótipo (Tailwind + shadcn), E2E Playwright no CI. **B2a (upload backend) concluído em 26/out/2026**: tabelas `simulations`/`simulation_files` (migration `0003`), upload de CSV ≤ 30 MB para storage local por conteúdo, sugestão e confirmação do mapeamento de colunas, `validate` falso (só `duplicate_date_channel`) até o A2. **B2b (telas do upload) concluído em 26/out/2026**: lista de simulações em `/w/$slug`, criação, detalhe com upload por drag & drop, mapeamento pré-preenchido, report de validação e botão Rodar sempre desabilitado com o motivo (o run é do B4). **B3a (parâmetros backend) concluído em 26/out/2026**: `EngineConfig` provisório, schema em `/api/engine/config-schema`, sugestões dos dados e do Gemini (só agregados no prompt), `PUT …/params`. **B3b (tela de parâmetros) concluído em 26/out/2026**: formulário gerado do schema com layout no front, selos de sugestão, "Sugerir com Gemini", erros do pydantic por campo, Rodar pede parâmetros salvos. **B4a (jobs backend) concluído em 27/out/2026**: tabelas `runs`/`run_logs` (migration `0004`), gate do Rodar no servidor, snapshot de config e inputs, um run ativo por simulação, worker em subprocess com `engine.run` falso, run morto após 20 min, log por SSE com retomada. **B4b (tela do run) concluído em 27/out/2026**: Rodar de verdade, página do run com log ao vivo e "em andamento há N s", lista de execuções na simulação. **B6a (histórico backend) concluído em 28/out/2026**: `GET …/runs` do workspace (até 500, filtros no front), `RunOut` com config, inputs e publicação, publicar/despublicar (só run concluído), download das entradas do snapshot (analyst+). **B6b (histórico telas) concluído em 28/out/2026**: `/w/$slug/execucoes` com busca e filtros na URL, viewer redirecionado para lá, página do run com parâmetros, entradas (download para analyst+), publicar/despublicar e "Rodar de novo". **B9a (uso, logs e retenção backend) concluído em 28/out/2026**: logs JSON com `user_id`/`workspace_id`/`run_id` na API e no worker, view `usage` (migration `0005`) com `GET /api/admin/usage` e o CSV, `DELETE` de simulação para o admin do workspace. **B9b (uso e apagar telas) concluído em 28/out/2026**: `/admin/uso` com filtro por mês e export CSV, "Apagar simulação" com confirmação pelo nome para o admin do workspace. **B8a (conectores backend) concluído em 29/out/2026**: config do conector Google por workspace em `settings["google"]` (só platform admin), import do DTS do Ads e do export do GA4 por período, que gera os CSV canônicos e passa pelo mesmo mapeamento e validate; SQL escrita contra a doc do DTS e do GA4, sem sandbox rodado; o ±1% contra o Google Ads UI espera acesso a uma conta real. **B8 (conector Google) está fora do escopo por ora (04/nov/2026)**: o código fica, mas o dado entra só por CSV. **B8b (telas do conector) concluído em 29/out/2026**: diálogo "Conector Google" em `/admin/workspaces` (datasets, customer ids, evento e métrica do GA4; remover), "Importar do Google" com período na página da simulação, visível só em workspace com conector. **A0 (pacote `engine/` e módulo `llm/`) concluído em 04/nov/2026**: `engine.run` único chamável como biblioteca, `EngineConfig`, `python -m engine`, `llm/` plugável (só Gemini), snapshot de paridade contra o protótipo congelado (idêntico a 1e-9 na máquina de desenvolvimento; falta rodar no servidor). `api/gemini.py` → `llm/` ainda está pendente (Dev B, `docs/decisoes/engine.md`). **A1 (`results.json` v1 e fixtures) concluído em 04/nov/2026**: `run` grava e devolve o documento tipado (`engine/results_schema.py`), com `status` e `reasons` por seção, sem `NaN`/`Infinity`, e fixtures da Gol anonimizada (`succeeded`, `inconclusive`, `failed`) em `tests/fixtures/results/`; seções de A5–A9 saem `null`. **A2 (validação) concluído em 04/nov/2026**: `engine.validate` com 14 checks (duplicata de (data, canal) e de data no KPI viram erro, KPI por canal é `kpi_not_single_source`), `run` valida antes e grava `validation` no `results.json`; a Gol como enviada é rejeitada (GOOGLE 5×/dia, antes média silenciosa), ver `docs/decisoes/engine.md`. **A0–A2 entraram no `main` em 05/nov/2026**, depois de uma revisão que corrigiu nomes de canal virando caminho fora do `out_dir`, a falta de `engine/`/`llm/` na imagem e o `engine_version` `unknown`, e que deixou o teste de paridade só no Linux (no Windows o MMM cai em outro ótimo). **Swap concluído em 05/nov/2026**: a API usa `engine.validate`, `engine.run` e o `EngineConfig` reais (migration `0006` renomeia os `require_*`), com o fake só atrás de `ENGINE_FAKE=1`; `api/gemini.py` → `llm/` segue pendente. **A3 (gate de colinearidade) concluído em 05/nov/2026**: `validate` preenche `collinearity` (|r| > 0.85 no spend cru, VIF e grupos sugeridos) e dá `collinearity_unresolved` enquanto, com os `channel_groups` somados, ainda houver par acima do limite (ou até `block_per_channel`); par de overlap DV360/CM360 não bloqueia; abaixo de 30 períodos completos não avalia. **A5 (identificabilidade) concluído em 05/nov/2026**: `coef_ci` da contribuição por canal do bootstrap, `identifiable=false` com p2.5 ≤ 0 ou IC mais largo que o ponto; o canal sai de curva, Hill, mix (vira `"Não identificados"`), cenários e Gemini, sem mudar o modelo; nenhum canal identificável deixa a elasticidade `inconclusive`. No sintético da paridade nenhum canal é identificável. **Ports do branch paralelo e A6 (06/nov/2026)**: o gate do A3 também bloqueia por VIF (`vif_max` 10, ainda não medido na Gol/Core) e grava `collinearity.unresolved`; `block_per_channel` deixa esses canais não identificáveis (`collinearity`); a realocação sai com qualquer canal escondido (`reallocation_suppressed`); run sem canal identificável segue `inconclusive`; `control_rejected` vira observação na aba Causal; paridade causal completa de volta no sintético (Linux a confirmar) e golden do motor para a Gol (não gerado). **A6 parcial**: placebo no meio do pré (`placebo_failed`), WMAPE fora da amostra, `sufficiency` do run (`spend_cv_min` 0.10, `oos_wmape_max` 0.30, provisórios), eventos `insufficient_run` sem lift e `cv_in_sample` deixando a elasticidade `inconclusive`; o aceite do ruído branco falha em 1 de 3 sementes (`xfail`) e depende da decisão do gate de robustez `model_dependent`, em aberto. Pela plataforma, dataset colinear só roda quando a tela do B2 existir. **A8 (guardrails e `engine.scenario`) concluído em 06/nov/2026**: banda p5/p95 do bootstrap da Ridge e `extrapolated` em todo ponto da curva, cenário e curva individual; curvas individuais dentro do cap; `ramp` em degraus de `max_budget_step` e nota tCPA/tROAS nos cenários; `engine.scenario` com os filtros do Streamlit em valores mensais, exposto em `GET /api/w/{slug}/runs/{run_id}/scenario`. Learning/budget-limited do Google Ads cortado. B5 desbloqueado. **B5 parte 1 (aba Causal) concluída em 06/nov/2026**: `GET …/runs/{run_id}/results` devolve o `results.json`, a página do run virou abas (`causal`, `detalhes`; Elasticidade desabilitada) e a aba Causal mostra os eventos com veredito, métricas e gráficos em Recharts (`chart` do shadcn); evento rejeitado mostra só o motivo; o E2E roda com `FAKE_ENGINE_RESULTS` apontando para a Gol anonimizada. **A4 (controles causais) concluído em 06/nov/2026**: sem Leads/Clicks/Impressions no causal; Trends e IPCA/Selic/IBC-Br (marcados pelo analista, buscados pela API na SGS ao criar o run, 502 se ela falhar) triados por evento (|r| com o spend > 0.5 → descartado, em `events[].controls`); `LassoCV` com `TimeSeriesSplit`. Pendência da Trilha A: o `incremental_investment` dos eventos é o investimento total do pós-período. Faltam: A6 (aceite do ruído branco), A7, A9 e A10 (Trilha A), regenerar os fixtures do A1 e o golden da Gol (precisam da Gol), B5 parte 2 (aba Elasticidade sobre o `scenario`), B7 (depende do B5), B10 (visual, contínuo), B11 (deploy no servidor próprio).

**Onde as decisões estão escritas.** Este arquivo e os quatro da raiz dizem as regras; `docs/decisoes/` diz **por quê** (índice em `docs/decisoes/README.md`). Leia o arquivo da área antes de mexer nela:

| Área | Arquivo |
| --- | --- |
| Hospedagem (servidor próprio, sem GCP), imagem única, health, SPA, CI, deps | `docs/decisoes/infra-e-operacao.md` |
| Auth, sessão, papéis, workspaces | `docs/decisoes/auth.md` |
| Simulação, upload, storage, validate | `docs/decisoes/upload-e-storage.md` |
| Runs, jobs, log do worker, SSE | `docs/decisoes/runs-e-jobs.md` |
| Conectores Google Ads/GA4, BigQuery (fora do escopo por ora) | `docs/decisoes/conectores-google.md` |
| Motor (`engine/`), `EngineConfig`, paridade, swap da API | `docs/decisoes/engine.md` |
| Acesso a LLM (`llm/`), como trocar de provedor | `docs/decisoes/llm.md` |
| Telas de resultado (abas do run, Recharts, evento rejeitado sem número) | `docs/decisoes/dashboards.md` |

Ao concluir um item `A*`/`B*`, atualize no mesmo commit o parágrafo "Estado atual" acima (o que já existe e o que falta) e a linha `Status` do item em `docs/m2/trilha-*.md`, com a data e o que foi verificado.

Sempre que concluir uma tarefa que muda isso (nova feature, pendência resolvida, decisão revista), atualize o arquivo da área em `docs/decisoes/` no mesmo commit. Rota nova entra na tabela do `API-GUIDE.md`, tabela ou coluna nova na do `DATABASE.md`, regra nova no arquivo da raiz do seu ramo — no mesmo commit. Pacote Python novo na raiz entra no `Dockerfile` (`COPY --chown=app:app <pacote>/ ./<pacote>/`), como `engine/` e `llm/`.
