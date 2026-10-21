# B1a — Auth, papéis e workspaces (backend)

Primeira metade do item B1 de [`docs/m2/trilha-b-plataforma.md`](../../m2/trilha-b-plataforma.md): tabelas, sessão, dependências de escopo e as rotas de auth, membros e workspaces, com os testes de aceite. As cinco telas (login, troca de senha, seletor de workspace, admin de membros, admin de workspaces) ficam no **B1b**, um spec separado que consome esta API. Depende do B0; destrava B2–B4.

## Contexto

O B0 deixou a API com `/api/health`, SQLAlchemy + Alembic sem revisões e nenhum conceito de usuário. O protótipo Streamlit confiava num cookie com `user_id` sem assinatura e mandava o token na URL (trilha B › B1 › Hoje); nada disso é portado. As regras-alvo já estão em `SECURITY.md`; este spec as torna concretas.

## Decisões

| Tema | Decisão |
|---|---|
| Fatiamento | B1a = backend + testes; B1b = telas. |
| Reset de senha | Só por admin (platform), sem e-mail no M2 (`SECURITY.md`). |
| Contas do protótipo | Não migrar; recriar. O v2 não tem acesso ao SQLite antigo. |
| Bootstrap | CLI `python -m api.cli create-admin <email> <nome>` (`mise run create-admin`), imprime senha temporária. Em produção roda como Cloud Run Job one-off. Nenhuma senha em env. |
| Sessão | Deslizante: expira com 8h sem uso, teto absoluto de 7d. |
| Cookie | `SameSite=Lax` + checagem de `Origin` nas mutações. Integração com o Metrics (B10) ainda indefinida; se virar iframe cross-site, troca para `SameSite=None` e o check de `Origin` já cobre CSRF. |
| Escopo por workspace | Slug no path: `/api/w/{slug}/...`. Slug é único e imutável. |
| Platform admin | Entra em qualquer workspace como `admin`, sem membership (BRD › Journey 3: monitora uso e logs de job, gerencia retenção). |
| Poderes sobre usuários | **Conta** é do platform admin (reset de senha, desativar: afetam todos os workspaces do usuário). **Membership** é do admin do workspace (adicionar, trocar papel, remover). |
| `gate_thresholds` | Fora do B1a. O formato pertence ao `EngineConfig` (A0); `settings` nasce `{}` e a rota de edição entra quando o A0 fechar o schema. |
| Uso por workspace | Fora do B1a (B9). |

## Dados

Uma migration Alembic. `api/migrations/env.py` passa a usar `Base.metadata` (models em `api/models.py`).

| Tabela | Colunas |
|---|---|
| `users` | `id bigint identity PK`, `email text` (gravado em minúsculas, índice único), `name text`, `password_hash text`, `must_change_password bool default true`, `is_platform_admin bool default false`, `active bool default true`, `failed_logins int default 0`, `locked_until timestamptz null`, `created_at timestamptz default now()` |
| `workspaces` | `id bigint identity PK`, `name text`, `slug text unique` (`^[a-z0-9-]{2,40}$`), `settings jsonb default '{}'`, `created_at` |
| `memberships` | `user_id FK users on delete cascade`, `workspace_id FK workspaces on delete cascade`, `role` enum `membership_role` (`admin`, `analyst`, `viewer`), `created_at`; PK `(user_id, workspace_id)` |
| `sessions` | `token_hash bytea PK` (sha256 do token), `user_id FK users on delete cascade`, `created_at`, `last_seen_at`, índice em `user_id` |

Timestamps em UTC (`DATABASE.md`).

## Senha

- `hashlib.scrypt`, N=2¹⁷, r=8, p=1, salt de 16 bytes, `maxmem=2**28`. Formato armazenado: `scrypt$N$r$p$<salt b64>$<hash b64>`; verificar lê os parâmetros do próprio hash (custo pode subir sem invalidar senhas antigas). Comparação com `hmac.compare_digest`.
- Login com e-mail inexistente roda um scrypt contra um hash fixo, para não vazar existência pelo tempo de resposta.
- Senha nova: mínimo 12 caracteres, diferente da atual. Senha temporária: `secrets.token_urlsafe(12)`.

## Sessão

