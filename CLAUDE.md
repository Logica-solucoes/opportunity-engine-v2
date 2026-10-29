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
  logs.py         logs JSON (Cloud Logging) com user_id/workspace_id/run_id do contexto da request
  accounts.py     regra de negócio de contas, membros e workspaces
  simulations.py  regra de negócio de simulações: upload, sugestão de mapeamento, validação
  runs.py         regra de negócio de runs: gate, criação, run morto, visibilidade
  usage.py        uso por workspace × usuário × mês (view `usage`) e o CSV
  launcher.py     dispara o worker por subprocess (Cloud Run Jobs no B11)
  engine_config.py EngineConfig provisório até o A0 (vira `from engine.config import …`)
  suggestions.py  sugestões de parâmetros: regras dos dados, resumo e validação do Gemini
  gemini.py       chamada ao Gemini (GEMINI_API_KEY); trocada por fake nos testes
  bigquery.py     query no BigQuery (ADC), com teto de bytes e timeout; trocada por fake nos testes
  google_import.py conector Google: config por workspace, SQL do DTS/GA4, CSV canônicos e import
  storage.py      put/path sobre STORAGE_DIR (local; GCS no B11)
  csvfile.py      encoding, delimitador e cabeçalho de CSV
  validation.py   validate falso até o A2 (vira `from engine import validate`)
  engine_run.py   engine.run falso até o A0 (vira `from engine import run`)
  routes/         routers finos (auth, members, admin, simulations, runs, engine)
  cli.py          python -m api.cli create-admin
  worker.py       executa um run do Cloud Run Job (`python -m api.worker <run_id>`)
  alembic.ini     config do Alembic (rodar sempre com -c api/alembic.ini)
  migrations/     revisões Alembic (env.py lê DATABASE_URL de api/db.py)
web/              Vite + React 19 + TypeScript + TanStack Router/Query (bun)
  src/routes/     rotas file-based; routeTree.gen.ts é gerado mas versionado
  src/lib/        api.ts (fetch + ApiError), auth.ts (meQuery, erros pt-BR), theme.ts, simulations.ts (tipos e regras de tela da simulação), params.ts (layout e estado do formulário de parâmetros), runs.ts (tipos, queries, filtros do histórico e useRunLog do SSE)
  src/components/ ui/ é do shadcn (gerado por `bunx shadcn@latest add`); o resto é nosso
  e2e/            Playwright contra a app real (banco app_e2e)
