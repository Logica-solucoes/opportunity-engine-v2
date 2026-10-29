# B8b · Conectores Google Ads e GA4 — telas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O platform admin configura o conector Google de cada workspace em `/admin/workspaces`. O analista de um workspace com conector importa um período na página da simulação e vê os arquivos, o mapeamento e o report preenchidos.

**Architecture:**
- Dois componentes novos, cada um com sua mutation:
  - `GoogleConnectorDialog` (admin) faz `PUT`/`DELETE …/google`;
  - `GoogleImport` (simulação) faz `POST …/google-import` e devolve o `SimulationOut` ao mesmo `saved` do upload.
- O `Me` ganha `google: boolean`, que decide se o import aparece.
- O `errorMessage` passa a mostrar a frase pt-BR de um 5xx que a traga, como o 502 do BigQuery.
- O E2E aponta `GOOGLE_APPLICATION_CREDENTIALS` para um arquivo inexistente. Assim o import em si roda de ponta a ponta até o BigQuery e volta com "sem credenciais", sem fake dentro da app.

**Tech Stack:** Vite + React 19 + TypeScript, TanStack Router/Query, shadcn (`radix-nova`), Playwright, `bun`.

Spec: `docs/superpowers/specs/2026-10-29-b8-conectores-google-design.md` (seção B8b). **Depende do B8a concluído** (plano `2026-10-29-b8a-conectores-google-backend.md`). Antes, leia `CODE-STYLE.md` e a seção "Verificar mudanças no frontend" do `CLAUDE.md`.

**Cuidado com o dev server:** escreva em `web/src/routes/**` com `Write`/`Edit`, nunca com heredoc de shell. O gerador do TanStack Router reescreve o arquivo com um placeholder se ler conteúdo vazio.

---

## Arquivos

| Arquivo | Mudança |
|---|---|
| `web/src/lib/auth.ts` | `Me.workspaces[].google`; `errorMessage` passa a frase dos 5xx |
| `web/src/components/GoogleConnectorDialog.tsx` | **novo**: tipo `GoogleConfig`, formulário, salvar e remover |
| `web/src/routes/_auth/admin/workspaces.tsx` | coluna "Conector Google" com selo e botão que abre o diálogo |
| `web/src/components/GoogleImport.tsx` | **novo**: período + "Importar" |
| `web/src/routes/_auth/w/$slug/simulacoes/$id.tsx` | `GoogleImport` na seção Arquivos quando o workspace tem conector |
| `web/e2e/env.ts` | `GOOGLE_APPLICATION_CREDENTIALS` inexistente, `GOOGLE_CLOUD_PROJECT` |
| `web/e2e/helpers.ts` | `configureGoogle` |
| `web/e2e/admin.spec.ts` | configurar, editar e remover o conector |
| `web/e2e/simulations.spec.ts` | import visível só com conector; erro do BigQuery na tela |
| docs | fechamento (Task 4) |

Ordem: as Tasks 1 e 2 mexem em arquivos diferentes, exceto o `auth.ts`, que é da Task 1. A Task 2 depende do `google` no `Me`, então rode em série: 1 → 2 → 3 → 4.

Antes de começar: B8a no `main`, `docker compose up -d`, `cd web && bun install`, e `mise run e2e` verde.

---

### Task 1: `/admin/workspaces` com o conector Google

**Files:**
- Modify: `web/src/lib/auth.ts`
- Create: `web/src/components/GoogleConnectorDialog.tsx`
- Modify: `web/src/routes/_auth/admin/workspaces.tsx`
- Modify: `web/e2e/helpers.ts`
- Modify: `web/e2e/admin.spec.ts`

- [ ] **Step 1: Escrever o E2E, que vai falhar**

Em `web/e2e/helpers.ts`, acrescente:

```ts
export async function configureGoogle(page: Page, slug: string) {
  await page.goto('/admin/workspaces')
  await page.getByRole('row').filter({ hasText: slug }).getByRole('button', { name: 'Conector Google' }).click()
  await page.getByLabel('Dataset do Google Ads').fill('proj-teste.google_ads')
  await page.getByLabel('Customer ids').fill('123-456-7890, 2222222222')
  await page.getByLabel('Dataset do GA4').fill('proj-teste.analytics_123')
  await page.getByLabel('Evento do KPI').fill('purchase')
  await page.getByLabel('Métrica').selectOption('revenue')
  await page.getByRole('button', { name: 'Salvar' }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(page.getByRole('row').filter({ hasText: slug }).getByText('configurado')).toBeVisible()
}
```

