# B4b · Jobs e log (tela) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** O analista clica em Rodar na simulação, cai na página do run, acompanha o log ao vivo (com retomada ao recarregar) e vê os runs da simulação listados.

**Architecture:** Tipos, queries, rótulos e o hook `useRunLog` (sobre o `EventSource` nativo) em `web/src/lib/runs.ts`. Página nova `/w/$slug/execucoes/$runId`. A página da simulação ganha o botão Rodar de verdade e o bloco "Execuções". Nenhuma conta no front além do relógio do "em andamento há N s".

**Tech Stack:** React 19, TypeScript, TanStack Router (file-based) e Query, shadcn (`radix-nova`), Playwright.

Pré-requisito: B4a concluído (`docs/superpowers/plans/2026-10-27-b4a-jobs-backend.md`). Spec: `docs/superpowers/specs/2026-10-27-b4-jobs-e-log-design.md`. Leia `CODE-STYLE.md` e a seção "Verificar mudanças no frontend" do `CLAUDE.md`.

---

## Mapa de arquivos

| Arquivo | Papel |
|---|---|
| `web/src/lib/runs.ts` (novo) | tipos `Run`/`LogLine`, `runQuery`, `simulationRunsQuery`, rótulos, `isActive`, `useRunLog` |
| `web/src/components/RunStatusBadge.tsx` (novo) | selo de status |
| `web/src/lib/simulations.ts` | `runBlockReason` com run ativo e sem a frase "em breve" |
| `web/src/routes/_auth/w/$slug/execucoes/$runId.tsx` (novo) | página do run |
| `web/src/routes/_auth/w/$slug/simulacoes/$id.tsx` | Rodar e "Execuções" |
| `web/src/routeTree.gen.ts` | regenerado pelo Vite (versionado) |
| `web/e2e/env.ts`, `web/e2e/simulations.spec.ts` | E2E do run |
| docs | `docs/decisoes/runs-e-jobs.md`, `docs/m2/trilha-b-plataforma.md`, `CLAUDE.md` |

Tasks 1 → 2 → 3 em ordem (2 e 3 dependem da 1; 3 linka para a rota da 2). A 4 depende de tudo.

Comandos rodam em `web/` salvo indicação. Depois de criar arquivo em `src/routes/`, rode `bunx vite build` uma vez antes do `bun run build` (o `tsc -b` roda antes de o plugin regenerar o `routeTree.gen.ts`). Com o dev server no ar, escreva arquivos de rota com `Write`/`Edit`, nunca com heredoc de shell.

---

### Task 1: `lib/runs.ts`, selo de status e `runBlockReason`

**Files:**
- Create: `web/src/lib/runs.ts`, `web/src/components/RunStatusBadge.tsx`
- Modify: `web/src/lib/simulations.ts:86-93`

- [ ] **Step 1: `web/src/lib/runs.ts`**

```ts
import { queryOptions } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from './api'

export type RunStatus = 'queued' | 'running' | 'succeeded' | 'inconclusive' | 'failed'

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
}

export type LogLine = { id: number; ts: string; level: 'info' | 'warning' | 'error'; message: string }

export const STATUS_LABELS: Record<RunStatus, string> = {
  queued: 'Na fila',
  running: 'Rodando',
  succeeded: 'Concluída',
  inconclusive: 'Inconclusiva',
  failed: 'Falhou',
}

export const isActive = (status: RunStatus) => status === 'queued' || status === 'running'

export const MAX_LINES = 300

export const runQuery = (slug: string, runId: string) =>
  queryOptions({
    queryKey: ['runs', slug, runId],
    queryFn: () => api<Run>(`/w/${slug}/runs/${runId}`),
    // queued → running has no event of its own; the log stream's `end` covers the last change
    refetchInterval: (q) => (q.state.data && isActive(q.state.data.status) ? 2000 : false),
  })

export const simulationRunsQuery = (slug: string, simulationId: number) =>
  queryOptions({
    queryKey: ['runs', slug, 'simulation', simulationId],
    queryFn: () => api<Run[]>(`/w/${slug}/simulations/${simulationId}/runs`),
    refetchInterval: (q) => (q.state.data?.some((r) => isActive(r.status)) ? 3000 : false),
  })

export type LogState = 'open' | 'ended' | 'lost'

export function useRunLog(slug: string, runId: string) {
  const [lines, setLines] = useState<LogLine[]>([])
  const [state, setState] = useState<LogState>('open')

  useEffect(() => {
    const source = new EventSource(`/api/w/${slug}/runs/${runId}/logs/stream`)
    source.onmessage = (e) => {
      const line: LogLine = { id: Number(e.lastEventId), ...JSON.parse(e.data) }
      // a reconnect resumes after Last-Event-ID, but StrictMode's second effect replays the backlog
      setLines((prev) => (prev.length && prev[prev.length - 1].id >= line.id ? prev : [...prev, line].slice(-MAX_LINES)))
    }
    source.addEventListener('end', () => {
      setState('ended')
      source.close()
    })
    // a dropped connection is retried by the browser; CLOSED means an answer it won't retry (401, 404)
    source.onerror = () => {
      if (source.readyState === EventSource.CLOSED) setState('lost')
    }
    return () => source.close()
  }, [slug, runId])

  return { lines, state }
}
```

