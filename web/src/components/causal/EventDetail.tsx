import { CaretDown, ProhibitInset } from '@phosphor-icons/react'
import type { ReactNode } from 'react'
import { NarrativeCard } from '@/components/NarrativeCard'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import {
  type CausalEvent,
  type EventReport,
  eventNotes,
  eventPeriod,
  formatDecimal,
  formatInteger,
  formatMoney,
  formatPValue,
  formatPct,
  formatSigned,
  formatSignedPct,
  reasonLabel,
  rejectionReasons,
} from '@/lib/results'
import { AccuracyChart, ImpactChart, InvestmentBars, KpiBars } from './EventCharts'

export function EventDetail({ event, report }: { event: CausalEvent; report?: EventReport }) {
  const published = event.status === 'published'
  return (
    <section aria-label="Evento selecionado" className="min-w-0 space-y-4">
      <div className="space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-semibold text-balance">{event.channels.join(', ')}</h2>
          <Badge variant={published ? 'success' : 'neutral'}>{published ? 'Publicado' : 'Rejeitado'}</Badge>
        </div>
        <p className="text-sm tabular-nums text-muted-foreground">{eventPeriod(event)}</p>
        {eventNotes(event).map((r) => (
          <p key={r} className="text-sm text-muted-foreground">
            {reasonLabel(r)}.
          </p>
        ))}
      </div>
      {published && report && (
        <NarrativeCard report={report} paragraphs={[report.verdict, report.analysis]} items={report.next_steps} />
      )}
      {published ? <Published event={event} /> : <Rejected event={event} />}
    </section>
  )
}

// gates keep a rejected event's numbers out of the dashboards (BRD), so only the why is shown
function Rejected({ event }: { event: CausalEvent }) {
  return (
    <Empty className="border">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <ProhibitInset />
        </EmptyMedia>
        <EmptyTitle>Este evento não foi publicado</EmptyTitle>
        <EmptyDescription>
          <ul className="space-y-1">
            {rejectionReasons(event).map((r) => (
              <li key={r}>{reasonLabel(r)}</li>
            ))}
          </ul>
        </EmptyDescription>
      </EmptyHeader>
    </Empty>
  )
}

function Published({ event }: { event: CausalEvent }) {
  const { lift, series, fit } = event
  const ci = lift?.ci
  return (
    <div className="space-y-4">
      <p className="text-sm">
        {(lift?.abs ?? 0) >= 0 ? 'Aumento significativo' : 'Queda significativa'} de{' '}
        <strong>{formatSigned(lift?.abs)}</strong> no KPI ({formatSignedPct(lift?.rel_pct)}), IC 95% [
        {formatInteger(ci?.[0])}; {formatInteger(ci?.[1])}], p {formatPValue(event.p_value)}.
      </p>
      <Card size="sm" className="break-inside-avoid">
        <CardContent className="grid gap-3 sm:grid-cols-3 sm:divide-x">
          <Metric label="Lift" value={`${formatSigned(lift?.abs)} · ${formatSignedPct(lift?.rel_pct)}`} />
          <Metric label="Investimento incremental" value={formatMoney(event.incremental_investment)} />
          <Metric label="CPA incremental" value={formatMoney(event.cpa_incremental)} />
        </CardContent>
      </Card>
      {series && series.line.length > 0 && (
        <Figure title="KPI real × contrafactual">
          <ImpactChart event={event} line={series.line} />
        </Figure>
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        {series && series.investment.length > 0 && (
          <Figure title="Investimento">
            <InvestmentBars data={series.investment} />
          </Figure>
        )}
        {series && series.kpi.length > 0 && (
          <Figure title="KPI previsto × real">
            <KpiBars data={series.kpi} />
          </Figure>
        )}
      </div>
      <Collapsible className="rounded-xl ring-1 ring-foreground/10">
        <CollapsibleTrigger className="group flex w-full items-center justify-between px-4 py-3 text-sm font-medium">
          <span>
            Qualidade do ajuste{' '}
            <span className="ml-2 font-normal tabular-nums text-muted-foreground">
              R² {formatDecimal(fit?.r2)} · MAE {formatInteger(fit?.mae)} · MAPE {formatPct(fit?.mape)}
            </span>
          </span>
          <CaretDown className="size-4 text-muted-foreground transition-transform group-data-[state=open]:rotate-180" />
        </CollapsibleTrigger>
        {series && series.accuracy.length > 0 && (
          <CollapsibleContent className="px-4 pb-4">
            <AccuracyChart data={series.accuracy} />
          </CollapsibleContent>
        )}
      </Collapsible>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="space-y-0.5 sm:px-4 sm:first:pl-0 sm:last:pr-0">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="text-base font-semibold tabular-nums">{value}</p>
    </div>
  )
}

function Figure({ title, children }: { title: string; children: ReactNode }) {
  return (
    <Card size="sm" className="break-inside-avoid">
      <CardHeader>
        <CardTitle className="text-sm">{title}</CardTitle>
      </CardHeader>
      <CardContent>
        <figure aria-label={title}>{children}</figure>
      </CardContent>
    </Card>
  )
}
