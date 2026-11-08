import { useQuery } from '@tanstack/react-query'
import { TriangleAlert } from 'lucide-react'
import { useState } from 'react'
import { ExportBar } from '@/components/ExportBar'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import {
  type Causal,
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

export function CausalTab({ slug, runId }: { slug: string; runId: string }) {
  const query = useQuery(resultsQuery(slug, runId))
  if (query.isPending) return <p className="text-sm text-muted-foreground">Carregando…</p>
  if (query.isError)
    return (
      <p role="alert" className="text-sm text-destructive">
        Não foi possível carregar o resultado.
      </p>
    )
  const causal = query.data.causal
  if (!causal) return <p className="text-sm text-muted-foreground">Sem análise causal nesta execução.</p>
  return <CausalView causal={causal} reports={query.data.reports} csvHref={eventsCsvHref(slug, runId)} />
}

function CausalView({ causal, reports, csvHref }: { causal: Causal; reports: Reports | null; csvHref: string }) {
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

      {causal.status !== 'ok' && (
        <Alert>
          <TriangleAlert />
          <AlertTitle>Análise causal inconclusiva</AlertTitle>
          <AlertDescription>
            <ul className="list-disc pl-5">
              {causal.reasons.map((r) => (
                <li key={r}>{reasonLabel(r)}</li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}

      <section aria-label="Resumo" className="grid gap-3 sm:grid-cols-3">
        <Stat value={causal.events_detected.length} label="eventos detectados" />
        <Stat value={published.length} label="publicados" />
        <Stat value={causal.events.length - published.length} label="rejeitados" />
      </section>

      {causal.events.length > 0 && (
        <div className="grid gap-6 md:grid-cols-[18rem_minmax(0,1fr)] print:block print:space-y-6">
          <section aria-label="Eventos" className="space-y-2">
            <div className="flex gap-2 print:hidden">
              <Button size="sm" variant={showAll ? 'outline' : 'secondary'} aria-pressed={!showAll} onClick={showPublished}>
                Publicados
              </Button>
              <Button size="sm" variant={showAll ? 'secondary' : 'outline'} aria-pressed={showAll} onClick={() => setShowAll(true)}>
                Todos
              </Button>
            </div>
            {listed.length === 0 ? (
              <p className="text-sm text-muted-foreground">
                Nenhum evento publicado.{' '}
                <button type="button" className="text-primary underline" onClick={() => setShowAll(true)}>
                  Ver todos
                </button>
              </p>
            ) : (
              // on paper the whole list, not a scroll box cut at 32rem
              <ul className="max-h-[32rem] space-y-1 overflow-auto print:max-h-none print:overflow-visible">
                {listed.map((e) => (
                  <li key={e.id}>
                    <button
                      type="button"
                      aria-current={e.id === selectedId}
                      onClick={() => setSelectedId(e.id)}
                      className={cn(
                        'w-full rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted',
                        e.id === selectedId && 'bg-muted',
                        e.status === 'rejected' && 'text-muted-foreground',
                      )}
                    >
                      <span className="block font-medium">{channelsLabel(e.channels)}</span>
                      <span className="block text-xs">
                        {eventPeriod(e)} ·{' '}
                        {e.status === 'published' ? formatSignedPct(e.lift?.rel_pct) : reasonLabel(e.reasons[0] ?? '')}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>
          {selected ? (
            <EventDetail event={selected} report={reports?.events[selected.id]} />
          ) : (
            <p className="text-sm text-muted-foreground">Selecione um evento.</p>
          )}
        </div>
      )}
    </div>
  )
}

function Stat({ value, label }: { value: number; label: string }) {
  return (
    <p className="break-inside-avoid rounded-md border p-3 text-sm">
      <span className="text-2xl font-semibold tabular-nums">{value}</span> {label}
    </p>
  )
}