- Token `secrets.token_urlsafe(32)` no cookie `gem_session`: `HttpOnly; Secure; SameSite=Lax; Path=/`, sem `Max-Age` (cookie de sessão; quem expira é o banco). Banco guarda só `sha256(token)`.
- Válida se `now - last_seen_at < 8h` **e** `now - created_at < 7d`. `last_seen_at` é atualizado quando tem mais de 1 min. Sessão vencida é apagada ao ser encontrada.
- Cookie ausente, desconhecido, truncado ou vencido → 401 `{"detail": "not_authenticated"}`.
- Apagadas: a sessão no logout; as **outras** sessões do usuário na troca de senha; **todas** no reset de senha e na desativação.
- Navegadores aceitam cookie `Secure` em `http://localhost`, então não há modo dev que desligue o `Secure`.

## Login e bloqueio

- `POST /api/auth/login {email, password}`.
- Conta com `locked_until > now` → 429 `{"detail": "locked", "retry_after_s": N}`, sem verificar senha. Revela que a conta existe; aceitável porque contas são criadas por admin.
- Credencial errada, e-mail inexistente ou conta inativa → 401 `{"detail": "invalid_credentials"}` (mesmo corpo nos três). Senha errada incrementa `failed_logins`; ao chegar em 5, `locked_until = now + 15min` e o contador zera.
- Sucesso zera `failed_logins`, cria sessão, seta o cookie e devolve o mesmo corpo de `GET /api/me`.
- `must_change_password = true`: login funciona, mas qualquer rota além de `GET /api/me`, `POST /api/auth/password` e `POST /api/auth/logout` responde 403 `{"detail": "password_change_required"}`.

## Dependências (`api/auth.py`)

- `get_db` (`api/db.py`): sessão SQLAlchemy por request; é o ponto que os testes sobrescrevem.
- `current_user` → `User` ou 401. Aceita troca de senha pendente.
- `active_user` → `current_user` + 403 `password_change_required`. Padrão de toda rota não listada acima.
- `require_role(min_role)` → `Ctx(user, workspace, role)`. Lê `{slug}` do path. Workspace inexistente ou sem membership → **404** `{"detail": "Not Found"}` (mesmo corpo do 404 padrão). Membership com papel abaixo de `min_role` → **403** (o usuário já sabe que o workspace existe; não há oráculo). Ordem: `viewer < analyst < admin`; platform admin vale `admin`.
- `require_platform_admin` → 403 para os demais.
- Middleware de origem: `POST/PUT/PATCH/DELETE` em `/api/*` com header `Origin` presente e diferente da origem do próprio request → 403 `{"detail": "bad_origin"}`. Sem `Origin` passa (clientes não-browser, CLI, testes).

## Rotas

| Método | Path | Dependência | Observação |
|---|---|---|---|
| POST | `/api/auth/login` | público | ver Login |
| POST | `/api/auth/logout` | `current_user` | apaga a sessão, limpa o cookie; 204 |
| POST | `/api/auth/password` | `current_user` | `{current, new}`; zera `must_change_password`; derruba as outras sessões; 204 |
| GET | `/api/me` | `current_user` | `{id, email, name, is_platform_admin, must_change_password, workspaces: [{slug, name, role}]}`; platform admin recebe todos os workspaces com `role: "admin"` |
| GET | `/api/w/{slug}/members` | `require_role("admin")` | `[{user_id, email, name, role, active}]` |
| POST | `/api/w/{slug}/members` | `require_role("admin")` | `{email, name, role}`. Conta inexistente: cria com temporária e devolve `temp_password` (única vez). Conta existente: só cria a membership, `temp_password: null`. Já membro → 409 |
| PATCH | `/api/w/{slug}/members/{user_id}` | `require_role("admin")` | `{role}`; membro de outro ws → 404 |
| DELETE | `/api/w/{slug}/members/{user_id}` | `require_role("admin")` | remove só a membership; 204 |
| GET | `/api/admin/workspaces` | `require_platform_admin` | `[{id, name, slug, created_at}]` |
| POST | `/api/admin/workspaces` | `require_platform_admin` | `{name, slug}`; slug duplicado → 409; slug inválido → 422 |
| GET | `/api/admin/users` | `require_platform_admin` | `[{id, email, name, active, is_platform_admin, locked_until}]` |
| POST | `/api/admin/users/{id}/reset-password` | `require_platform_admin` | nova temporária, `must_change_password = true`, zera bloqueio, derruba todas as sessões; devolve `{temp_password}` |
| PATCH | `/api/admin/users/{id}` | `require_platform_admin` | `{active}`; desativar derruba todas as sessões |

Rotas literais antes das parametrizadas (`API-GUIDE.md`). Routers: `api/routes/auth.py`, `api/routes/members.py`, `api/routes/admin.py`, incluídos em `create_app()` antes do `mount_spa`.

