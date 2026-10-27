# Guia da API

REST em FastAPI, tudo sob `/api`. O `docs/m2/README.md` vence em dúvida de contrato; o porquê do comportamento de cada rota está em `docs/decisoes/`. O OpenAPI do FastAPI fica em `/docs` (a exposição em produção é decisão do B11, ver `SECURITY.md`).

## Regras

- **Rota fina**: valida entrada, chama o serviço, traduz exceção de domínio em status. Regra de negócio fica fora da rota.
- **Escopo por workspace**: rota de dado de cliente vive sob `/api/w/{slug}/…` e recebe `ctx: Ctx = Depends(require_role("viewer"|"analyst"|"admin"))` (`api/auth.py`); queries filtram por `ctx.workspace.id`. Workspace inexistente ou sem membership → **404, nunca 403**; papel insuficiente → 403. Rotas fora de workspace usam `current_user` (aceita troca de senha pendente), `active_user` ou `require_platform_admin`.
- **`detail` dos erros de auth é código estável** (`not_authenticated`, `invalid_credentials`, `locked`, `password_change_required`, `bad_origin`, `invalid_current_password`, `password_unchanged`, `cannot_deactivate_self`, `account_not_found`, `name_required`, `last_admin`): o front decide o fluxo por ele e traduz para pt-BR. Os demais erros trazem a mensagem pt-BR pronta.
- **Status de erro**: 401 sem sessão, cookie adulterado ou sessão de usuário desativado; 400 senha atual errada ou desativar a si mesmo (`invalid_current_password`, `cannot_deactivate_self`); 403 papel insuficiente, troca de senha pendente ou `Origin` de outro site; 404 recurso inexistente ou de outro workspace; 409 conflito com o estado do recurso (run bloqueado pelo gate ou já ativo); 413 upload acima de 30 MB; 422 entrada inválida; 429 conta bloqueada (`locked`, no login e na troca de senha); 503 `busy` com `Retry-After: 1` quando nenhum slot de scrypt abre em 5 s (qualquer rota que faz hash); provedor externo fora do ar degrada, nunca vira 500. O 422 de validação do corpo traz `type`, `loc`, `msg` e `ctx` de cada erro, sem o `input` (handler em `api/main.py`).
- **`/api/health` responde sempre 200** com `{"status":"ok","db":"ok|down"}`: liveness não depende do banco.
- **Ordem de declaração**: rota literal antes da parametrizada.
- **SPA**: `mount_spa()` registra o catch-all **depois** de todos os routers; `/api/*` desconhecido devolve 404 JSON (`{"detail":"Not Found"}`), nunca o `index.html`. Sem `web/dist/index.html` não há SPA. O diretório vem de `WEB_DIST` (default `web/dist`).
- Matemática (curva, CPA, ponto ótimo) vem pronta do `engine/` pela API; o front só exibe.

## Endpoints

