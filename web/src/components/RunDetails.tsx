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
