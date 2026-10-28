# B6b · Histórico telas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Página de histórico de execuções do workspace com filtros, e página do run com parâmetros, entradas, publicação e "Rodar de novo".

**Architecture:** Rota nova `/w/$slug/execucoes/` lê `GET …/runs` (B6a) e filtra no navegador com uma função pura de `web/src/lib/runs.ts`; os filtros moram nos search params da rota. A página do run ganha as seções num componente próprio (`web/src/components/RunDetails.tsx`). "Rodar de novo" reaproveita o `PUT …/params` da B3 e leva à simulação. O viewer é redirecionado da home do workspace para o histórico.

**Tech Stack:** React 19, TypeScript, TanStack Router/Query, shadcn (`radix-nova`), Playwright, `bun`.

Spec: `docs/superpowers/specs/2026-10-28-b6-historico-design.md` (seção B6b). **Requer o B6a concluído** (`docs/superpowers/plans/2026-10-28-b6a-historico-backend.md`). Leia antes o `CLAUDE.md` (seções "Rodando o projeto" e "Verificar mudanças no frontend") e `docs/decisoes/runs-e-jobs.md`.

---

## Arquivos

| Arquivo | Mudança |
|---|---|
| `web/src/lib/runs.ts` | `Run` com campos novos, `isPublishable`, `workspaceRunsQuery`, `RunFilters`, `parseRunFilters`, `filterRuns` |
| `web/src/lib/params.ts` | exporta `getPath`; `displayValue` novo |
| `web/src/routes/_auth/w/$slug/execucoes/index.tsx` | **nova**: histórico |
| `web/src/routes/_auth/w/$slug/index.tsx` | link "Execuções"; viewer redirecionado |
| `web/src/components/RunDetails.tsx` | **novo**: Parâmetros, Entradas, Publicação, Rodar de novo |
| `web/src/routes/_auth/w/$slug/execucoes/$runId.tsx` | usa `RunDetails`; versão do motor no cabeçalho |
| `web/e2e/helpers.ts` | recebe `template`, `createSimulation`, `uploadTemplatesAndValidate`, `runToCompletion` |
| `web/e2e/simulations.spec.ts` | importa os helpers movidos; teste do viewer atualizado |
| `web/e2e/history.spec.ts` | **novo** |
| docs | fechamento |

**Cuidado (do `CLAUDE.md`):** com o dev server no ar, crie arquivos em `web/src/routes/**` com a ferramenta `Write`, nunca por heredoc. Depois de criar a rota nova, rode `cd web && bunx vite build` uma vez antes do `bun run build`, para o plugin regenerar o `routeTree.gen.ts`.

Verificação por task: `cd web && bun run build && bun run lint`. E2E: `mise run e2e` (precisa do Postgres no ar; sobe build + uvicorn em `:8001` + banco `app_e2e`).

---

### Task 1: tipos, query e filtros em `lib/`

**Files:**
- Modify: `web/src/lib/runs.ts`
- Modify: `web/src/lib/params.ts`

Não há runner de teste de componente (`CODE-STYLE.md`); `filterRuns` é coberto pelo E2E da Task 5.

- [ ] **Step 1: `web/src/lib/runs.ts`**

Acrescente o import de tipo no topo:

```ts
import type { Simulation } from './simulations'
```

Troque o tipo `Run` por:

```ts
export type RunInput = { filename: string; sha256: string } | null

export type Run = {
  id: number
  status: RunStatus
  simulation: { id: number; name: string }
  created_by_name: string
  created_at: string
  started_at: string | null
  finished_at: string | null
  error: string | null
  summary: Record<string, unknown> | null
  engine_version: string | null
  // snapshot of the simulation's config when the run was created, column_mapping included
  config: Simulation['config']
  // keyed like column_mapping: investment_file, performance_file, generic_trends_file
  inputs: Record<string, RunInput>
  published_at: string | null
  published_by_name: string | null
}
```

Depois de `isActive`:

```ts
export const isPublishable = (status: RunStatus) => status === 'succeeded' || status === 'inconclusive'
```

Depois de `simulationRunsQuery`:

```ts
export const workspaceRunsQuery = (slug: string) =>
  queryOptions({
    queryKey: ['runs', slug, 'workspace'],
    queryFn: () => api<Run[]>(`/w/${slug}/runs`),
    refetchInterval: (q) => (q.state.data?.some((r) => isActive(r.status)) ? 3000 : false),
  })

export type RunFilters = { q?: string; status?: RunStatus; author?: string; from?: string; to?: string }

const text = (v: unknown) => (typeof v === 'string' && v ? v : undefined)

// unknown or empty values drop out, so a hand-edited URL never breaks the page
export function parseRunFilters(search: Record<string, unknown>): RunFilters {
  const status = text(search.status)
  return {
    q: text(search.q),
    status: status && status in STATUS_LABELS ? (status as RunStatus) : undefined,
    author: text(search.author),
    from: text(search.from),
    to: text(search.to),
  }
}

// YYYY-MM-DD in the browser's timezone, the format <input type="date"> gives
function localDay(iso: string) {
  const d = new Date(iso)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function filterRuns(runs: Run[], f: RunFilters): Run[] {
  const q = f.q?.trim().toLocaleLowerCase('pt-BR')
  return runs.filter((r) => {
    const day = localDay(r.created_at)
    return (
      (!q || r.simulation.name.toLocaleLowerCase('pt-BR').includes(q)) &&
      (!f.status || r.status === f.status) &&
      (!f.author || r.created_by_name === f.author) &&
      (!f.from || day >= f.from) &&
      (!f.to || day <= f.to)
    )
  })
}
```

- [ ] **Step 2: `web/src/lib/params.ts`**

Troque `const getPath = ` por `export const getPath = ` (mesma função). Logo depois de `ENUM_LABELS`, acrescente:

```ts
// read-only display of a saved value (run page); "—" for a field the run's config doesn't have
export function displayValue(field: FormField, value: unknown): string {
  if (value == null) return '—'
  if (field.schema.type === 'boolean') return value ? 'Sim' : 'Não'
  if (field.schema.enum) return ENUM_LABELS[String(value)] ?? String(value)
  return typeof value === 'number' ? value.toLocaleString('pt-BR') : String(value)
}
```

- [ ] **Step 3: Build e lint**

Run: `cd web && bun run build && bun run lint`
Expected: sem erros

- [ ] **Step 4: Commit**

```bash
git add web/src/lib/runs.ts web/src/lib/params.ts
git commit -m "feat(web): run history types, query and filters"
```

---

### Task 2: página do histórico e home do workspace

**Files:**
- Create: `web/src/routes/_auth/w/$slug/execucoes/index.tsx`
- Modify: `web/src/routes/_auth/w/$slug/index.tsx`

- [ ] **Step 1: Criar `web/src/routes/_auth/w/$slug/execucoes/index.tsx`** (com `Write`)