Em `web/e2e/admin.spec.ts`, importe `configureGoogle` e acrescente:

```ts
test('platform admin configures, edits and removes the google connector', async ({ page }) => {
  await loggedInAdmin(page)
  const slug = await createWorkspace(page)
  await configureGoogle(page, slug)

  await page.reload()
  const row = page.getByRole('row').filter({ hasText: slug })
  await expect(row.getByText('configurado')).toBeVisible()
  await row.getByRole('button', { name: 'Conector Google' }).click()
  await expect(page.getByLabel('Customer ids')).toHaveValue('1234567890, 2222222222')
  await expect(page.getByLabel('Métrica')).toHaveValue('revenue')

  await page.getByLabel('Customer ids').fill('1234567890, 1234567890')
  await page.getByRole('button', { name: 'Salvar' }).click()
  await expect(page.getByText('Cada customer id tem 10 dígitos, sem repetir.')).toBeVisible()

  await page.getByRole('button', { name: 'Remover conector' }).click()
  await page.getByRole('button', { name: 'Remover', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(row.getByText('configurado')).toHaveCount(0)
})
```

`1234567890, 1234567890` passa no `pattern` do navegador e só o servidor recusa. Isso prova que o 422 do pydantic aparece no campo.

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd web && bunx playwright test e2e/admin.spec.ts -g "google connector"` (com `mise run e2e` já tendo feito o build ao menos uma vez; se o `bunx playwright test` não fizer o build sozinho, use `mise run e2e -- -g "google connector"`)
Expected: FAIL, sem botão "Conector Google".

- [ ] **Step 3: `google` no `Me` e frase dos 5xx**

Em `web/src/lib/auth.ts`:
- troque o tipo dos workspaces do `Me`:

```ts
  // google: the workspace has the Google connector; its datasets never reach non-admins
  workspaces: { slug: string; name: string; role: Role; google: boolean }[]
```

- troque a linha `if (error.status >= 500) return 'Erro no servidor. Tente de novo.'` por:

```ts
  // a 5xx with our own sentence (the 502 of the Google connector) says what failed; a bare one doesn't
  if (error.status >= 500 && typeof error.body.detail !== 'string') return 'Erro no servidor. Tente de novo.'
```

O 503 `busy` continua saindo do `MESSAGES`, que vem antes. Um 500 do FastAPI chega como texto, sem `detail`, e cai na frase genérica.

- [ ] **Step 4: O diálogo**

Crie `web/src/components/GoogleConnectorDialog.tsx`:

```tsx
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { NativeSelect } from '@/components/NativeSelect'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import { errorMessage, meQuery } from '@/lib/auth'
import { fieldErrors } from '@/lib/params'

export type GoogleConfig = {
  ads: { dataset: string; customer_ids: string[] }
  ga4: { dataset: string; event: string; metric: 'count' | 'revenue' }
}

export type AdminWorkspace = { id: number; name: string; slug: string; created_at: string; google: GoogleConfig | null }

// same rules as GoogleConfig in api/google_import.py; the server checks again
const DATASET = '[a-z][a-z0-9\\-]{4,28}[a-z0-9]\\.[A-Za-z0-9_]{1,1024}'
const DATASET_HINT = 'projeto.dataset, como meu-projeto.google_ads'

// the server's pydantic error is per field; the hint says what the field needs
const HINTS: Record<string, string> = {
  'ads.dataset': `Use ${DATASET_HINT}.`,
  'ads.customer_ids': 'Cada customer id tem 10 dígitos, sem repetir.',
  'ga4.dataset': 'Use projeto.dataset, como meu-projeto.analytics_123456.',
  'ga4.event': 'Nome de evento do GA4: letras, números e _, começando por letra.',
}

const splitIds = (text: string) => text.split(/[\s,;]+/).map((id) => id.replace(/-/g, '')).filter(Boolean)

type Props = { workspace: AdminWorkspace | null; onClose: () => void }

export function GoogleConnectorDialog({ workspace, onClose }: Props) {
  return (
    <Dialog open={workspace !== null} onOpenChange={(open) => !open && onClose()}>
      {/* keyed: each workspace opens with its own saved values */}
      {workspace && <ConnectorForm key={workspace.id} workspace={workspace} onClose={onClose} />}
    </Dialog>
  )
}

