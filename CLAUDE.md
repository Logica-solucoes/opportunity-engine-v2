# Marketing GEM

Plataforma multi-marca de análise de investimento em mídia (projeto Omnicom / AlmapBBDO). Um **motor** estatístico (Trilha A, `engine/`) roda duas análises — causal por evento e saturação/elasticidade com guardrails de CPA/ROAS — e uma **plataforma** (Trilha B: `api/` + `web/`) cuida de auth, upload, jobs assíncronos, dashboards, histórico e export. Sucessor do protótipo Streamlit (Max Impact Engine, repo `opportunity-engine`, sem acesso para este time).

Spec canônica: `docs/m2/README.md` (decisões, arquitetura alvo, contrato A↔B, calendário), com o detalhe por item em `docs/m2/trilha-a-motor.md` e `docs/m2/trilha-b-plataforma.md`. Requisitos do cliente: o BRD `[Omnicom - AlmapBBDO] BRD - Marketing GEM - 2026 v2.docx` na raiz (**não versionado**, confidencial; peça ao time). Em dúvida de escopo, contrato ou schema, o `docs/m2/README.md` vence; ele por sua vez responde ao BRD.

Antes de escrever spec, plano ou código de qualquer item `A*`/`B*`, leia `docs/m2/README.md` e o arquivo da sua trilha.

Mapa do código (arquitetura, endpoints, schema, fluxos): `docs/CODEBASE_MAP.md` (gerado em 08/nov/2026; rodar o cartographer de novo após mudanças grandes). Ele diz **onde**; `docs/decisoes/` diz **por quê**.

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
  exports.py      CSV do run (eventos, cenários, curva) a partir do results.json e do `engine.scenario`
  launcher.py     dispara o worker por subprocess (também em produção)
  engine_config.py `ParamsIn` recortado do `EngineConfig` do motor (`ANALYST_FIELDS`)
  suggestions.py  sugestões de parâmetros: regras dos dados, resumo e validação do Gemini
  gemini.py       chamada ao Gemini (GEMINI_API_KEY); trocada por fake nos testes
  bcb.py          séries do Banco Central (SGS) para os controles do causal; trocada por fake nos testes
  bigquery.py     query no BigQuery (ADC), com teto de bytes e timeout; trocada por fake nos testes (conector fora do escopo por ora)
  google_import.py conector Google: config por workspace, SQL do DTS/GA4, CSV canônicos e import
  storage.py      put/path sobre STORAGE_DIR (disco local, também em produção)
  csvfile.py      leitura de CSV (encoding, delimitador, cabeçalho) e o escritor pt-BR (`;`, vírgula decimal, BOM, `safe`)
  validation.py   chama `engine.validate`
  engine_run.py   chama `engine.run`; fake com `ENGINE_FAKE=1` (E2E e testes)
  routes/         routers finos (auth, members, admin, simulations, runs, engine)
  cli.py          python -m api.cli create-admin
  worker.py       executa um run (`python -m api.worker <run_id>`)
  alembic.ini     config do Alembic (rodar sempre com -c api/alembic.ini)
  migrations/     revisões Alembic (env.py lê DATABASE_URL de api/db.py)
web/              Vite + React 19 + TypeScript + TanStack Router/Query (bun)
  src/routes/     rotas file-based; routeTree.gen.ts é gerado mas versionado
  src/lib/        api.ts (fetch + ApiError), auth.ts (meQuery, erros pt-BR), theme.ts, simulations.ts (tipos e regras de tela da simulação), params.ts (layout e estado do formulário de parâmetros), runs.ts (tipos, queries, filtros do histórico e useRunLog do SSE), results.ts (tipos do results.json, query e formatação pt-BR), scenario.ts (tipos e query do `scenario`, debounce, rótulos e erros dos filtros)
  src/components/ ui/ é do shadcn (gerado por `bunx shadcn@latest add`); o resto é nosso
  e2e/            Playwright contra a app real (banco app_e2e)