engine/           (Trilha A, ainda não existe) motor estatístico — criado pelo A0
tests/            pytest; tests/api/ para a plataforma
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
uv run alembic -c api/alembic.ini revision -m "…"   # nova migration
cd web && bun run build                             # tsc -b + vite build
cd web && bun run lint                              # oxlint
```

Depois de criar arquivo novo em `web/src/routes/`, rode `cd web && bunx vite build` uma vez antes do `bun run build`: o `tsc -b` roda antes de o plugin do Vite regenerar o `routeTree.gen.ts`.

Use `uv` e `bun` — não pip, poetry, npm ou yarn. Se a porta 5432 estiver ocupada por outro Postgres local, o `docker compose up` falha: libere a porta ou troque o mapeamento no compose.

## Deploy

Uma imagem só (`Dockerfile`): API (padrão), SPA (`web/dist` servido pelo FastAPI) e worker (`python -m api.worker`, outro comando na mesma imagem). Alvo: Cloud Run (service + Job) com Cloud SQL, definido no B11. O porquê das escolhas em `docs/decisoes/infra-e-operacao.md`. Passo a passo de deploy: `docs/deploy-gcp.md` (a criar no B11).

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

**B0 (esqueleto) concluído em 21/out/2026**: API com `/api/health`, SPA servida com fallback, worker stub, Postgres no compose, imagem única, CI (`py` com Postgres + `web`). **B1a (auth backend) concluído em 21/out/2026**: tabelas `users`/`workspaces`/`memberships`/`sessions` (migration `0001`), sessão por cookie opaco com expiração deslizante, bloqueio por falhas, troca de senha obrigatória, RBAC por workspace (`require_role`, 404 entre workspaces), rotas de membros e de platform admin, CLI `create-admin`. **B1b (telas) concluído em 22/out/2026**: login, troca de senha obrigatória, seletor de workspace por slug na URL, membros, admin de workspaces e usuários, tema claro/escuro do protótipo (Tailwind + shadcn), E2E Playwright no CI. **B2a (upload backend) concluído em 26/out/2026**: tabelas `simulations`/`simulation_files` (migration `0003`), upload de CSV ≤ 30 MB para storage local por conteúdo, sugestão e confirmação do mapeamento de colunas, `validate` falso (só `duplicate_date_channel`) até o A2. **B2b (telas do upload) concluído em 26/out/2026**: lista de simulações em `/w/$slug`, criação, detalhe com upload por drag & drop, mapeamento pré-preenchido, report de validação e botão Rodar sempre desabilitado com o motivo (o run é do B4). **B3a (parâmetros backend) concluído em 26/out/2026**: `EngineConfig` provisório, schema em `/api/engine/config-schema`, sugestões dos dados e do Gemini (só agregados no prompt), `PUT …/params`. **B3b (tela de parâmetros) concluído em 26/out/2026**: formulário gerado do schema com layout no front, selos de sugestão, "Sugerir com Gemini", erros do pydantic por campo, Rodar pede parâmetros salvos. **B4a (jobs backend) concluído em 27/out/2026**: tabelas `runs`/`run_logs` (migration `0004`), gate do Rodar no servidor, snapshot de config e inputs, um run ativo por simulação, worker em subprocess com `engine.run` falso, run morto após 20 min, log por SSE com retomada. **B4b (tela do run) concluído em 27/out/2026**: Rodar de verdade, página do run com log ao vivo e "em andamento há N s", lista de execuções na simulação. **B6a (histórico backend) concluído em 28/out/2026**: `GET …/runs` do workspace (até 500, filtros no front), `RunOut` com config, inputs e publicação, publicar/despublicar (só run concluído), download das entradas do snapshot (analyst+). **B6b (histórico telas) concluído em 28/out/2026**: `/w/$slug/execucoes` com busca e filtros na URL, viewer redirecionado para lá, página do run com parâmetros, entradas (download para analyst+), publicar/despublicar e "Rodar de novo". B5 bloqueado nos fixtures do A1 e no `scenario` do A8. **B9a (uso, logs e retenção backend) concluído em 28/out/2026**: logs JSON com `user_id`/`workspace_id`/`run_id` na API e no worker, view `usage` (migration `0005`) com `GET /api/admin/usage` e o CSV, `DELETE` de simulação para o admin do workspace. **B9b (uso e apagar telas) concluído em 28/out/2026**: `/admin/uso` com filtro por mês e export CSV, "Apagar simulação" com confirmação pelo nome para o admin do workspace. **B8a (conectores backend) concluído em 29/out/2026**: config do conector Google por workspace em `settings["google"]` (só platform admin), import do DTS do Ads e do export do GA4 por período, que gera os CSV canônicos e passa pelo mesmo mapeamento e validate; SQL escrita contra a doc do DTS e do GA4, sem sandbox rodado; o ±1% contra o Google Ads UI espera acesso a uma conta real. **B8b (telas do conector) concluído em 29/out/2026**: diálogo "Conector Google" em `/admin/workspaces` (datasets, customer ids, evento e métrica do GA4; remover), "Importar do Google" com período na página da simulação, visível só em workspace com conector. Faltam: B7 (depende do B5), B10 (visual, contínuo), B11 (deploy). A Trilha A (`engine/`) é do outro dev.

**Onde as decisões estão escritas.** Este arquivo e os quatro da raiz dizem as regras; `docs/decisoes/` diz **por quê** (índice em `docs/decisoes/README.md`). Leia o arquivo da área antes de mexer nela:

| Área | Arquivo |
| --- | --- |
| Imagem única, health, SPA, CI, deps | `docs/decisoes/infra-e-operacao.md` |
| Auth, sessão, papéis, workspaces | `docs/decisoes/auth.md` |
| Simulação, upload, storage, validate | `docs/decisoes/upload-e-storage.md` |
| Runs, jobs, log do worker, SSE | `docs/decisoes/runs-e-jobs.md` |
| Conectores Google Ads/GA4, BigQuery | `docs/decisoes/conectores-google.md` |

Ao concluir um item `A*`/`B*`, atualize no mesmo commit o parágrafo "Estado atual" acima (o que já existe e o que falta) e a linha `Status` do item em `docs/m2/trilha-*.md`, com a data e o que foi verificado.

Sempre que concluir uma tarefa que muda isso (nova feature, pendência resolvida, decisão revista), atualize o arquivo da área em `docs/decisoes/` no mesmo commit. Rota nova entra na tabela do `API-GUIDE.md`, tabela ou coluna nova na do `DATABASE.md`, regra nova no arquivo da raiz do seu ramo — no mesmo commit. Quando o `engine/` entrar: `COPY engine/ ./engine/` no `Dockerfile` e as deps dele no `pyproject.toml`.
