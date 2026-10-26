import { useIsMutating, useMutation, useQuery, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
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
  fileProblem,
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
  // one write at a time: a slower earlier response would overwrite the newer SimulationOut in the cache
  const busy = useIsMutating() > 0
  // 404 (another workspace or deleted) and 422 (non-numeric id) look the same to the user;
  // a failed refetch keeps the data, so only a missing simulation replaces the page
  if (!sim) return isError ? <p>Simulação não encontrada.</p> : null

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
            <FileCard key={spec.kind} slug={slug} sim={sim} spec={spec} busy={busy} onSaved={saved} />
          ))}
        </div>
      </section>

      {sim.files.investment && sim.files.performance && (
        <MappingForm key={filesKey} slug={slug} sim={sim} busy={busy} onSaved={saved} />
      )}

      <ValidationBlock key={JSON.stringify(sim.validation)} report={sim.validation} />
    </div>
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
          disabled={busy}
          onFile={(f) => {
            const p = fileProblem(f)
            setProblem(p)
            if (!p) upload.mutate(f)
          }}
        />
        {file && (
          <p className="text-xs text-muted-foreground">
            <span className="font-medium text-foreground">{file.filename}</span> · {formatSize(file.size_bytes)} ·{' '}
            {formatDate(file.uploaded_at)}
          </p>
        )}
        {(problem || upload.isError) && (
          <p role="alert" className="text-sm text-destructive">
            {problem ?? errorMessage(upload.error)}
          </p>
        )}
        <a href={spec.template} download className="text-sm text-primary hover:underline">
          Baixar template
        </a>
      </CardContent>
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
        <Button type="submit" disabled={busy}>
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