- [ ] **Step 2: `web/src/components/RunStatusBadge.tsx`**

```tsx
import { Badge } from '@/components/ui/badge'
import { type RunStatus, STATUS_LABELS } from '@/lib/runs'

const VARIANTS: Record<RunStatus, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  queued: 'secondary',
  running: 'default',
  succeeded: 'outline',
  inconclusive: 'secondary',
  failed: 'destructive',
}

export function RunStatusBadge({ status }: { status: RunStatus }) {
  return <Badge variant={VARIANTS[status]}>{STATUS_LABELS[status]}</Badge>
}
```

- [ ] **Step 3: `runBlockReason`**

Em `web/src/lib/simulations.ts`, substitua a função inteira:

```ts
// display only: POST …/runs checks the same gate on the server (block_reason in api/runs.py)
export function runBlockReason(
  report: ValidationReport | null,
  confirmed: Set<number>,
  paramsSaved: boolean,
  hasActiveRun: boolean,
): string {
  if (hasActiveRun) return 'Já há uma execução em andamento.'
  if (!report) return 'Valide os arquivos antes de rodar.'
  if (!report.ok) return 'Corrija os erros antes de rodar.'
  if (report.checks.some((c, i) => c.level === 'warning' && !confirmed.has(i))) return 'Confirme os avisos antes de rodar.'
  if (!paramsSaved) return 'Salve os parâmetros antes de rodar.'
  return ''
}
```

- [ ] **Step 4: Ver o build quebrar no único chamador**

Run: `bun run build`
Expected: FAIL em `src/routes/_auth/w/$slug/simulacoes/$id.tsx` (`Expected 4 arguments, but got 3`). É o que a Task 3 conserta; não commite ainda. Para seguir, ajuste provisoriamente a chamada para `runBlockReason(report, confirmed, saved, false)` e rode de novo.
Expected: build ok.

Run: `bun run lint`
Expected: sem erros.

- [ ] **Step 5: Commit**

```bash
git add src/lib/runs.ts src/components/RunStatusBadge.tsx src/lib/simulations.ts 'src/routes/_auth/w/$slug/simulacoes/$id.tsx'
git commit -m "feat(web): add run types, queries and the log stream hook"
```

---

### Task 2: Página do run

**Files:**
- Create: `web/src/routes/_auth/w/$slug/execucoes/$runId.tsx`
- Modify: `web/src/routeTree.gen.ts` (gerado)

- [ ] **Step 1: Escrever a rota** (com `Write`)

