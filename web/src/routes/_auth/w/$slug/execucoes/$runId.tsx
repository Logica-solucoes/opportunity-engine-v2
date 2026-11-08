import { useQuery, useSuspenseQuery } from '@tanstack/react-query'
import { Link, Outlet, createFileRoute } from '@tanstack/react-router'
import { CircleX } from 'lucide-react'
import type { ReactNode } from 'react'
import { RunStatusBadge } from '@/components/RunStatusBadge'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { meQuery, roleIn } from '@/lib/auth'
import { isPublishable, runQuery } from '@/lib/runs'
import { formatDate } from '@/lib/simulations'

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
      <div className="space-y-1">
        {/* viewers can't open simulations, so their way back is the history */}
        {canEdit ? (
          <Link
            to="/w/$slug/simulacoes/$id"
            params={{ slug, id: String(run.simulation.id) }}
            className="text-sm text-muted-foreground hover:text-primary"
          >
            ← {run.simulation.name}
          </Link>
        ) : (
          <Link to="/w/$slug/execucoes" params={{ slug }} className="text-sm text-muted-foreground hover:text-primary">
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
          <CircleX />
          <AlertTitle>Falhou</AlertTitle>
          <AlertDescription>{run.error}</AlertDescription>
        </Alert>
      )}

      <nav aria-label="Seções da execução" className="flex gap-6 border-b text-sm">
        {isPublishable(run.status) && tab('/w/$slug/execucoes/$runId/causal', 'Causal')}
        {isPublishable(run.status) && tab('/w/$slug/execucoes/$runId/elasticidade', 'Elasticidade')}
        {tab('/w/$slug/execucoes/$runId/detalhes', 'Detalhes')}
      </nav>

      <Outlet />
    </div>
  )
}