engine/           Trilha A: motor estatístico (A0, 04/nov/2026)
  __init__.py     exporta run, validate, scenario, ScenarioFilters, EngineConfig, EngineError
  __main__.py     python -m engine --config run.json --out DIR
  config.py       EngineConfig (pydantic) e to_legacy_dict(); única fonte dos defaults
  pipeline.py     run() e os estágios em memória (load_inputs, detect_events, analyze_events, run_elasticity, compute)
  inputs.py, validation.py  leitura dos CSV e `validate` (A2): checks com id estável, `EngineError.check_id`
  results_schema.py  contrato do results.json v1 (pydantic, extra=forbid); results.py monta, sanitiza (NaN→null) e grava
  outputs.py      escritores legados (PNG/CSV/MD) a partir do Computed
  analysis.py, elasticity_analysis.py, data_preprocessor.py, presentation.py   cópias do protótipo
  logmessages.py  tradução pt-BR dos logs e a ponte para o on_log
  errors.py       EngineError (mensagem pt-BR segura para a tela)
  scenario.py     `ramp`, notas tCPA/tROAS e `scenario()` (A8): filtros do planner sobre o results.json, mensal
  grounding.py    checagem pós-geração (A9): números pt-BR, datas e canais do texto contra o payload
  narratives.py   narrativas por LLM (A9) a partir do results.json, com uma regeneração e texto determinístico
  experiment.py   experiment designer (A7): MDE, duração e orçamento em risco por canal quando o run é inconclusive
llm/              acesso plugável a LLM (get_llm, LLM, LLMUnavailable…); só o adaptador Gemini existe
deploy/           compose de produção, .env.example, backup.sh/restore.sh (B11)
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

Uma imagem só (`Dockerfile`): API (padrão), SPA (`web/dist` servido pelo FastAPI) e worker (`python -m api.worker`, outro comando na mesma imagem). **Alvo (decidido em 04/nov/2026): servidor próprio x86-64 com Docker, sem GCP.** Nada de Cloud Run, Cloud SQL, GCS, Secret Manager nem Vertex. O Postgres roda em Docker no próprio servidor, os arquivos ficam em disco (`STORAGE_DIR`), os segredos vêm do `.env` do servidor e o worker é subprocess da API. O conector Google (BigQuery) está **fora do escopo por ora**: o dado entra só por CSV. O porquê e o que o B11 precisa cobrir (proxy com TLS e limite de corpo, backup) estão em `docs/decisoes/infra-e-operacao.md`. Passo a passo: `docs/deploy.md`. A imagem copia `api/`, `engine/` e `llm/`; o build passa `--build-arg ENGINE_VERSION=$(git rev-parse --short HEAD)` para o `results.json` levar a versão do motor.

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

## Refino do front-end

Para qualquer tarefa de UI (tela, componente, tema), leia `docs/audit/front-end.md` (achados por tela e skills de design a usar) e `docs/superpowers/plans/2026-11-09-refino-front.md` (ordem T0–T4 e regras). Sob demanda, não antes.

## Estado atual

Histórico por item, pendências e o plano do refino do front-end estão em `docs/status.md`: **leia sob demanda**, só quando a tarefa pedir (contexto de um item `A*`/`B*`, o que falta, o refino visual). Resumo: B0–B9, B11 (sem servidor) e A0–A9 concluídos; auditoria matemática do motor tratada em 09/nov/2026; faltam A10 (Data Science), paridade no servidor, B10 (visual) e o que depende do servidor no B11. Próxima fase: refino do front-end (lucide→Phosphor, Inter→Geist, tudo em primitivos shadcn), auditoria antes de editar.

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

Ao concluir um item `A*`/`B*`, atualize no mesmo commit o `docs/status.md` (o que já existe e o que falta) e a linha `Status` do item em `docs/m2/trilha-*.md`, com a data e o que foi verificado.

Sempre que concluir uma tarefa que muda isso (nova feature, pendência resolvida, decisão revista), atualize o arquivo da área em `docs/decisoes/` no mesmo commit. Rota nova entra na tabela do `API-GUIDE.md`, tabela ou coluna nova na do `DATABASE.md`, regra nova no arquivo da raiz do seu ramo — no mesmo commit. Pacote Python novo na raiz entra no `Dockerfile` (`COPY --chown=app:app <pacote>/ ./<pacote>/`), como `engine/` e `llm/`.