## CLI

`python -m api.cli create-admin <email> <nome>`: cria (ou promove, se já existe) um usuário com `is_platform_admin = true`, `must_change_password = true`, e imprime a senha temporária no stdout. Task `create-admin` no `mise.toml`.

## Logs

`logging` padrão, logger `api.auth`. Eventos: `auth.login_ok` (`user_id`), `auth.login_failed` (e-mail tentado), `auth.locked` (`user_id`), `auth.password_changed`, `auth.password_reset` (`user_id`, `by`), `auth.user_deactivated`. Senha, senha temporária, token e hash nunca entram em log.

## Testes

Infra (`tests/conftest.py`):
- `TEST_DATABASE_URL` (default `postgresql+psycopg://app:app@localhost:5432/app_test`). O conftest cria o banco se não existir e roda `alembic upgrade head` uma vez por sessão.
- Cada teste numa conexão com transação externa + `Session(join_transaction_mode="create_savepoint")`, sobrescrevendo `get_db`; rollback no fim.
- Testes de banco **falham** com Postgres fora do ar (não pulam): skip esconderia o RBAC no CI.
- scrypt com N=2¹⁴ via monkeypatch, para velocidade.
- `TestClient(app, base_url="https://testserver")`, senão o cookie `Secure` não volta.
- Fábricas simples (`make_user`, `make_workspace`, `login_as`) no conftest.
- CI: service `postgres:16` no job `py`, com `TEST_DATABASE_URL` apontando para ele.

Aceite do B1 → verificação:

| Aceite | Teste |
|---|---|
| Papel × endpoint cobrindo toda rota | `tests/api/test_rbac.py`: tabela `ROUTES = {(método, path): papel_mínimo}` parametrizada × {anônimo, viewer, analyst, admin do ws, platform}. Abaixo do mínimo → 401 (anônimo) / 403 / 404 conforme a regra; a partir dele, com path e corpo válidos (fixtures reais) → status 2xx. Um teste percorre `app.routes` e **falha se houver rota `/api/*` fora da tabela** (exceto `/api/health`, pública). |
| Acesso entre workspaces → 404 | admin do ws `a` em `GET/POST/PATCH/DELETE /api/w/b/members…` → 404; slug inexistente → 404 com corpo idêntico; `PATCH /api/w/a/members/{id de membro só do b}` → 404. |
| Cookie adulterado → 401 | token aleatório, token truncado, sessão com 8h ociosa, sessão com 7d de vida (relógio controlado por monkeypatch de uma função `now()` em `api/auth.py`). |
| Senha nunca em log | `caplog` em DEBUG durante login certo, login errado, troca de senha, reset e `create-admin`; nenhuma senha, temporária ou token aparece no texto capturado. |

Outros testes:
- 5ª falha bloqueia → 429; libera depois de 15 min; acerto zera o contador.
- Troca de senha pendente → 403 numa rota de workspace, 200 em `/api/me`.
- Troca de senha derruba as outras sessões e mantém a atual.
- Reset e desativação derrubam todas as sessões.
- `POST` com `Origin: https://evil.example` → 403.
- `POST /api/w/{slug}/members` com conta existente não devolve senha e não altera a conta.
- `create-admin` cria um platform admin que consegue logar.
- `tests/test_passwords.py`: hash/verify, rejeita hash adulterado, parâmetros lidos do hash.

## Docs no mesmo commit da entrega

- `DATABASE.md`: as quatro tabelas saem de "planejada" e ganham o id da revisão; `target_metadata` atualizado.
- `API-GUIDE.md`: as 13 rotas na tabela.
- `SECURITY.md`: marcar o que foi implementado; seção "Mexer em auth" listando `api/auth.py`, `api/passwords.py`, `api/routes/{auth,members,admin}.py`, `api/cli.py`, o middleware de origem.
- `docs/decisoes/auth.md` (novo, e linha no índice): por que Lax + Origin, 404 × 403, sessão deslizante 8h/7d, divisão conta × membership, CLI de bootstrap.
- `CLAUDE.md` › Estado atual e a linha `Status` do B1 na trilha (B1a feito, B1b pendente).
- `.env.example`: `TEST_DATABASE_URL`.

## Fora do escopo

Telas (B1b); edição de `gate_thresholds`; tela/view de uso (B9); reset por e-mail; SSO com o Metrics; rate limit por IP (o bloqueio por conta cobre força bruta direcionada; rever no B11).
