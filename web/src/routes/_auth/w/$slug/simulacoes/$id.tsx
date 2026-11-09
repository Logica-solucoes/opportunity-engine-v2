import { useIsMutating, useMutation, useQuery, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router'
import { CheckCircle, FileCsv, Flask, Info, Play, Sliders, Warning, XCircle } from '@phosphor-icons/react'
import { FieldGrid, FormSection } from '@/components/FormSection'
import { Field, FieldLabel } from '@/components/ui/field'
import { type FormEvent, useEffect, useState } from 'react'
import { PageHeader } from '@/components/PageHeader'
import { DeleteSimulation } from '@/components/DeleteSimulation'
import { FileDrop } from '@/components/FileDrop'
import { GoogleImport } from '@/components/GoogleImport'
import { ParamsForm } from '@/components/ParamsForm'
import { RunStatusBadge } from '@/components/RunStatusBadge'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { api } from '@/lib/api'
import { errorMessage, meQuery } from '@/lib/auth'
import { paramsSaved } from '@/lib/params'
import { type Run, isActive, simulationRunsQuery } from '@/lib/runs'
import {
  type Check,
  type ColumnMapping,
  ETAPAS,
  type Etapa,
  FIELD_LABELS,
  FILES,
  type FileSpec,
  LEVEL_LABELS,
  type Simulation,
  type ValidationReport,
  fileProblem,
  formatDate,
  formatSize,
  initialColumn,
  runBlockReason,
  simulationQuery,
  simulationsQuery,
} from '@/lib/simulations'
import { rowLink, textLink } from '@/lib/links'

export const Route = createFileRoute('/_auth/w/$slug/simulacoes/$id')({
  validateSearch: (search: Record<string, unknown>): { etapa?: Etapa } => ({
    etapa: ETAPAS.find((e) => e.value === search.etapa)?.value,
  }),
  component: SimulationPage,
})

const LEVEL_ICONS: Record<Check['level'], typeof Info> = { error: XCircle, warning: Warning, info: Info }
const LEVEL_VARIANTS = { error: 'destructive', warning: 'warning', info: 'info' } as const

function SimulationPage() {
  const { slug, id } = Route.useParams()
  const { data: me } = useSuspenseQuery(meQuery)
  const workspace = me.workspaces.find((w) => w.slug === slug)
  if (workspace?.role === 'viewer')
    return (
      <Alert variant="destructive">
        <XCircle />
        <AlertDescription>Sem permissão para editar simulações deste workspace.</AlertDescription>
      </Alert>
    )
  return (
    <SimulationDetail slug={slug} id={id} isAdmin={workspace?.role === 'admin'} google={Boolean(workspace?.google)} />
  )
}

function SimulationDetail({
  slug,
  id,
  isAdmin,
  google,
}: {
  slug: string
  id: string
  isAdmin: boolean
  google: boolean
}) {
  const queryClient = useQueryClient()
  const query = simulationQuery(slug, id)
  const { data: sim, isError } = useQuery(query)
  // one write at a time: a slower earlier response would overwrite the newer SimulationOut in the cache
  const busy = useIsMutating() > 0
  // 404 (another workspace or deleted) and 422 (non-numeric id) look the same to the user;
  // a failed refetch keeps the data, so only a missing simulation replaces the page
  if (!sim)
    return isError ? (
      <Empty>
        <EmptyHeader>
          <EmptyTitle>Simulação não encontrada.</EmptyTitle>
        </EmptyHeader>
      </Empty>
    ) : null

  // every mutation answers with the whole SimulationOut, so the cache is set instead of refetched
  const saved = (next: Simulation) => {
    queryClient.setQueryData(query.queryKey, next)
    queryClient.invalidateQueries({ queryKey: simulationsQuery(slug).queryKey, exact: true })
  }

  // a new report (new mapping or file) remounts the steps: the data suggestions and the confirmed warnings are stale
  return (
    <SimulationView
      key={JSON.stringify(sim.validation)}
      slug={slug}
      sim={sim}
      isAdmin={isAdmin}
      google={google}
      busy={busy}
      onSaved={saved}
    />
  )
}

function SimulationView({
  slug,
  sim,
  isAdmin,
  google,
  busy,
  onSaved,
}: {
  slug: string
  sim: Simulation
  isAdmin: boolean
  google: boolean
  busy: boolean
  onSaved: (sim: Simulation) => void
}) {
  const { etapa = 'arquivos' } = Route.useSearch()
  const navigate = Route.useNavigate()
  const [paramsDirty, setParamsDirty] = useState(false)
  const gate = useRunGate(slug, sim, paramsSaved(sim) && !paramsDirty)
  // a new file resets the mapping form to that file's columns
  const filesKey = FILES.map((f) => sim.files[f.kind]?.sha256).join()
  const go = (next: string) =>
    navigate({ search: { etapa: next === 'arquivos' ? undefined : (next as Etapa) }, replace: true })

  return (
    <div className="space-y-6">
      <Tabs value={etapa} onValueChange={go} className="flex-col gap-5">
        <PageHeader
          slug={slug}
          trail={[{ label: 'Simulações', link: { to: '/w/$slug', params: { slug } } }, { label: sim.name }]}
          title={sim.name}
          icon={Flask}
        />
        {/* the title scrolls away; the tabs line, with Rodar, stays in reach from any step */}
        <div className="z-20 flex flex-wrap items-center justify-between gap-x-4 border-b bg-background/90 backdrop-blur md:sticky md:top-14">
          <TabsList variant="line" aria-label="Etapas da simulação" className="h-11 w-auto justify-start gap-4 rounded-none p-0">
            {ETAPAS.map((e) => (
              <TabsTrigger
                key={e.value}
                value={e.value}
                className="h-11 flex-none rounded-none px-1 data-[state=active]:text-foreground after:inset-x-0 after:bottom-[-1px] after:h-0.5 after:bg-primary data-[state=active]:after:opacity-100"
              >
                {e.label}
              </TabsTrigger>
            ))}
          </TabsList>
          <RunAction slug={slug} gate={gate} busy={busy} />
        </div>

        {/* forceMount: the parameters typed and not yet saved survive a trip to another step */}
        <TabsContent value="arquivos" forceMount className="space-y-4 data-[state=inactive]:hidden">
          <div className="grid gap-4 md:grid-cols-3">
            {FILES.map((spec) => (
              <FileCard key={spec.kind} slug={slug} sim={sim} spec={spec} busy={busy} onSaved={onSaved} />
            ))}
          </div>
          {google && <GoogleImport slug={slug} sim={sim} busy={busy} onSaved={onSaved} />}
        </TabsContent>

        <TabsContent
          value="mapeamento"
          forceMount
          className={`grid items-start gap-4 data-[state=inactive]:hidden ${sim.validation ? 'xl:grid-cols-[3fr_2fr]' : ''}`}
        >
          {sim.files.investment && sim.files.performance ? (
            <MappingForm key={filesKey} slug={slug} sim={sim} busy={busy} onSaved={onSaved} />
          ) : (
            <StepEmpty
              title="Falta enviar os arquivos"
              text="Envie investimento e performance para mapear as colunas."
              action={() => go('arquivos')}
              actionLabel="Ir para arquivos"
            />
          )}
          {sim.validation && <ValidationResult report={sim.validation} gate={gate} />}
        </TabsContent>

        <TabsContent value="parametros" forceMount className="data-[state=inactive]:hidden">
          {sim.validation ? (
            <ParamsForm slug={slug} sim={sim} busy={busy} onSaved={onSaved} onDirty={setParamsDirty} />
          ) : (
            <StepEmpty
              title="Valide os arquivos primeiro"
              text="Os parâmetros partem das sugestões que vêm da validação."
              action={() => go('mapeamento')}
              actionLabel="Ir para o mapeamento"
            />
          )}
        </TabsContent>

        <TabsContent value="execucoes" forceMount className="data-[state=inactive]:hidden">
          <RunList slug={slug} runs={gate.runs} />
        </TabsContent>
      </Tabs>

      {isAdmin && <DeleteSimulation slug={slug} sim={sim} />}
    </div>
  )
}

function StepEmpty({
  title,
  text,
  action,
  actionLabel,
}: {
  title: string
  text: string
  action: () => void
  actionLabel: string
}) {
  return (
    <Empty className="border">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <Sliders />
        </EmptyMedia>
        <EmptyTitle>{title}</EmptyTitle>
        <EmptyDescription>{text}</EmptyDescription>
      </EmptyHeader>
      <Button variant="outline" onClick={action}>
        {actionLabel}
      </Button>
    </Empty>
  )
}

function FileCard({
  slug,
  sim,
  spec,
  busy,
  onSaved,
}: {
  slug: string
  sim: Simulation
  spec: FileSpec
  busy: boolean
  onSaved: (sim: Simulation) => void
}) {
  const file = sim.files[spec.kind]
  const [problem, setProblem] = useState<string | null>(null)
  const upload = useMutation({
    mutationFn: (f: File) => {
      const body = new FormData()
      body.append('file', f)
      return api<Simulation>(`/w/${slug}/simulations/${sim.id}/files/${spec.kind}`, { method: 'PUT', body })
    },
    onSuccess: onSaved,
  })

  return (
    <Card className="h-full">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {spec.label}
          {spec.optional && <Badge variant="neutral">opcional</Badge>}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <FileDrop
          id={`file-${spec.kind}`}
          label={`Arquivo de ${spec.label.toLowerCase()}`}
          disabled={busy}
          uploading={upload.isPending}
          hasFile={Boolean(file)}
          onFile={(f) => {
            const p = fileProblem(f)
            setProblem(p)
            if (!p) upload.mutate(f)
          }}
        />
        {file && (
          <div className="flex items-center gap-3 rounded-lg bg-muted/60 p-3">
            <FileCsv aria-hidden className="size-6 shrink-0 text-muted-foreground" />
            <div className="min-w-0 text-xs">
              <span className="block truncate text-sm font-medium">{file.filename}</span>
              <span className="text-muted-foreground">
                {formatSize(file.size_bytes)} · {formatDate(file.uploaded_at)}
              </span>
            </div>
          </div>
        )}
        {(problem || upload.isError) && (
          <p role="alert" className="text-sm text-destructive">
            {problem ?? errorMessage(upload.error)}
          </p>
        )}
      </CardContent>
      <CardFooter className="mt-auto">
        <a href={spec.template} download className={`text-sm ${textLink}`}>
          Baixar template
        </a>
      </CardFooter>
    </Card>
  )
}

function MappingForm({
  slug,
  sim,
  busy,
  onSaved,
}: {
  slug: string
  sim: Simulation
  busy: boolean
  onSaved: (sim: Simulation) => void
}) {
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
    <form onSubmit={submit}>
      <Card className="[--card-spacing:--spacing(6)]">
        <CardHeader className="border-b">
          <CardTitle>Mapeamento de colunas</CardTitle>
          <CardDescription>Diga qual coluna de cada arquivo tem cada informação.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-x-10 gap-y-8 2xl:grid-cols-2">
          {uploaded.map((spec) => {
            const file = sim.files[spec.kind]!
            return (
              <FormSection
                key={spec.kind}
                title={spec.label}
                description={`Colunas de ${file.filename}`}
              >
                <FieldGrid className="sm:grid-cols-2">
                  {Object.keys(file.suggested).map((field) => {
                    const id = `${spec.key}.${field}`
                    return (
                      <Field key={field}>
                        <FieldLabel htmlFor={id} className="text-muted-foreground">
                          {FIELD_LABELS[field] ?? field}
                        </FieldLabel>
                        <Select name={id} required defaultValue={initialColumn(sim, spec, field) || undefined}>
                          <SelectTrigger id={id} className="w-full">
                            <SelectValue placeholder="Escolha a coluna" />
                          </SelectTrigger>
                          <SelectContent>
                            {file.columns.map((c) => (
                              <SelectItem key={c} value={c}>
                                {c}
                              </SelectItem>
                            ))}
                          </SelectContent>
                        </Select>
                      </Field>
                    )
                  })}
                </FieldGrid>
              </FormSection>
            )
          })}
        </CardContent>
        <CardFooter className="gap-3">
          <Button type="submit" disabled={busy}>
            Validar
          </Button>
          {save.isError && (
            <p role="alert" className="text-sm text-destructive">
              {errorMessage(save.error)}
            </p>
          )}
        </CardFooter>
      </Card>
    </form>
  )
}

