# B2b · Telas de upload, mapeamento e validação Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O analista cria uma simulação, sobe os CSVs (com drag & drop), confirma o mapeamento sugerido e vê o `ValidationReport` com o botão Rodar desabilitado e o motivo, tudo sobre as 5 rotas do B2a.

**Architecture:** Três rotas novas no TanStack Router (`/w/$slug/` vira a lista, `simulacoes/nova`, `simulacoes/$id`). `lib/simulations.ts` concentra tipos, query options e as regras de tela (pré-preenchimento do mapping, motivo do Rodar desabilitado). As mutations recebem o `SimulationOut` da API e gravam direto no cache com `setQueryData`, sem refetch. Nenhuma rota nova na API.

**Tech Stack:** React 19, TypeScript 6, TanStack Router/Query, Tailwind v4, shadcn (estilo `radix-nova`: `alert`, `badge` e `checkbox` novos), dropzone adaptado do `@blocks-so/file-upload-04`, lucide, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-26-b2-upload-validacao-design.md`, seção B2b. A API está em `api/routes/simulations.py` (B2a, já na branch).

**Branch:** `b2-upload` (a mesma do B2a). Comandos de front rodam em `web/`, os demais na raiz.

**Pré-requisito:** `docker compose up -d` (Postgres em `:5432`). O E2E usa o banco `app_e2e`, criado pelo `globalSetup`.

**Cuidado:** não rode `mise run web` enquanto cria arquivos em `web/src/routes/`: o gerador do TanStack Router reescreve arquivo vazio com placeholder. Use Write/Edit, nunca heredoc. Depois de criar rota nova, rode `cd web && bunx vite build` uma vez antes do `bun run build` (o `tsc -b` roda antes de o plugin regenerar o `routeTree.gen.ts`, que é versionado: commite junto).

**Shell:** paths com `$slug`/`$id` vão entre aspas simples em qualquer comando (`'web/src/routes/_auth/w/$slug/index.tsx'`); sem aspas o shell expande `$slug` para vazio.

**Convenções:** UI em pt-BR; código, nomes de teste e commits em inglês (`CODE-STYLE.md`). `bun`/`bunx`, nunca npm. A matemática fica no Python: o front só exibe o report, não recalcula nada.

**Decisões tomadas com o usuário (26/out/2026):**
- Seams de teste: só os 3 E2E da spec, em `web/e2e/simulations.spec.ts`. O bloco de avisos (warning + checkbox) fica sem E2E: o `validate` falso só gera `error`.
- Pré-preenchimento do mapping: o salvo em `config.column_mapping` se a coluna ainda existe no arquivo, senão o `suggested`. O backend não muda (um re-upload mantém o mapping antigo).
- O upload dispara ao escolher ou soltar o arquivo, sem botão.
- Componentes: shadcn `alert` + `badge` + `checkbox` e o dropzone do blocks.so (`file-upload-04`, sem a barra de progresso fake). Stack registrado no `CLAUDE.md` (Task 4); ícones, tema e fontes ficam até o B10.

---

## Mapa de arquivos

| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `web/src/components/ui/alert.tsx`, `badge.tsx`, `checkbox.tsx` | criar (shadcn) | primitivos |
| `web/src/lib/api.ts` | modificar | `FormData` vai sem `Content-Type` e sem `JSON.stringify` |
| `web/src/lib/auth.ts` | modificar | `errorMessage`: 422 com `detail` em texto mostra o texto da API |
| `web/src/lib/simulations.ts` | criar | tipos, `FILES`, query options, `initialColumn`, `runBlockReason`, formatação |
| `web/src/components/FileDrop.tsx` | criar | área de drag & drop + `<input type=file>` |
| `web/public/templates/{investimento,performance,trends}.csv` | criar | templates para download |
| `web/src/routes/_auth/w/$slug/index.tsx` | modificar | lista de simulações |
| `web/src/routes/_auth/w/$slug/simulacoes/nova.tsx` | criar | formulário de nome |
| `web/src/routes/_auth/w/$slug/simulacoes/$id.tsx` | criar | arquivos, mapeamento, validação |
| `web/src/routeTree.gen.ts` | regenerado | — |
| `web/e2e/env.ts` | modificar | `STORAGE_DIR` em diretório temporário |
| `web/e2e/helpers.ts` | modificar | `newSession` |
| `web/e2e/simulations.spec.ts` | criar | 3 cenários |
| `CLAUDE.md`, `docs/m2/trilha-b-plataforma.md`, `docs/decisoes/upload-e-storage.md` | modificar | Task 4 |

---

### Task 1: Base (primitivos, api, lib, dropzone, templates, E2E env)

Sem teste próprio: tudo aqui é exercitado pelos E2E das Tasks 2 e 3. A verificação é `build` + `lint`.

**Files:**
- Create: `web/src/components/ui/alert.tsx`, `badge.tsx`, `checkbox.tsx` (via shadcn)
- Modify: `web/src/lib/api.ts`, `web/src/lib/auth.ts`, `web/e2e/env.ts`, `web/e2e/helpers.ts`
- Create: `web/src/lib/simulations.ts`, `web/src/components/FileDrop.tsx`, `web/public/templates/investimento.csv`, `web/public/templates/performance.csv`, `web/public/templates/trends.csv`

- [ ] **Step 1: Primitivos do shadcn**

Run: `cd web && bunx shadcn@latest add alert badge checkbox --yes`
Expected: cria `src/components/ui/alert.tsx`, `badge.tsx` e `checkbox.tsx`. Nenhuma dependência nova no `package.json` (usam `radix-ui`, `class-variance-authority` e `lucide-react`, já instalados). Se o CLI perguntar se sobrescreve algum arquivo existente, responda **não**. Confira com `git status` que só os 3 arquivos apareceram (e talvez `components.json` intacto).

- [ ] **Step 2: `api()` aceita `FormData`**

Em `web/src/lib/api.ts`, troque a função `api` por:

```ts
export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  // FormData sets its own multipart Content-Type with the boundary
  const json = init.body !== undefined && !(init.body instanceof FormData)
  const r = await fetch(`/api${path}`, {
    method: init.method ?? 'GET',
    headers: json ? { 'Content-Type': 'application/json' } : undefined,
    body: json ? JSON.stringify(init.body) : (init.body as FormData | undefined),
  })
  if (r.status === 204) return undefined as T
  const body = await r.json().catch(() => ({}))
  if (!r.ok) throw new ApiError(r.status, body)
  return body as T
}
```

- [ ] **Step 3: 422 com texto da API**

Em `web/src/lib/auth.ts`, dentro de `errorMessage`, troque:

```ts
  if (error.status === 422) return 'Dados inválidos.'
