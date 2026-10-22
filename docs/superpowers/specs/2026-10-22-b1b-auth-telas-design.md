# B1b · Telas de autenticação, workspaces e admin — design

Data: 22/out/2026. Item: B1 em `docs/m2/trilha-b-plataforma.md` (B1a, o backend, está pronto). Decisões de backend em `docs/decisoes/auth.md`.

## Objetivo

Telas sobre a API do B1a: login, troca de senha obrigatória, seletor de workspace, admin de membros (por workspace) e admin de workspaces e usuários (platform admin). Nenhuma rota nova na API.

## Estilo

- Tailwind v4 + shadcn/ui (componentes copiados para `web/src/components/ui/` pelo CLI do shadcn).
- Paleta e estilo do protótipo Streamlit (`opportunity-engine/scripts/streamlit_app.py:340-535`), como tokens do shadcn em `web/src/index.css`:
  - primária `#ff4b4b`; fonte Inter; raio 10–12px; sombras suaves;
  - claro: fundo `#f8f9fa`, card `#ffffff`, borda `#e0e0e0`, texto `#202124`, texto secundário `#5f6368`;
  - escuro: fundo `#0e1117`, card `#262730`, borda `rgba(255,255,255,0.1)`, texto `#fafafa`.
- Dois temas. Padrão: segue o sistema; toggle no header (claro / escuro / sistema) salvo em `localStorage`, aplicado como classe `.dark` no `<html>`.
- Logos DASH e AlmapBBDO (positivo no claro, negativo no escuro) copiados de `opportunity-engine/Logos/` para `web/src/assets/logos/`.
- Visual definitivo vem do design system do Almap Metrics no B10; trocar os tokens deve bastar.

## Rotas

```
/login                    pública; já logado → redirect para `redirect` ou /
/trocar-senha             logado; obrigatória enquanto must_change_password
/_auth (layout)           exige sessão; header com logos, seletor de workspace, tema, usuário/sair
  /                       1 workspace → /w/$slug; vários → lista para escolher; 0 → "sem acesso, fale com o admin"
  /w/$slug                home do workspace (placeholder até o B2)
  /w/$slug/membros        admin do workspace: listar, adicionar, trocar papel, remover
  /admin/workspaces       platform admin: listar, criar
  /admin/usuarios         platform admin: listar, resetar senha, ativar/desativar
```

O workspace ativo é o slug na URL, espelhando `/api/w/{slug}`. O seletor só navega.

## Controle de acesso no front

Guardas no `beforeLoad` do TanStack Router, com `/api/me` no cache do TanStack Query (`ensureQueryData`):

- `_auth`: 401 → `/login?redirect=<rota>`; `must_change_password` → `/trocar-senha`.
- `/w/$slug`: slug fora de `me.workspaces` → `notFound()` (mesma tela de rota inexistente, como o 404 da API).
- `/admin`: sem `is_platform_admin` → `notFound()`.
- `/w/$slug/membros`: papel ≠ admin no workspace → tela "sem permissão".

Links de "Membros" e "Admin" só aparecem para quem pode usar. Esconder é UX; quem barra é a API.

Após login, troca de senha, logout e mutações que mudam o `/me` (criar workspace), invalidar a query `me`.

## Fluxos

- **Login**: e-mail e senha. `invalid_credentials` → "E-mail ou senha inválidos"; `locked` → "Conta bloqueada. Tente de novo em N min" (de `retry_after_s`, arredondado para cima).
- **Troca de senha**: atual, nova (mín. 12) e confirmação (checada no front). `invalid_current_password`, `password_unchanged` e `locked` viram mensagem no formulário. Sucesso → `/`.
- **Adicionar membro**: e-mail, nome, papel. Se a resposta trouxer `temp_password`, abre `TempPasswordDialog`: mostra a senha uma vez, botão de copiar, aviso "não será mostrada de novo". 409 → mensagem no formulário.
- **Trocar papel / remover**: select na linha; remover pede confirmação.
- **Criar workspace**: nome e slug (`^[a-z0-9-]{2,40}$`, sugerido a partir do nome). Para dar o primeiro admin, o platform admin usa a tela de membros do workspace (a API o trata como admin em todos).
- **Resetar senha**: confirmação → `TempPasswordDialog`. **Desativar/ativar**: toggle na linha; o próprio usuário não aparece desativável (a API responde `cannot_deactivate_self`).
- **Sair**: `POST /api/auth/logout`, limpa o cache, vai para `/login`.