```tsx
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, createFileRoute } from '@tanstack/react-router'
import { CircleX } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { RunStatusBadge } from '@/components/RunStatusBadge'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { type LogLine, isActive, runQuery, useRunLog } from '@/lib/runs'
import { formatDate } from '@/lib/simulations'

export const Route = createFileRoute('/_auth/w/$slug/execucoes/$runId')({ component: RunPage })

const LEVEL_CLASS: Record<LogLine['level'], string> = {
  info: '',
  warning: 'text-amber-600 dark:text-amber-400',
  error: 'text-destructive',
}

const formatTime = (iso: string) => new Date(iso).toLocaleTimeString('pt-BR')

function RunPage() {
  const { slug, runId } = Route.useParams()
  const queryClient = useQueryClient()
  const { data: run, isError } = useQuery(runQuery(slug, runId))
  const log = useRunLog(slug, runId)

  // the key is rebuilt inside: a fresh array in the deps would re-run this after every refetch
  useEffect(() => {
    if (log.state === 'ended') queryClient.invalidateQueries({ queryKey: runQuery(slug, runId).queryKey })
  }, [log.state, queryClient, slug, runId])

  // 404 covers another workspace, a run a viewer can't see yet and a non-numeric id
  if (!run) return isError ? <p>Execução não encontrada.</p> : null
  const active = isActive(run.status) && log.state !== 'ended'

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <Link
          to="/w/$slug/simulacoes/$id"
          params={{ slug, id: String(run.simulation.id) }}
          className="text-sm text-muted-foreground hover:text-primary"
        >
          ← {run.simulation.name}
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold">Execução #{run.id}</h1>
          <RunStatusBadge status={run.status} />
        </div>
        <p className="text-sm text-muted-foreground">
          {run.created_by_name} · {formatDate(run.created_at)}
        </p>
      </div>

      {run.status === 'failed' && run.error && (
        <Alert variant="destructive">
          <CircleX />
          <AlertTitle>Falhou</AlertTitle>
          <AlertDescription>{run.error}</AlertDescription>
        </Alert>
      )}
      {(run.status === 'succeeded' || run.status === 'inconclusive') && (
        <p>Execução concluída. Os dashboards chegam em breve.</p>
      )}

      <LogPanel lines={log.lines} active={active} />
      {log.state === 'lost' && (
        <p role="alert" className="text-sm text-destructive">
          Não foi possível acompanhar o log.
        </p>
      )}
    </div>
  )
}

function LogPanel({ lines, active }: { lines: LogLine[]; active: boolean }) {
  const box = useRef<HTMLDivElement>(null)
  // follow new lines only while the reader is at the bottom; scrolling up to read stops it
  const atEnd = useRef(true)

  useEffect(() => {
    const el = box.current
    if (el && atEnd.current) el.scrollTop = el.scrollHeight
  }, [lines])

  const last = lines.at(-1)
  return (
    <section className="space-y-2">
      <div className="flex flex-wrap items-baseline justify-between gap-4">
        <h2 className="text-lg font-medium">Log</h2>
        {active && last && <Elapsed since={last.ts} />}
      </div>
      <div
        ref={box}
        role="log"
        aria-label="Log da execução"
        onScroll={(e) => {
          const el = e.currentTarget
          atEnd.current = el.scrollHeight - el.scrollTop - el.clientHeight < 8
        }}
        className="h-96 overflow-auto rounded-md border bg-muted/30 p-3 font-mono text-xs leading-relaxed"
      >
        {lines.length === 0 && (
          <p className="text-muted-foreground">{active ? 'Aguardando o início da execução…' : 'Nenhuma linha de log.'}</p>
        )}
        {lines.map((line) => (
          <div key={line.id} className={LEVEL_CLASS[line.level]}>
            <span className="text-muted-foreground">{formatTime(line.ts)}</span> {line.message}
          </div>
        ))}
      </div>
    </section>
  )
}

function Elapsed({ since }: { since: string }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  // the browser's clock and the server's can disagree by a few seconds; never show a negative time
  const seconds = Math.max(0, Math.round((now - Date.parse(since)) / 1000))
  return <p className="text-sm text-muted-foreground">Etapa em andamento há {seconds} s</p>
}
```

- [ ] **Step 2: Regenerar a árvore e buildar**

Run: `bunx vite build && bun run build && bun run lint`
Expected: ok; `src/routeTree.gen.ts` passa a ter `/_auth/w/$slug/execucoes/$runId`.

- [ ] **Step 3: Commit**