```tsx
import { useQuery, useSuspenseQuery } from '@tanstack/react-query'
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router'
import { LoadState } from '@/components/LoadState'
import { NativeSelect } from '@/components/NativeSelect'
import { RunStatusBadge } from '@/components/RunStatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { meQuery, roleIn } from '@/lib/auth'
import {
  type Run,
  type RunFilters,
  type RunStatus,
  STATUS_LABELS,
  filterRuns,
  parseRunFilters,
  workspaceRunsQuery,
} from '@/lib/runs'
import { formatDate } from '@/lib/simulations'

export const Route = createFileRoute('/_auth/w/$slug/execucoes/')({
  validateSearch: parseRunFilters,
  component: HistoryPage,
})

function HistoryPage() {
  const { slug } = Route.useParams()
  const filters = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const { data: me } = useSuspenseQuery(meQuery)
  const query = useQuery(workspaceRunsQuery(slug))
  const { data } = query
  // replace: typing in the search box must not push one history entry per key
  const set = (patch: RunFilters) => navigate({ search: (prev) => ({ ...prev, ...patch }), replace: true })
  const clear = () => navigate({ search: {}, replace: true })
  const authors = [...new Set(data?.map((r) => r.created_by_name))].sort((a, b) => a.localeCompare(b, 'pt-BR'))
  const shown = data ? filterRuns(data, filters) : []

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        {/* a viewer's workspace home redirects here, so the link would loop */}
        {roleIn(me, slug) !== 'viewer' && (
          <Link to="/w/$slug" params={{ slug }} className="text-sm text-muted-foreground hover:text-primary">
            ← Simulações
          </Link>
        )}
        <h1 className="text-2xl font-semibold">Execuções</h1>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <Label htmlFor="filter-q">Simulação</Label>
          <Input
            id="filter-q"
            type="search"
            placeholder="Buscar pelo nome"
            className="w-56"
            value={filters.q ?? ''}
            onChange={(e) => set({ q: e.target.value || undefined })}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="filter-status">Status</Label>
          <NativeSelect
            id="filter-status"
            value={filters.status ?? ''}
            onChange={(e) => set({ status: (e.target.value || undefined) as RunStatus | undefined })}
          >
            <option value="">Todos</option>
            {Object.entries(STATUS_LABELS).map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className="space-y-1">
          <Label htmlFor="filter-author">Autor</Label>
          <NativeSelect
            id="filter-author"
            value={filters.author ?? ''}
            onChange={(e) => set({ author: e.target.value || undefined })}
          >
            <option value="">Todos</option>
            {authors.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className="space-y-1">
          <Label htmlFor="filter-from">De</Label>
          <Input
            id="filter-from"
            type="date"
            value={filters.from ?? ''}
            onChange={(e) => set({ from: e.target.value || undefined })}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="filter-to">Até</Label>
          <Input
            id="filter-to"
            type="date"
            value={filters.to ?? ''}
            onChange={(e) => set({ to: e.target.value || undefined })}
          />
        </div>
      </div>

      {!data ? (
        <LoadState query={query} />
      ) : data.length === 0 ? (
        <p className="text-muted-foreground">Nenhuma execução ainda.</p>
      ) : shown.length === 0 ? (
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-muted-foreground">Nenhuma execução com esses filtros.</p>
          <Button variant="outline" size="sm" onClick={clear}>
            Limpar filtros
          </Button>
        </div>
      ) : (
        <HistoryTable slug={slug} runs={shown} />
      )}
    </div>
  )
}

function HistoryTable({ slug, runs }: { slug: string; runs: Run[] }) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Execução</TableHead>
          <TableHead>Simulação</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Criada por</TableHead>
          <TableHead>Criada em</TableHead>
          <TableHead>Motor</TableHead>
          <TableHead>Publicação</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {runs.map((r) => (
          <TableRow key={r.id}>
            <TableCell>
              <Link
                to="/w/$slug/execucoes/$runId"
                params={{ slug, runId: String(r.id) }}
                className="font-medium hover:text-primary"
              >
                #{r.id}
              </Link>
            </TableCell>
            <TableCell>{r.simulation.name}</TableCell>
            <TableCell>
              <RunStatusBadge status={r.status} />
            </TableCell>
            <TableCell>{r.created_by_name}</TableCell>
            <TableCell>{formatDate(r.created_at)}</TableCell>
            <TableCell className="font-mono text-xs">{r.engine_version ?? '—'}</TableCell>
            <TableCell>{r.published_at ? <Badge variant="outline">Publicada</Badge> : '—'}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
```

A simulação aparece como texto, não como link: o viewer não abre simulações, e a linha já leva ao run, que linka a simulação.

- [ ] **Step 2: Home do workspace (`web/src/routes/_auth/w/$slug/index.tsx`)**

Imports:

```tsx
import { Link, createFileRoute, redirect } from '@tanstack/react-router'
import { meQuery, roleIn } from '@/lib/auth'
```

(substituem as linhas atuais de `@tanstack/react-router` e `@/lib/auth`)

Troque a declaração da rota por:

```tsx
export const Route = createFileRoute('/_auth/w/$slug/')({
  // the run history is all a viewer sees in a workspace
  beforeLoad: ({ context: { me }, params }) => {
    if (roleIn(me, params.slug) === 'viewer') throw redirect({ to: '/w/$slug/execucoes', params })
  },
  component: WorkspaceHome,
})
```

E troque o bloco do botão "Nova simulação" por:

```tsx
        {canEdit && (
          <div className="flex flex-wrap gap-2">
            <Button asChild variant="outline">
              <Link to="/w/$slug/execucoes" params={{ slug }}>
                Execuções
              </Link>
            </Button>
            <Button asChild>
              <Link to="/w/$slug/simulacoes/nova" params={{ slug }}>
                Nova simulação
              </Link>
            </Button>
          </div>
        )}
```