```

por:

```ts
  // pydantic's 422 has a list in `detail`; ours (upload, mapping) is already a pt-BR sentence
  if (error.status === 422 && typeof error.body.detail !== 'string') return 'Dados inválidos.'
```

(O 422 com texto cai no `return error.detail` do fim. Os códigos `password_unchanged` e `name_required` continuam traduzidos pelo `MESSAGES`, que vem antes. O 413 já cai no `return error.detail` com "Arquivo maior que 30 MB.")

- [ ] **Step 4: `lib/simulations.ts`**

Create `web/src/lib/simulations.ts`:

```ts
import { queryOptions } from '@tanstack/react-query'
import { api } from './api'

export type FileKind = 'investment' | 'performance' | 'trends'

export type SimulationFile = {
  filename: string
  size_bytes: number
  sha256: string
  columns: string[]
  suggested: Record<string, string | null>
  uploaded_at: string
}

export type Check = { id: string; level: 'error' | 'warning' | 'info'; message: string; details?: unknown }

export type ValidationReport = {
  ok: boolean
  cadence: string | null
  period_days: number | null
  date_range: [string, string] | null
  channels: string[]
  checks: Check[]
  collinearity: unknown
}

// EngineConfig.column_mapping: {investment_file: {date_col: "data", ...}, ...}
export type ColumnMapping = Record<string, Record<string, string>>

export type Simulation = {
  id: number
  name: string
  config: { column_mapping?: ColumnMapping }
  validation: ValidationReport | null
  files: Record<FileKind, SimulationFile | null>
}

export type SimulationSummary = {
  id: number
  name: string
  created_by_name: string
  created_at: string
  updated_at: string
}

export type FileSpec = { kind: FileKind; key: string; label: string; template: string; optional: boolean }

// key = the column_mapping key the API expects for that file
export const FILES: FileSpec[] = [
  { kind: 'investment', key: 'investment_file', label: 'Investimento', template: '/templates/investimento.csv', optional: false },
  { kind: 'performance', key: 'performance_file', label: 'Performance', template: '/templates/performance.csv', optional: false },
  { kind: 'trends', key: 'generic_trends_file', label: 'Trends', template: '/templates/trends.csv', optional: true },
]

// the fields of each file come from the API (keys of `suggested`); only their labels live here
export const FIELD_LABELS: Record<string, string> = {
  date_col: 'Data',
  channel_col: 'Canal',
  investment_col: 'Investimento',
  kpi_col: 'KPI',
  trends_col: 'Trends',
}

export const LEVEL_LABELS: Record<Check['level'], string> = { error: 'Erro', warning: 'Aviso', info: 'Informação' }

export const simulationsQuery = (slug: string) =>
  queryOptions({
    queryKey: ['simulations', slug],
    queryFn: () => api<SimulationSummary[]>(`/w/${slug}/simulations`),
  })

export const simulationQuery = (slug: string, id: string) =>
  queryOptions({
    queryKey: ['simulations', slug, id],
    queryFn: () => api<Simulation>(`/w/${slug}/simulations/${id}`),
  })

// a re-upload keeps the saved mapping, which may point at a column the new file no longer has
export function initialColumn(sim: Simulation, spec: FileSpec, field: string): string {
  const file = sim.files[spec.kind]!
  const saved = sim.config.column_mapping?.[spec.key]?.[field]
  return saved && file.columns.includes(saved) ? saved : (file.suggested[field] ?? '')
}

// display only: B4 creates the run and checks the same gate on the server
export function runBlockReason(report: ValidationReport | null, confirmed: Set<number>): string {
  if (!report) return 'Valide os arquivos antes de rodar.'
  if (!report.ok) return 'Corrija os erros antes de rodar.'
  if (report.checks.some((c, i) => c.level === 'warning' && !confirmed.has(i))) return 'Confirme os avisos antes de rodar.'
  return 'Execução disponível em breve'
}

export const formatDate = (iso: string) =>
  new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })

export const formatSize = (bytes: number) =>
  bytes < 1024 * 1024
    ? `${Math.max(1, Math.round(bytes / 1024))} KB`
    : `${(bytes / 1024 / 1024).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} MB`
```

- [ ] **Step 5: Dropzone**

Create `web/src/components/FileDrop.tsx`:

```tsx
import { FileSpreadsheet } from 'lucide-react'
import type { DragEvent } from 'react'
import { cn } from '@/lib/utils'

// drag & drop area adapted from blocks.so file-upload-04, minus its fake progress bar
export function FileDrop({
  id,
  label,
  disabled,
  onFile,
}: {
  id: string
  label: string
  disabled?: boolean
  onFile: (file: File) => void
}) {
  function drop(e: DragEvent) {
    e.preventDefault()
    const file = e.dataTransfer.files[0]
    if (file && !disabled) onFile(file)
  }

  return (
    <div
      onDragOver={(e) => e.preventDefault()}
      onDrop={drop}
      className={cn(
        'flex flex-col items-center gap-2 rounded-md border border-dashed border-input px-4 py-6 text-center text-sm text-muted-foreground',
        disabled && 'opacity-50',
      )}
    >
      <FileSpreadsheet aria-hidden className="size-8" />
      <p>
        Arraste o CSV ou{' '}
        <label htmlFor={id} className="cursor-pointer font-medium text-primary hover:underline">
          escolha o arquivo
        </label>
      </p>
      <p className="text-xs">Até 30 MB</p>
      <input
        id={id}
        type="file"
        accept=".csv"
        aria-label={label}
        className="sr-only"
        disabled={disabled}
        onChange={(e) => {
          const file = e.target.files?.[0]
          // lets the same file be picked again after a failed upload
          e.target.value = ''
          if (file) onFile(file)
        }}
      />
    </div>
  )
}
```

- [ ] **Step 6: Templates**

Create `web/public/templates/investimento.csv`:

```
data,canal,investimento
2024-01-01,SEARCH,1000
2024-01-01,YOUTUBE,500
2024-01-02,SEARCH,1200
```

Create `web/public/templates/performance.csv`:

```
data,conversoes
2024-01-01,35
2024-01-02,41
2024-01-03,38
```

Create `web/public/templates/trends.csv`:

```
data,trends
2024-01-01,40
2024-01-02,42
2024-01-03,39
```

(O Vite copia `public/` para `dist/`; o `mount_spa` da API serve qualquer arquivo de `dist/`, então `/templates/*.csv` funciona no dev e no E2E. Trocados pelos oficiais quando o Data Analytics entregar.)

- [ ] **Step 7: E2E não grava no `./data` do repo**

Em `web/e2e/env.ts`, troque o conteúdo por:

```ts
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'

export const ROOT = fileURLToPath(new URL('../..', import.meta.url))
export const PORT = 8001
export const DATABASE_URL =
  process.env.E2E_DATABASE_URL ?? 'postgresql+psycopg://app:app@localhost:5432/app_e2e'
// uploads from the E2E server go to a temp dir, never the repo's ./data
export const pyEnv = {
  ...process.env,
  DATABASE_URL,
  PYTHONIOENCODING: 'utf-8',
  STORAGE_DIR: join(tmpdir(), 'gem-e2e-storage'),
}
```

- [ ] **Step 8: Helper `newSession`**

Em `web/e2e/helpers.ts`, troque `import { expect, type Page } from '@playwright/test'` por `import { type Browser, expect, type Page } from '@playwright/test'` e adicione no fim:

```ts
export async function newSession(browser: Browser, user: { email: string; temp: string }) {
  const page = await (await browser.newContext()).newPage()
  await login(page, user.email, user.temp)
  await changePassword(page, user.temp)
  return page
}
```

- [ ] **Step 9: Build e lint**

Run: `cd web && bun run build && bun run lint`
Expected: sem erro (o oxlint pode avisar de export sem uso, não de erro).

- [ ] **Step 10: Commit**

```bash
git add web/src/components/ui/alert.tsx web/src/components/ui/badge.tsx web/src/components/ui/checkbox.tsx web/src/lib/api.ts web/src/lib/auth.ts web/src/lib/simulations.ts web/src/components/FileDrop.tsx web/public/templates web/e2e/env.ts web/e2e/helpers.ts
git commit -m "feat(web): add simulation types, csv dropzone, templates and multipart api calls"
```

---

### Task 2: Lista, nova simulação e guarda do viewer

**Files:**
- Create: `web/e2e/simulations.spec.ts`
- Modify: `web/src/routes/_auth/w/$slug/index.tsx`
- Create: `web/src/routes/_auth/w/$slug/simulacoes/nova.tsx`, `web/src/routes/_auth/w/$slug/simulacoes/$id.tsx` (só o cabeçalho; os blocos vêm na Task 3)
- Modify: `web/src/routeTree.gen.ts` (regenerado)

- [ ] **Step 1: E2E que falham**

Create `web/e2e/simulations.spec.ts`:

```ts
import { type Browser, expect, type Page, test } from '@playwright/test'
import { addMember, createWorkspace, loggedInAdmin, newSession } from './helpers'

async function analystOnNewWorkspace(page: Page, browser: Browser) {
  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  const analyst = await addMember(page, slug, 'analyst')
  return { slug, analystPage: await newSession(browser, analyst) }
}

async function createSimulation(page: Page, slug: string, name: string) {
  await page.goto(`/w/${slug}`)
  await page.getByRole('link', { name: 'Nova simulação' }).click()
  await page.getByLabel('Nome').fill(name)
  await page.getByRole('button', { name: 'Criar' }).click()
  await expect(page.getByRole('heading', { name })).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`/w/${slug}/simulacoes/\\d+$`))
}

test('analyst creates a simulation and finds it in the list', async ({ page, browser }) => {
  const { slug, analystPage } = await analystOnNewWorkspace(page, browser)
  await expect(analystPage.getByText('Nenhuma simulação ainda.')).toBeVisible()

  await createSimulation(analystPage, slug, 'Black Friday')

  await analystPage.getByRole('link', { name: '← Simulações' }).click()
  await expect(analystPage.getByRole('link', { name: 'Black Friday' })).toBeVisible()
})

test('viewer cannot create or edit simulations', async ({ page, browser }) => {
  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  const viewer = await addMember(page, slug, 'viewer')

  const viewerPage = await newSession(browser, viewer)
  await expect(viewerPage).toHaveURL(new RegExp(`/w/${slug}$`))
  await expect(viewerPage.getByText('Nenhuma simulação ainda.')).toBeVisible()
  await expect(viewerPage.getByRole('link', { name: 'Nova simulação' })).toHaveCount(0)

  await viewerPage.goto(`/w/${slug}/simulacoes/nova`)
  await expect(viewerPage.getByText('Sem permissão para editar simulações deste workspace.')).toBeVisible()
})
```

(O primeiro teste é a metade "criar" do fluxo feliz; a Task 3 estende ele com upload e validação.)

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd web && bun run build && bunx playwright test e2e/simulations.spec.ts`
Expected: FAIL nos dois — não existe link "Nova simulação" e `/simulacoes/nova` mostra "Página não encontrada.".

- [ ] **Step 3: Lista**

Troque o conteúdo de `web/src/routes/_auth/w/$slug/index.tsx` por:

```tsx
import { useQuery, useSuspenseQuery } from '@tanstack/react-query'
import { Link, createFileRoute } from '@tanstack/react-router'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { meQuery } from '@/lib/auth'
import { formatDate, simulationsQuery } from '@/lib/simulations'

export const Route = createFileRoute('/_auth/w/$slug/')({ component: WorkspaceHome })

function WorkspaceHome() {
  const { slug } = Route.useParams()
  const { data: me } = useSuspenseQuery(meQuery)
  const workspace = me.workspaces.find((w) => w.slug === slug)!
  // the list route is analyst+ in the api, so a viewer never asks for it
  const canEdit = workspace.role !== 'viewer'
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold">{workspace.name}</h1>
        {canEdit && (
          <Button asChild>
            <Link to="/w/$slug/simulacoes/nova" params={{ slug }}>
              Nova simulação
            </Link>
          </Button>
        )}
      </div>
      {canEdit ? <SimulationList slug={slug} /> : <p className="text-muted-foreground">Nenhuma simulação ainda.</p>}
    </div>
  )
}

function SimulationList({ slug }: { slug: string }) {
  const { data } = useQuery(simulationsQuery(slug))
  if (!data) return null
  if (data.length === 0) return <p className="text-muted-foreground">Nenhuma simulação ainda.</p>
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Nome</TableHead>
          <TableHead>Criada por</TableHead>
          <TableHead>Atualizada em</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.map((s) => (
          <TableRow key={s.id}>
            <TableCell>
              <Link
                to="/w/$slug/simulacoes/$id"
                params={{ slug, id: String(s.id) }}
                className="font-medium hover:text-primary"
              >
                {s.name}
              </Link>
            </TableCell>
            <TableCell>{s.created_by_name}</TableCell>
            <TableCell>{formatDate(s.updated_at)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
```

- [ ] **Step 4: Nova simulação**

Create `web/src/routes/_auth/w/$slug/simulacoes/nova.tsx`:

```tsx
import { useMutation, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import type { FormEvent } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import { errorMessage, meQuery, roleIn } from '@/lib/auth'
import { type Simulation, simulationQuery, simulationsQuery } from '@/lib/simulations'

export const Route = createFileRoute('/_auth/w/$slug/simulacoes/nova')({ component: NewSimulation })

function NewSimulation() {
  const { slug } = Route.useParams()
  const { data: me } = useSuspenseQuery(meQuery)
  if (roleIn(me, slug) === 'viewer') return <p>Sem permissão para editar simulações deste workspace.</p>
  return <NewSimulationForm slug={slug} />
}

function NewSimulationForm({ slug }: { slug: string }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const create = useMutation({
    mutationFn: (name: string) => api<Simulation>(`/w/${slug}/simulations`, { method: 'POST', body: { name } }),
    onSuccess: (sim) => {
      const id = String(sim.id)
      queryClient.setQueryData(simulationQuery(slug, id).queryKey, sim)
      queryClient.invalidateQueries({ queryKey: simulationsQuery(slug).queryKey, exact: true })
      navigate({ to: '/w/$slug/simulacoes/$id', params: { slug, id } })
    },
  })

  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    create.mutate(String(new FormData(e.currentTarget).get('name')))
  }

  return (
    <form onSubmit={submit} className="max-w-md space-y-4">
      <h1 className="text-2xl font-semibold">Nova simulação</h1>
      <div className="space-y-2">
        <Label htmlFor="sim-name">Nome</Label>
        <Input id="sim-name" name="name" required maxLength={120} />
      </div>
      {create.isError && (
        <p role="alert" className="text-sm text-destructive">
          {errorMessage(create.error)}
        </p>
      )}
      <Button type="submit" disabled={create.isPending}>
        Criar
      </Button>
    </form>
  )
}
```

- [ ] **Step 5: Detalhe (só cabeçalho)**

Create `web/src/routes/_auth/w/$slug/simulacoes/$id.tsx`:

```tsx
import { useQuery, useSuspenseQuery } from '@tanstack/react-query'
import { Link, createFileRoute } from '@tanstack/react-router'
import { meQuery, roleIn } from '@/lib/auth'
import { simulationQuery } from '@/lib/simulations'

export const Route = createFileRoute('/_auth/w/$slug/simulacoes/$id')({ component: SimulationPage })

function SimulationPage() {
  const { slug, id } = Route.useParams()
  const { data: me } = useSuspenseQuery(meQuery)
  if (roleIn(me, slug) === 'viewer') return <p>Sem permissão para editar simulações deste workspace.</p>
  return <SimulationDetail slug={slug} id={id} />
}

function SimulationDetail({ slug, id }: { slug: string; id: string }) {
  const { data: sim, isError } = useQuery(simulationQuery(slug, id))
  // 404 (another workspace or deleted) and 422 (non-numeric id) look the same to the user
  if (isError) return <p>Simulação não encontrada.</p>
  if (!sim) return null
  return (
    <div className="space-y-8">
      <div className="space-y-1">
        <Link to="/w/$slug" params={{ slug }} className="text-sm text-muted-foreground hover:text-primary">
          ← Simulações
        </Link>
        <h1 className="text-2xl font-semibold">{sim.name}</h1>
      </div>
    </div>
  )
}
```

- [ ] **Step 6: Regenerar rotas, rodar e ver passar**

Run: `cd web && bunx vite build && bun run build && bunx playwright test e2e/simulations.spec.ts`
Expected: PASS (2 testes). `src/routeTree.gen.ts` mudou.

- [ ] **Step 7: Suíte E2E inteira e lint**

Run: `cd web && bun run lint && bunx playwright test`
Expected: tudo verde (os specs do B1b continuam passando com a lista nova em `/w/$slug`).

- [ ] **Step 8: Commit**

```bash
git add web/e2e/simulations.spec.ts 'web/src/routes/_auth/w/$slug/index.tsx' 'web/src/routes/_auth/w/$slug/simulacoes' web/src/routeTree.gen.ts
git commit -m "feat(web): list and create simulations, viewer sees no edit controls"
```

---

### Task 3: Detalhe — arquivos, mapeamento e validação

**Files:**
- Modify: `web/e2e/simulations.spec.ts`
- Modify: `web/src/routes/_auth/w/$slug/simulacoes/$id.tsx`

- [ ] **Step 1: E2E que falham**

Em `web/e2e/simulations.spec.ts`, troque a primeira linha de import por:

```ts
import { fileURLToPath } from 'node:url'
import { type Browser, expect, type Page, test } from '@playwright/test'
```

Abaixo dos imports, adicione:

```ts
const template = (name: string) => fileURLToPath(new URL(`../public/templates/${name}`, import.meta.url))
```

Troque o teste `analyst creates a simulation and finds it in the list` por:

```ts
test('analyst uploads the templates, accepts the suggested mapping and validates', async ({ page, browser }) => {
  const { slug, analystPage } = await analystOnNewWorkspace(page, browser)
  await expect(analystPage.getByText('Nenhuma simulação ainda.')).toBeVisible()
  await createSimulation(analystPage, slug, 'Black Friday')

  await analystPage.getByLabel('Arquivo de investimento').setInputFiles(template('investimento.csv'))
  await expect(analystPage.getByText('investimento.csv', { exact: true })).toBeVisible()
  await analystPage.getByLabel('Arquivo de performance').setInputFiles(template('performance.csv'))
  await expect(analystPage.getByText('performance.csv', { exact: true })).toBeVisible()
  await expect(analystPage.getByRole('button', { name: 'Rodar' })).toBeDisabled()
  await expect(analystPage.getByText('Valide os arquivos antes de rodar.')).toBeVisible()

  await analystPage.getByRole('button', { name: 'Validar' }).click()

  await expect(analystPage.getByText('Nenhum problema encontrado.')).toBeVisible()
  await expect(analystPage.getByText('SEARCH, YOUTUBE')).toBeVisible()
  await expect(analystPage.getByRole('button', { name: 'Rodar' })).toBeDisabled()
  await expect(analystPage.getByText('Execução disponível em breve')).toBeVisible()

  await analystPage.getByRole('link', { name: '← Simulações' }).click()
  await expect(analystPage.getByRole('link', { name: 'Black Friday' })).toBeVisible()
})

test('a repeated (date, channel) row shows the pt-BR error and blocks the run', async ({ page, browser }) => {
  const { slug, analystPage } = await analystOnNewWorkspace(page, browser)
  await createSimulation(analystPage, slug, 'Duplicada')

  await analystPage.getByLabel('Arquivo de investimento').setInputFiles({
    name: 'investimento.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from('data,canal,investimento\n2024-01-01,SEARCH,100\n2024-01-01,SEARCH,30\n'),
  })
  await expect(analystPage.getByText('investimento.csv', { exact: true })).toBeVisible()
  await analystPage.getByLabel('Arquivo de performance').setInputFiles(template('performance.csv'))
  await expect(analystPage.getByText('performance.csv', { exact: true })).toBeVisible()
  await analystPage.getByRole('button', { name: 'Validar' }).click()

  await expect(analystPage.getByText('1 linha repetida de (data, canal) no investimento')).toBeVisible()
  await expect(analystPage.getByRole('button', { name: 'Rodar' })).toBeDisabled()
  await expect(analystPage.getByText('Corrija os erros antes de rodar.')).toBeVisible()
})
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd web && bun run build && bunx playwright test e2e/simulations.spec.ts`
Expected: FAIL nos dois novos (não existe o campo "Arquivo de investimento"); o do viewer passa.

- [ ] **Step 3: Detalhe completo**

Troque o conteúdo de `web/src/routes/_auth/w/$slug/simulacoes/$id.tsx` por:

```tsx
import { useMutation, useQuery, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { Link, createFileRoute } from '@tanstack/react-router'
import { CircleX, Info, TriangleAlert } from 'lucide-react'
import { type FormEvent, useState } from 'react'
import { FileDrop } from '@/components/FileDrop'
import { NativeSelect } from '@/components/NativeSelect'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import { errorMessage, meQuery, roleIn } from '@/lib/auth'
import {
  type Check,
  type ColumnMapping,
  FIELD_LABELS,
  FILES,
  type FileSpec,
  LEVEL_LABELS,
  type Simulation,
  type ValidationReport,
  formatDate,
  formatSize,
  initialColumn,
  runBlockReason,
  simulationQuery,
  simulationsQuery,
} from '@/lib/simulations'

export const Route = createFileRoute('/_auth/w/$slug/simulacoes/$id')({ component: SimulationPage })

const LEVEL_ICONS: Record<Check['level'], typeof Info> = { error: CircleX, warning: TriangleAlert, info: Info }

function SimulationPage() {
  const { slug, id } = Route.useParams()
  const { data: me } = useSuspenseQuery(meQuery)
  if (roleIn(me, slug) === 'viewer') return <p>Sem permissão para editar simulações deste workspace.</p>
  return <SimulationDetail slug={slug} id={id} />
}

function SimulationDetail({ slug, id }: { slug: string; id: string }) {
  const queryClient = useQueryClient()
  const query = simulationQuery(slug, id)
  const { data: sim, isError } = useQuery(query)
  // 404 (another workspace or deleted) and 422 (non-numeric id) look the same to the user
  if (isError) return <p>Simulação não encontrada.</p>
  if (!sim) return null

  // every mutation answers with the whole SimulationOut, so the cache is set instead of refetched
  const saved = (next: Simulation) => {
    queryClient.setQueryData(query.queryKey, next)
    queryClient.invalidateQueries({ queryKey: simulationsQuery(slug).queryKey, exact: true })
  }
  // a new file resets the mapping form to that file's columns
  const filesKey = FILES.map((f) => sim.files[f.kind]?.sha256).join()

  return (
    <div className="space-y-8">
      <div className="space-y-1">
        <Link to="/w/$slug" params={{ slug }} className="text-sm text-muted-foreground hover:text-primary">
          ← Simulações
        </Link>
        <h1 className="text-2xl font-semibold">{sim.name}</h1>
      </div>

      <section className="space-y-3">
        <h2 className="text-lg font-medium">Arquivos</h2>
        <div className="grid gap-4 md:grid-cols-3">
          {FILES.map((spec) => (
            <FileCard key={spec.kind} slug={slug} sim={sim} spec={spec} onSaved={saved} />
          ))}
        </div>
      </section>

      {sim.files.investment && sim.files.performance && (
        <MappingForm key={filesKey} slug={slug} sim={sim} onSaved={saved} />
      )}

      <ValidationBlock key={JSON.stringify(sim.validation)} report={sim.validation} />
    </div>
  )
}

function FileCard({
  slug,
  sim,
  spec,
  onSaved,
}: {
  slug: string
  sim: Simulation
  spec: FileSpec
  onSaved: (sim: Simulation) => void
}) {
  const file = sim.files[spec.kind]
  const upload = useMutation({
    mutationFn: (f: File) => {
      const body = new FormData()
      body.append('file', f)
      return api<Simulation>(`/w/${slug}/simulations/${sim.id}/files/${spec.kind}`, { method: 'PUT', body })
    },
    onSuccess: onSaved,
  })

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {spec.label}
          {spec.optional && <Badge variant="secondary">opcional</Badge>}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <FileDrop
          id={`file-${spec.kind}`}
          label={`Arquivo de ${spec.label.toLowerCase()}`}
          disabled={upload.isPending}
          onFile={(f) => upload.mutate(f)}
        />
        {file && (
          <p className="text-xs text-muted-foreground">
            <span className="font-medium text-foreground">{file.filename}</span> · {formatSize(file.size_bytes)} ·{' '}
            {formatDate(file.uploaded_at)}
          </p>
        )}
        {upload.isError && (
          <p role="alert" className="text-sm text-destructive">
            {errorMessage(upload.error)}
          </p>
        )}
        <a href={spec.template} download className="text-sm text-primary hover:underline">
          Baixar template
        </a>
      </CardContent>
    </Card>
  )
}

function MappingForm({ slug, sim, onSaved }: { slug: string; sim: Simulation; onSaved: (sim: Simulation) => void }) {
  const save = useMutation({
    mutationFn: (body: ColumnMapping) =>
      api<Simulation>(`/w/${slug}/simulations/${sim.id}/mapping`, { method: 'PUT', body }),
    onSuccess: onSaved,
  })
  const uploaded = FILES.filter((spec) => sim.files[spec.kind])

  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    const mapping: ColumnMapping = {}
    for (const spec of uploaded) {
      const fields = Object.keys(sim.files[spec.kind]!.suggested)
      mapping[spec.key] = Object.fromEntries(fields.map((field) => [field, String(form.get(`${spec.key}.${field}`))]))
    }
    save.mutate(mapping)
  }

  return (
    <section className="space-y-3">
      <h2 className="text-lg font-medium">Mapeamento de colunas</h2>
      <form onSubmit={submit} className="space-y-4">
        {uploaded.map((spec) => {
          const file = sim.files[spec.kind]!
          return (
            <fieldset key={spec.kind} className="space-y-2">
              <legend className="text-sm font-medium">{spec.label}</legend>
              <div className="flex flex-wrap gap-4">
                {Object.keys(file.suggested).map((field) => {
                  const id = `${spec.key}.${field}`
                  return (
                    <div key={field} className="space-y-1">
                      <Label htmlFor={id}>{FIELD_LABELS[field] ?? field}</Label>
                      <NativeSelect id={id} name={id} required defaultValue={initialColumn(sim, spec, field)}>
                        <option value="">Escolha a coluna</option>
                        {file.columns.map((c) => (
                          <option key={c} value={c}>
                            {c}
                          </option>
                        ))}
                      </NativeSelect>
                    </div>
                  )
                })}
              </div>
            </fieldset>
          )
        })}
        {save.isError && (
          <p role="alert" className="text-sm text-destructive">
            {errorMessage(save.error)}
          </p>
        )}
        <Button type="submit" disabled={save.isPending}>
          Validar
        </Button>
      </form>
    </section>
  )
}

function ValidationBlock({ report }: { report: ValidationReport | null }) {
  // confirmations live only in the page until B4 stores them with the run
  const [confirmed, setConfirmed] = useState<Set<number>>(new Set())

  function toggle(i: number, on: boolean) {
    const next = new Set(confirmed)
    if (on) next.add(i)
    else next.delete(i)
    setConfirmed(next)
  }

  return (
    <section className="space-y-3">
      <h2 className="text-lg font-medium">Validação</h2>
      {!report && (
        <p className="text-muted-foreground">Envie investimento e performance e confirme o mapeamento para validar.</p>
      )}
      {report?.checks.map((check, i) => {
        const Icon = LEVEL_ICONS[check.level]
        return (
          <Alert key={i} variant={check.level === 'error' ? 'destructive' : 'default'}>
            <Icon />
            <AlertTitle>{LEVEL_LABELS[check.level]}</AlertTitle>
            <AlertDescription>
              <p>{check.message}</p>
              {check.level === 'warning' && (
                <div className="mt-2 flex items-center gap-2">
                  <Checkbox
                    id={`confirm-${i}`}
                    checked={confirmed.has(i)}
                    onCheckedChange={(v) => toggle(i, v === true)}
                  />
                  <Label htmlFor={`confirm-${i}`}>Estou ciente</Label>
                </div>
              )}
            </AlertDescription>
          </Alert>
        )
      })}
      {report && report.checks.length === 0 && <p>Nenhum problema encontrado.</p>}
      {report && report.channels.length > 0 && (
        <p className="text-sm">
          <span className="font-medium">Canais:</span> {report.channels.join(', ')}
        </p>
      )}
      <div className="flex flex-wrap items-center gap-3 border-t pt-4">
        {/* never enabled in B2: the run is B4's */}
        <Button disabled>Rodar</Button>
        <p className="text-sm text-muted-foreground">{runBlockReason(report, confirmed)}</p>
      </div>
    </section>
  )
}
```

Notas para quem implementa:
- Os hooks (`useQueryClient`, `useQuery`) vêm antes dos `return` antecipados. Mantenha essa ordem.
- Se o `alert.tsx` gerado pelo shadcn exportar nomes diferentes de `Alert`/`AlertTitle`/`AlertDescription`, ou o `badge.tsx` não tiver a variante `secondary`, use o que o arquivo gerado tem e anote no relatório.
- O `key={JSON.stringify(sim.validation)}` remonta o bloco quando o report muda, o que zera as confirmações de aviso. Revalidar com o mesmo resultado mantém as confirmações.

- [ ] **Step 4: Rodar e ver passar**

Run: `cd web && bun run build && bunx playwright test e2e/simulations.spec.ts`
Expected: PASS (3 testes).

- [ ] **Step 5: Lint e suíte E2E inteira**

Run: `cd web && bun run lint && bunx playwright test`
Expected: tudo verde.

- [ ] **Step 6: Commit**

```bash
git add web/e2e/simulations.spec.ts 'web/src/routes/_auth/w/$slug/simulacoes/$id.tsx'
git commit -m "feat(web): upload files, confirm column mapping and show the validation report"
```

---

### Task 4: Conferência visual e documentação

**Files:**
- Modify: `CLAUDE.md`, `docs/m2/trilha-b-plataforma.md`, `docs/decisoes/upload-e-storage.md`

- [ ] **Step 1: Screenshots nos dois temas**

Com a API (`mise run api`, `:8000`) e o web (`mise run web`, `:5173`) no ar, contra o banco de dev `app`:
1. Crie um admin se não tiver (`mise run create-admin voce@exemplo.com "Seu Nome"`), faça login, crie um workspace em `/admin/workspaces` e adicione-se como analyst em `/w/<slug>/membros` (ou use uma conta analyst que já exista).
2. Abra `/w/<slug>`, crie uma simulação, suba `web/public/templates/investimento.csv` e `performance.csv` e clique em Validar.
3. Com o MCP `playwright`: screenshot de `/w/<slug>` (lista) e do detalhe validado, no tema claro e no escuro (menu "Tema" no cabeçalho). Suba também um investimento com `(data, canal)` repetido e tire um screenshot do erro.

Verificar: cards dos três arquivos alinhados (empilhados no mobile, 3 colunas no `md`), selo "opcional" no Trends, área tracejada visível nos dois temas, alert de erro em vermelho legível no escuro, nada renderizou vazio. Corrija o que estiver quebrado antes de seguir (e rode de novo `bunx playwright test e2e/simulations.spec.ts`).

- [ ] **Step 2: `CLAUDE.md`**

No bloco **Estrutura**, troque:

```
  src/lib/        api.ts (fetch + ApiError), auth.ts (meQuery, erros pt-BR), theme.ts
