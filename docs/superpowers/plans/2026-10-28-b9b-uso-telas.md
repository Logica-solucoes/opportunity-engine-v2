# B9b · Uso e apagar simulação — telas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Tela `/admin/uso` com filtro por mês e export CSV para o platform admin, e a seção "Apagar simulação" (com confirmação pelo nome) para o admin do workspace.

**Architecture:** Rota nova `web/src/routes/_auth/admin/uso.tsx` lê `GET /api/admin/usage` (B9a) com o mês no search param e linka o `.csv`; a aba entra em `admin.tsx`. O apagar fica num componente próprio (`web/src/components/DeleteSimulation.tsx`), usado no fim da página da simulação quando o papel é `admin`.

**Tech Stack:** React 19, TypeScript, TanStack Router/Query, shadcn (`radix-nova`), Playwright, `bun`.

Spec: `docs/superpowers/specs/2026-10-28-b9-uso-logs-retencao-design.md` (seção B9b). **Requer o B9a concluído** (`docs/superpowers/plans/2026-10-28-b9a-uso-logs-backend.md`). Leia antes o `CLAUDE.md` (seções "Rodando o projeto" e "Verificar mudanças no frontend").

---

## Arquivos

| Arquivo | Mudança |
|---|---|
| `web/src/routes/_auth/admin/uso.tsx` | **nova**: tela de uso |
| `web/src/routes/_auth/admin.tsx` | aba "Uso" |
| `web/src/components/DeleteSimulation.tsx` | **novo**: seção e diálogo de apagar |
| `web/src/routes/_auth/w/$slug/simulacoes/$id.tsx` | usa `DeleteSimulation` para admin |
| `web/e2e/admin.spec.ts` | teste da tela de uso |
| `web/e2e/simulations.spec.ts` | teste do apagar |
| docs | fechamento |

**Cuidado (do `CLAUDE.md`):** com o dev server no ar, crie arquivos em `web/src/routes/**` com a ferramenta `Write`, nunca por heredoc. Depois de criar a rota nova, rode `cd web && bunx vite build` uma vez antes do `bun run build`, para o plugin regenerar o `routeTree.gen.ts`.

Verificação por task: `cd web && bun run build && bun run lint`. E2E: `cd web && bun run e2e` (precisa do Postgres no ar; sobe build + uvicorn em `:8001` + banco `app_e2e`).

---

### Task 1: tela de uso

**Files:**
- Create: `web/src/routes/_auth/admin/uso.tsx`
- Modify: `web/src/routes/_auth/admin.tsx`

Não há runner de teste de componente (`CODE-STYLE.md`); a tela é coberta pelo E2E da Task 3.

- [ ] **Step 1: Criar `web/src/routes/_auth/admin/uso.tsx`** (com `Write`)

```tsx
import { useQuery } from '@tanstack/react-query'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { LoadState } from '@/components/LoadState'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api } from '@/lib/api'

type UsageRow = {
  month: string
  workspace_id: number
  workspace_name: string
  user_id: number
  user_name: string
  user_email: string
  succeeded: number
  inconclusive: number
  failed: number
  active: number
  total: number
  run_seconds: number
}

// "todos" = every month; no param = this month
type UsageSearch = { month?: string }

const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/

export const Route = createFileRoute('/_auth/admin/uso')({
  validateSearch: (search: Record<string, unknown>): UsageSearch => {
    const month = search.month
    return { month: typeof month === 'string' && (month === 'todos' || MONTH.test(month)) ? month : undefined }
  },
  component: Usage,
})

function thisMonth() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

// display only: the seconds come summed from the api
function formatDuration(seconds: number) {
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min`
  return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, '0')} min`
}

const formatMonth = (month: string) => `${month.slice(5)}/${month.slice(0, 4)}`

function Usage() {
  const search = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const month = search.month === 'todos' ? undefined : (search.month ?? thisMonth())
  const qs = month ? `?month=${month}` : ''
  const usage = useQuery({
    queryKey: ['admin', 'usage', month ?? 'todos'],
    queryFn: () => api<UsageRow[]>(`/admin/usage${qs}`),
  })

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <Label htmlFor="usage-month">Mês</Label>
          <Input
            id="usage-month"
            type="month"
            className="w-44"
            value={month ?? ''}
            onChange={(e) => navigate({ search: { month: e.target.value || 'todos' }, replace: true })}
          />
        </div>
        {month && (
          <Button variant="outline" size="sm" onClick={() => navigate({ search: { month: 'todos' }, replace: true })}>
            Todos os meses
          </Button>
        )}
        <Button asChild variant="outline" size="sm" className="ml-auto">
          <a href={`/api/admin/usage.csv${qs}`} download>
            Exportar CSV
          </a>
        </Button>
      </div>

      {!usage.data ? (
        <LoadState query={usage} />
      ) : usage.data.length === 0 ? (
        <p className="text-muted-foreground">Nenhuma execução neste período.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Mês</TableHead>
              <TableHead>Workspace</TableHead>
              <TableHead>Usuário</TableHead>
              <TableHead className="text-right">Concluídas</TableHead>
              <TableHead className="text-right">Inconclusivas</TableHead>
              <TableHead className="text-right">Falharam</TableHead>
              <TableHead className="text-right">Em andamento</TableHead>
              <TableHead className="text-right">Total</TableHead>
              <TableHead className="text-right">Tempo de execução</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {usage.data.map((r) => (
              <TableRow key={`${r.month}-${r.workspace_id}-${r.user_id}`}>
                <TableCell>{formatMonth(r.month)}</TableCell>
                <TableCell>{r.workspace_name}</TableCell>
                <TableCell title={r.user_email}>{r.user_name}</TableCell>
                <TableCell className="text-right">{r.succeeded}</TableCell>
                <TableCell className="text-right">{r.inconclusive}</TableCell>
                <TableCell className="text-right">{r.failed}</TableCell>
                <TableCell className="text-right">{r.active}</TableCell>
                <TableCell className="text-right">{r.total}</TableCell>
                <TableCell className="text-right">{formatDuration(r.run_seconds)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
```