O ramo `canEdit ? … : <p>Nenhuma simulação ainda.</p>` fica: o papel pode mudar no meio da sessão sem o `beforeLoad` rodar de novo.

Se o `tsc` reclamar que falta `search` no `Link`/`redirect` para `/w/$slug/execucoes`, passe `search={{}}` (no `redirect`, `search: {}`): todos os filtros são opcionais.

- [ ] **Step 3: Regenerar rotas, build e lint**

Run: `cd web && bunx vite build && bun run build && bun run lint`
Expected: sem erros; `routeTree.gen.ts` passa a ter `/_auth/w/$slug/execucoes/`

- [ ] **Step 4: Commit**

```bash
git add web/src/routes/_auth/w/$slug/execucoes/index.tsx web/src/routes/_auth/w/$slug/index.tsx web/src/routeTree.gen.ts
git commit -m "feat(web): workspace run history with filters"
```

---

### Task 3: seções da página do run

**Files:**
- Create: `web/src/components/RunDetails.tsx`
- Modify: `web/src/routes/_auth/w/$slug/execucoes/$runId.tsx`

- [ ] **Step 1: Criar `web/src/components/RunDetails.tsx`**

```tsx
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { Fragment } from 'react'
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { errorMessage } from '@/lib/auth'
import { configSchemaQuery, displayValue, fieldErrors, getPath, visibleLayout } from '@/lib/params'
import { type Run, isActive, isPublishable, runQuery, workspaceRunsQuery } from '@/lib/runs'
import { FIELD_LABELS, FILES, type Simulation, formatDate, simulationQuery } from '@/lib/simulations'

export function RunDetails({ slug, run, canEdit }: { slug: string; run: Run; canEdit: boolean }) {
  return (
    <div className="space-y-8">
      <Publication slug={slug} run={run} canEdit={canEdit} />
      <Params run={run} />
      <Inputs slug={slug} run={run} canEdit={canEdit} />
    </div>
  )
}

function Publication({ slug, run, canEdit }: { slug: string; run: Run; canEdit: boolean }) {
  const queryClient = useQueryClient()
  const toggle = useMutation({
    mutationFn: (publish: boolean) =>
      api<Run>(`/w/${slug}/runs/${run.id}/${publish ? 'publish' : 'unpublish'}`, { method: 'POST' }),
    onSuccess: (next) => {
      queryClient.setQueryData(runQuery(slug, String(run.id)).queryKey, next)
      queryClient.invalidateQueries({ queryKey: workspaceRunsQuery(slug).queryKey })
    },
  })
  const publishable = isPublishable(run.status)

  return (
    <section className="space-y-2">
      <h2 className="text-lg font-medium">Publicação</h2>
      <p className="text-sm">
        {run.published_at
          ? `Publicada por ${run.published_by_name ?? '—'} em ${formatDate(run.published_at)}.`
          : 'Não publicada. Leitores ainda não veem esta execução.'}
      </p>
      {canEdit && (
        <div className="flex flex-wrap items-center gap-3">
          {run.published_at ? (
            <Button variant="outline" disabled={toggle.isPending} onClick={() => toggle.mutate(false)}>
              Despublicar
            </Button>
          ) : (
            <Button disabled={!publishable || toggle.isPending} onClick={() => toggle.mutate(true)}>
              Publicar
            </Button>
          )}
          {!run.published_at && !publishable && (
            <p className="text-sm text-muted-foreground">Só execuções concluídas podem ser publicadas.</p>
          )}
          {!isActive(run.status) && <Rerun slug={slug} run={run} />}
          {toggle.isError && (
            <p role="alert" className="text-sm text-destructive">
              {errorMessage(toggle.error)}
            </p>
          )}
        </div>
      )}
    </section>
  )
}

function Rerun({ slug, run }: { slug: string; run: Run }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const restore = useMutation({
    mutationFn: () => {
      // ParamsIn forbids unknown keys, and the PUT keeps the simulation's own column_mapping
      const params = { ...run.config }
      delete params.column_mapping
      return api<Simulation>(`/w/${slug}/simulations/${run.simulation.id}/params`, { method: 'PUT', body: params })
    },
  })

  function confirm() {
    restore.mutate(undefined, {
      onSuccess: (sim) => {
        queryClient.setQueryData(simulationQuery(slug, String(sim.id)).queryKey, sim)
        navigate({ to: '/w/$slug/simulacoes/$id', params: { slug, id: String(sim.id) } })
      },
    })
  }

  return (
    <AlertDialog onOpenChange={(open) => !open && restore.reset()}>
      <AlertDialogTrigger asChild>
        <Button variant="outline">Rodar de novo</Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Substituir os parâmetros de {run.simulation.name} pelos desta execução?</AlertDialogTitle>
          <AlertDialogDescription>
            Os arquivos continuam os atuais da simulação. Revise e clique em Rodar.
          </AlertDialogDescription>
        </AlertDialogHeader>
        {restore.isError && (
          <p role="alert" className="text-sm text-destructive">
            {/* pydantic's per-field 422: the engine's parameters changed since this run */}
            {fieldErrors(restore.error)
              ? 'Os parâmetros desta execução não valem mais para o motor atual.'
              : errorMessage(restore.error)}
          </p>
        )}
        <AlertDialogFooter>
          <AlertDialogCancel>Cancelar</AlertDialogCancel>
          {/* a plain Button: AlertDialogAction would close the dialog before a 422 could show */}
          <Button disabled={restore.isPending} onClick={confirm}>
            Substituir
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  )
}

function Params({ run }: { run: Run }) {
  const { data: schema } = useQuery(configSchemaQuery)
  if (!schema) return null
  const mapping = run.config.column_mapping ?? {}

  return (
    <section className="space-y-3">
      <h2 className="text-lg font-medium">Parâmetros</h2>
      <div className="grid gap-6 md:grid-cols-2">
        {visibleLayout(schema).map((group) => (
          <div key={group.title} className="space-y-1">
            <h3 className="text-sm font-medium">{group.title}</h3>
            <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 text-sm">
              {group.fields.map((field) => (
                <Fragment key={field.path}>
                  <dt className="text-muted-foreground">{field.label}</dt>
                  <dd>{displayValue(field, getPath(run.config, field.path))}</dd>
                </Fragment>
              ))}
            </dl>
          </div>
        ))}
        <div className="space-y-1">
          <h3 className="text-sm font-medium">Mapeamento de colunas</h3>
          <dl className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1 text-sm">
            {FILES.flatMap((spec) =>
              Object.entries(mapping[spec.key] ?? {}).map(([field, column]) => (
                <Fragment key={`${spec.key}.${field}`}>
                  <dt className="text-muted-foreground">
                    {spec.label} · {FIELD_LABELS[field] ?? field}
                  </dt>
                  <dd className="font-mono text-xs">{column}</dd>
                </Fragment>
              )),
            )}
          </dl>
        </div>
      </div>
    </section>
  )
}

function Inputs({ slug, run, canEdit }: { slug: string; run: Run; canEdit: boolean }) {
  return (
    <section className="space-y-2">
      <h2 className="text-lg font-medium">Entradas</h2>
      <ul className="space-y-1 text-sm">
        {FILES.map((spec) => {
          const input = run.inputs[spec.key]
          if (!input) return null
          return (
            <li key={spec.key} className="flex flex-wrap items-baseline gap-x-3">
              <span className="font-medium">{spec.label}</span>
              {/* the api serves the raw csv to analysts only */}
              {canEdit ? (
                <a
                  href={`/api/w/${slug}/runs/${run.id}/inputs/${spec.key}`}
                  download
                  className="text-primary hover:underline"
                >
                  {input.filename}
                </a>
              ) : (
                <span>{input.filename}</span>
              )}
              <code className="text-xs text-muted-foreground" title={input.sha256}>
                {input.sha256.slice(0, 12)}
              </code>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
```

