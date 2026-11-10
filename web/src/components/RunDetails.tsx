import { toast } from 'sonner'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
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
import { FormSection } from '@/components/FormSection'
import { BlockSkeleton } from '@/components/LoadState'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api } from '@/lib/api'
import { errorMessage } from '@/lib/auth'
import { Badge } from '@/components/ui/badge'
import { type FormField, configSchemaQuery, displayValue, fieldErrors, getPath, visibleLayout } from '@/lib/params'
import { type Run, isActive, isPublishable, runQuery, workspaceRunsQuery } from '@/lib/runs'
import { FIELD_LABELS, FILES, type Simulation, formatDate, simulationQuery } from '@/lib/simulations'
import { textLink } from '@/lib/links'

export function RunDetails({ slug, run, canEdit }: { slug: string; run: Run; canEdit: boolean }) {
  return (
    <div className="space-y-6">
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
      toast.success(next.published_at ? 'Execução publicada.' : 'Execução despublicada.')
    },
  })
  const publishable = isPublishable(run.status)

  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>Publicação</CardTitle>
        <CardDescription>
          {run.published_at
            ? `Publicada por ${run.published_by_name ?? '—'} em ${formatDate(run.published_at)}.`
            : 'Não publicada. Leitores ainda não veem esta execução.'}
        </CardDescription>
      </CardHeader>
      {canEdit && (
        <CardContent className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            {run.published_at ? (
              <Button variant="outline" size="sm" disabled={toggle.isPending} onClick={() => toggle.mutate(false)}>
                Despublicar
              </Button>
            ) : (
              <Button size="sm" disabled={!publishable || toggle.isPending} onClick={() => toggle.mutate(true)}>
                Publicar
              </Button>
            )}
            {!isActive(run.status) && <Rerun slug={slug} run={run} />}
          </div>
          {!run.published_at && !publishable && (
            <p className="text-xs text-muted-foreground">Só execuções concluídas podem ser publicadas.</p>
          )}
          {toggle.isError && (
            <Alert variant="destructive">
              <AlertDescription>{errorMessage(toggle.error)}</AlertDescription>
            </Alert>
          )}
        </CardContent>
      )}
    </Card>
  )
}

