# B1b — Telas de auth, workspaces e admin — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Telas sobre a API do B1a (login, troca de senha obrigatória, seletor de workspace, membros, admin de workspaces e usuários), com tema claro/escuro do protótipo e testes E2E com Playwright no CI.

**Architecture:** SPA em `web/` com TanStack Router (file-based) e TanStack Query. `lib/api.ts` é o único `fetch` e lança `ApiError`. `lib/auth.ts` guarda o `meQuery` e a tradução de códigos de erro. As guardas ficam no `beforeLoad` das rotas (`_auth`, `w/$slug`, `admin`), lendo `/api/me` do cache do Query. Um handler global em `main.tsx` trata 401 e `password_change_required` vindos de qualquer query ou mutation. Nenhuma rota nova na API.

**Tech Stack:** Vite 8, React 19, TypeScript 6, TanStack Router/Query, Tailwind v4, shadcn/ui, sonner, `@fontsource-variable/inter`, `@playwright/test` (Chromium). Back: FastAPI do B1a, sem mudança.

**Spec:** [`docs/superpowers/specs/2026-10-22-b1b-auth-telas-design.md`](../specs/2026-10-22-b1b-auth-telas-design.md)

**Repo:** `opportunity-engine-v2`. Comandos de front rodam em `web/`, os demais na raiz. **Branch:** `b1b-telas`, criada a partir da `main` antes da Task 1.

**Pré-requisito local:** `docker compose up -d` (Postgres em `:5432`). O E2E usa o banco `app_e2e`, criado sozinho pelo `globalSetup`.

**Cuidado:** não rode `mise run web` enquanto cria arquivos em `web/src/routes/`. O gerador do TanStack Router reescreve arquivo vazio com placeholder. O `bun run build` regenera `routeTree.gen.ts` (versionado; commite junto).

**Convenções:** UI em pt-BR; código, nomes de teste e commits em inglês (`CODE-STYLE.md`). Path de API e campos JSON em inglês. Use `bun`/`bunx`, nunca npm.

---

## Mapa de arquivos

```
web/
  components.json                   criado pelo shadcn init
  playwright.config.ts              novo
  e2e/env.ts                        DATABASE_URL e raiz do repo para o E2E
  e2e/create_db.py                  cria o banco app_e2e se faltar
  e2e/global-setup.ts               cria banco + migrations
  e2e/helpers.ts                    createAdmin, login, changePassword, createWorkspace, addMember
  e2e/auth.spec.ts
  e2e/admin.spec.ts
  e2e/members.spec.ts
  src/index.css                     Tailwind + tokens claro/escuro
  src/main.tsx                      QueryClient com handler global, router com contexto
  src/lib/utils.ts                  criado pelo shadcn init (cn)
  src/lib/api.ts                    fetch central + ApiError
  src/lib/auth.ts                   Me, meQuery, roleIn, ROLE_LABELS, errorMessage
  src/lib/theme.ts                  light/dark/system
  src/components/ui/*               shadcn: button, input, label, card, table, dialog, alert-dialog, dropdown-menu
  src/components/AuthCard.tsx       moldura centrada de login e troca de senha
  src/components/AppHeader.tsx      logos, seletor de workspace, links, tema, usuário
  src/components/TempPasswordDialog.tsx
  src/components/NativeSelect.tsx   <select> nativo com estilo
  src/assets/logos/*.png            4 logos do protótipo
  src/routes/__root.tsx             createRootRouteWithContext
  src/routes/index.tsx              REMOVIDO (tela de health)
  src/routes/login.tsx
  src/routes/trocar-senha.tsx
  src/routes/_auth.tsx
  src/routes/_auth/index.tsx
  src/routes/_auth/w/$slug.tsx
  src/routes/_auth/w/$slug/index.tsx
  src/routes/_auth/w/$slug/membros.tsx
  src/routes/_auth/admin.tsx
  src/routes/_auth/admin/workspaces.tsx
  src/routes/_auth/admin/usuarios.tsx
mise.toml                           task e2e
.github/workflows/ci.yml            job e2e
```

Para os selects usamos `<select>` nativo em vez do Select do shadcn (Radix): é acessível de graça e o Playwright usa `selectOption` direto.

---

### Task 1: Tailwind, shadcn e tema do protótipo

**Files:**
- Modify: `web/package.json`, `web/bun.lock` (via `bun add`)
- Modify: `web/tsconfig.json`, `web/tsconfig.app.json`, `web/vite.config.ts`, `web/index.html`, `web/src/main.tsx`
- Create: `web/src/index.css`, `web/components.json`, `web/src/lib/utils.ts`, `web/src/components/ui/*`
- Create: `web/src/assets/logos/{dash-positivo,dash-negativo,almap-positivo,almap-negativo}.png`

- [ ] **Step 1: Criar a branch**

```bash
git switch -c b1b-telas
```

- [ ] **Step 2: Instalar Tailwind v4, a fonte e o sonner**

```bash
cd web && bun add tailwindcss @tailwindcss/vite @fontsource-variable/inter sonner
```

- [ ] **Step 3: Alias `@/` no TypeScript**

O shadcn exige o alias nos dois tsconfig. TS 6 deprecia `baseUrl`; `paths` relativos funcionam sem ele.

`web/tsconfig.json`:

```json
{
  "files": [],
  "references": [
    { "path": "./tsconfig.app.json" },
    { "path": "./tsconfig.node.json" }
  ],
  "compilerOptions": {
    "paths": { "@/*": ["./src/*"] }
  }
}
```

Em `web/tsconfig.app.json`, adicione dentro de `compilerOptions`, logo depois de `"types": ["vite/client"],`:

```json
    "paths": { "@/*": ["./src/*"] },
```

- [ ] **Step 4: Plugin do Tailwind e alias no Vite**

`web/vite.config.ts`:

```ts
import { fileURLToPath } from 'node:url'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { tanstackRouter } from '@tanstack/router-plugin/vite'

export default defineConfig({
  plugins: [tanstackRouter({ target: 'react', autoCodeSplitting: true }), react(), tailwindcss()],
  resolve: { alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) } },
  server: {
    // keep the browser's Host: the api's check_origin compares it to the Origin header
    proxy: { '/api': { target: 'http://localhost:8000', changeOrigin: false } },
  },
})
```

- [ ] **Step 5: CSS mínimo para o shadcn detectar o Tailwind**

`web/src/index.css`:

```css
@import "tailwindcss";
```

E em `web/src/main.tsx`, primeira linha:

```ts
import './index.css'
```

- [ ] **Step 6: `shadcn init` e componentes**

```bash
cd web && bunx shadcn@latest init
```

Respostas: base color **Neutral**, CSS variables **sim**. Ele cria `components.json` e `src/lib/utils.ts`, instala `class-variance-authority`, `clsx`, `tailwind-merge`, `lucide-react`, `tw-animate-css` e reescreve `src/index.css` (será sobrescrito no Step 7). Depois:

```bash
cd web && bunx shadcn@latest add button input label card table dialog alert-dialog dropdown-menu
```

Confira que existem `web/src/components/ui/{button,input,label,card,table,dialog,alert-dialog,dropdown-menu}.tsx`.

- [ ] **Step 7: Tokens do protótipo**

Sobrescreva `web/src/index.css` inteiro. As cores vêm de `opportunity-engine/scripts/streamlit_app.py:340-535` e do tema padrão do Streamlit:

```css
@import "tailwindcss";
@import "tw-animate-css";

@custom-variant dark (&:is(.dark *));

:root {
  --radius: 0.75rem;
  --background: #f8f9fa;
  --foreground: #202124;
  --card: #ffffff;
  --card-foreground: #202124;
  --popover: #ffffff;
  --popover-foreground: #202124;
  --primary: #ff4b4b;
  --primary-foreground: #ffffff;
  --secondary: #f1f3f4;
  --secondary-foreground: #202124;
  --muted: #f1f3f4;
  --muted-foreground: #5f6368;
  --accent: #fdecec;
  --accent-foreground: #202124;
  --destructive: #d93025;
  --border: #e0e0e0;
  --input: #e0e0e0;
  --ring: #ff4b4b;
}

.dark {
  --background: #0e1117;
  --foreground: #fafafa;
  --card: #262730;
  --card-foreground: #fafafa;
  --popover: #262730;
  --popover-foreground: #fafafa;
  --primary: #ff4b4b;
  --primary-foreground: #ffffff;
  --secondary: #31333f;
  --secondary-foreground: #fafafa;
  --muted: #31333f;
  --muted-foreground: #a3a8b8;
  --accent: #3a2328;
  --accent-foreground: #fafafa;
  --destructive: #ff6b6b;
  --border: rgba(255, 255, 255, 0.1);
  --input: rgba(255, 255, 255, 0.15);
  --ring: #ff4b4b;
}

@theme inline {
  --font-sans: "Inter Variable", ui-sans-serif, system-ui, sans-serif;
  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-card: var(--card);
  --color-card-foreground: var(--card-foreground);
  --color-popover: var(--popover);
  --color-popover-foreground: var(--popover-foreground);
  --color-primary: var(--primary);
  --color-primary-foreground: var(--primary-foreground);
  --color-secondary: var(--secondary);
  --color-secondary-foreground: var(--secondary-foreground);
  --color-muted: var(--muted);
  --color-muted-foreground: var(--muted-foreground);
  --color-accent: var(--accent);
  --color-accent-foreground: var(--accent-foreground);
  --color-destructive: var(--destructive);
  --color-border: var(--border);
  --color-input: var(--input);
  --color-ring: var(--ring);
  --radius-sm: calc(var(--radius) - 4px);
  --radius-md: calc(var(--radius) - 2px);
  --radius-lg: var(--radius);
  --radius-xl: calc(var(--radius) + 4px);
}

@layer base {
  * {
    @apply border-border outline-ring/50;
  }
  body {
    @apply bg-background text-foreground font-sans antialiased;
  }
}
```

E em `web/src/main.tsx`, logo abaixo de `import './index.css'`:

```ts
import '@fontsource-variable/inter'
```

- [ ] **Step 8: Logos e idioma do HTML**

```bash
mkdir -p web/src/assets/logos
cp "../opportunity-engine/Logos/DASH_POSITIVO (1).png" web/src/assets/logos/dash-positivo.png
cp ../opportunity-engine/Logos/DASH_NEGATIVO.png web/src/assets/logos/dash-negativo.png
cp "../opportunity-engine/Logos/AF_ALMAPBBDO_LOGO_FINAL FILIPE-01.png" web/src/assets/logos/almap-positivo.png
cp "../opportunity-engine/Logos/AF_ALMAPBBDO_LOGO_FINAL FILIPE-02.png" web/src/assets/logos/almap-negativo.png
rm web/src/assets/hero.png web/src/assets/vite.svg
```

(Positivo = tema claro, negativo = tema escuro, como em `streamlit_app.py:650-653`.) Se `hero.png`/`vite.svg` forem referenciados em algum lugar (`grep -rn "hero.png\|vite.svg" web/src web/index.html`), remova a referência.

Em `web/index.html`, troque `<html lang="en">` por `<html lang="pt-BR">`.

- [ ] **Step 9: Build e lint**

```bash
cd web && bun run build && bun run lint
```

Expected: build OK. Se o oxlint reclamar de `only-export-components` nos arquivos gerados em `src/components/ui/`, adicione ao `web/.oxlintrc.json`:

```json
  "ignorePatterns": ["src/components/ui/**"]
```

- [ ] **Step 10: Commit**

```bash
git add web
git commit -m "build(web): add tailwind v4, shadcn/ui and prototype theme tokens"
```

---

### Task 2: Infra do Playwright e primeiro teste (vermelho)

**Files:**
- Create: `web/playwright.config.ts`, `web/e2e/env.ts`, `web/e2e/create_db.py`, `web/e2e/global-setup.ts`, `web/e2e/helpers.ts`, `web/e2e/auth.spec.ts`
- Modify: `web/package.json` (script `e2e`), `web/.gitignore`, `mise.toml`

- [ ] **Step 1: Instalar o Playwright**

```bash
cd web && bun add -d @playwright/test && bunx playwright install chromium
```

- [ ] **Step 2: Ambiente do E2E**

`web/e2e/env.ts`:

```ts
import { fileURLToPath } from 'node:url'

export const ROOT = fileURLToPath(new URL('../..', import.meta.url))
export const PORT = 8001
export const DATABASE_URL =
  process.env.E2E_DATABASE_URL ?? 'postgresql+psycopg://app:app@localhost:5432/app_e2e'
export const pyEnv = { ...process.env, DATABASE_URL, PYTHONIOENCODING: 'utf-8' }
```

`web/e2e/create_db.py`:

```python
import os

from sqlalchemy import create_engine, make_url, text

target = make_url(os.environ["DATABASE_URL"])
server = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
with server.connect() as conn:
    if not conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": target.database}):
        conn.execute(text(f'CREATE DATABASE "{target.database}"'))
```

`web/e2e/global-setup.ts`:

```ts
import { execSync } from 'node:child_process'
import { ROOT, pyEnv } from './env'

export default function globalSetup() {
  execSync('uv run python web/e2e/create_db.py', { cwd: ROOT, env: pyEnv, stdio: 'inherit' })
  execSync('uv run alembic -c api/alembic.ini upgrade head', { cwd: ROOT, env: pyEnv, stdio: 'inherit' })
}
```

O banco `app_e2e` não é limpo entre execuções: cada teste usa e-mails e slugs aleatórios.

- [ ] **Step 3: Config**

`web/playwright.config.ts`:

```ts
import { defineConfig, devices } from '@playwright/test'
import { PORT, ROOT, pyEnv } from './e2e/env'

export default defineConfig({
  testDir: './e2e',
  globalSetup: './e2e/global-setup.ts',
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? 'github' : 'list',
  use: { baseURL: `http://localhost:${PORT}`, trace: 'retain-on-failure' },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: {
    // serves the built SPA from web/dist, so run `bun run build` first (the e2e script does)
    command: `uv run uvicorn api.main:app --port ${PORT}`,
    cwd: ROOT,
    env: pyEnv,
    url: `http://localhost:${PORT}/api/health`,
    reuseExistingServer: false,
  },
})
```

Em `web/package.json`, dentro de `scripts`:

```json
    "e2e": "bun run build && playwright test",
```

Em `web/.gitignore`, ao final:

```
test-results
playwright-report
```

Em `mise.toml`, ao final:

```toml
[tasks.e2e]
description = "Playwright E2E against the built SPA (needs docker compose up)"
dir = "web"
run = "bun run e2e"
```

- [ ] **Step 4: Helpers**

`web/e2e/helpers.ts`:

```ts
import { execSync } from 'node:child_process'
import { expect, type Page } from '@playwright/test'
import { ROOT, pyEnv } from './env'

export const NEW_PASSWORD = 'senha-nova-e2e-123'

export const uid = () => Math.random().toString(36).slice(2, 8)

export function createAdmin() {
  const email = `admin-${uid()}@e2e.test`
  const out = execSync(`uv run python -m api.cli create-admin ${email} E2E`, {
    cwd: ROOT,
    env: pyEnv,
    encoding: 'utf8',
  })
  return { email, temp: out.trim().split(' ').pop()! }
}

export async function login(page: Page, email: string, password: string) {
  await page.goto('/login')
  await page.getByLabel('E-mail').fill(email)
  await page.getByLabel('Senha', { exact: true }).fill(password)
  await page.getByRole('button', { name: 'Entrar' }).click()
}

export async function changePassword(page: Page, current: string) {
  await expect(page).toHaveURL(/\/trocar-senha/)
  await page.getByLabel('Senha atual').fill(current)
  await page.getByLabel('Nova senha', { exact: true }).fill(NEW_PASSWORD)
  await page.getByLabel('Confirme a nova senha').fill(NEW_PASSWORD)
  await page.getByRole('button', { name: 'Salvar' }).click()
}