- [ ] **Step 2: Usar em `web/src/routes/_auth/w/$slug/execucoes/$runId.tsx`**

Imports a acrescentar:

```tsx
import { useQuery, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { RunDetails } from '@/components/RunDetails'
import { meQuery, roleIn } from '@/lib/auth'
```

(a primeira substitui a linha atual de `@tanstack/react-query`)

Em `RunPage`, logo depois de `const log = useRunLog(slug, runId)`:

```tsx
  const { data: me } = useSuspenseQuery(meQuery)
  const canEdit = roleIn(me, slug) !== 'viewer'
```

Troque a linha do autor e data no cabeçalho por:

```tsx
        <p className="text-sm text-muted-foreground">
          {run.created_by_name} · {formatDate(run.created_at)} · motor {run.engine_version ?? '—'}
        </p>
```

E, entre o parágrafo "Execução concluída. Os dashboards chegam em breve." e o `<LogPanel …/>`, acrescente:

```tsx
      <RunDetails slug={slug} run={run} canEdit={canEdit} />
```

O `useSuspenseQuery` fica antes do `if (!run) return …`: hooks não podem vir depois de um return condicional.

- [ ] **Step 3: Build e lint**

Run: `cd web && bun run build && bun run lint`
Expected: sem erros

- [ ] **Step 4: Commit**

