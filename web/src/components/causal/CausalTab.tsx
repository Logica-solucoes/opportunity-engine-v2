import { useQuery } from '@tanstack/react-query'
import { CursorClick, Funnel, Warning } from '@phosphor-icons/react'
import { useState } from 'react'
import { BlockSkeleton } from '@/components/LoadState'
import { ExportBar } from '@/components/ExportBar'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { ScrollArea } from '@/components/ui/scroll-area'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import {
  type Causal,
  type ExperimentDesign,
  type Reports,
  channelsLabel,
  eventPeriod,
  eventsCsvHref,
  formatSignedPct,
  reasonLabel,
  resultsQuery,
} from '@/lib/results'
import { cn } from '@/lib/utils'
import { EventDetail } from './EventDetail'
import { ExperimentCard } from './ExperimentCard'

export function CausalTab({ slug, runId }: { slug: string; runId: string }) {
  const query = useQuery(resultsQuery(slug, runId))
  if (query.isPending) return <BlockSkeleton className="h-64" />
  if (query.isError)
    return (
      <Alert variant="destructive">
        <Warning />
        <AlertDescription>Não foi possível carregar o resultado.</AlertDescription>
      </Alert>
    )
  const causal = query.data.causal
  if (!causal)
    return (
      <Empty className="border">
        <EmptyHeader>
          <EmptyTitle>Sem análise causal</EmptyTitle>
          <EmptyDescription>Esta execução não trouxe análise causal.</EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  return (
    <CausalView
      causal={causal}
      reports={query.data.reports}
      experiment={query.data.experiment_design}
      csvHref={eventsCsvHref(slug, runId)}
    />
  )
}

function CausalView({
  causal,
  reports,
  experiment,
  csvHref,
}: {
  causal: Causal
  reports: Reports | null
  experiment: ExperimentDesign | null
  csvHref: string
}) {
  const published = causal.events.filter((e) => e.status === 'published')
  const [showAll, setShowAll] = useState(false)
  const [selectedId, setSelectedId] = useState(published[0]?.id ?? null)
  const listed = showAll ? causal.events : published
  const selected = causal.events.find((e) => e.id === selectedId)

  // a rejected event picked under "Todos" would stay open with no row highlighted
  const showPublished = () => {
    setShowAll(false)
    if (selected?.status === 'rejected') setSelectedId(published[0]?.id ?? null)
  }

  return (
    <div className="space-y-6">
      <ExportBar links={causal.events.length > 0 ? [['Baixar CSV', csvHref]] : []} />

      {experiment && <ExperimentCard design={experiment} />}

      {causal.status !== 'ok' && (
        <Alert variant="warning">
          <Warning />
          <AlertTitle>Análise causal inconclusiva</AlertTitle>
          <AlertDescription>
            <ul className="list-disc pl-4">
              {causal.reasons.map((r) => (
                <li key={r}>{reasonLabel(r)}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}

      <Card size="sm" role="region" aria-label="Resumo" className="break-inside-avoid">
        <CardContent className="grid grid-cols-3 divide-x">
          <Stat value={causal.events_detected.length} label="eventos detectados" />
          <Stat value={published.length} label="publicados" />
          <Stat value={causal.events.length - published.length} label="rejeitados" />
        </CardContent>
      </Card>

      {causal.events.length > 0 && (
        <div className="grid items-start gap-5 md:grid-cols-[18rem_minmax(0,1fr)] print:block print:space-y-6">
          <section
            aria-label="Eventos"
            className={cn('space-y-2 md:sticky md:top-18 print:static', listed.length === 0 && 'md:col-span-2')}
          >
            <ToggleGroup
              type="single"
              variant="outline"
              size="sm"
              spacing={0}
              aria-label="Filtro de eventos"
              value={showAll ? 'all' : 'published'}
              onValueChange={(v) => (v === 'all' ? setShowAll(true) : v === 'published' && showPublished())}
              className="print:hidden"
            >
              <ToggleGroupItem value="published">Publicados</ToggleGroupItem>
              <ToggleGroupItem value="all">Todos</ToggleGroupItem>
            </ToggleGroup>
            {listed.length === 0 ? (
              <Empty className="border">
                <EmptyHeader>
                  <EmptyMedia variant="icon">
                    <Funnel />
                  </EmptyMedia>
                  <EmptyTitle>Nenhum evento publicado</EmptyTitle>
                  <EmptyDescription>Nenhum evento passou nos critérios de publicação.</EmptyDescription>
                </EmptyHeader>
                <EmptyContent>
                  <Button size="sm" variant="outline" onClick={() => setShowAll(true)}>
                    Ver todos
                  </Button>
                </EmptyContent>
              </Empty>
            ) : (
              // on paper the whole list, not a scroll box
              <ScrollArea className="rounded-lg border [&>[data-slot=scroll-area-viewport]]:max-h-[calc(100svh-8rem)] print:[&>[data-slot=scroll-area-viewport]]:max-h-none">
                <ul className="space-y-0.5 p-1">
                  {listed.map((e) => (
                    <li key={e.id}>
                      <button
                        type="button"
                        aria-current={e.id === selectedId}
                        onClick={() => setSelectedId(e.id)}
                        className={cn(
                          'w-full rounded-md px-2.5 py-1.5 text-left text-sm transition-colors hover:bg-muted',
                          e.id === selectedId && 'bg-muted',
                          e.status === 'rejected' && 'text-muted-foreground',
                        )}
                      >
                        <span className="block font-medium">{channelsLabel(e.channels)}</span>
                        <span className="block text-xs tabular-nums text-muted-foreground">
                          {eventPeriod(e)} ·{' '}
                          {e.status === 'published' ? formatSignedPct(e.lift?.rel_pct) : reasonLabel(e.reasons[0] ?? '')}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              </ScrollArea>
            )}
          </section>
          {selected ? (
            <EventDetail event={selected} report={reports?.events[selected.id]} />
          ) : listed.length > 0 ? (
            <Empty className="border">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                  <CursorClick />
                </EmptyMedia>
                <EmptyTitle>Nenhum evento selecionado</EmptyTitle>
                <EmptyDescription>Escolha um evento na lista para ver o impacto, os gráficos e a análise.</EmptyDescription>
              </EmptyHeader>
            </Empty>
          ) : null}
        </div>
      )}
    </div>
  )
}

function Stat({ value, label }: { value: number; label: string }) {
  return (
    <p className="px-4 first:pl-0 last:pr-0">
      <span className="block text-2xl font-semibold tabular-nums">{value}</span>{' '}
      <span className="text-xs text-muted-foreground">{label}</span>
    </p>
  )
}
