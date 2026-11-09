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
import { BlockSkeleton } from '@/components/LoadState'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api } from '@/lib/api'
import { errorMessage } from '@/lib/auth'
import { configSchemaQuery, displayValue, fieldErrors, getPath, visibleLayout } from '@/lib/params'
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

function Params({ run }: { run: Run }) {
  const { data: schema } = useQuery(configSchemaQuery)
  if (!schema) return <BlockSkeleton className="h-48" />
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
        <CardContent className="grid gap-x-10 gap-y-6 md:grid-cols-2">
          {visibleLayout(schema).map((group) => (
            <div key={group.title} className="space-y-1">
              <h3 className="text-sm font-medium">{group.title}</h3>
              <dl className="divide-y text-sm">
                {group.fields.map((field) => (
                  <div key={field.path} className="flex items-baseline justify-between gap-4 py-1.5">
                    <dt className="text-muted-foreground">{field.label}</dt>
                    <dd className="text-right font-medium tabular-nums">
                      {displayValue(field, getPath(run.config, field.path))}
                    </dd>
                  </div>
                ))}
              </dl>
            </div>
          ))}
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
