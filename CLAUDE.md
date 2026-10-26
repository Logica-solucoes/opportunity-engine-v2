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
  models.py       User, Workspace, Membership, UserSession, Simulation, SimulationFile
  passwords.py    scrypt
  auth.py         sessão, login, bloqueio, dependências de escopo (require_role…)
  accounts.py     regra de negócio de contas, membros e workspaces
  simulations.py  regra de negócio de simulações: upload, sugestão de mapeamento, validação
  storage.py      put/path sobre STORAGE_DIR (local; GCS no B11)
  csvfile.py      encoding, delimitador e cabeçalho de CSV
  validation.py   validate falso até o A2 (vira `from engine import validate`)
  routes/         routers finos (auth, members, admin, simulations)
  cli.py          python -m api.cli create-admin
  worker.py       entrypoint do Cloud Run Job (python -m api.worker)
  alembic.ini     config do Alembic (rodar sempre com -c api/alembic.ini)
  migrations/     revisões Alembic (env.py lê DATABASE_URL de api/db.py)
web/              Vite + React 19 + TypeScript + TanStack Router/Query (bun)
  src/routes/     rotas file-based; routeTree.gen.ts é gerado mas versionado
  src/lib/        api.ts (fetch + ApiError), auth.ts (meQuery, erros pt-BR), theme.ts, simulations.ts (tipos e regras de tela da simulação)
  src/components/ ui/ é do shadcn (gerado por `bunx shadcn@latest add`); o resto é nosso
  e2e/            Playwright contra a app real (banco app_e2e)
engine/           (Trilha A, ainda não existe) motor estatístico — criado pelo A0
tests/            pytest; tests/api/ para a plataforma
docs/m2/          plano do M2 · docs/superpowers/ specs e planos · docs/decisoes/ porquês
```

## Rodando o projeto

1. `docker compose up -d` — Postgres 16 em `:5432` (usuário/senha/banco `app`). Variáveis em `.env.example`; sem `.env` valem os defaults.
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

**B0 (esqueleto) concluído em 21/out/2026**: API com `/api/health`, SPA servida com fallback, worker stub, Postgres no compose, imagem única, CI (`py` com Postgres + `web`). **B1a (auth backend) concluído em 21/out/2026**: tabelas `users`/`workspaces`/`memberships`/`sessions` (migration `0001`), sessão por cookie opaco com expiração deslizante, bloqueio por falhas, troca de senha obrigatória, RBAC por workspace (`require_role`, 404 entre workspaces), rotas de membros e de platform admin, CLI `create-admin`. **B1b (telas) concluído em 22/out/2026**: login, troca de senha obrigatória, seletor de workspace por slug na URL, membros, admin de workspaces e usuários, tema claro/escuro do protótipo (Tailwind + shadcn), E2E Playwright no CI. **B2a (upload backend) concluído em 26/out/2026**: tabelas `simulations`/`simulation_files` (migration `0003`), upload de CSV ≤ 30 MB para storage local por conteúdo, sugestão e confirmação do mapeamento de colunas, `validate` falso (só `duplicate_date_channel`) até o A2. **B2b (telas do upload) concluído em 26/out/2026**: lista de simulações em `/w/$slug`, criação, detalhe com upload por drag & drop, mapeamento pré-preenchido, report de validação e botão Rodar sempre desabilitado com o motivo (o run é do B4). Faltam, em ordem: B3–B4 (Gemini, jobs), B5–B9, B10 (visual, contínuo), B11 (deploy). A Trilha A (`engine/`) é do outro dev.

**Onde as decisões estão escritas.** Este arquivo e os quatro da raiz dizem as regras; `docs/decisoes/` diz **por quê** (índice em `docs/decisoes/README.md`). Leia o arquivo da área antes de mexer nela:

| Área | Arquivo |
| --- | --- |
| Imagem única, health, SPA, CI, deps | `docs/decisoes/infra-e-operacao.md` |
| Auth, sessão, papéis, workspaces | `docs/decisoes/auth.md` |
| Simulação, upload, storage, validate | `docs/decisoes/upload-e-storage.md` |

Ao concluir um item `A*`/`B*`, atualize no mesmo commit o parágrafo "Estado atual" acima (o que já existe e o que falta) e a linha `Status` do item em `docs/m2/trilha-*.md`, com a data e o que foi verificado.

Sempre que concluir uma tarefa que muda isso (nova feature, pendência resolvida, decisão revista), atualize o arquivo da área em `docs/decisoes/` no mesmo commit. Rota nova entra na tabela do `API-GUIDE.md`, tabela ou coluna nova na do `DATABASE.md`, regra nova no arquivo da raiz do seu ramo — no mesmo commit. Quando o `engine/` entrar: `COPY engine/ ./engine/` no `Dockerfile` e as deps dele no `pyproject.toml`.