function ConnectorForm({ workspace, onClose }: { workspace: AdminWorkspace; onClose: () => void }) {
  const queryClient = useQueryClient()
  const google = workspace.google
  const [confirmRemove, setConfirmRemove] = useState(false)
  const done = () => {
    queryClient.invalidateQueries({ queryKey: ['admin', 'workspaces'] })
    queryClient.invalidateQueries({ queryKey: meQuery.queryKey })
    onClose()
  }
  const save = useMutation({
    mutationFn: (body: GoogleConfig) => api(`/admin/workspaces/${workspace.id}/google`, { method: 'PUT', body }),
    onSuccess: done,
  })
  const remove = useMutation({
    mutationFn: () => api<void>(`/admin/workspaces/${workspace.id}/google`, { method: 'DELETE' }),
    onSuccess: done,
  })
  const errors = fieldErrors(save.error)
  const hint = (path: string) =>
    errors && Object.keys(errors).some((k) => k.startsWith(path)) ? (
      <p className="text-sm text-destructive">{HINTS[path]}</p>
    ) : null

  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    const text = (name: string) => String(form.get(name)).trim()
    save.mutate({
      ads: { dataset: text('ads.dataset'), customer_ids: splitIds(text('ads.customer_ids')) },
      ga4: { dataset: text('ga4.dataset'), event: text('ga4.event'), metric: text('ga4.metric') as 'count' | 'revenue' },
    })
  }

  return (
    <DialogContent>
      <DialogHeader>
        <DialogTitle>Conector Google · {workspace.name}</DialogTitle>
        <DialogDescription>
          Datasets do BigQuery que a service account da plataforma lê: o do Data Transfer do Google Ads e o do export
          do GA4.
        </DialogDescription>
      </DialogHeader>
      <form id="google-connector" onSubmit={submit} className="space-y-4">
        <fieldset className="space-y-3">
          <legend className="text-sm font-medium">Google Ads</legend>
          <div className="space-y-1">
            <Label htmlFor="ads.dataset">Dataset do Google Ads</Label>
            <Input
              id="ads.dataset"
              name="ads.dataset"
              required
              pattern={DATASET}
              title={DATASET_HINT}
              defaultValue={google?.ads.dataset}
            />
            {hint('ads.dataset')}
          </div>
          <div className="space-y-1">
            <Label htmlFor="ads.customer_ids">Customer ids</Label>
            <Input
              id="ads.customer_ids"
              name="ads.customer_ids"
              required
              placeholder="123-456-7890, 987-654-3210"
              defaultValue={google?.ads.customer_ids.join(', ')}
            />
            <p className="text-xs text-muted-foreground">Separados por vírgula; o spend das contas é somado.</p>
            {hint('ads.customer_ids')}
          </div>
        </fieldset>
        <fieldset className="space-y-3">
          <legend className="text-sm font-medium">GA4</legend>
          <div className="space-y-1">
            <Label htmlFor="ga4.dataset">Dataset do GA4</Label>
            <Input
              id="ga4.dataset"
              name="ga4.dataset"
              required
              pattern={DATASET}
              title={DATASET_HINT}
              defaultValue={google?.ga4.dataset}
            />
            {hint('ga4.dataset')}
          </div>
          <div className="flex flex-wrap gap-4">
            <div className="space-y-1">
              <Label htmlFor="ga4.event">Evento do KPI</Label>
              <Input
                id="ga4.event"
                name="ga4.event"
                required
                pattern="[A-Za-z][A-Za-z0-9_]{0,39}"
                placeholder="purchase"
                defaultValue={google?.ga4.event}
              />
              {hint('ga4.event')}
            </div>
            <div className="space-y-1">
              <Label htmlFor="ga4.metric">Métrica</Label>
              <NativeSelect id="ga4.metric" name="ga4.metric" defaultValue={google?.ga4.metric ?? 'count'}>
                <option value="count">Contagem de eventos</option>
                <option value="revenue">Receita (purchase_revenue)</option>
              </NativeSelect>
            </div>
          </div>
        </fieldset>
      </form>
      {(save.isError && !errors) || remove.isError ? (
        <p role="alert" className="text-sm text-destructive">
          {errorMessage(save.error ?? remove.error)}
        </p>
      ) : null}
      <DialogFooter className="sm:justify-between">
        {google &&
          (confirmRemove ? (
            <div className="flex items-center gap-2">
              <span className="text-sm">Remover o conector?</span>
              <Button variant="destructive" size="sm" disabled={remove.isPending} onClick={() => remove.mutate()}>
                Remover
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setConfirmRemove(false)}>
                Cancelar
              </Button>
            </div>
          ) : (
            <Button variant="outline" onClick={() => setConfirmRemove(true)}>
              Remover conector
            </Button>
          ))}
        <Button type="submit" form="google-connector" disabled={save.isPending}>
          Salvar
        </Button>
      </DialogFooter>
    </DialogContent>
  )
}
```

A confirmação de remover fica inline no rodapé, e não num `AlertDialog` dentro do `Dialog`: diálogo aninhado no Radix briga pelo foco. O conector se recria em segundos, então a confirmação simples basta.

- [ ] **Step 5: A coluna na tabela**

Em `web/src/routes/_auth/admin/workspaces.tsx`, com `Edit`:
- troque o `type Workspace = …` por `import { type AdminWorkspace, GoogleConnectorDialog } from '@/components/GoogleConnectorDialog'` e use `AdminWorkspace` onde estava `Workspace` (no `useQuery` e no `useMutation`);
- importe `Badge` de `@/components/ui/badge`;
- no componente, crie o estado do diálogo: `const [editing, setEditing] = useState<AdminWorkspace | null>(null)`;
- no `TableHeader`, entre "Criado em" e a coluna vazia, acrescente `<TableHead>Conector Google</TableHead>`;
- em cada linha, na mesma posição:

```tsx
              <TableCell>
                <div className="flex items-center gap-2">
                  {w.google && <Badge variant="secondary">configurado</Badge>}
                  <Button variant="outline" size="sm" onClick={() => setEditing(w)}>
                    Conector Google
                  </Button>
                </div>
              </TableCell>