```bash
git add 'src/routes/_auth/w/$slug/execucoes/$runId.tsx' src/routeTree.gen.ts
git commit -m "feat(web): add the run page with the live log panel"
```

---

### Task 3: Rodar e "Execuções" na simulação

**Files:**
- Modify: `web/src/routes/_auth/w/$slug/simulacoes/$id.tsx`

- [ ] **Step 1: Imports**

Troque as linhas de import do React Query, do Router e acrescente as novas:

```tsx
import { useIsMutating, useMutation, useQuery, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router'
```

```tsx
import { RunStatusBadge } from '@/components/RunStatusBadge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { type Run, isActive, simulationRunsQuery } from '@/lib/runs'
```

- [ ] **Step 2: Passar slug e id ao `ValidationBlock`**

Em `SimulationDetail`:

```tsx
      <ValidationBlock
        key={JSON.stringify(sim.validation)}
        slug={slug}
        simId={sim.id}
        report={sim.validation}
        saved={paramsSaved(sim)}
      >
```

- [ ] **Step 3: Novo `ValidationBlock`**

Substitua a assinatura, o estado e a barra do Rodar (os `Alert` de cada check ficam como estão):

```tsx
function ValidationBlock({
  slug,
  simId,
  report,
  saved,
  children,
}: {
  slug: string
  simId: number
  report: ValidationReport | null
  saved: boolean
  children?: ReactNode
}) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const runsQuery = simulationRunsQuery(slug, simId)
  const { data: runs } = useQuery(runsQuery)
  const activeRun = runs?.find((r) => isActive(r.status))
  // by index, since two checks may share an id; the server gets the ids of the confirmed ones
  const [confirmed, setConfirmed] = useState<Set<number>>(new Set())
  const start = useMutation({
    mutationFn: () =>
      api<Run>(`/w/${slug}/simulations/${simId}/runs`, {
        method: 'POST',
        body: {
          confirmed_warnings: (report?.checks ?? [])
            .filter((c, i) => c.level === 'warning' && confirmed.has(i))
            .map((c) => c.id),
        },
      }),
    onSuccess: (run) => {
      queryClient.invalidateQueries({ queryKey: runsQuery.queryKey })
      navigate({ to: '/w/$slug/execucoes/$runId', params: { slug, runId: String(run.id) } })
    },
  })
  const reason = runBlockReason(report, confirmed, saved, Boolean(activeRun))
```

`toggle` e o JSX dos checks não mudam. Troque o bloco final (o `div` com o `Button disabled` e o comentário "never enabled in B2") por:

```tsx
      <div className="flex flex-wrap items-center gap-3 border-t pt-4">
        <Button disabled={Boolean(reason) || start.isPending} onClick={() => start.mutate()}>
          Rodar
        </Button>
        {reason && (
          <p className="text-sm text-muted-foreground">
            {reason}{' '}
            {activeRun && (
              <Link
                to="/w/$slug/execucoes/$runId"
                params={{ slug, runId: String(activeRun.id) }}
                className="text-primary hover:underline"
              >
                Acompanhar
              </Link>
            )}
          </p>
        )}
        {start.isError && (
          <p role="alert" className="text-sm text-destructive">
            {errorMessage(start.error)}
          </p>
        )}
      </div>
      {runs && runs.length > 0 && <RunList slug={slug} runs={runs} />}
    </section>
  )
}

function RunList({ slug, runs }: { slug: string; runs: Run[] }) {
  return (
    <div className="space-y-2">
      <h3 className="font-medium">Execuções</h3>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Execução</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Criada por</TableHead>
            <TableHead>Criada em</TableHead>
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
              <TableCell>
                <RunStatusBadge status={r.status} />
              </TableCell>
              <TableCell>{r.created_by_name}</TableCell>
              <TableCell>{formatDate(r.created_at)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
```

O comentário `// confirmations live only in the page until B4 stores them with the run` sai (o novo fica acima do `useState`).

- [ ] **Step 4: Build e lint**

Run: `bun run build && bun run lint`
Expected: ok.

- [ ] **Step 5: Commit**

```bash
git add 'src/routes/_auth/w/$slug/simulacoes/$id.tsx'
git commit -m "feat(web): run a simulation and list its runs"
```

