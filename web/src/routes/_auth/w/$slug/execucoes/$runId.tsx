import { useQuery, useSuspenseQuery } from '@tanstack/react-query'
import { Link, Outlet, createFileRoute, useRouterState } from '@tanstack/react-router'
import { XCircle } from '@phosphor-icons/react'
import { RunStatusBadge } from '@/components/RunStatusBadge'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { TooltipProvider } from '@/components/ui/tooltip'
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

const TABS = [
  ['causal', 'Causal'],
  ['elasticidade', 'Elasticidade'],
  ['detalhes', 'Detalhes'],
] as const

function RunLayout() {
  const { slug, runId } = Route.useParams()
  const { data: run, isError } = useQuery(runQuery(slug, runId))
  const { data: me } = useSuspenseQuery(meQuery)
  const canEdit = roleIn(me, slug) !== 'viewer'
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const current = TABS.find(([key]) => pathname.endsWith(`/${key}`))?.[0]

  // 404 covers another workspace, a run a viewer can't see yet and a non-numeric id
  if (!run)
    return isError ? (
      <Empty className="border">
        <EmptyHeader>
          <EmptyTitle>Execução não encontrada</EmptyTitle>
          <EmptyDescription>Ela não existe ou você não tem acesso.</EmptyDescription>
        </EmptyHeader>
      </Empty>
    ) : null

  const visible = TABS.filter(([key]) => key === 'detalhes' || isPublishable(run.status))

  return (
    <div className="space-y-5">
      <PrintHeader
        slug={slug}
        runId={runId}
        run={run}
        workspace={me.workspaces.find((w) => w.slug === slug)?.name ?? slug}
      />
      <header className="space-y-1.5 print:hidden">
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
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <h1 className="text-xl font-semibold text-balance">Execução #{run.id}</h1>
          <RunStatusBadge status={run.status} />
          <p className="text-sm text-muted-foreground">
            {run.created_by_name} · {formatDate(run.created_at)} · motor{' '}
            <span className="font-mono text-xs">{run.engine_version ?? '—'}</span>
          </p>
        </div>
      </header>

      {run.status === 'failed' && run.error && (
        <Alert variant="destructive">
          <XCircle />
          <AlertTitle>Falhou</AlertTitle>
          <AlertDescription>{run.error}</AlertDescription>
        </Alert>
      )}

      <TooltipProvider delayDuration={150}>
        <Tabs value={current ?? ''} className="gap-5">
          <TabsList variant="line" aria-label="Seções da execução" className="print:hidden">
            {visible.map(([key, label]) => (
              <TabsTrigger key={key} value={key} asChild>
                <Link to={`/w/$slug/execucoes/$runId/${key}`} params={{ slug, runId }}>
                  {label}
                </Link>
              </TabsTrigger>
            ))}
          </TabsList>
          <Outlet />
        </Tabs>
      </TooltipProvider>
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