function Rerun({ slug, run }: { slug: string; run: Run }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const restore = useMutation({
    mutationFn: async () => {
      // ParamsIn forbids unknown keys: column_mapping, channel_groups etc. stay as the simulation has them
      const schema = await queryClient.fetchQuery(configSchemaQuery)
      const params = Object.fromEntries(Object.entries(run.config).filter(([key]) => key in (schema.properties ?? {})))
      return api<Simulation>(`/w/${slug}/simulations/${run.simulation.id}/params`, { method: 'PUT', body: params })
    },
  })

  function confirm() {
    restore.mutate(undefined, {
      onSuccess: (sim) => {
        queryClient.setQueryData(simulationQuery(slug, String(sim.id)).queryKey, sim)
        toast.success('Parâmetros restaurados. Revise e clique em Rodar.')
        navigate({ to: '/w/$slug/simulacoes/$id', params: { slug, id: String(sim.id) } })
      },
    })
  }

  return (
    <AlertDialog onOpenChange={(open) => !open && restore.reset()}>
      <AlertDialogTrigger asChild>
        <Button variant="outline" size="sm">
          Rodar de novo
        </Button>
      </AlertDialogTrigger>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Substituir os parâmetros de {run.simulation.name} pelos desta execução?</AlertDialogTitle>
          <AlertDialogDescription>
            Os arquivos continuam os atuais da simulação. Revise e clique em Rodar.
          </AlertDialogDescription>
        </AlertDialogHeader>
        {restore.isError && (
          <Alert variant="destructive">
            {/* the per-field 422 of pydantic: the engine parameters changed since this run */}
            <AlertDescription>
              {fieldErrors(restore.error)
                ? 'Os parâmetros desta execução não valem mais para o motor atual.'
                : errorMessage(restore.error)}
            </AlertDescription>
          </Alert>
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

// "Pós-evento (dias)" shows as "Pós-evento" / "14 dias"
const splitUnit = (label: string) => {
  const m = label.match(/^(.*?) \((dias|%)\)$/)
  if (m) return { label: m[1], unit: m[2] === '%' ? '%' : ' dias' }
  // long qualifiers ("(Banco Central)") would wrap the label and misalign the row; they stay in the tooltip
  return { label: label.replace(/ \(.*\)$/, ''), unit: '' }
}

type ParamRow = { field: FormField; value: unknown }

// flat on purpose: the page card is the only box, groups are a title and a hairline
// flat cells in a grid whose column count is balanced (11 fields -> 6 + 5, not 8 + 3), so no row is left half empty
const MAX_COLS = 8
const COL_GAP_REM = 1.5

function ParamGroup({ title, rows }: { title: string; rows: ParamRow[] }) {
  const cols = Math.ceil(rows.length / Math.ceil(rows.length / MAX_COLS))
  const colMin = `max(12rem, calc((100% - ${(cols - 1) * COL_GAP_REM}rem) / ${cols} - 1px))`
  return (
    <section
      className={`min-w-0 rounded-lg border bg-muted/20 p-4 ${rows.length > 6 ? 'basis-full' : 'basis-72'}`}
      style={{ flexGrow: rows.length }}
    >
      <FormSection title={title}>
        <dl className="grid gap-x-6 gap-y-5" style={{ gridTemplateColumns: `repeat(auto-fit, minmax(${colMin}, 1fr))` }}>
          {rows.map(({ field, value }) => {
            const { label, unit } = splitUnit(field.label)
            return (
              // pushed to the bottom: values line up across the row even when a label wraps
              <div key={field.path} className="flex flex-col justify-end gap-1 text-center">
                <dt className="text-balance text-xs text-muted-foreground" title={[field.label, field.help].filter(Boolean).join(' — ')}>
                  {label}
                </dt>
                <dd className="flex h-6 items-center justify-center text-[13px] font-medium">
                  {typeof value === 'boolean' ? (
                    <Badge variant={value ? 'success' : 'neutral'}>{value ? 'Sim' : 'Não'}</Badge>
                  ) : (
                    <span
                      className={
                        typeof value === 'number'
                          ? 'font-mono tabular-nums'
                          : Array.isArray(value) && !value.length
                            ? 'font-normal text-muted-foreground'
                            : ''
                      }
                    >
                      {displayValue(field, value)}
                      {unit && <span className="ml-1 font-sans text-xs font-normal text-muted-foreground">{unit}</span>}
                    </span>
                  )}
                </dd>
              </div>
            )
          })}
        </dl>
      </FormSection>
    </section>
  )
}

function Params({ run }: { run: Run }) {
  const { data: schema } = useQuery(configSchemaQuery)
  if (!schema) return <BlockSkeleton className="h-48" />
  const all = visibleLayout(schema).map((g) => ({
    title: g.title,
    rows: g.fields.map((field) => ({ field, value: getPath(run.config, field.path) })),
  }))
  const groups = all.map((g) => ({ ...g, rows: g.rows.filter((r) => r.value != null) })).filter((g) => g.rows.length > 0)
  const unset = all.flatMap((g) => g.rows.filter((r) => r.value == null))
  const mapping = run.config.column_mapping ?? {}
  const mapped = FILES.flatMap((spec) =>
    Object.entries(mapping[spec.key] ?? {}).map(([field, column]) => ({ spec, field, column })),
  )

  return (
    <>
      <Card size="sm">
        <CardHeader>
          <CardTitle>Parâmetros</CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
          <div className="flex flex-wrap items-start gap-4">
            {groups.map(({ title, rows }) => (
              <ParamGroup key={title} title={title} rows={rows} />
            ))}
          </div>
          {unset.length > 0 && (
            <p className="border-t pt-3 text-xs text-muted-foreground">
              Não definidos: {unset.map((r) => r.field.label).join(', ')}.
            </p>
          )}
        </CardContent>
      </Card>
      {mapped.length > 0 && (
        <Card size="sm">
          <CardHeader>
            <CardTitle>Mapeamento de colunas</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Arquivo</TableHead>
                  <TableHead>Campo</TableHead>
                  <TableHead>Coluna</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {mapped.map(({ spec, field, column }) => (
                  <TableRow key={`${spec.key}.${field}`}>
                    <TableCell className="text-muted-foreground">{spec.label}</TableCell>
                    <TableCell>{FIELD_LABELS[field] ?? field}</TableCell>
                    <TableCell className="font-mono text-xs">{column}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </>
  )
}

// the uploads plus what the platform fetched for the run (A4)
const RUN_INPUTS = [...FILES, { key: 'bcb_file', label: 'Séries do Banco Central' }]

function Inputs({ slug, run, canEdit }: { slug: string; run: Run; canEdit: boolean }) {
  const inputs = RUN_INPUTS.flatMap((spec) => {
    const input = run.inputs[spec.key]
    return input ? [{ spec, input }] : []
  })
  if (inputs.length === 0) return null
  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>Entradas</CardTitle>
      </CardHeader>
      <CardContent>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Entrada</TableHead>
              <TableHead>Arquivo</TableHead>
              <TableHead>SHA-256</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {inputs.map(({ spec, input }) => (
              <TableRow key={spec.key}>
                <TableCell className="font-medium">{spec.label}</TableCell>
                <TableCell>
                  {/* the api serves the raw csv to analysts only */}
                  {canEdit ? (
                    <a href={`/api/w/${slug}/runs/${run.id}/inputs/${spec.key}`} download className={textLink}>
                      {input.filename}
                    </a>
                  ) : (
                    input.filename
                  )}
                </TableCell>
                <TableCell>
                  <code className="font-mono text-xs text-muted-foreground" title={input.sha256}>
                    {input.sha256.slice(0, 12)}
                  </code>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}