## Arquivos

```
web/src/
  lib/api.ts                      fetch central: JSON, ApiError(status, detail); 401 fora do /login → limpa cache e vai para /login
  lib/auth.ts                     meQuery, role(me, slug), errorMessage(code) → pt-BR
  lib/theme.ts                    tema light/dark/system
  components/ui/                  shadcn: button, input, label, card, table, dialog, alert-dialog, select, dropdown-menu, sonner
  components/AppHeader.tsx
  components/TempPasswordDialog.tsx
  routes/login.tsx
  routes/trocar-senha.tsx
  routes/_auth.tsx
  routes/_auth/index.tsx
  routes/_auth/w/$slug.tsx
  routes/_auth/w/$slug/index.tsx
  routes/_auth/w/$slug/membros.tsx
  routes/_auth/admin.tsx
  routes/_auth/admin/workspaces.tsx
  routes/_auth/admin/usuarios.tsx
  index.css
  assets/logos/
```

A tela atual de health (`routes/index.tsx`) sai; `/api/health` continua para o deploy.

Cada tela usa `useQuery`/`useMutation` direto e invalida a lista no sucesso; sem camada de service. Formulários com `<form>` nativo, `FormData` e validação HTML; sem react-hook-form/zod.

## Erros

| Resposta | Tratamento |
| --- | --- |
| 401 (fora do login) | limpa cache → `/login?redirect=…` |
| 403 `password_change_required` | → `/trocar-senha` |
| 403 sem código | "Sem permissão" |
| 404 | tela de não encontrado |
| 400 / 409 / 422 | mensagem no formulário (código traduzido ou `detail` já em pt-BR) |
| 429 `locked` | tempo restante |
| 5xx / rede | toast genérico |

O cookie `Secure` funciona em `http://localhost` no Chromium (localhost é contexto seguro); dev e CI dispensam HTTPS.

## Testes

Playwright, só Chromium, em `web/e2e/`, contra a app real: uvicorn em `:8000` servindo `web/dist`, Postgres de verdade.

- `globalSetup` roda `uv run python -m api.cli create-admin <email único> E2E` e lê a senha temporária do stdout.
- E-mails e slugs com sufixo aleatório; roda de novo sem resetar o banco.
- Fluxos:
  1. Admin loga → forçado a trocar senha → cai em `/`.
  2. Admin cria workspace e adiciona analista → senha temporária aparece uma vez → analista loga, troca a senha, cai em `/w/<slug>`.
  3. 5 senhas erradas → mensagem de bloqueio com tempo restante.
  4. Analista em `/w/<outro-slug>` → não encontrado; `/admin` → não encontrado; sem link de Membros nem de Admin no header.
  5. Logout → login; rota protegida depois disso → login.
- CI: job `e2e` com serviço Postgres: `uv sync` → migrate → `bun run build` → uvicorn em background → `bunx playwright test`; trace como artifact em falha.
- Local: `mise run e2e` com o compose no ar.

Verificação visual: screenshot das telas nos dois temas antes de declarar pronto (regra do `CLAUDE.md`).

## Fora do escopo

Vitest de componente, Firefox/WebKit, i18n além de pt-BR, "esqueci minha senha", editar nome/slug de workspace, paginação, página de uso/logs do platform admin (item próprio da trilha B).

## Docs a atualizar ao concluir

`CLAUDE.md` (Estado atual, estrutura do `web/`, comando `mise run e2e`), `docs/m2/trilha-b-plataforma.md` (Status do B1), `docs/decisoes/auth.md` (guardas no front, tema), `CODE-STYLE.md` se surgir regra de front, `.github/workflows/ci.yml` (job `e2e`).