```

- depois da `</Table>`: `<GoogleConnectorDialog workspace={editing} onClose={() => setEditing(null)} />`.

- [ ] **Step 6: Build, lint e E2E**

```bash
cd web && bun run build && bun run lint
mise run e2e -- -g "google connector"
```

Expected: build e lint limpos, E2E passa.

- [ ] **Step 7: Commit**

```bash
git add web/src/lib/auth.ts web/src/components/GoogleConnectorDialog.tsx web/src/routes/_auth/admin/workspaces.tsx web/e2e/helpers.ts web/e2e/admin.spec.ts
git commit -m "feat(web): platform admin configures the google connector per workspace"
```

---

### Task 2: "Importar do Google" na simulação

**Files:**
- Create: `web/src/components/GoogleImport.tsx`
- Modify: `web/src/routes/_auth/w/$slug/simulacoes/$id.tsx`
- Modify: `web/e2e/env.ts`
- Modify: `web/e2e/simulations.spec.ts`

- [ ] **Step 1: Ambiente do E2E sem credenciais do Google**

Em `web/e2e/env.ts`, acrescente ao `pyEnv`:

```ts
  // no Google credentials even if the dev shell has some: the import reaches BigQuery's client and comes back
  // with "sem credenciais", which is the whole path short of a real dataset
  GOOGLE_APPLICATION_CREDENTIALS: join(tmpdir(), 'gem-e2e-no-such-credentials.json'),
  GOOGLE_CLOUD_PROJECT: 'gem-e2e',
```

- [ ] **Step 2: Escrever o E2E, que vai falhar**

Em `web/e2e/simulations.spec.ts`, importe `configureGoogle` e acrescente:

```ts
test('analyst imports from google only where the workspace has the connector', async ({ page, browser }) => {
  await loggedInAdmin(page)
  const withGoogle = await createWorkspace(page)
  const without = await createWorkspace(page)
  await configureGoogle(page, withGoogle)
  const analyst = await addMember(page, withGoogle, 'analyst')
  const other = await addMember(page, without, 'analyst')

  const analystPage = await newSession(browser, analyst)
  await createSimulation(analystPage, withGoogle, 'Do Google')
  await expect(analystPage.getByLabel('Início')).toHaveValue(/^\d{4}-\d{2}-\d{2}$/)
  await analystPage.getByRole('button', { name: 'Importar do Google' }).click()
  await expect(analystPage.getByText('Conector Google sem credenciais neste ambiente.')).toBeVisible()
  await expect(analystPage.getByRole('button', { name: 'Importar do Google' })).toBeEnabled()

  const otherPage = await newSession(browser, other)
  await createSimulation(otherPage, without, 'Sem Google')
  await expect(otherPage.getByLabel('Arquivo de investimento')).toBeAttached()
  await expect(otherPage.getByRole('button', { name: 'Importar do Google' })).toHaveCount(0)
})
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `mise run e2e -- -g "imports from google"`
Expected: FAIL, sem campo "Início".