export async function loggedInAdmin(page: Page) {
  const admin = createAdmin()
  await login(page, admin.email, admin.temp)
  await changePassword(page, admin.temp)
  await expect(page.getByRole('heading', { name: 'Workspaces' })).toBeVisible()
  return admin
}

export async function createWorkspace(page: Page) {
  const slug = `ws-${uid()}`
  await page.goto('/admin/workspaces')
  await page.getByLabel('Nome').fill(`Marca ${slug}`)
  await page.getByLabel('Slug').fill(slug)
  await page.getByRole('button', { name: 'Criar workspace' }).click()
  await expect(page.getByRole('cell', { name: slug, exact: true })).toBeVisible()
  return slug
}

export async function addMember(page: Page, slug: string, role: 'admin' | 'analyst' | 'viewer') {
  const email = `user-${uid()}@e2e.test`
  await page.goto(`/w/${slug}/membros`)
  await page.getByLabel('E-mail').fill(email)
  await page.getByLabel('Nome').fill('Pessoa E2E')
  // .first(): the form's select comes before the per-row role selects
  await page.getByLabel('Papel').first().selectOption(role)
  await page.getByRole('button', { name: 'Adicionar' }).click()
  const temp = (await page.getByTestId('temp-password').textContent())!.trim()
  await page.getByRole('button', { name: 'Fechar' }).click()
  return { email, temp }
}
```

- [ ] **Step 5: Primeiro teste**

`web/e2e/auth.spec.ts`:

```ts
import { expect, test } from '@playwright/test'
import { loggedInAdmin } from './helpers'

test('first login forces a password change, then shows the workspaces', async ({ page }) => {
  await loggedInAdmin(page)
  await expect(page).toHaveURL(/\/$/)
})
```

- [ ] **Step 6: Rodar e ver falhar**

```bash
docker compose up -d
cd web && bun run e2e
```

Expected: FAIL em `loggedInAdmin`, sem campo `E-mail` em `/login` (a rota ainda não existe). Se falhar antes disso (banco, uvicorn, CLI), conserte a infra antes de seguir.

- [ ] **Step 7: Commit**

```bash
git add web mise.toml
git commit -m "test(web): add playwright e2e setup and first-login test"
```

---

### Task 3: Cliente da API, guardas, login e troca de senha

**Files:**
- Create: `web/src/lib/api.ts`, `web/src/lib/auth.ts`, `web/src/components/AuthCard.tsx`, `web/src/routes/login.tsx`, `web/src/routes/trocar-senha.tsx`, `web/src/routes/_auth.tsx`, `web/src/routes/_auth/index.tsx`
- Modify: `web/src/main.tsx`, `web/src/routes/__root.tsx`
- Delete: `web/src/routes/index.tsx`
- Test: `web/e2e/auth.spec.ts` (da Task 2)

- [ ] **Step 1: `lib/api.ts`**

```ts
export class ApiError extends Error {
  status: number
  detail: string
  body: Record<string, unknown>

  constructor(status: number, body: Record<string, unknown>) {
    const detail = typeof body.detail === 'string' ? body.detail : `HTTP ${status}`
    super(detail)
    this.status = status
    this.detail = detail
    this.body = body
  }
}

export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const hasBody = init.body !== undefined
  const r = await fetch(`/api${path}`, {
    method: init.method ?? 'GET',
    headers: hasBody ? { 'Content-Type': 'application/json' } : undefined,
    body: hasBody ? JSON.stringify(init.body) : undefined,
  })
  if (r.status === 204) return undefined as T
  const body = await r.json().catch(() => ({}))
  if (!r.ok) throw new ApiError(r.status, body)
  return body as T
}
```

- [ ] **Step 2: `lib/auth.ts`**

```ts
import { queryOptions } from '@tanstack/react-query'
import { ApiError, api } from './api'

export type Role = 'admin' | 'analyst' | 'viewer'

export type Me = {
  id: number
  email: string
  name: string
  is_platform_admin: boolean
  must_change_password: boolean
  workspaces: { slug: string; name: string; role: Role }[]
}

export const ROLE_LABELS: Record<Role, string> = { admin: 'Admin', analyst: 'Analista', viewer: 'Leitor' }

export const meQuery = queryOptions({
  queryKey: ['me'],
  queryFn: () => api<Me>('/me'),
  staleTime: Infinity,
  // the route guards handle a 401 on /me themselves
  meta: { skipAuthRedirect: true },
})

export const roleIn = (me: Me, slug: string) => me.workspaces.find((w) => w.slug === slug)?.role

const MESSAGES: Record<string, string> = {
  invalid_credentials: 'E-mail ou senha inválidos.',
  invalid_current_password: 'Senha atual incorreta.',
  password_unchanged: 'A nova senha precisa ser diferente da atual.',
  cannot_deactivate_self: 'Você não pode desativar a própria conta.',
}

export function errorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return 'Falha de conexão. Tente de novo.'
  if (error.detail === 'locked') {
    const minutes = Math.max(1, Math.ceil(Number(error.body.retry_after_s) / 60))
    return `Conta bloqueada. Tente de novo em ${minutes} min.`
  }
  if (MESSAGES[error.detail]) return MESSAGES[error.detail]
  if (error.status === 403) return 'Sem permissão.'
  if (error.status === 422) return 'Dados inválidos.'
  if (error.status >= 500) return 'Erro no servidor. Tente de novo.'
  // 409 and other domain errors already come in pt-BR
  return error.detail
}
```

- [ ] **Step 3: Root com contexto**

`web/src/routes/__root.tsx`:

```tsx
import type { QueryClient } from '@tanstack/react-query'
import { Outlet, createRootRouteWithContext } from '@tanstack/react-router'
import { Toaster } from 'sonner'

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  component: () => (
    <>
      <Outlet />
      <Toaster richColors />
    </>
  ),
})
```

- [ ] **Step 4: `main.tsx` com handler global**

`web/src/main.tsx` inteiro:

```tsx
import './index.css'
import '@fontsource-variable/inter'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { Link, RouterProvider, createRouter } from '@tanstack/react-router'
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ApiError } from './lib/api'
import { routeTree } from './routeTree.gen'

function onApiError(error: unknown, skipAuthRedirect = false) {
  if (!(error instanceof ApiError)) return
  if (error.status === 401 && !skipAuthRedirect && error.detail === 'not_authenticated') {
    queryClient.clear()
    router.navigate({ to: '/login', search: { redirect: router.state.location.href } })
  } else if (error.detail === 'password_change_required') {
    router.navigate({ to: '/trocar-senha' })
  } else if (error.status >= 500) {
    toast.error('Erro no servidor. Tente de novo.')
  }
}

const queryClient = new QueryClient({
  queryCache: new QueryCache({ onError: (e, query) => onApiError(e, Boolean(query.meta?.skipAuthRedirect)) }),
  mutationCache: new MutationCache({ onError: (e) => onApiError(e) }),
  defaultOptions: {
    queries: { retry: (count, e) => !(e instanceof ApiError && e.status < 500) && count < 2 },
  },
})

const router = createRouter({
  routeTree,
  context: { queryClient },
  defaultNotFoundComponent: () => (
    <div className="p-10 text-center">
      <p className="mb-4 text-lg">Página não encontrada.</p>
      <Link to="/" className="text-primary underline">
        Voltar ao início
      </Link>
    </div>
  ),
})

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
```

O `detail === 'not_authenticated'` separa sessão expirada do `invalid_credentials` do login, que também é 401.

- [ ] **Step 5: `AuthCard`**

`web/src/components/AuthCard.tsx`:

```tsx
import type { ReactNode } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