O mês da API é o de São Paulo e o "mês atual" da tela é o do navegador; para quem usa a ferramenta (Brasil) os dois coincidem.

- [ ] **Step 2: Aba em `web/src/routes/_auth/admin.tsx`**

Depois do `Link` de "Usuários":

```tsx
        <Link to="/admin/uso" className={tab} activeProps={{ className: 'border-primary! text-primary' }}>
          Uso
        </Link>
```

Se o `tsc` pedir `search` no `Link` para `/admin/uso`, passe `search={{}}`: o `month` é opcional.

- [ ] **Step 3: Regenerar rotas, build e lint**

Run: `cd web && bunx vite build && bun run build && bun run lint`
Expected: sem erros; `routeTree.gen.ts` passa a ter `/_auth/admin/uso`

- [ ] **Step 4: Commit**

```bash
git add web/src/routes/_auth/admin/uso.tsx web/src/routes/_auth/admin.tsx web/src/routeTree.gen.ts
git commit -m "feat(web): usage page for the platform admin with csv export"
```

---

### Task 2: apagar simulação

**Files:**
- Create: `web/src/components/DeleteSimulation.tsx`
- Modify: `web/src/routes/_auth/w/$slug/simulacoes/$id.tsx`

- [ ] **Step 1: Criar `web/src/components/DeleteSimulation.tsx`**

```tsx
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
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
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import { errorMessage } from '@/lib/auth'
import { type Simulation, simulationQuery, simulationsQuery } from '@/lib/simulations'

export function DeleteSimulation({ slug, sim }: { slug: string; sim: Simulation }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [typed, setTyped] = useState('')
  const remove = useMutation({
    mutationFn: () => api<void>(`/w/${slug}/simulations/${sim.id}`, { method: 'DELETE' }),
    onSuccess: async () => {
      // leave first: dropping the query while the page is mounted would refetch it into a 404
      await navigate({ to: '/w/$slug', params: { slug } })
      queryClient.removeQueries({ queryKey: simulationQuery(slug, String(sim.id)).queryKey })
      queryClient.invalidateQueries({ queryKey: simulationsQuery(slug).queryKey })
      queryClient.invalidateQueries({ queryKey: ['runs', slug] })
    },
  })

  return (
    <section className="space-y-2 border-t pt-6">
      <h2 className="text-lg font-medium">Apagar simulação</h2>
      <p className="text-sm text-muted-foreground">
        Apaga a simulação, todas as execuções dela e os arquivos enviados. Não dá para desfazer.
      </p>
      <AlertDialog
        onOpenChange={(open) => {
          if (!open) {
            setTyped('')
            remove.reset()
          }
        }}
      >
        <AlertDialogTrigger asChild>
          <Button variant="destructive">Apagar simulação</Button>
        </AlertDialogTrigger>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Apagar {sim.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              As execuções e os arquivos somem junto. Digite o nome da simulação para confirmar.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-1">
            <Label htmlFor="confirm-name">Nome da simulação</Label>
            <Input id="confirm-name" autoComplete="off" value={typed} onChange={(e) => setTyped(e.target.value)} />
          </div>
          {remove.isError && (
            <p role="alert" className="text-sm text-destructive">
              {errorMessage(remove.error)}
            </p>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            {/* a plain Button: AlertDialogAction would close the dialog before a 409 could show */}
            <Button
              variant="destructive"
              disabled={typed !== sim.name || remove.isPending}
              onClick={() => remove.mutate()}
            >
              Apagar
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  )
}
```