- [ ] **Step 4: O componente**

Crie `web/src/components/GoogleImport.tsx`:

```tsx
import { useMutation } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import { errorMessage } from '@/lib/auth'
import type { Simulation } from '@/lib/simulations'

// YYYY-MM-DD in the browser's time zone (sv-SE formats dates that way)
const daysAgo = (n: number) => {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return d.toLocaleDateString('sv-SE')
}

type Props = { slug: string; sim: Simulation; busy: boolean; onSaved: (sim: Simulation) => void }

export function GoogleImport({ slug, sim, busy, onSaved }: Props) {
  const [start, setStart] = useState(() => daysAgo(730))
  const [end, setEnd] = useState(() => daysAgo(1))
  const run = useMutation({
    mutationFn: () =>
      api<Simulation>(`/w/${slug}/simulations/${sim.id}/google-import`, { method: 'POST', body: { start, end } }),
    onSuccess: onSaved,
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    run.mutate()
  }

  return (
    <form onSubmit={submit} className="space-y-2 rounded-md border p-4">
      <p className="text-sm">
        <span className="font-medium">Ou importe do Google:</span> investimento do Google Ads e KPI do GA4 do
        período, no lugar dos arquivos de investimento e performance.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <Label htmlFor="google-start">Início</Label>
          <Input
            id="google-start"
            type="date"
            className="w-40"
            required
            max={end}
            value={start}
            onChange={(e) => setStart(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="google-end">Fim</Label>
          <Input
            id="google-end"
            type="date"
            className="w-40"
            required
            min={start}
            max={daysAgo(0)}
            value={end}
            onChange={(e) => setEnd(e.target.value)}
          />
        </div>
        <Button type="submit" disabled={busy}>
          {run.isPending ? 'Consultando o BigQuery…' : 'Importar do Google'}
        </Button>
      </div>
      {run.isError && (
        <p role="alert" className="text-sm text-destructive">
          {errorMessage(run.error)}
        </p>
      )}
    </form>
  )
}
```

O teto de 3 anos fica com o servidor, que devolve 422; o `errorMessage` mostra "Dados inválidos." O `busy` vem do `useIsMutating` da página, então o próprio import também trava o botão.

- [ ] **Step 5: Na página da simulação**

Em `web/src/routes/_auth/w/$slug/simulacoes/$id.tsx`, com `Edit`:
- importe `GoogleImport` de `@/components/GoogleImport`;
- no `SimulationPage`, passe o conector:

```tsx
  const workspace = me.workspaces.find((w) => w.slug === slug)
  if (workspace?.role === 'viewer') return <p>Sem permissão para editar simulações deste workspace.</p>
  return <SimulationDetail slug={slug} id={id} isAdmin={workspace?.role === 'admin'} google={Boolean(workspace?.google)} />
```

  e tire o `roleIn` do import de `@/lib/auth` se ele ficar sem uso;
- no `SimulationDetail`, acrescente `google` às props (`{ slug, id, isAdmin, google }: { …; google: boolean }`);
- na seção "Arquivos", depois da `div` do grid dos `FileCard`:

```tsx
        {google && <GoogleImport slug={slug} sim={sim} busy={busy} onSaved={saved} />}
```

- [ ] **Step 6: Build, lint e E2E**

```bash
cd web && bun run build && bun run lint
mise run e2e
```

Expected: tudo verde. O `mise run e2e` inteiro roda porque o `errorMessage` e o `/me` mudaram.

- [ ] **Step 7: Commit**

```bash
git add web/src/components/GoogleImport.tsx "web/src/routes/_auth/w/\$slug/simulacoes/\$id.tsx" web/e2e/env.ts web/e2e/simulations.spec.ts
git commit -m "feat(web): import a simulation's data from google"
```

---

### Task 3: verificação visual

Sem código novo. Se algo quebrar, corrija na task de origem e commite como `fix(web): …`.

- [ ] **Step 1: Subir a app**

`docker compose up -d`, `mise run api` e `mise run web`. Entre como platform admin no `http://localhost:5173`.

- [ ] **Step 2: Screenshots com o MCP `playwright`**

Nos dois temas (o seletor de tema está no cabeçalho):
1. `/admin/workspaces` com um workspace configurado (selo) e outro não;
2. o diálogo aberto com valores salvos, e o mesmo diálogo com o erro de customer id repetido;
3. a página de uma simulação desse workspace, com o bloco "Ou importe do Google" e o erro do BigQuery embaixo.

  Sem credenciais, a API de dev responde "Conector Google sem credenciais neste ambiente.".

