# Segurança

## Reportar uma vulnerabilidade

Abra um relato privado pelo GitHub: aba **Security → Report a vulnerability** deste repositório. Não abra issue pública. Só a versão em produção (a `main`) recebe correção.

O resto deste arquivo são as regras que o código segue. O porquê de cada uma está no arquivo da área em `docs/decisoes/`. As regras de auth e escopo abaixo estão implementadas desde o B1a (21/out/2026); as telas são do B1b.

## Escopo por workspace

- **Toda** query de dado de cliente filtra por `workspace_id`. Sem exceção, inclusive em join e subquery.
- O workspace chega por uma dependência do FastAPI que valida a **membership** do usuário da sessão — nunca por body ou query param confiado cegamente.
- Recurso de outro workspace responde **404, nunca 403**: 403 vira oráculo de existência.
- Papéis: **viewer** (vê runs publicados, mexe em cenários, exporta) < **analyst** (upload, roda, publica/despublica) < **admin** (membros e thresholds) · **platform admin** (cria workspaces, vê o uso de todos). Todo endpoint tem teste papel × rota.

## Auth

- Sem auto-cadastro: só o platform admin cria contas, com senha temporária e troca obrigatória no 1º login. O admin do workspace só vincula contas existentes, senão poderia criar uma conta, ficar com a senha e herdar o acesso que outra marca desse a ela. Reset de senha só pelo platform admin no M2.
- Senha com `hashlib.scrypt` (stdlib). Bloqueio após 5 falhas seguidas por 15 min, com a linha do usuário travada (`FOR NO KEY UPDATE`) para palpites em paralelo não furarem a contagem; senha atual errada na troca de senha conta para o mesmo bloqueio. No máximo 4 scrypts simultâneos, e o login não segura conexão do pool durante o scrypt, para uma rajada de logins não derrubar a instância nem esgotar o pool. Senha acima de 1024 caracteres é 422.
- Sessão em cookie `HttpOnly; Secure; SameSite=Lax` guardando um token aleatório; o banco guarda só o **hash**. Nunca guardar `user_id` ou `username` no cookie, nem token de sessão na URL (o protótipo fazia as duas coisas).
- Cookie adulterado → 401. Sessão de usuário desativado também é rejeitada, mesmo que tenha sobrevivido à desativação.
- Senha temporária sai com `Cache-Control: no-store`, para não ficar em cache de browser ou proxy.
- Senha, token e chave nunca aparecem em log.
- Sessão deslizante: expira com 8h sem uso, teto de 7d desde o login. Troca de senha derruba as outras sessões; reset e desativação derrubam todas.
- Mutações (`POST/PUT/PATCH/DELETE` em `/api/*`) com `Origin` de outro host → 403, além do `SameSite=Lax`.
- Conta é do platform admin (criar, reset, desativar); membership é do admin do workspace (vincular conta existente, papel, remover). O último admin do workspace não pode ser rebaixado nem removido. Bootstrap do primeiro platform admin: `mise run create-admin <email> <nome>`, nunca senha em env.

## Segredos e superfícies expostas

- Segredo só via env, nunca no código nem no repositório: `DATABASE_URL`, a chave do Gemini (Secret Manager em produção), o que o B1 e o B8 acrescentarem. O `.env.example` traz o que cada um é e como gerar.
- Chave do Gemini é **única da plataforma** (Secret Manager), nunca por usuário nem em texto puro no banco.
- O BRD e dados de cliente (CSV de investimento, resultados) **não vão para o repositório** (`.gitignore`: `*.docx`, `inputs/`, `outputs/`).
- `/docs`, `/redoc` e `/openapi.json`: fechar em produção (decisão a registrar no B11).
- Mesma origem (API serve o SPA): sem CORS aberto.
- Upload (B2): só `.csv` até 30 MB, conferido antes de guardar; o conteúdo só é lido pelo `csv` da stdlib, nunca executado. O nome original só é exibido; o arquivo vive em `ws/{workspace_id}/sim/{simulation_id}/inputs/{sha256}.csv`, chave montada pela API. CSV exportado deve escapar texto que começa com `=`, `+`, `-`, `@`, tab ou CR (o Excel executaria a fórmula).

## Mexer em auth

- `api/passwords.py` — scrypt (params dentro do hash), `dummy_hash` contra timing, senha temporária.
- `api/auth.py` — sessão (cookie, hash, expiração), login e bloqueio, dependências `current_user` / `active_user` / `require_role` / `require_platform_admin`, middleware `check_origin`.
- `api/accounts.py` — troca e reset de senha, membros, workspaces, desativar, `create_platform_admin`.
- `api/routes/auth.py`, `members.py`, `admin.py` — rotas finas.
- `api/cli.py` — `create-admin`.
- `tests/api/test_rbac.py` — matriz papel × rota; rota nova entra na tabela `ROUTES`.

O porquê de cada escolha: `docs/decisoes/auth.md`.
