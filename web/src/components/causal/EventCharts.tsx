import { Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceArea, XAxis, YAxis } from 'recharts'
import {
  type ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from '@/components/ui/chart'
import { type CausalEvent, type EventSeries, formatCompact, formatDay, seriesLabel } from '@/lib/results'

const impactConfig = {
  actual_kpi: { label: 'KPI real', color: 'var(--chart-1)' },
  forecasted_kpi: { label: 'Contrafactual', color: 'var(--chart-2)' },
  investment: { label: 'Investimento', color: 'var(--chart-3)' },
} satisfies ChartConfig

export function ImpactChart({ event, line }: { event: CausalEvent; line: EventSeries['line'] }) {
  return (
    <ChartContainer config={impactConfig} className="h-72 w-full">
      <LineChart data={line} margin={{ left: 4, right: 4 }}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="date" tickFormatter={formatDay} minTickGap={32} />
        <YAxis yAxisId="kpi" tickFormatter={formatCompact} width={56} />
        <YAxis yAxisId="investment" orientation="right" tickFormatter={formatCompact} width={56} />
        {event.start && event.end && (
          <ReferenceArea yAxisId="kpi" x1={event.start} x2={event.end} fill="var(--muted-foreground)" fillOpacity={0.08} />
        )}
        <Line yAxisId="kpi" dataKey="actual_kpi" stroke="var(--color-actual_kpi)" strokeWidth={2} dot={false} />
        <Line
          yAxisId="kpi"
          dataKey="forecasted_kpi"
          stroke="var(--color-forecasted_kpi)"
          strokeWidth={2}
          strokeDasharray="4 4"
          dot={false}
        />
        <Line yAxisId="investment" dataKey="investment" stroke="var(--color-investment)" dot={false} />
        <ChartTooltip content={<ChartTooltipContent labelFormatter={(d) => formatDay(String(d))} />} />
        <ChartLegend content={<ChartLegendContent />} />
      </LineChart>
    </ChartContainer>
  )
}

const investmentConfig = { investment: { label: 'Investimento', color: 'var(--chart-3)' } } satisfies ChartConfig
const kpiConfig = { kpi: { label: 'KPI', color: 'var(--chart-1)' } } satisfies ChartConfig

export function InvestmentBars({ data }: { data: EventSeries['investment'] }) {
  const rows = data.map((p) => ({ ...p, period: seriesLabel(p.period) }))
  return (
    <ChartContainer config={investmentConfig} className="h-48 w-full">
      <BarChart data={rows}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="period" />
        <YAxis tickFormatter={formatCompact} width={56} />
        <Bar dataKey="investment" fill="var(--color-investment)" radius={4} />
        <ChartTooltip content={<ChartTooltipContent />} />
      </BarChart>
    </ChartContainer>
  )
}

export function KpiBars({ data }: { data: EventSeries['kpi'] }) {
  const rows = data.map((p) => ({ ...p, category: seriesLabel(p.category) }))
  return (
    <ChartContainer config={kpiConfig} className="h-48 w-full">
      <BarChart data={rows}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="category" />
        <YAxis tickFormatter={formatCompact} width={56} />
        <Bar dataKey="kpi" fill="var(--color-kpi)" radius={4} />
        <ChartTooltip content={<ChartTooltipContent />} />
      </BarChart>
    </ChartContainer>
  )
}

const accuracyConfig = {
  kpi: { label: 'KPI real', color: 'var(--chart-1)' },
  predicted: { label: 'Previsto', color: 'var(--chart-2)' },
} satisfies ChartConfig

export function AccuracyChart({ data }: { data: EventSeries['accuracy'] }) {
  return (
    <ChartContainer config={accuracyConfig} className="h-56 w-full">
      <LineChart data={data}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="date" tickFormatter={formatDay} minTickGap={32} />
        <YAxis tickFormatter={formatCompact} width={56} />
        <Line dataKey="kpi" stroke="var(--color-kpi)" strokeWidth={2} dot={false} />
        <Line dataKey="predicted" stroke="var(--color-predicted)" strokeWidth={2} strokeDasharray="4 4" dot={false} />
        <ChartTooltip content={<ChartTooltipContent labelFormatter={(d) => formatDay(String(d))} />} />
        <ChartLegend content={<ChartLegendContent />} />
      </LineChart>
    </ChartContainer>
  )
}