```

por:

```
  src/lib/        api.ts (fetch + ApiError), auth.ts (meQuery, erros pt-BR), theme.ts, simulations.ts (tipos e regras de tela da simulação)
```

Em **Estado atual**, logo depois da frase que termina em `` `validate` falso (só `duplicate_date_channel`) até o A2.``, adicione:

```
**B2b (telas do upload) concluído em <dd/mmm/2026>**: lista de simulações em `/w/$slug`, criação, detalhe com upload por drag & drop, mapeamento pré-preenchido, report de validação e botão Rodar sempre desabilitado com o motivo (o run é do B4).
```

e troque `Faltam, em ordem: B2b (telas do upload), B3–B4 (Gemini, jobs)` por `Faltam, em ordem: B3–B4 (Gemini, jobs)`.

Logo antes de `## Estado atual`, adicione a seção:

```markdown
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
```

- [ ] **Step 3: `docs/m2/trilha-b-plataforma.md`**

Troque a linha de status do B2:

```
- **Status:** 🟡 B2a (backend) feito em 26/out/2026, verificado por `tests/api/test_simulations.py` e `tests/api/test_rbac.py`. B2b (telas) pendente. Desvios em `docs/decisoes/upload-e-storage.md`.
```

por (com a data do dia):

```
- **Status:** ✅ feito. B2a (backend) em 26/out/2026, verificado por `tests/api/test_simulations.py` e `tests/api/test_rbac.py`; B2b (telas) em <dd/mmm/2026>, verificado por `web/e2e/simulations.spec.ts` (fluxo com templates, duplicata bloqueia o Rodar, viewer sem permissão) e screenshots nos dois temas. Fora até a Trilha A: agrupamento por colinearidade (A3), DV360/CM360 (A2), resultado de experimento (A7). Desvios em `docs/decisoes/upload-e-storage.md`.
```