```bash
git add web/src/components/RunDetails.tsx web/src/routes/_auth/w/$slug/execucoes/$runId.tsx
git commit -m "feat(web): show params, inputs and publication on the run page, with rodar de novo"
```

---

### Task 4: helpers do E2E e teste do viewer

**Files:**
- Modify: `web/e2e/helpers.ts`
- Modify: `web/e2e/simulations.spec.ts`

- [ ] **Step 1: Mover helpers para `web/e2e/helpers.ts`**

Acrescente no topo de `helpers.ts`:

```ts
import { fileURLToPath } from 'node:url'
```

E no fim do arquivo:

```ts
export const template = (name: string) => fileURLToPath(new URL(`../public/templates/${name}`, import.meta.url))

export async function createSimulation(page: Page, slug: string, name: string) {
  await page.goto(`/w/${slug}`)
  await page.getByRole('link', { name: 'Nova simulação' }).click()
  await page.getByLabel('Nome').fill(name)
  await page.getByRole('button', { name: 'Criar' }).click()
  await expect(page.getByRole('heading', { name })).toBeVisible()
  await expect(page).toHaveURL(new RegExp(`/w/${slug}/simulacoes/\\d+$`))
}

export async function uploadTemplatesAndValidate(page: Page) {
  await page.getByLabel('Arquivo de investimento').setInputFiles(template('investimento.csv'))
  await expect(page.getByText('investimento.csv', { exact: true })).toBeVisible()
  await page.getByLabel('Arquivo de performance').setInputFiles(template('performance.csv'))
  await expect(page.getByText('performance.csv', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Validar' }).click()
  await expect(page.getByText('Nenhum problema encontrado.')).toBeVisible()
}

// the fake engine takes ~5 s (FAKE_ENGINE_STEP_SECONDS=1 in env.ts); returns the run page's URL
export async function runToCompletion(page: Page, slug: string, name: string) {
  await createSimulation(page, slug, name)
  await uploadTemplatesAndValidate(page)
  await page.getByRole('button', { name: 'Salvar parâmetros' }).click()
  await expect(page.getByRole('button', { name: 'Rodar' })).toBeEnabled()
  await page.getByRole('button', { name: 'Rodar' }).click()
  await expect(page).toHaveURL(new RegExp(`/w/${slug}/execucoes/\\d+$`))
  await expect(page.getByText('Concluída', { exact: true })).toBeVisible()
  return page.url()
}
```

Em `simulations.spec.ts`, apague `template`, `createSimulation` e `uploadTemplatesAndValidate` (e o import de `fileURLToPath`) e importe-os de `./helpers`:

```ts
import { type Browser, expect, type Page, test } from '@playwright/test'
import {
  addMember,
  createSimulation,
  createWorkspace,
  loggedInAdmin,
  newSession,
  template,
  uploadTemplatesAndValidate,
} from './helpers'
```

- [ ] **Step 2: Atualizar o teste do viewer em `simulations.spec.ts`**

Em `test('viewer cannot create or edit simulations', …)`, troque as duas linhas:

```ts
  await expect(viewerPage).toHaveURL(new RegExp(`/w/${slug}$`))
  await expect(viewerPage.getByText('Nenhuma simulação ainda.')).toBeVisible()
```