`errorMessage` devolve o `detail` do 409 ("Há uma execução em andamento."); confira em `web/src/lib/auth.ts` que um `detail` fora do mapa `MESSAGES` passa direto. Se não passar, use `remove.error.message`.

- [ ] **Step 2: Usar em `web/src/routes/_auth/w/$slug/simulacoes/$id.tsx`**

Import:

```tsx
import { DeleteSimulation } from '@/components/DeleteSimulation'
```

Em `SimulationPage`, troque `return <SimulationDetail slug={slug} id={id} />` por:

```tsx
  return <SimulationDetail slug={slug} id={id} isAdmin={roleIn(me, slug) === 'admin'} />
```

A assinatura de `SimulationDetail` passa a ser:

```tsx
function SimulationDetail({ slug, id, isAdmin }: { slug: string; id: string; isAdmin: boolean }) {
```

E, no fim do `return` de `SimulationDetail`, depois do `</ValidationBlock>` e antes do `</div>` que fecha a página:

```tsx
      {isAdmin && <DeleteSimulation slug={slug} sim={sim} />}
```

(o platform admin chega aqui como `admin`: o `/api/me` devolve todos os workspaces com esse papel para ele.)

- [ ] **Step 3: Build e lint**

Run: `cd web && bun run build && bun run lint`
Expected: sem erros

- [ ] **Step 4: Commit**

```bash
git add web/src/components/DeleteSimulation.tsx 'web/src/routes/_auth/w/$slug/simulacoes/$id.tsx'
git commit -m "feat(web): workspace admins delete a simulation after typing its name"
```

---

### Task 3: E2E

**Files:**
- Modify: `web/e2e/admin.spec.ts`
- Modify: `web/e2e/simulations.spec.ts`

- [ ] **Step 1: Teste do uso em `web/e2e/admin.spec.ts`**

Imports (substituem os atuais):

```ts
import { readFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import { createAdmin, createWorkspace, loggedInAdmin, runToCompletion } from './helpers'
```

No fim do arquivo:

```ts
test('platform admin sees a finished run in the usage and exports it', async ({ page }) => {
  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  await runToCompletion(page, slug, 'Uso do mês')

  await page.goto('/admin/workspaces')
  await page.getByRole('link', { name: 'Uso' }).click()
  const row = page.getByRole('row').filter({ hasText: `Marca ${slug}` })
  // columns: Mês, Workspace, Usuário, Concluídas, …, Total
  await expect(row.getByRole('cell').nth(2)).toHaveText('E2E')
  await expect(row.getByRole('cell').nth(3)).toHaveText('1')
  await expect(row.getByRole('cell').nth(7)).toHaveText('1')

  const download = page.waitForEvent('download')
  await page.getByRole('link', { name: 'Exportar CSV' }).click()
  const file = await download
  expect(file.suggestedFilename()).toMatch(/^uso-\d{4}-\d{2}\.csv$/)
  expect(readFileSync(await file.path(), 'utf8')).toContain(`Marca ${slug};E2E;`)

  await page.getByRole('button', { name: 'Todos os meses' }).click()
  await expect(page).toHaveURL(/month=todos/)
  await expect(page.getByRole('row').filter({ hasText: `Marca ${slug}` })).toBeVisible()
})
```

O `createAdmin` cria o platform admin com o nome "E2E", e ele é admin de todo workspace, então roda a simulação ele mesmo.

- [ ] **Step 2: Teste do apagar em `web/e2e/simulations.spec.ts`**

Acrescente `runToCompletion` ao import de `./helpers` (em ordem alfabética, depois de `newSession`). No fim do arquivo:

```ts
test('workspace admin deletes a simulation and its runs; analysts never see the button', async ({
  page,
  browser,
}) => {
  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  const analystPage = await newSession(browser, await addMember(page, slug, 'analyst'))

  const runUrl = await runToCompletion(page, slug, 'Descartável')
  await page.getByRole('link', { name: '← Descartável' }).click()
  const simUrl = page.url()

  await analystPage.goto(simUrl)
  await expect(analystPage.getByRole('heading', { name: 'Descartável' })).toBeVisible()
  await expect(analystPage.getByRole('button', { name: 'Apagar simulação' })).toHaveCount(0)

  await page.getByRole('button', { name: 'Apagar simulação' }).click()
  const confirm = page.getByRole('button', { name: 'Apagar', exact: true })
  await expect(confirm).toBeDisabled()
  await page.getByLabel('Nome da simulação').fill('Descartáve')
  await expect(confirm).toBeDisabled()
  await page.getByLabel('Nome da simulação').fill('Descartável')
  await confirm.click()

  await expect(page).toHaveURL(new RegExp(`/w/${slug}$`))
  await expect(page.getByText('Descartável')).toHaveCount(0)
  await page.goto(runUrl)
  await expect(page.getByText('Execução não encontrada.')).toBeVisible()
  await analystPage.goto(simUrl)
  await expect(analystPage.getByText('Simulação não encontrada.')).toBeVisible()
})
```

- [ ] **Step 3: Rodar**

Run: `cd web && bun run e2e`
Expected: PASS (todos, incluindo os 2 novos). Se um seletor bater em dois elementos, ajuste o seletor, não o texto da tela.

- [ ] **Step 4: Commit**

```bash
git add web/e2e/admin.spec.ts web/e2e/simulations.spec.ts
git commit -m "test(web): e2e for the usage page and deleting a simulation"
```

---

### Task 4: verificação visual e fechamento

**Files:**
- Modify: `docs/decisoes/infra-e-operacao.md`, `docs/decisoes/upload-e-storage.md`, `docs/m2/trilha-b-plataforma.md`, `CLAUDE.md`

Os arquivos de docs usam CRLF: edite com a ferramenta `Edit`, não com `sed`.

- [ ] **Step 1: Screenshots**

Com `mise run api` e `mise run web` no ar e o MCP `playwright`, em `http://localhost:5173`, como platform admin com ao menos um run no banco de dev:
- `/admin/uso` no mês atual e com "Todos os meses";
- a página de uma simulação com a seção "Apagar simulação" e o diálogo aberto (botão desabilitado e habilitado);
- os dois temas (claro e escuro).

Confira se a tabela de uso cabe em 1280 px e se os números ficam alinhados à direita. Corrija o que aparecer antes de seguir.

- [ ] **Step 2: `docs/decisoes/infra-e-operacao.md`**

No fim da seção `## Uso derivado de `runs` (B9)`, acrescente o parágrafo:

```markdown
A tela `/admin/uso` guarda o mês no search param (`month=YYYY-MM`, ou `todos`; sem o param, o mês atual do navegador). O tempo vem somado em segundos da API e a tela só formata ("1 h 05 min"). "Exportar CSV" é um link para a rota `.csv` com o mesmo filtro.
```

- [ ] **Step 3: `docs/decisoes/upload-e-storage.md`**

Na seção `## Telas (B2b)`, troque o título por `## Telas (B2b e B9b)` e acrescente no fim da seção:

```markdown
- **Apagar pede o nome.** A seção "Apagar simulação" fica no fim da página e só aparece para admin. O diálogo só habilita o botão com o nome exato digitado, e o botão é um `Button` comum, não o `AlertDialogAction`, para o 409 (run em andamento) aparecer no próprio diálogo. Ao apagar, a tela navega para a lista antes de descartar a query da simulação, senão ela seria buscada de novo e daria 404.
```

- [ ] **Step 4: `docs/m2/trilha-b-plataforma.md`**

Na linha `Status` do B9, troque `🟡 em andamento` por `✅ feito` e "Falta o B9b (telas)." por "B9b (telas) em <data de hoje>, verificado por `web/e2e/admin.spec.ts` (uso com o run, CSV, todos os meses) e `web/e2e/simulations.spec.ts` (apagar com confirmação, analista sem o botão) e screenshots nos dois temas."

- [ ] **Step 5: `CLAUDE.md`**

No "Estado atual", depois da frase do B9a, acrescente:

```markdown
**B9b (uso e apagar telas) concluído em <data de hoje>**: `/admin/uso` com filtro por mês e export CSV, "Apagar simulação" com confirmação pelo nome para o admin do workspace.
```

e troque "Faltam: B9b, B7 (depende do B5), B8," por "Faltam: B7 (depende do B5), B8,".

Troque `<data de hoje>` pela data real no formato `28/out/2026`.

- [ ] **Step 6: Commit**

```bash
git add docs/decisoes/infra-e-operacao.md docs/decisoes/upload-e-storage.md docs/m2/trilha-b-plataforma.md CLAUDE.md
git commit -m "docs: record the b9b usage and delete screens"
```