- [ ] **Step 3: Import de verdade, se houver sandbox**

Se a Task 4 do B8a rodou contra um sandbox, faça o import com dado real:
1. reinicie a API com `GOOGLE_CLOUD_PROJECT=<projeto>` (e o ADC do `gcloud auth application-default login`);
2. configure o workspace com o Ads `"<projeto>.b8_ads_seed"`, customer ids `1111111111, 2222222222`, GA4 `bigquery-public-data.ga4_obfuscated_sample_ecommerce`, evento `purchase`, métrica "Contagem de eventos";
3. importe de `2026-01-01` a `2026-01-10`.

O GA4 público só tem 2020/21, então o esperado é a mensagem "Nenhum evento 'purchase' no GA4 neste período.". Isso prova que o Ads passou.

Depois:
1. importe de `2020-11-01` a `2020-11-30`;
2. desta vez o esperado é "Nenhum investimento no Google Ads neste período.", porque o seed do Ads é de 2026;
3. tire o screenshot.

Os dois datasets de teste não se sobrepõem no tempo, então um import completo com sucesso só sai com dado real ou com um seed do Ads em nov/2020. Se quiser o screenshot de sucesso, troque as datas do `seed_ads.sql` para `2020-11-01`..`2020-11-10` só localmente, sem commitar.

Registre no relatório da task o que foi visto.

---

### Task 4: fechamento da documentação

**Files:**
- Modify: `CLAUDE.md`, `docs/m2/trilha-b-plataforma.md`, `docs/decisoes/conectores-google.md`

- [ ] **Step 1: `docs/decisoes/conectores-google.md`**

Acrescente ao fim:

```markdown
## Telas

- O import aparece na página da simulação só quando o `/api/me` diz `google: true` para o workspace. O analista nunca vê dataset nem customer id.
- Erro do BigQuery chega como 502 com a frase pt-BR. O `errorMessage` do front mostra a frase de qualquer 5xx que a traga, e só o 5xx sem `detail` (um 500 do FastAPI, um 502 do proxy) vira "Erro no servidor".
- O E2E aponta `GOOGLE_APPLICATION_CREDENTIALS` para um arquivo que não existe. O import roda de verdade até o cliente do BigQuery e volta "sem credenciais", e assim o teste cobre rota, botão e mensagem sem fake dentro da app. O resto (SQL, grade, mapeamento) está no pytest e no teste contra o sandbox.
- A confirmação de "Remover conector" fica no rodapé do próprio diálogo: um `AlertDialog` dentro do `Dialog` brigaria pelo foco, e o conector se recria em segundos.
```

- [ ] **Step 2: `docs/m2/trilha-b-plataforma.md`**

Troque a linha `- **Status:** 🟡 B8a …` do B8 por:

```markdown
- **Status:** ✅ feito, com o aceite de ±1% pendente. B8a (backend) em <data do B8a>, verificado por `tests/api/test_google_import.py`, `tests/api/test_admin.py`, `tests/api/test_rbac.py` e `tests/api/test_bigquery_live.py` (<o que o B8a registrou>). B8b (telas) em <data>, verificado por `web/e2e/admin.spec.ts` (configurar, editar, erro por campo, remover) e `web/e2e/simulations.spec.ts` (import só com conector, erro do BigQuery na tela) e screenshots nos dois temas. Pendente: total do período contra o Google Ads UI (±1%) quando houver acesso a uma conta Core com DTS. Respostas do "Em aberto" e desvios em `docs/decisoes/conectores-google.md`.
```

Preencha os `<…>` com o que está na linha atual e com a data do dia.

- [ ] **Step 3: `CLAUDE.md`**

No "Estado atual":
- depois do parágrafo do B8a, acrescente:

  > **B8b (telas do conector) concluído em <data>**: diálogo "Conector Google" em `/admin/workspaces` (datasets, customer ids, evento e métrica do GA4; remover), "Importar do Google" com período na página da simulação, visível só em workspace com conector.

- troque `B8b (telas do conector), ` por nada na frase `Faltam:`.

- [ ] **Step 4: Verificar e commitar**

```bash
uv run pytest -q
cd web && bun run build && bun run lint && cd ..
mise run e2e
git add CLAUDE.md docs/m2/trilha-b-plataforma.md docs/decisoes/conectores-google.md
git commit -m "docs: b8b google connectors screens"
```