function useRunGate(slug: string, sim: Simulation, saved: boolean) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const runsQuery = simulationRunsQuery(slug, sim.id)
  const { data: runs, isPending } = useQuery(runsQuery)
  const activeRun = runs?.find((r) => isActive(r.status))
  // by index, since two checks may share an id; the server gets the ids of the confirmed ones
  const [confirmed, setConfirmed] = useState<Set<number>>(new Set())
  const report = sim.validation
  const start = useMutation({
    mutationFn: () =>
      api<Run>(`/w/${slug}/simulations/${sim.id}/runs`, {
        method: 'POST',
        body: {
          confirmed_warnings: (report?.checks ?? [])
            .filter((c, i) => c.level === 'warning' && confirmed.has(i))
            .map((c) => c.id),
        },
      }),
    // a 409 means a run started elsewhere: refetching shows it and its Acompanhar link
    onSettled: () => queryClient.invalidateQueries({ queryKey: runsQuery.queryKey }),
  })
  const reason = runBlockReason(report, confirmed, saved, Boolean(activeRun))
  // a run that started or ended since the last click makes its answer stale (and the 409 repeats the reason)
  const { reset } = start
  const activeId = activeRun?.id
  useEffect(() => {
    reset()
  }, [activeId, reset])

  function run() {
    // passed to mutate, not useMutation: leaving the page during the POST must not pull the user back
    start.mutate(undefined, {
      onSuccess: (created) => navigate({ to: '/w/$slug/execucoes/$runId', params: { slug, runId: String(created.id) } }),
    })
  }

  function toggle(i: number, on: boolean) {
    const next = new Set(confirmed)
    if (on) next.add(i)
    else next.delete(i)
    setConfirmed(next)
  }

  return { runs: runs ?? [], isPending, activeRun, confirmed, toggle, reason, start, run }
}