---

### Task 4: E2E

**Files:**
- Modify: `web/e2e/env.ts`, `web/e2e/simulations.spec.ts`

- [ ] **Step 1: Env do servidor E2E**

Em `pyEnv` (`web/e2e/env.ts`), depois de `GEMINI_API_KEY: ''`:

```ts
  // the worker subprocess inherits this env: ~3 s per run, long enough to reload mid-run
  FAKE_ENGINE_STEP_SECONDS: '0.5',
  FAKE_ENGINE_FAIL: '',
```

- [ ] **Step 2: Ajustar o teste de parâmetros**

Em `web/e2e/simulations.spec.ts`, no teste `parameters open with the data suggestions, save and persist`, troque

```ts
  await expect(analystPage.getByText('Execução disponível em breve')).toBeVisible()
```

por

```ts
  await expect(analystPage.getByRole('button', { name: 'Rodar' })).toBeEnabled()
```

- [ ] **Step 3: Teste do run** (no fim do mesmo arquivo, para reaproveitar `analystOnNewWorkspace`, `createSimulation` e `uploadTemplatesAndValidate`)

```ts
test('analyst runs a simulation and the log resumes after a reload', async ({ page, browser }) => {
  const { slug, analystPage } = await analystOnNewWorkspace(page, browser)
  await createSimulation(analystPage, slug, 'Rodada')
  await uploadTemplatesAndValidate(analystPage)
  await analystPage.getByRole('button', { name: 'Salvar parâmetros' }).click()

  await analystPage.getByRole('button', { name: 'Rodar' }).click()

  await expect(analystPage).toHaveURL(new RegExp(`/w/${slug}/execucoes/\\d+$`))
  const log = analystPage.getByRole('log', { name: 'Log da execução' })
  await expect(log.getByText('Lendo os arquivos de investimento e performance')).toBeVisible()

  await analystPage.reload()

  await expect(analystPage.getByText('Concluída', { exact: true })).toBeVisible()
  await expect(log.getByText('Lendo os arquivos de investimento e performance')).toBeVisible()
  await expect(log.getByText('Montando o resultado')).toBeVisible()
  await expect(analystPage.getByText('Execução concluída. Os dashboards chegam em breve.')).toBeVisible()

  await analystPage.getByRole('link', { name: '← Rodada' }).click()
  await expect(analystPage.getByRole('heading', { name: 'Execuções' })).toBeVisible()
  await expect(analystPage.getByRole('cell', { name: 'Concluída' })).toBeVisible()
  await expect(analystPage.getByRole('button', { name: 'Rodar' })).toBeEnabled()
})
```

- [ ] **Step 4: Rodar o E2E**

Na raiz do repo, com `docker compose up -d`: `mise run e2e`
Expected: todos passam, inclusive o novo. Se o novo falhar por tempo, veja o trace (`retain-on-failure`) antes de mexer no `FAKE_ENGINE_STEP_SECONDS`.

- [ ] **Step 5: Commit**

```bash
git add e2e/env.ts e2e/simulations.spec.ts
git commit -m "test(web): cover running a simulation and resuming its log"
```

---

### Task 5: Verificação visual e fechamento do B4

**Files:**
- Modify: `docs/decisoes/runs-e-jobs.md`, `docs/m2/trilha-b-plataforma.md`, `CLAUDE.md`

- [ ] **Step 1: Screenshots** (MCP `playwright`)

Na raiz: `mise run api` e `mise run web` em background (o worker do dev usa o default de 1 s por etapa). Logado como analyst numa simulação com parâmetros salvos:

1. clicar em Rodar e tirar screenshot da página do run **rodando** (selo "Rodando", linhas aparecendo, "Etapa em andamento há N s");
2. screenshot dela **concluída**;
3. screenshot do bloco "Execuções" na simulação;
4. repetir 1–3 no tema escuro (alternador no cabeçalho).

Para o caminho de erro, suba a API com `FAKE_ENGINE_FAIL=1` (`$env:FAKE_ENGINE_FAIL='1'; mise run api` no PowerShell), rode de novo e tire screenshot do card "Falhou" e da linha vermelha no log. Confira que nenhuma mensagem em inglês aparece na tela.