export function AuthCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="flex min-h-screen items-center justify-center p-4">
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>{title}</CardTitle>
        </CardHeader>
        <CardContent>{children}</CardContent>
      </Card>
    </div>
  )
}
```

- [ ] **Step 6: `/login`**

Apague `web/src/routes/index.tsx`. Crie `web/src/routes/login.tsx`:

```tsx
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, redirect, useRouter } from '@tanstack/react-router'
import type { FormEvent } from 'react'
import { AuthCard } from '@/components/AuthCard'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import { type Me, errorMessage, meQuery } from '@/lib/auth'

// only same-site paths: an absolute URL here would be an open redirect
const safePath = (v: unknown) => (typeof v === 'string' && v.startsWith('/') && !v.startsWith('//') ? v : undefined)

export const Route = createFileRoute('/login')({
  validateSearch: (search: Record<string, unknown>) => ({ redirect: safePath(search.redirect) }),
  beforeLoad: async ({ context }) => {
    const me = await context.queryClient.ensureQueryData(meQuery).catch(() => null)
    if (me) throw redirect({ to: '/' })
  },
  component: Login,
})

function Login() {
  const { redirect: next } = Route.useSearch()
  const router = useRouter()
  const queryClient = useQueryClient()
  const login = useMutation({
    mutationFn: (body: { email: string; password: string }) => api<Me>('/auth/login', { method: 'POST', body }),
    onSuccess: (me) => {
      queryClient.setQueryData(meQuery.queryKey, me)
      router.history.push(me.must_change_password ? '/trocar-senha' : (next ?? '/'))
    },
  })

  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    login.mutate({ email: String(form.get('email')), password: String(form.get('password')) })
  }

  return (
    <AuthCard title="Entrar">
      <form onSubmit={submit} className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="email">E-mail</Label>
          <Input id="email" name="email" type="email" autoComplete="username" required autoFocus />
        </div>
        <div className="space-y-2">
          <Label htmlFor="password">Senha</Label>
          <Input id="password" name="password" type="password" autoComplete="current-password" required />
        </div>
        {login.isError && <p className="text-sm text-destructive">{errorMessage(login.error)}</p>}
        <Button type="submit" className="w-full" disabled={login.isPending}>
          Entrar
        </Button>
      </form>
    </AuthCard>
  )
}
```

- [ ] **Step 7: `/trocar-senha`**

`web/src/routes/trocar-senha.tsx`:

```tsx
import { useMutation, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { createFileRoute, redirect, useNavigate } from '@tanstack/react-router'
import { type FormEvent, useState } from 'react'
import { AuthCard } from '@/components/AuthCard'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import { errorMessage, meQuery } from '@/lib/auth'

export const Route = createFileRoute('/trocar-senha')({
  beforeLoad: async ({ context, location }) => {
    const me = await context.queryClient.ensureQueryData(meQuery).catch(() => null)
    if (!me) throw redirect({ to: '/login', search: { redirect: location.href } })
  },
  component: ChangePassword,
})

function ChangePassword() {
  const { data: me } = useSuspenseQuery(meQuery)
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [mismatch, setMismatch] = useState(false)
  const change = useMutation({
    mutationFn: (body: { current: string; new: string }) => api('/auth/password', { method: 'POST', body }),
    onSuccess: () => {
      queryClient.setQueryData(meQuery.queryKey, { ...me, must_change_password: false })
      navigate({ to: '/' })
    },
  })

  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    const next = String(form.get('new'))
    setMismatch(next !== form.get('confirm'))
    if (next !== form.get('confirm')) return
    change.mutate({ current: String(form.get('current')), new: next })
  }

  return (
    <AuthCard title={me.must_change_password ? 'Defina sua senha' : 'Trocar senha'}>
      <form onSubmit={submit} className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="current">Senha atual</Label>
          <Input id="current" name="current" type="password" autoComplete="current-password" required />
        </div>
        <div className="space-y-2">
          <Label htmlFor="new">Nova senha</Label>
          <Input id="new" name="new" type="password" autoComplete="new-password" minLength={12} required />
          <p className="text-xs text-muted-foreground">Mínimo de 12 caracteres.</p>
        </div>
        <div className="space-y-2">
          <Label htmlFor="confirm">Confirme a nova senha</Label>
          <Input id="confirm" name="confirm" type="password" autoComplete="new-password" required />
        </div>
        {mismatch && <p className="text-sm text-destructive">As senhas não conferem.</p>}
        {change.isError && <p className="text-sm text-destructive">{errorMessage(change.error)}</p>}
        <Button type="submit" className="w-full" disabled={change.isPending}>
          Salvar
        </Button>
      </form>
    </AuthCard>
  )
}
```

- [ ] **Step 8: Layout `_auth` (ainda sem header) e `/`**

`web/src/routes/_auth.tsx`:

```tsx
import { Outlet, createFileRoute, redirect } from '@tanstack/react-router'
import { ApiError } from '@/lib/api'
import { meQuery } from '@/lib/auth'

export const Route = createFileRoute('/_auth')({
  beforeLoad: async ({ context, location }) => {
    try {
      const me = await context.queryClient.ensureQueryData(meQuery)
      if (me.must_change_password) throw redirect({ to: '/trocar-senha' })
      return { me }
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) throw redirect({ to: '/login', search: { redirect: location.href } })
      throw e
    }
  },
  component: AuthLayout,
})

function AuthLayout() {
  return (
    <main className="mx-auto max-w-5xl p-6">
      <Outlet />
    </main>
  )
}
```

`web/src/routes/_auth/index.tsx`:

```tsx
import { useSuspenseQuery } from '@tanstack/react-query'
import { Link, createFileRoute, redirect } from '@tanstack/react-router'
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { ROLE_LABELS, meQuery } from '@/lib/auth'

export const Route = createFileRoute('/_auth/')({
  beforeLoad: ({ context: { me } }) => {
    if (!me.is_platform_admin && me.workspaces.length === 1) {
      throw redirect({ to: '/w/$slug', params: { slug: me.workspaces[0].slug } })
    }
  },
  component: Home,
})