type Gate = ReturnType<typeof useRunGate>

function RunAction({ slug, gate, busy }: { slug: string; gate: Gate; busy: boolean }) {
  const { reason, activeRun, start } = gate
  return (
    <div className="flex flex-wrap items-center justify-end gap-x-3 gap-y-1">
      {reason && (
        <p className="text-xs text-muted-foreground">
          {reason}{' '}
          {activeRun && (
            <Link to="/w/$slug/execucoes/$runId" params={{ slug, runId: String(activeRun.id) }} className={textLink}>
              Acompanhar
            </Link>
          )}
        </p>
      )}
      <Button size="sm" disabled={Boolean(reason) || busy || gate.isPending} onClick={gate.run}>
        <Play aria-hidden weight="fill" />
        Rodar
      </Button>
      {start.isError && (
        <p role="alert" className="text-sm text-destructive">
          {errorMessage(start.error)}
        </p>
      )}
    </div>
  )
}

function ValidationResult({ report, gate }: { report: ValidationReport; gate: Gate }) {
  return (
    <Card className="[--card-spacing:--spacing(6)]">
      <CardHeader>
        <CardTitle>Validação</CardTitle>
        {report.channels.length > 0 && (
          <CardDescription className="flex flex-wrap items-center gap-1.5">
            <span>Canais:</span>
            {report.channels.map((c) => (
              <Badge key={c} variant="neutral">
                {c}
              </Badge>
            ))}
          </CardDescription>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        {!report.checks.some((c) => c.level !== 'info') && (
          <Alert>
            <CheckCircle className="text-success" />
            <AlertDescription>Arquivos válidos, sem erros nem avisos.</AlertDescription>
          </Alert>
        )}
        {report.checks.map((check, i) => {
          const Icon = LEVEL_ICONS[check.level]
          return (
            <Alert key={i} variant={LEVEL_VARIANTS[check.level]}>
              <Icon />
              <AlertTitle>{LEVEL_LABELS[check.level]}</AlertTitle>
              <AlertDescription>
                <p>{check.message}</p>
                {check.level === 'warning' && (
                  <div className="mt-2 flex items-center gap-2">
                    <Checkbox
                      id={`confirm-${i}`}
                      checked={gate.confirmed.has(i)}
                      onCheckedChange={(v) => gate.toggle(i, v === true)}
                    />
                    <Label htmlFor={`confirm-${i}`}>Estou ciente</Label>
                  </div>
                )}
              </AlertDescription>
            </Alert>
          )
        })}
      </CardContent>
    </Card>
  )
}

function RunList({ slug, runs }: { slug: string; runs: Run[] }) {
  if (runs.length === 0)
    return (
      <Empty className="border">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <Play />
          </EmptyMedia>
          <EmptyTitle>Nenhuma execução ainda</EmptyTitle>
          <EmptyDescription>Valide, salve os parâmetros e use Rodar.</EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  return (
    <Card>
      <CardContent>
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
                  <Link to="/w/$slug/execucoes/$runId" params={{ slug, runId: String(r.id) }} className={rowLink}>
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
      </CardContent>
    </Card>
  )
}