| Método | Path | Observação |
|---|---|---|
| GET | `/api/health` | **Público.** Sempre 200; `db` reporta `ok` ou `down` |
| POST | `/api/auth/login` | **Público.** `{email, password}` → corpo do `/api/me` + cookie `gem_session`. 401 `invalid_credentials`, 429 `{detail: "locked", retry_after_s}`, 503 `busy` com `Retry-After` |
| POST | `/api/auth/logout` | Sessão. 204, limpa o cookie |
| POST | `/api/auth/password` | Sessão (aceita troca pendente). `{current, new}` (≥ 12). 204; 400 `invalid_current_password` (conta para o bloqueio, como no login); 422 `password_unchanged`; 429 `{detail: "locked", retry_after_s}`; 503 `busy`. Derruba todas as sessões, inclusive a atual, e responde com cookie novo |
| GET | `/api/me` | Sessão (aceita troca pendente). `{id, email, name, is_platform_admin, must_change_password, workspaces: [{slug, name, role}]}` |
| GET | `/api/w/{slug}/members` | Admin do ws. `[{user_id, email, name, role, active}]` |
| POST | `/api/w/{slug}/members` | Admin do ws. `{email, role, name?}` → 201 + `temp_password` (só se a conta foi criada agora; senão `null`; resposta `Cache-Control: no-store`). Só o platform admin cria conta: e-mail desconhecido é 404 `account_not_found` para o admin do ws, e 422 `name_required` para o platform admin sem `name`. 409 se já é membro |
| PATCH | `/api/w/{slug}/members/{user_id}` | Admin do ws. `{role}`; 409 `last_admin` ao rebaixar o último admin |
| DELETE | `/api/w/{slug}/members/{user_id}` | Admin do ws. Remove só a membership; 204; 409 `last_admin` ao remover o último admin |
| GET | `/api/w/{slug}/simulations` | Analyst+. `[{id, name, created_by_name, created_at, updated_at}]`, mais recente primeiro |
| POST | `/api/w/{slug}/simulations` | Analyst+. `{name}` (1–120) → 201 `SimulationOut` = `{id, name, config, validation, files: {investment\|performance\|trends: {filename, size_bytes, sha256, columns, suggested, uploaded_at} \| null}}` |
| GET | `/api/w/{slug}/simulations/{simulation_id}` | Analyst+. `SimulationOut` |
| PUT | `/api/w/{slug}/simulations/{simulation_id}/files/{kind}` | Analyst+. Multipart `file` (`.csv`, ≤ 30 MB) → `SimulationOut`; substitui o arquivo do `kind` e zera `validation`. 413 acima de 30 MB; 422 extensão ou cabeçalho ilegível |
| PUT | `/api/w/{slug}/simulations/{simulation_id}/mapping` | Analyst+. `{investment_file, performance_file, generic_trends_file?}` (formato do `column_mapping`) → salva em `config`, roda o validate e devolve `SimulationOut`; 422 arquivo faltando ou coluna inexistente |
| GET | `/api/engine/config-schema` | Sessão ativa. JSON Schema do `ParamsIn` (campos do formulário de parâmetros, com defaults e limites) |
| GET | `/api/w/{slug}/simulations/{simulation_id}/suggestions` | Analyst+. `{campo: {value, reason, source: "dados"}}` tirado dos arquivos; campo com ponto (`financial_targets.target_cpa`). 422 sem mapeamento confirmado para os arquivos atuais |
| POST | `/api/w/{slug}/simulations/{simulation_id}/suggestions/gemini` | Analyst+. `{available, suggestions: {campo: {value, reason, source: "gemini"}}}`; Gemini sem chave, fora do ar ou com resposta ruim → 200 `available: false`. 422 sem mapeamento confirmado |
| PUT | `/api/w/{slug}/simulations/{simulation_id}/params` | Analyst+. `ParamsIn` → `SimulationOut`; grava em `config` com os defaults e preserva o `column_mapping`; não mexe no `validation`. 422 do pydantic com `loc` por campo; 422 sem mapeamento confirmado |
| POST | `/api/w/{slug}/simulations/{simulation_id}/runs` | Analyst+. `{confirmed_warnings: [check_id]}` → 201 `RunOut` (`queued`, ou `failed` se o worker não subiu); snapshot de `config` e do sha256 dos inputs. 409 com a frase pt-BR: sem validação, erro na validação, aviso não confirmado, parâmetros não salvos, ou já há run ativo na simulação |
| GET | `/api/w/{slug}/simulations/{simulation_id}/runs` | Viewer+ (viewer só vê publicados). Até 20 `RunOut`, mais recente primeiro |
| GET | `/api/w/{slug}/runs/{run_id}` | Viewer+ (viewer só vê publicado; senão 404). `RunOut`: `{id, status, simulation: {id, name}, created_by_name, created_at, started_at, finished_at, error, summary, engine_version}` |
| GET | `/api/w/{slug}/runs/{run_id}/logs/stream` | Viewer+, mesma visibilidade. SSE: `id: <log id>` + `data: {ts, level, message}`; sem `Last-Event-ID` manda as 300 últimas, com ele as de id maior; `event: end` + `data: {status}` quando o run termina |
| GET | `/api/admin/workspaces` | Platform admin |
| POST | `/api/admin/workspaces` | Platform admin. `{name, slug}` (`^[a-z0-9-]{2,40}$`); 409 slug repetido |
| GET | `/api/admin/users` | Platform admin. `[{id, email, name, active, is_platform_admin, locked_until}]` |
| POST | `/api/admin/users/{user_id}/reset-password` | Platform admin. `{temp_password}` (`Cache-Control: no-store`); derruba as sessões e desbloqueia |
| PATCH | `/api/admin/users/{user_id}` | Platform admin. `{active}`; desativar derruba as sessões; reativar zera o bloqueio; 400 `cannot_deactivate_self` ao desativar a si mesmo |

Os demais entram com B5–B9. Cada rota nova ganha uma linha aqui **e** uma entrada em `ROUTES` de `tests/api/test_rbac.py` no mesmo commit; o teste falha se uma rota `/api/*` ficar de fora.

## Nova rota REST

router em `api/` → schemas Pydantic → serviço → `app.include_router` em `create_app()` (`api/main.py`) → teste em `tests/api/test_<recurso>.py` → tipo e `useQuery`/`useMutation` em `web/src/` → linha na tabela acima.

No frontend, chamadas vão para `/api/…` na mesma origem (o Vite faz proxy para `:8000` em dev). O front usa TanStack Query; invalide as queries afetadas depois de cada mutation.
