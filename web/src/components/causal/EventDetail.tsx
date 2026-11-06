import type { ReactNode } from 'react'
import { Badge } from '@/components/ui/badge'
import {
  type CausalEvent,
  eventPeriod,
  formatDecimal,
  formatInteger,
  formatMoney,
  formatPValue,
  formatPct,
  formatSigned,
  formatSignedPct,
  reasonLabel,
} from '@/lib/results'
import { AccuracyChart, ImpactChart, InvestmentBars, KpiBars } from './EventCharts'

export function EventDetail({ event }: { event: CausalEvent }) {
  const published = event.status === 'published'
  return (
    <section aria-label="Evento selecionado" className="min-w-0 space-y-4">
      <div className="space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="text-lg font-medium">{event.channels.join(', ')}</h2>
          <Badge variant={published ? 'default' : 'outline'}>{published ? 'Publicado' : 'Rejeitado'}</Badge>
        </div>
        <p className="text-sm text-muted-foreground">{eventPeriod(event)}</p>
      </div>
      {published ? <Published event={event} /> : <Rejected event={event} />}
    </section>
  )
}

// gates keep a rejected event's numbers out of the dashboards (BRD), so only the why is shown
function Rejected({ event }: { event: CausalEvent }) {
  return (
    <div className="space-y-2 text-sm">
      <p>Este evento não foi publicado:</p>
      <ul className="list-disc space-y-1 pl-5">
        {event.reasons.map((r) => (
          <li key={r}>{reasonLabel(r)}</li>
        ))}
      </ul>
    </div>
  )
}

function Published({ event }: { event: CausalEvent }) {
  const { lift, series, fit } = event
  const ci = lift?.ci
  return (
    <div className="space-y-6">
      <p className="text-sm">
        {(lift?.abs ?? 0) >= 0 ? 'Aumento significativo' : 'Queda significativa'} de{' '}
        <strong>{formatSigned(lift?.abs)}</strong> no KPI ({formatSignedPct(lift?.rel_pct)}), IC 95% [
        {formatInteger(ci?.[0])}; {formatInteger(ci?.[1])}], p {formatPValue(event.p_value)}.
      </p>
      <div className="grid gap-3 sm:grid-cols-3">
        <Metric label="Lift" value={`${formatSigned(lift?.abs)} · ${formatSignedPct(lift?.rel_pct)}`} />
        <Metric label="Investimento incremental" value={formatMoney(event.incremental_investment)} />
        <Metric label="CPA incremental" value={formatMoney(event.cpa_incremental)} />
      </div>
      {series && series.line.length > 0 && (
        <Figure title="KPI real × contrafactual">
          <ImpactChart event={event} line={series.line} />
        </Figure>
      )}
      <div className="grid gap-6 sm:grid-cols-2">
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
      <details className="space-y-3 text-sm">
        <summary className="cursor-pointer font-medium">Qualidade do ajuste</summary>
        <p className="text-muted-foreground">
          R² {formatDecimal(fit?.r2)} · MAE {formatInteger(fit?.mae)} · MAPE {formatPct(fit?.mape)}
        </p>
        {series && series.accuracy.length > 0 && <AccuracyChart data={series.accuracy} />}
      </details>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border p-3">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="font-medium tabular-nums">{value}</p>
    </div>
  )
}

function Figure({ title, children }: { title: string; children: ReactNode }) {
  return (
    <figure className="space-y-2">
      <figcaption className="text-sm font-medium">{title}</figcaption>
      {children}
    </figure>
  )
}
