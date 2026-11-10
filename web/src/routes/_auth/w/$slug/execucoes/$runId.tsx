import { toast } from 'sonner'
import { useQuery, useSuspenseQuery } from '@tanstack/react-query'
import { useEffect, useRef } from 'react'
import { Link, Outlet, createFileRoute, useRouterState } from '@tanstack/react-router'
import { ClockCounterClockwise, XCircle } from '@phosphor-icons/react'
import { RunStatusBadge } from '@/components/RunStatusBadge'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { TooltipProvider } from '@/components/ui/tooltip'
import { meQuery, roleIn } from '@/lib/auth'
import { GROUNDING_LABELS, resultsQuery } from '@/lib/results'
import { type Run, type RunStatus, STATUS_LABELS, isActive, isPublishable, runQuery } from '@/lib/runs'
import { formatDate } from '@/lib/simulations'
import { PageHeader } from '@/components/PageHeader'

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
  // viewers can't open simulations, so their way back is the history
  const canEdit = roleIn(me, slug) !== 'viewer'
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const current = TABS.find(([key]) => pathname.endsWith(`/${key}`))?.[0]

  // only a change seen while the page is open: opening a finished run must not toast
  const seen = useRef<RunStatus>(undefined)
  const status = run?.status
  useEffect(() => {
    if (seen.current && isActive(seen.current) && status && !isActive(status)) {
      if (status === 'succeeded') toast.success('Execução concluída.')
      else if (status === 'inconclusive') toast.info('Execução concluída, sem resultado conclusivo.')
      else toast.error('A execução falhou.')
    }
    seen.current = status
  }, [status])

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
    <div className="space-y-4">
      <PrintHeader
        slug={slug}
        runId={runId}
        run={run}
        workspace={me.workspaces.find((w) => w.slug === slug)?.name ?? slug}
      />
      <PageHeader
        slug={slug}
        trail={
          canEdit
            ? [
                { label: 'Simulações', link: { to: '/w/$slug', params: { slug } } },
                { label: run.simulation.name, link: { to: '/w/$slug/simulacoes/$id', params: { slug, id: String(run.simulation.id) } } },
                { label: `Execução #${run.id}` },
              ]
            : [{ label: 'Execuções', link: { to: '/w/$slug/execucoes', params: { slug } } }, { label: `#${run.id}` }]
        }
        title={`Execução #${run.id}`}
        icon={ClockCounterClockwise}
      >
        <RunStatusBadge status={run.status} />
        <p className="text-sm text-muted-foreground md:ml-auto">
          {run.created_by_name} · {formatDate(run.created_at)} · motor{' '}
          <span className="font-mono text-xs">{run.engine_version ?? '—'}</span>
        </p>
      </PageHeader>

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