- [ ] **Step 2: `docs/decisoes/runs-e-jobs.md`**

Acrescente no fim:

```markdown
## Tela (B4b)

- **Página própria do run** (`/w/$slug/execucoes/$runId`), onde os dashboards do B5 vão entrar. A simulação lista os runs dela (até 20); a lista do workspace é do B6.
- **`EventSource` nativo**, sem lib. Ele reconecta sozinho mandando `Last-Event-ID`; um fechamento sem `end` (401, 404) vira "Não foi possível acompanhar o log." O hook descarta linha com id menor ou igual à última, porque o segundo efeito do StrictMode reabre o stream e recebe o backlog de novo.
- **Status por polling curto** enquanto o run está ativo (2 s na página, 3 s na lista): `queued → running` não tem evento próprio. O `end` do stream invalida a query na hora.
- **"Etapa em andamento há N s"** é o relógio do navegador menos o `ts` da última linha, nunca negativo (relógios diferentes). É exibição, não conta do motor.
- **Confirmações de aviso** continuam por índice na tela e viram `check.id` no `POST`.
- **Rodar com run ativo** fica desabilitado com "Já há uma execução em andamento." e o link para ela; o 409 do servidor cobre duas abas.
```

- [ ] **Step 3: Status do B4 no trilha-b**

Em `docs/m2/trilha-b-plataforma.md`, logo abaixo de `## B4 · Jobs assíncronos e log em tempo real — semana 2`:

```markdown
- **Status:** ✅ feito. B4a (backend) em <data>, verificado por `tests/api/test_runs.py` (gate, snapshot, worker, run morto, SSE com retomada, isolamento entre workspaces, erro do motor em pt-BR com traceback só no stdout) e `tests/api/test_rbac.py`; B4b (tela) em <data>, verificado por `web/e2e/simulations.spec.ts` (rodar, log ao vivo, recarregar e retomar) e screenshots nos dois temas. Fora até a Trilha A: `engine.run` real e tradução do log (A0/A1). Fora até o B11: launcher do Cloud Run Jobs. Desvios em `docs/decisoes/runs-e-jobs.md`.
```

Troque `<data>` pela data real de cada parte (`dd/mmm/aaaa`, como nos outros itens).

- [ ] **Step 4: `CLAUDE.md`**

- Em **Estrutura**, na lista de `api/`, depois de `validation.py`:

```
  engine_run.py   engine.run falso até o A0 (vira `from engine import run`)
  runs.py         regra de negócio de runs: gate, snapshot, run morto, visibilidade
  launcher.py     dispara o worker (subprocess local; Cloud Run Jobs no B11)
```

  e troque a linha do `worker.py` por `worker.py       python -m api.worker <run_id>: roda o motor, grava run_logs e results.json`. Em `src/lib/`, acrescente `runs.ts (tipos, queries e useRunLog do SSE)`.
- Em **Estado atual**, depois da frase do B3b: `**B4a (jobs backend) concluído em <data>**: tabelas \`runs\`/\`run_logs\` (migration \`0004\`), gate do Rodar no servidor, snapshot de config e inputs, um run ativo por simulação, worker em subprocess com \`engine.run\` falso, run morto após 20 min, log por SSE com retomada. **B4b (tela do run) concluído em <data>**: Rodar de verdade, página do run com log ao vivo e "em andamento há N s", lista de execuções na simulação.` e troque "Faltam, em ordem: B4 (jobs), B5–B9" por "Faltam, em ordem: B5–B9".
- Na tabela de áreas: `| Runs, worker, log ao vivo | \`docs/decisoes/runs-e-jobs.md\` |`.

- [ ] **Step 5: Suites finais**

Run (raiz): `uv run pytest && uv run ruff check . && cd web && bun run build && bun run lint && cd .. && mise run e2e`
Expected: tudo verde.

- [ ] **Step 6: Commit**

```bash
git add docs/decisoes/runs-e-jobs.md docs/m2/trilha-b-plataforma.md CLAUDE.md
git commit -m "docs: record b4b run screen and close b4"
```
