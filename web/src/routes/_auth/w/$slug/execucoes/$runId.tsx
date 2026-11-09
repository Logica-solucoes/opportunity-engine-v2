import { useQuery, useSuspenseQuery } from '@tanstack/react-query'
import { Link, Outlet, createFileRoute } from '@tanstack/react-router'
import { XCircle } from '@phosphor-icons/react'
import type { ReactNode } from 'react'
import { RunStatusBadge } from '@/components/RunStatusBadge'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { meQuery, roleIn } from '@/lib/auth'
import { GROUNDING_LABELS, resultsQuery } from '@/lib/results'
import { type Run, STATUS_LABELS, isPublishable, runQuery } from '@/lib/runs'
import { formatDate } from '@/lib/simulations'
import { backLink } from '@/lib/links'

export const Route = createFileRoute('/_auth/w/$slug/execucoes/$runId')({ component: RunRoute })

// the router keeps the component when only runId changes; remounting drops the old log lines and the selected event
function RunRoute() {
  return <RunLayout key={Route.useParams().runId} />
}

const TAB = '-mb-px border-b-2 pb-2 hover:text-foreground'

function RunLayout() {
  const { slug, runId } = Route.useParams()
  const { data: run, isError } = useQuery(runQuery(slug, runId))
  const { data: me } = useSuspenseQuery(meQuery)
  const canEdit = roleIn(me, slug) !== 'viewer'

  // 404 covers another workspace, a run a viewer can't see yet and a non-numeric id
  if (!run) return isError ? <p>Execução não encontrada.</p> : null

  const tab = (
    to:
      | '/w/$slug/execucoes/$runId/causal'
      | '/w/$slug/execucoes/$runId/elasticidade'
      | '/w/$slug/execucoes/$runId/detalhes',
    label: ReactNode,
  ) => (
    // active and inactive colors in separate props: two border-color classes on one element let the CSS order pick
    <Link
      to={to}
      params={{ slug, runId }}
      className={TAB}
      activeProps={{ className: 'border-primary text-foreground' }}
      inactiveProps={{ className: 'border-transparent text-muted-foreground' }}
    >
      {label}
    </Link>
  )

  return (
    <div className="space-y-6">
      <PrintHeader
        slug={slug}
        runId={runId}
        run={run}
        workspace={me.workspaces.find((w) => w.slug === slug)?.name ?? slug}
      />
      <div className="space-y-1 print:hidden">
        {/* viewers can't open simulations, so their way back is the history */}
        {canEdit ? (
          <Link
            to="/w/$slug/simulacoes/$id"
            params={{ slug, id: String(run.simulation.id) }}
            className={backLink}
          >
            ← {run.simulation.name}
          </Link>
        ) : (
          <Link to="/w/$slug/execucoes" params={{ slug }} className={backLink}>
            ← Execuções
          </Link>
        )}
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold">Execução #{run.id}</h1>
          <RunStatusBadge status={run.status} />
        </div>
        <p className="text-sm text-muted-foreground">
          {run.created_by_name} · {formatDate(run.created_at)} · motor {run.engine_version ?? '—'}
        </p>
      </div>

      {run.status === 'failed' && run.error && (
        <Alert variant="destructive">
          <XCircle />
          <AlertTitle>Falhou</AlertTitle>
          <AlertDescription>{run.error}</AlertDescription>
        </Alert>
      )}

      <nav aria-label="Seções da execução" className="flex gap-6 border-b text-sm print:hidden">
        {isPublishable(run.status) && tab('/w/$slug/execucoes/$runId/causal', 'Causal')}
        {isPublishable(run.status) && tab('/w/$slug/execucoes/$runId/elasticidade', 'Elasticidade')}
        {tab('/w/$slug/execucoes/$runId/detalhes', 'Detalhes')}
      </nav>

      <Outlet />
    </div>
  )
}

// on paper this replaces the app header, the back link and the tabs
function PrintHeader({ slug, runId, run, workspace }: { slug: string; runId: string; run: Run; workspace: string }) {
  // same guard as the tabs: a run still going would cache the results 404 for good (staleTime: Infinity)
  const { data: results } = useQuery({ ...resultsQuery(slug, runId), enabled: isPublishable(run.status) })
  // only once the A9 has judged the reports: the PDF never claims a grounding nobody checked
  const grounding = results?.reports?.grounding
  return (
    <section aria-label="Cabeçalho de impressão" className="hidden space-y-1 border-b pb-3 print:block">
      <p className="text-sm">
        {workspace} · {run.simulation.name}
      </p>
      <h1 className="text-xl font-semibold">
        Execução #{run.id} · {STATUS_LABELS[run.status]}
      </h1>
      <p className="text-sm text-muted-foreground">
        {formatDate(run.created_at)} · motor {run.engine_version ?? '—'}
      </p>
      {grounding && <p className="text-sm">Grounding: {GROUNDING_LABELS[grounding.status]}</p>}
    </section>
  )
}