- [ ] **Step 4: `docs/decisoes/upload-e-storage.md`**

No fim do arquivo, adicione:

```markdown
## Telas (B2b)

- **Pré-preenchimento do mapping.** Um re-upload zera o `validation` mas mantém o `config.column_mapping`, que pode apontar para uma coluna que o arquivo novo não tem. A tela usa o salvo só se a coluna ainda existe e cai no `suggested` caso contrário (`initialColumn` em `web/src/lib/simulations.ts`). O backend não limpa o mapping: quem decide o que mostrar é a tela, e o `PUT …/mapping` recusa coluna inexistente de qualquer jeito.
- **Cache sem refetch.** Upload, mapping e criação devolvem o `SimulationOut` inteiro; a tela grava a resposta com `setQueryData` e só invalida a lista.
- **Rodar sempre desabilitado no B2.** O texto ao lado diz o motivo (não validado, erro, aviso sem confirmação) ou "Execução disponível em breve". As confirmações de aviso vivem no estado da página e zeram quando o report muda; o B4 as guarda com o run e confere o gate no servidor.
- **Upload ao escolher o arquivo**, sem botão. A área de drag & drop é o `file-upload-04` do blocks.so sem a barra de progresso fake (o arquivo real é < 1 MB).
```

- [ ] **Step 5: Verificação final e commit**

Run: `cd web && bun run build && bun run lint && bunx playwright test` e, na raiz, `uv run pytest -q`
Expected: tudo verde.

```bash
git add CLAUDE.md docs/m2/trilha-b-plataforma.md docs/decisoes/upload-e-storage.md
git commit -m "docs: record b2b screens, ui stack and screen-side decisions"
```

---

## Ordem de execução

Sequencial: 1 → 2 → 3 → 4. A Task 2 depende dos tipos e do `newSession` da 1; a 3 reescreve o `$id.tsx` e o spec da 2; a 4 descreve o que 1–3 entregaram e precisa da tela pronta para os screenshots. Modelo sugerido: haiku para 1, sonnet para 2–4 (a 4 precisa do MCP `playwright` e de julgamento visual).