por:

```ts
  // the history is all a viewer sees: the workspace home sends them there
  await expect(viewerPage).toHaveURL(new RegExp(`/w/${slug}/execucoes$`))
  await expect(viewerPage.getByText('Nenhuma execução ainda.')).toBeVisible()
```

- [ ] **Step 3: Rodar o E2E existente**

Run: `mise run e2e`
Expected: PASS (todos os testes de `simulations.spec.ts`, `members.spec.ts`, `auth.spec.ts`, `admin.spec.ts`)

- [ ] **Step 4: Commit**

```bash
git add web/e2e/helpers.ts web/e2e/simulations.spec.ts
git commit -m "test(web): share simulation helpers and send viewers to the history"
```

---

### Task 5: E2E do histórico

**Files:**
- Create: `web/e2e/history.spec.ts`

- [ ] **Step 1: Escrever os testes**

```ts
import { expect, test } from '@playwright/test'
import { addMember, createWorkspace, loggedInAdmin, newSession, runToCompletion } from './helpers'

test('analyst filters the history, publishes a run and the viewer sees only that one', async ({ page, browser }) => {
  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  const analyst = await addMember(page, slug, 'analyst')
  const viewer = await addMember(page, slug, 'viewer')
  const analystPage = await newSession(browser, analyst)

  await runToCompletion(analystPage, slug, 'Verão')
  await runToCompletion(analystPage, slug, 'Inverno')
  await analystPage.getByRole('button', { name: 'Publicar' }).click()
  await expect(analystPage.getByText(/Publicada por Pessoa E2E/)).toBeVisible()

  await analystPage.goto(`/w/${slug}`)
  await analystPage.getByRole('link', { name: 'Execuções' }).click()
  await expect(analystPage.getByRole('cell', { name: 'Verão' })).toBeVisible()
  await expect(analystPage.getByRole('cell', { name: 'Inverno' })).toBeVisible()

  await analystPage.getByLabel('Simulação').fill('verão')
  await expect(analystPage.getByRole('cell', { name: 'Inverno' })).toHaveCount(0)
  await expect(analystPage.getByRole('cell', { name: 'Verão' })).toBeVisible()
  await expect(analystPage).toHaveURL(/q=ver/)

  await analystPage.getByLabel('Status').selectOption('failed')
  await expect(analystPage.getByText('Nenhuma execução com esses filtros.')).toBeVisible()
  await analystPage.getByRole('button', { name: 'Limpar filtros' }).click()
  await expect(analystPage.getByRole('cell', { name: 'Inverno' })).toBeVisible()
  await expect(analystPage.getByRole('cell', { name: 'Verão' })).toBeVisible()

  const viewerPage = await newSession(browser, viewer)
  await expect(viewerPage).toHaveURL(new RegExp(`/w/${slug}/execucoes$`))
  await expect(viewerPage.getByRole('cell', { name: 'Inverno' })).toBeVisible()
  await expect(viewerPage.getByRole('cell', { name: 'Verão' })).toHaveCount(0)

  await viewerPage.getByRole('link', { name: /^#\d+$/ }).click()
  await expect(viewerPage.getByText('investimento.csv', { exact: true })).toBeVisible()
  await expect(viewerPage.getByRole('link', { name: 'investimento.csv' })).toHaveCount(0)
  await expect(viewerPage.getByRole('button', { name: 'Despublicar' })).toHaveCount(0)
  await expect(viewerPage.getByRole('button', { name: 'Rodar de novo' })).toHaveCount(0)
})

test('rodar de novo restores the run parameters and the inputs download', async ({ page, browser }) => {
  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  const analystPage = await newSession(browser, await addMember(page, slug, 'analyst'))

  const runUrl = await runToCompletion(analystPage, slug, 'Reprise')
  await expect(analystPage.getByText('Fator limite de investimento')).toBeVisible()

  const download = analystPage.waitForEvent('download')
  await analystPage.getByRole('link', { name: 'investimento.csv' }).click()
  expect((await download).suggestedFilename()).toBe('investimento.csv')

  await analystPage.getByRole('link', { name: '← Reprise' }).click()
  const factor = analystPage.getByLabel('Fator limite de investimento')
  const original = await factor.inputValue()
  await factor.fill('3')
  await analystPage.getByRole('button', { name: 'Salvar parâmetros' }).click()
  await expect(analystPage.getByRole('button', { name: 'Rodar' })).toBeEnabled()

  await analystPage.goto(runUrl)
  await analystPage.getByRole('button', { name: 'Rodar de novo' }).click()
  await analystPage.getByRole('button', { name: 'Substituir' }).click()

  await expect(analystPage).toHaveURL(new RegExp(`/w/${slug}/simulacoes/\\d+$`))
  await expect(analystPage.getByLabel('Fator limite de investimento')).toHaveValue(original)
})
```