function Home() {
  const { data: me } = useSuspenseQuery(meQuery)
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Workspaces</h1>
      {me.workspaces.length === 0 &&
        (me.is_platform_admin ? (
          <p>
            Nenhum workspace ainda.{' '}
            <Link to="/admin/workspaces" className="text-primary underline">
              Criar o primeiro
            </Link>
          </p>
        ) : (
          <p>Você ainda não tem acesso a nenhum workspace. Fale com o administrador.</p>
        ))}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {me.workspaces.map((w) => (
          <Link key={w.slug} to="/w/$slug" params={{ slug: w.slug }}>
            <Card className="transition hover:border-primary hover:shadow-md">
              <CardHeader>
                <CardTitle>{w.name}</CardTitle>
                <p className="text-sm text-muted-foreground">{ROLE_LABELS[w.role]}</p>
              </CardHeader>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  )
}
```

Os links para `/w/$slug` e `/admin/workspaces` só tipam depois que essas rotas existirem (Tasks 4 e 5). Para o build desta task passar, crie já os stubs mínimos:

`web/src/routes/_auth/w/$slug.tsx`:

```tsx
import { Outlet, createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/_auth/w/$slug')({ component: Outlet })
```

`web/src/routes/_auth/admin/workspaces.tsx`:

```tsx
import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/_auth/admin/workspaces')({ component: () => null })
```

- [ ] **Step 9: Build, lint e E2E**

```bash
cd web && bun run lint && bun run e2e
```

Expected: build OK, lint sem erro, `auth.spec.ts` PASS (1 passed).

- [ ] **Step 10: Commit**

```bash
git add web
git commit -m "feat(web): add api client, route guards, login and password change screens"
```

---

### Task 4: Header, tema, workspace e logout

**Files:**
- Create: `web/src/lib/theme.ts`, `web/src/components/AppHeader.tsx`, `web/src/components/NativeSelect.tsx`, `web/src/routes/_auth/w/$slug/index.tsx`
- Modify: `web/src/routes/_auth.tsx`, `web/src/routes/_auth/w/$slug.tsx`, `web/src/main.tsx`
- Test: `web/e2e/auth.spec.ts`

- [ ] **Step 1: Teste de logout (vermelho)**

Acrescente a `web/e2e/auth.spec.ts`:

```ts
test('logout returns to login and protected routes redirect there', async ({ page }) => {
  await loggedInAdmin(page)
  await page.getByRole('button', { name: 'Conta' }).click()
  await page.getByRole('menuitem', { name: 'Sair' }).click()
  await expect(page).toHaveURL(/\/login/)

  await page.goto('/admin/workspaces')
  await expect(page).toHaveURL(/\/login\?redirect=/)
})

test('theme toggle switches to dark and survives a reload', async ({ page }) => {
  await loggedInAdmin(page)
  await page.getByRole('button', { name: 'Tema' }).click()
  await page.getByRole('menuitem', { name: 'Escuro' }).click()
  await expect(page.locator('html')).toHaveClass(/dark/)
  await page.reload()
  await expect(page.locator('html')).toHaveClass(/dark/)
})
```

Run: `cd web && bun run e2e`
Expected: os dois novos FAIL (sem botão `Conta`/`Tema`).

- [ ] **Step 2: `lib/theme.ts`**

```ts
export type Theme = 'light' | 'dark' | 'system'

const KEY = 'theme'
const systemDark = window.matchMedia('(prefers-color-scheme: dark)')

export function getTheme(): Theme {
  try {
    return (localStorage.getItem(KEY) as Theme | null) ?? 'system'
  } catch {
    return 'system'
  }
}

export function applyTheme(theme: Theme = getTheme()) {
  const dark = theme === 'dark' || (theme === 'system' && systemDark.matches)
  document.documentElement.classList.toggle('dark', dark)
}

export function setTheme(theme: Theme) {
  try {
    localStorage.setItem(KEY, theme)
  } catch {
    // private mode: the choice just doesn't persist
  }
  applyTheme(theme)
}

systemDark.addEventListener('change', () => applyTheme())
```

Em `web/src/main.tsx`, adicione o import e chame antes do `createRoot`:

```ts
import { applyTheme } from './lib/theme'
```

```ts
applyTheme()
```

- [ ] **Step 3: `NativeSelect`**

`web/src/components/NativeSelect.tsx`:

```tsx
import type { ComponentProps } from 'react'
import { cn } from '@/lib/utils'

export function NativeSelect({ className, ...props }: ComponentProps<'select'>) {
  return (
    <select
      className={cn(
        'h-9 rounded-md border border-input bg-background px-2 text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring',
        className,
      )}
      {...props}
    />
  )
}
```

- [ ] **Step 4: `AppHeader`**

`web/src/components/AppHeader.tsx`:

```tsx
import { useMutation, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from '@tanstack/react-router'
import { Moon, Sun, User } from 'lucide-react'
import almapDark from '@/assets/logos/almap-negativo.png'
import almapLight from '@/assets/logos/almap-positivo.png'
import dashDark from '@/assets/logos/dash-negativo.png'
import dashLight from '@/assets/logos/dash-positivo.png'
import { NativeSelect } from '@/components/NativeSelect'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { api } from '@/lib/api'
import { meQuery, roleIn } from '@/lib/auth'
import { setTheme } from '@/lib/theme'

function Logo({ light, dark, alt }: { light: string; dark: string; alt: string }) {
  return (
    <>
      <img src={light} alt={alt} className="h-8 w-auto dark:hidden" />
      <img src={dark} alt={alt} className="hidden h-8 w-auto dark:block" />
    </>
  )
}

export function AppHeader() {
  const { data: me } = useSuspenseQuery(meQuery)
  const { slug } = useParams({ strict: false })
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const logout = useMutation({
    mutationFn: () => api('/auth/logout', { method: 'POST' }),
    onSettled: () => {
      queryClient.clear()
      navigate({ to: '/login', search: { redirect: undefined } })
    },
  })

  return (
    <header className="border-b bg-card">
      <div className="mx-auto flex max-w-5xl items-center gap-4 px-6 py-3">
        <Link to="/" className="flex items-center gap-3">
          <Logo light={dashLight} dark={dashDark} alt="DASH" />
          <span className="h-6 w-px bg-border" />
          <Logo light={almapLight} dark={almapDark} alt="AlmapBBDO" />
        </Link>

        {me.workspaces.length > 0 && (
          <NativeSelect
            aria-label="Workspace"
            value={slug ?? ''}
            onChange={(e) => navigate({ to: '/w/$slug', params: { slug: e.target.value } })}
          >
            {!slug && <option value="">Escolha um workspace</option>}
            {me.workspaces.map((w) => (
              <option key={w.slug} value={w.slug}>
                {w.name}
              </option>
            ))}
          </NativeSelect>
        )}

        <nav className="flex gap-4 text-sm">
          {slug && roleIn(me, slug) === 'admin' && (
            <Link to="/w/$slug/membros" params={{ slug }} className="hover:text-primary">
              Membros
            </Link>
          )}
          {me.is_platform_admin && (
            <Link to="/admin/workspaces" className="hover:text-primary">
              Admin
            </Link>
          )}
        </nav>

        <div className="ml-auto flex items-center gap-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" aria-label="Tema">
                <Sun className="dark:hidden" />
                <Moon className="hidden dark:block" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => setTheme('light')}>Claro</DropdownMenuItem>
              <DropdownMenuItem onClick={() => setTheme('dark')}>Escuro</DropdownMenuItem>
              <DropdownMenuItem onClick={() => setTheme('system')}>Sistema</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" aria-label="Conta">
                <User />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>
                {me.name}
                <div className="text-xs font-normal text-muted-foreground">{me.email}</div>
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => navigate({ to: '/trocar-senha' })}>Trocar senha</DropdownMenuItem>
              <DropdownMenuItem onClick={() => logout.mutate()}>Sair</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </header>
  )
}
```

O link `/w/$slug/membros` só tipa depois da Task 6. Crie já o stub `web/src/routes/_auth/w/$slug/membros.tsx`:

```tsx
import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/_auth/w/$slug/membros')({ component: () => null })
```

Se o `DropdownMenuTrigger` gerado pelo shadcn usar `render` em vez de `asChild` (versões com Base UI), siga a API do arquivo gerado em `src/components/ui/dropdown-menu.tsx`.

- [ ] **Step 5: Header no layout**

Em `web/src/routes/_auth.tsx`, troque `AuthLayout` por:

```tsx
function AuthLayout() {
  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-5xl p-6">
        <Outlet />
      </main>
    </div>
  )
}
```

e adicione `import { AppHeader } from '@/components/AppHeader'`.

- [ ] **Step 6: Guarda e home do workspace**

`web/src/routes/_auth/w/$slug.tsx`:

```tsx
import { Outlet, createFileRoute, notFound } from '@tanstack/react-router'

export const Route = createFileRoute('/_auth/w/$slug')({
  beforeLoad: ({ context: { me }, params }) => {
    // same answer as the api: another workspace looks like one that doesn't exist
    if (!me.workspaces.some((w) => w.slug === params.slug)) throw notFound()
  },
  component: Outlet,
})
```

`web/src/routes/_auth/w/$slug/index.tsx`:

```tsx
import { useSuspenseQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { meQuery } from '@/lib/auth'

export const Route = createFileRoute('/_auth/w/$slug/')({ component: WorkspaceHome })

function WorkspaceHome() {
  const { slug } = Route.useParams()
  const { data: me } = useSuspenseQuery(meQuery)
  const workspace = me.workspaces.find((w) => w.slug === slug)!
  return (
    <div className="space-y-2">
      <h1 className="text-2xl font-semibold">{workspace.name}</h1>
      <p className="text-muted-foreground">Nenhuma simulação ainda.</p>
    </div>
  )
}
```

- [ ] **Step 7: Build, lint e E2E**

```bash
cd web && bun run lint && bun run e2e
```

Expected: 3 passed.

- [ ] **Step 8: Commit**

```bash
git add web
git commit -m "feat(web): add app header with workspace switcher, theme toggle and logout"
```

---

### Task 5: Admin de workspaces e usuários

**Files:**
- Create: `web/src/routes/_auth/admin.tsx`, `web/src/routes/_auth/admin/usuarios.tsx`, `web/src/components/TempPasswordDialog.tsx`
- Modify: `web/src/routes/_auth/admin/workspaces.tsx` (substitui o stub)
- Test: `web/e2e/admin.spec.ts`

- [ ] **Step 1: Teste (vermelho)**

`web/e2e/admin.spec.ts`:

```ts
import { expect, test } from '@playwright/test'
import { createAdmin, createWorkspace, loggedInAdmin } from './helpers'

test('platform admin creates a workspace and sees it on the home page', async ({ page }) => {
  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  await page.goto('/')
  await expect(page.getByRole('link', { name: new RegExp(`Marca ${slug}`) })).toBeVisible()
})

test('duplicate slug shows the api message', async ({ page }) => {
  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  await page.getByLabel('Nome').fill('Outra')
  await page.getByLabel('Slug').fill(slug)
  await page.getByRole('button', { name: 'Criar workspace' }).click()
  await expect(page.getByText('Já existe um workspace com esse slug')).toBeVisible()
})

test('platform admin resets a password and sees it once', async ({ page }) => {
  const admin = await loggedInAdmin(page)
  await page.goto('/admin/usuarios')
  const row = page.getByRole('row', { name: new RegExp(admin.email) })
  await expect(row.getByRole('button', { name: 'Desativar' })).toHaveCount(0)

  const other = createAdmin()
  await page.reload()
  await page.getByRole('row', { name: new RegExp(other.email) }).getByRole('button', { name: 'Resetar senha' }).click()
  await page.getByRole('button', { name: 'Resetar', exact: true }).click()
  await expect(page.getByTestId('temp-password')).not.toBeEmpty()
})
```

Run: `cd web && bun run e2e`
Expected: os 3 de `admin.spec.ts` FAIL.

- [ ] **Step 2: `TempPasswordDialog`**

`web/src/components/TempPasswordDialog.tsx`:

```tsx
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

type Props = { password: string | null; email: string; onClose: () => void }

export function TempPasswordDialog({ password, email, onClose }: Props) {
  async function copy() {
    await navigator.clipboard.writeText(password!)
    toast.success('Senha copiada.')
  }

  return (
    <Dialog open={password !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Senha temporária</DialogTitle>
          <DialogDescription>
            Envie para {email} por um canal seguro. Ela não será mostrada de novo e precisa ser trocada no primeiro
            login.
          </DialogDescription>
        </DialogHeader>
        <code data-testid="temp-password" className="block rounded-md bg-muted p-3 text-center font-mono text-lg">
          {password}
        </code>
        <DialogFooter>
          <Button variant="outline" onClick={copy}>
            Copiar
          </Button>
          <Button onClick={onClose}>Fechar</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
```

O `DialogContent` do shadcn tem um botão "Close" (X) com `sr-only` "Close". Se ele colidir com `getByRole('button', { name: 'Fechar' })`, não colide: o nome é diferente.

- [ ] **Step 3: Layout `/admin`**

`web/src/routes/_auth/admin.tsx`:

```tsx
import { Link, Outlet, createFileRoute, notFound } from '@tanstack/react-router'

export const Route = createFileRoute('/_auth/admin')({
  beforeLoad: ({ context: { me } }) => {
    if (!me.is_platform_admin) throw notFound()
  },
  component: AdminLayout,
})

const tab = 'border-b-2 border-transparent pb-2 hover:text-primary'

function AdminLayout() {
  return (
    <div className="space-y-6">
      <nav className="flex gap-6 border-b text-sm">
        <Link to="/admin/workspaces" className={tab} activeProps={{ className: 'border-primary! text-primary' }}>
          Workspaces
        </Link>
        <Link to="/admin/usuarios" className={tab} activeProps={{ className: 'border-primary! text-primary' }}>
          Usuários
        </Link>
      </nav>
      <Outlet />
    </div>
  )
}
```

O link para `/admin/usuarios` precisa da rota do Step 5; escreva os dois antes de buildar.

- [ ] **Step 4: `/admin/workspaces`**

Substitua `web/src/routes/_auth/admin/workspaces.tsx`:

```tsx
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, createFileRoute } from '@tanstack/react-router'
import { type FormEvent, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api } from '@/lib/api'
import { errorMessage, meQuery } from '@/lib/auth'

type Workspace = { id: number; name: string; slug: string; created_at: string }

export const Route = createFileRoute('/_auth/admin/workspaces')({ component: Workspaces })

const slugify = (name: string) =>
  name
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 40)

function Workspaces() {
  const queryClient = useQueryClient()
  const workspaces = useQuery({ queryKey: ['admin', 'workspaces'], queryFn: () => api<Workspace[]>('/admin/workspaces') })
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [slugTouched, setSlugTouched] = useState(false)
  const create = useMutation({
    mutationFn: (body: { name: string; slug: string }) => api<Workspace>('/admin/workspaces', { method: 'POST', body }),
    onSuccess: () => {
      setName('')
      setSlug('')
      setSlugTouched(false)
      queryClient.invalidateQueries({ queryKey: ['admin', 'workspaces'] })
      queryClient.invalidateQueries({ queryKey: meQuery.queryKey })
    },
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    create.mutate({ name, slug })
  }

  return (
    <div className="space-y-6">
      <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
        <div className="space-y-2">
          <Label htmlFor="ws-name">Nome</Label>
          <Input
            id="ws-name"
            value={name}
            required
            onChange={(e) => {
              setName(e.target.value)
              if (!slugTouched) setSlug(slugify(e.target.value))
            }}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="ws-slug">Slug</Label>
          <Input
            id="ws-slug"
            value={slug}
            required
            pattern="[a-z0-9-]{2,40}"
            title="2 a 40 caracteres: letras minúsculas, números e hífen"
            onChange={(e) => {
              setSlug(e.target.value)
              setSlugTouched(true)
            }}
          />
        </div>
        <Button type="submit" disabled={create.isPending}>
          Criar workspace
        </Button>
      </form>
      {create.isError && <p className="text-sm text-destructive">{errorMessage(create.error)}</p>}

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Nome</TableHead>
            <TableHead>Slug</TableHead>
            <TableHead>Criado em</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {workspaces.data?.map((w) => (
            <TableRow key={w.id}>
              <TableCell>{w.name}</TableCell>
              <TableCell>{w.slug}</TableCell>
              <TableCell>{new Date(w.created_at).toLocaleDateString('pt-BR')}</TableCell>
              <TableCell className="text-right">
                <Link to="/w/$slug/membros" params={{ slug: w.slug }} className="text-primary underline">
                  Membros
                </Link>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
```

- [ ] **Step 5: `/admin/usuarios`**

`web/src/routes/_auth/admin/usuarios.tsx`:

```tsx
import { useMutation, useQuery, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'
import { toast } from 'sonner'
import { TempPasswordDialog } from '@/components/TempPasswordDialog'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api } from '@/lib/api'
import { errorMessage, meQuery } from '@/lib/auth'

type User = {
  id: number
  email: string
  name: string
  active: boolean
  is_platform_admin: boolean
  locked_until: string | null
}

export const Route = createFileRoute('/_auth/admin/usuarios')({ component: Users })

const USERS = ['admin', 'users']

function status(u: User) {
  if (!u.active) return 'Inativo'
  if (u.locked_until && new Date(u.locked_until) > new Date()) return 'Bloqueado'
  return 'Ativo'
}

function Users() {
  const { data: me } = useSuspenseQuery(meQuery)
  const queryClient = useQueryClient()
  const users = useQuery({ queryKey: USERS, queryFn: () => api<User[]>('/admin/users') })
  const [temp, setTemp] = useState<{ password: string; email: string } | null>(null)

  const reset = useMutation({
    mutationFn: (u: User) => api<{ temp_password: string }>(`/admin/users/${u.id}/reset-password`, { method: 'POST' }),
    onSuccess: (r, u) => {
      setTemp({ password: r.temp_password, email: u.email })
      queryClient.invalidateQueries({ queryKey: USERS })
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const setActive = useMutation({
    mutationFn: (u: User) => api<User>(`/admin/users/${u.id}`, { method: 'PATCH', body: { active: !u.active } }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: USERS }),
    onError: (e) => toast.error(errorMessage(e)),
  })

  return (
    <>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>E-mail</TableHead>
            <TableHead>Nome</TableHead>
            <TableHead>Status</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {users.data?.map((u) => (
            <TableRow key={u.id}>
              <TableCell>
                {u.email}
                {u.is_platform_admin && <span className="ml-2 text-xs text-primary">platform admin</span>}
              </TableCell>
              <TableCell>{u.name}</TableCell>
              <TableCell>{status(u)}</TableCell>
              <TableCell className="space-x-2 text-right">
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button variant="outline" size="sm">
                      Resetar senha
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>Resetar a senha de {u.email}?</AlertDialogTitle>
                      <AlertDialogDescription>
                        As sessões dessa pessoa caem e ela terá de trocar a senha no próximo login.
                      </AlertDialogDescription>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Cancelar</AlertDialogCancel>
                      <AlertDialogAction onClick={() => reset.mutate(u)}>Resetar</AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
                {u.id !== me.id && (
                  <Button variant="outline" size="sm" onClick={() => setActive.mutate(u)}>
                    {u.active ? 'Desativar' : 'Ativar'}
                  </Button>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <TempPasswordDialog password={temp?.password ?? null} email={temp?.email ?? ''} onClose={() => setTemp(null)} />
    </>
  )
}
```

- [ ] **Step 6: Build, lint e E2E**

```bash
cd web && bun run lint && bun run e2e
```

Expected: 6 passed.

- [ ] **Step 7: Commit**

```bash
git add web
git commit -m "feat(web): add platform admin screens for workspaces and users"
```

---

### Task 6: Membros do workspace

**Files:**
- Modify: `web/src/routes/_auth/w/$slug/membros.tsx` (substitui o stub)
- Test: `web/e2e/members.spec.ts`

- [ ] **Step 1: Testes (vermelho)**

`web/e2e/members.spec.ts`:

```ts
import { expect, test } from '@playwright/test'
import { addMember, changePassword, createWorkspace, loggedInAdmin, login } from './helpers'

test('analyst gets a temp password, logs in and lands on the only workspace', async ({ page, browser }) => {
  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  const other = await createWorkspace(page)
  const analyst = await addMember(page, slug, 'analyst')

  const analystPage = await (await browser.newContext()).newPage()
  await login(analystPage, analyst.email, analyst.temp)
  await changePassword(analystPage, analyst.temp)
  await expect(analystPage).toHaveURL(new RegExp(`/w/${slug}$`))
  await expect(analystPage.getByRole('link', { name: 'Membros' })).toHaveCount(0)
  await expect(analystPage.getByRole('link', { name: 'Admin' })).toHaveCount(0)

  await analystPage.goto(`/w/${other}`)
  await expect(analystPage.getByText('Página não encontrada.')).toBeVisible()
  await analystPage.goto('/admin/workspaces')
  await expect(analystPage.getByText('Página não encontrada.')).toBeVisible()
  await analystPage.goto(`/w/${slug}/membros`)
  await expect(analystPage.getByText('Sem permissão')).toBeVisible()
})

test('five wrong passwords lock the account', async ({ page, browser }) => {
  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  const member = await addMember(page, slug, 'viewer')

  const other = await (await browser.newContext()).newPage()
  for (let i = 0; i < 6; i++) await login(other, member.email, 'senha-errada-123')
  await expect(other.getByText(/Conta bloqueada\. Tente de novo em \d+ min\./)).toBeVisible()
})

test('workspace admin changes a role and removes a member', async ({ page }) => {
  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  const member = await addMember(page, slug, 'viewer')

  const row = page.getByRole('row', { name: new RegExp(member.email) })
  await row.getByLabel('Papel').selectOption('analyst')
  await page.reload()
  await expect(page.getByRole('row', { name: new RegExp(member.email) }).getByLabel('Papel')).toHaveValue('analyst')

  await page.getByRole('row', { name: new RegExp(member.email) }).getByRole('button', { name: 'Remover' }).click()
  await page.getByRole('button', { name: 'Remover', exact: true }).last().click()
  await expect(page.getByRole('row', { name: new RegExp(member.email) })).toHaveCount(0)
})
```

O `login()` do helper espera o clique; entre as tentativas, a página continua em `/login` com a mensagem de erro, e o `goto` recarrega o formulário.

Run: `cd web && bun run e2e`
Expected: os 3 de `members.spec.ts` FAIL.

- [ ] **Step 2: Tela de membros**

Substitua `web/src/routes/_auth/w/$slug/membros.tsx`:

```tsx
import { useMutation, useQuery, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { type FormEvent, useState } from 'react'
import { toast } from 'sonner'
import { NativeSelect } from '@/components/NativeSelect'
import { TempPasswordDialog } from '@/components/TempPasswordDialog'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api } from '@/lib/api'
import { ROLE_LABELS, type Role, errorMessage, meQuery, roleIn } from '@/lib/auth'

type Member = { user_id: number; email: string; name: string; role: Role; active: boolean }
type NewMember = Member & { temp_password: string | null }

export const Route = createFileRoute('/_auth/w/$slug/membros')({ component: Members })

const ROLES = Object.entries(ROLE_LABELS) as [Role, string][]

function Members() {
  const { slug } = Route.useParams()
  const { data: me } = useSuspenseQuery(meQuery)
  if (roleIn(me, slug) !== 'admin') return <p>Sem permissão para gerenciar membros deste workspace.</p>
  return <MemberAdmin slug={slug} />
}

function MemberAdmin({ slug }: { slug: string }) {
  const queryClient = useQueryClient()
  const key = ['members', slug]
  const base = `/w/${slug}/members`
  const members = useQuery({ queryKey: key, queryFn: () => api<Member[]>(base) })
  const [temp, setTemp] = useState<{ password: string; email: string } | null>(null)
  const refresh = () => queryClient.invalidateQueries({ queryKey: key })

  const add = useMutation({
    mutationFn: (body: { email: string; name: string; role: Role }) => api<NewMember>(base, { method: 'POST', body }),
    onSuccess: (m) => {
      refresh()
      if (m.temp_password) setTemp({ password: m.temp_password, email: m.email })
      else toast.success(`${m.email} adicionado.`)
    },
  })
  const changeRole = useMutation({
    mutationFn: ({ id, role }: { id: number; role: Role }) => api(`${base}/${id}`, { method: 'PATCH', body: { role } }),
    onSuccess: refresh,
    onError: (e) => toast.error(errorMessage(e)),
  })
  const remove = useMutation({
    mutationFn: (id: number) => api(`${base}/${id}`, { method: 'DELETE' }),
    onSuccess: refresh,
    onError: (e) => toast.error(errorMessage(e)),
  })

  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const formEl = e.currentTarget
    const form = new FormData(formEl)
    add.mutate(
      { email: String(form.get('email')), name: String(form.get('name')), role: form.get('role') as Role },
      { onSuccess: () => formEl.reset() },
    )
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Membros</h1>
      <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
        <div className="space-y-2">
          <Label htmlFor="m-email">E-mail</Label>
          <Input id="m-email" name="email" type="email" required />
        </div>
        <div className="space-y-2">
          <Label htmlFor="m-name">Nome</Label>
          <Input id="m-name" name="name" required />
        </div>
        <div className="space-y-2">
          <Label htmlFor="m-role">Papel</Label>
          <NativeSelect id="m-role" name="role" defaultValue="analyst">
            {ROLES.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </NativeSelect>
        </div>
        <Button type="submit" disabled={add.isPending}>
          Adicionar
        </Button>
      </form>
      {add.isError && <p className="text-sm text-destructive">{errorMessage(add.error)}</p>}

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>E-mail</TableHead>
            <TableHead>Nome</TableHead>
            <TableHead>Papel</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {members.data?.map((m) => (
            <TableRow key={m.user_id}>
              <TableCell>
                {m.email}
                {!m.active && <span className="ml-2 text-xs text-muted-foreground">inativo</span>}
              </TableCell>
              <TableCell>{m.name}</TableCell>
              <TableCell>
                <NativeSelect
                  aria-label="Papel"
                  value={m.role}
                  onChange={(e) => changeRole.mutate({ id: m.user_id, role: e.target.value as Role })}
                >
                  {ROLES.map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </NativeSelect>
              </TableCell>
              <TableCell className="text-right">
                <AlertDialog>
                  <AlertDialogTrigger asChild>
                    <Button variant="outline" size="sm">
                      Remover
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>Remover {m.email} deste workspace?</AlertDialogTitle>
                    </AlertDialogHeader>
                    <AlertDialogFooter>
                      <AlertDialogCancel>Cancelar</AlertDialogCancel>
                      <AlertDialogAction onClick={() => remove.mutate(m.user_id)}>Remover</AlertDialogAction>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <TempPasswordDialog password={temp?.password ?? null} email={temp?.email ?? ''} onClose={() => setTemp(null)} />
    </div>
  )
}
```

`addMember` do helper sempre cria e-mail novo, então a API sempre devolve `temp_password` e o dialog sempre abre. Usuário já existente entra sem senha nova e só ganha o toast.

- [ ] **Step 3: Build, lint e E2E**

```bash
cd web && bun run lint && bun run e2e
```

Expected: 9 passed.

- [ ] **Step 4: Commit**

```bash
git add web
git commit -m "feat(web): add workspace members screen"
```

---

### Task 7: CI, verificação visual e docs

**Files:**
- Modify: `.github/workflows/ci.yml`, `CLAUDE.md`, `docs/m2/trilha-b-plataforma.md`, `docs/decisoes/auth.md`, `CODE-STYLE.md`

- [ ] **Step 1: Job `e2e` no CI**

Acrescente ao final de `.github/workflows/ci.yml` (no mesmo nível de `py` e `web`):

```yaml
  e2e:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_USER: app
          POSTGRES_PASSWORD: app
          POSTGRES_DB: app
        ports: ["5432:5432"]
        options: >-
          --health-cmd pg_isready
          --health-interval 5s
          --health-timeout 5s
          --health-retries 10
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - uses: oven-sh/setup-bun@v2
      - run: uv sync --frozen
      - run: bun install --frozen-lockfile
        working-directory: web
      - run: bunx playwright install --with-deps chromium
        working-directory: web
      - run: bun run e2e
        working-directory: web
      - if: failure()
        uses: actions/upload-artifact@v4
        with:
          name: playwright-traces
          path: web/test-results
```

No job `web`, depois de `bun run build`, adicione o lint (o CI ainda não roda):

```yaml
      - run: bun run lint
```

- [ ] **Step 2: Verificação visual**

Com `docker compose up -d`, `mise run api` e `mise run web` no ar, crie um admin (`mise run create-admin voce@exemplo.com "Você"`) e, com o MCP `playwright` (ou o navegador), tire screenshot de `/login`, `/trocar-senha`, `/`, `/w/<slug>`, `/w/<slug>/membros`, `/admin/workspaces` e `/admin/usuarios` **nos temas claro e escuro**. Confira: logos trocam com o tema, cores batem com o protótipo, nada renderiza vazio, a 375px de largura nada estoura horizontalmente (o header pode quebrar linha). Corrija o que destoar antes de seguir.

- [ ] **Step 3: Docs**

`CLAUDE.md`:
- Em "Estrutura", troque a linha de `web/src/routes/` por:

```
  src/routes/     rotas file-based; routeTree.gen.ts é gerado mas versionado
  src/lib/        api.ts (fetch + ApiError), auth.ts (meQuery, erros pt-BR), theme.ts
  src/components/ ui/ é do shadcn (gerado por `bunx shadcn@latest add`); o resto é nosso
  e2e/            Playwright contra a app real (banco app_e2e)
```

- Em "Rodando o projeto", depois de `mise run test`, adicione:

```bash
mise run e2e                                        # Playwright: build do web + uvicorn em :8001 + banco app_e2e
```

- Em "Rodando o projeto", passo 5: troque "deve mostrar `API: ok · banco: ok`" por "deve abrir a tela de login".
- Em "Estado atual", troque "Faltam, em ordem: B1b (telas de login, troca de senha, seletor de workspace, admin), B2–B4" por: "**B1b (telas) concluído em <data>**: login, troca de senha obrigatória, seletor de workspace por slug na URL, membros, admin de workspaces e usuários, tema claro/escuro do protótipo (Tailwind + shadcn), E2E Playwright no CI. Faltam, em ordem: B2–B4".

`docs/m2/trilha-b-plataforma.md`, linha `Status` do B1: troque por "✅ feito. B1a (backend) em 21/out/2026, verificado por `tests/api/test_rbac.py`, `test_auth.py` e `test_logging.py`; B1b (telas) em <data>, verificado por `web/e2e/*.spec.ts` (login, troca obrigatória, bloqueio, 404 entre workspaces, papel, admin) e screenshots nos dois temas. Em aberto respondido: reset só pelo admin; contas do protótipo não migram."

`docs/decisoes/auth.md`, ao final:

```markdown
## Guardas do front no `beforeLoad`, lendo `/api/me`

Decisões do B1b, 22/out/2026. Spec: `docs/superpowers/specs/2026-10-22-b1b-auth-telas-design.md`.

O `/api/me` fica no cache do TanStack Query e as rotas `_auth`, `w/$slug` e `admin` decidem no `beforeLoad`, antes de renderizar: sem flash de tela protegida. Slug de workspace fora de `me.workspaces` cai na mesma tela de "não encontrado" de uma rota inexistente, como o 404 da API. Esconder link é só UX; quem barra é a API. Sessão que expira no meio do uso volta como 401 `not_authenticated` em qualquer query ou mutation e um handler global em `main.tsx` manda para o login com `redirect`; o 401 `invalid_credentials` do próprio login não dispara isso.

## Workspace ativo na URL

`/w/$slug/...` espelha `/api/w/{slug}`: link compartilhável e abas em marcas diferentes sem brigar por estado. O seletor do header só navega.

## Tema do protótipo, trocável no B10

Tailwind v4 + shadcn/ui com as cores do Streamlit (primária `#ff4b4b`, Inter), claro e escuro, padrão do sistema com escolha salva no `localStorage`. As cores moram só nos tokens de `web/src/index.css`; trocar pelo design system do Almap Metrics no B10 é trocar esses tokens.
```

`CODE-STYLE.md`, seção "Testes", ao final:

```markdown
- Front: E2E com Playwright em `web/e2e/` contra a app real (`mise run e2e`, banco `app_e2e`). Cada teste cria os próprios usuários e workspaces com sufixo aleatório; nada de depender de ordem ou de limpar o banco. Sem testes de componente por ora.
```

- [ ] **Step 4: Rodar tudo**

```bash
mise run test
cd web && bun run lint && bun run e2e
```

Expected: pytest verde; lint limpo; 9 passed.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/ci.yml CLAUDE.md docs CODE-STYLE.md
git commit -m "docs: record b1b screens, e2e job and front-end auth decisions"
```

- [ ] **Step 6: Push e CI**

```bash
git push -u origin b1b-telas
gh run watch
```

Expected: jobs `py`, `web` e `e2e` verdes. Depois, `superpowers:finishing-a-development-branch`.