- [ ] **Step 2: Rodar**

Run: `mise run e2e`
Expected: PASS (incluindo os 2 de `history.spec.ts`). Se um seletor bater em dois elementos (ex.: `getByLabel('Simulação')`), ajuste o seletor, não o texto da tela.

- [ ] **Step 3: Commit**

```bash
git add web/e2e/history.spec.ts
git commit -m "test(web): e2e for the run history, publishing and rodar de novo"
```

---

### Task 6: verificação visual e fechamento

**Files:**
- Modify: `docs/decisoes/runs-e-jobs.md`, `docs/m2/trilha-b-plataforma.md`, `CLAUDE.md`

- [ ] **Step 1: Screenshots**

Com `mise run api` e `mise run web` no ar e o MCP `playwright`, em `http://localhost:5173`, com um analista que tenha ao menos dois runs:
- `/w/<slug>/execucoes` sem filtro e com um filtro que não acha nada;
- a página de um run publicado e a de um não publicado (seções Publicação, Parâmetros, Entradas);
- os dois temas (claro e escuro).

Confira se a tabela não estoura a largura em 1280 px e se os filtros quebram de linha em tela estreita. Corrija o que aparecer antes de seguir.

- [ ] **Step 2: `docs/decisoes/runs-e-jobs.md`**

Na seção `## Tela (B4b)`, troque o título por `## Telas (B4b e B6b)` e acrescente no fim da lista:

```markdown
- **Histórico em `/w/$slug/execucoes`.** Os filtros (busca, status, autor, período) ficam nos search params, com `replace` para a digitação não encher o histórico do navegador. O período compara o dia local de `created_at` com o `<input type="date">`. O autor é filtrado pelo nome, porque o `RunOut` não traz o id de quem criou.
- **Viewer cai no histórico.** A home do workspace redireciona o viewer no `beforeLoad`; para ele o histórico não tem o link "← Simulações", que voltaria em loop.
- **"Rodar de novo" no diálogo.** O botão de confirmar é um `Button` comum, não o `AlertDialogAction`, para o 422 (parâmetros que o motor atual não aceita mais) aparecer no próprio diálogo.
```

- [ ] **Step 3: `docs/m2/trilha-b-plataforma.md`**

Na linha `Status` do B6, troque `🟡 em andamento` por `✅ feito` e "Falta o B6b (telas)." por "B6b (telas) em <data de hoje>, verificado por `web/e2e/history.spec.ts` (filtros, publicar, viewer vendo só o publicado, download, rodar de novo) e screenshots nos dois temas."

- [ ] **Step 4: `CLAUDE.md`**

No "Estado atual", depois da frase do B6a, acrescente:

```markdown
**B6b (histórico telas) concluído em <data de hoje>**: `/w/$slug/execucoes` com busca e filtros na URL, viewer redirecionado para lá, página do run com parâmetros, entradas (download para analyst+), publicar/despublicar e "Rodar de novo".
```

E troque "Faltam: B6b, B7–B9" por "Faltam: B7–B9" (B7 depende do B5, então o próximo livre é B8 ou B9). Na seção Estrutura, na descrição de `src/lib/`, troque `runs.ts (tipos, queries e useRunLog do SSE)` por `runs.ts (tipos, queries, filtros do histórico e useRunLog do SSE)`.

Troque `<data de hoje>` pela data real no formato `28/out/2026`.

- [ ] **Step 5: Commit**

```bash
git add docs/decisoes/runs-e-jobs.md docs/m2/trilha-b-plataforma.md CLAUDE.md
git commit -m "docs: record the b6b history screens"
```
