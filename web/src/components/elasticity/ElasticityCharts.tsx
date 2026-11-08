import {
  Area,
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceDot,
  XAxis,
  YAxis,
} from 'recharts'
import {
  type ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from '@/components/ui/chart'
import { formatCompact, formatMoney } from '@/lib/results'
import type { CurveRow, Mix, Scenario, TableRow } from '@/lib/scenario'

const investmentAxis = (
  <XAxis
    dataKey="investment"
    type="number"
    domain={['dataMin', 'dataMax']}
    tickFormatter={formatCompact}
    minTickGap={32}
  />
)
const moneyLabel = (_: unknown, payload: readonly { payload?: { investment?: number } }[]) =>
  formatMoney(payload[0]?.payload?.investment)

const saturationConfig = {
  band: { label: 'Faixa p5–p95', color: 'var(--chart-2)' },
  observed: { label: 'KPI projetado', color: 'var(--chart-1)' },
  extrapolated: { label: 'Extrapolado', color: 'var(--chart-1)' },
  filtered_out: { label: 'Fora do filtro', color: 'var(--muted-foreground)' },
} satisfies ChartConfig

export function SaturationChart({ scenario }: { scenario: Scenario }) {
  const data = scenario.curve.map((r) => ({
    investment: r.investment,
    band: r.kpi_lo != null && r.kpi_hi != null ? [r.kpi_lo, r.kpi_hi] : null,
    observed: r.extrapolated ? null : r.kpi,
    extrapolated: r.extrapolated ? r.kpi : null,
    filtered_out: r.in_filter ? null : r.kpi,
  }))
  const marks: [string, TableRow | null, string][] = [
    ['Atual', scenario.current, 'var(--chart-3)'],
    ['Recomendado', scenario.recommended, 'var(--chart-4)'],
    ['Saturação', scenario.saturation, 'var(--chart-5)'],
  ]
  return (
    <ChartContainer config={saturationConfig} className="h-80 w-full">
      <ComposedChart data={data} margin={{ left: 4, right: 4 }}>
        <CartesianGrid vertical={false} />
        {investmentAxis}
        <YAxis tickFormatter={formatCompact} width={56} />
        <Area dataKey="band" stroke="none" fill="var(--color-band)" fillOpacity={0.2} isAnimationActive={false} />
        <Line dataKey="observed" stroke="var(--color-observed)" strokeWidth={2} dot={false} isAnimationActive={false} />
        <Line
          dataKey="extrapolated"
          stroke="var(--color-extrapolated)"
          strokeWidth={2}
          strokeDasharray="4 4"
          dot={false}
          isAnimationActive={false}
        />
        <Line
          dataKey="filtered_out"
          stroke="var(--color-filtered_out)"
          strokeOpacity={0.5}
          strokeWidth={4}
          dot={false}
          isAnimationActive={false}
        />
        {marks.map(
          ([label, row, color]) =>
            row?.kpi != null && (
              <ReferenceDot
                key={label}
                x={row.investment}
                y={row.kpi}
                r={5}
                fill={color}
                stroke="var(--background)"
                label={{ value: label, position: 'top', fontSize: 11 }}
              />
            ),
        )}
        <ChartTooltip content={<ChartTooltipContent labelFormatter={moneyLabel} />} />
        <ChartLegend content={<ChartLegendContent />} />
      </ComposedChart>
    </ChartContainer>
  )
}

const icpaConfig = { icpa: { label: 'iCPA', color: 'var(--chart-1)' } } satisfies ChartConfig

export function IcpaChart({ curve }: { curve: CurveRow[] }) {
  return (
    <ChartContainer config={icpaConfig} className="h-56 w-full">
      <ComposedChart data={curve}>
        <CartesianGrid vertical={false} />
        {investmentAxis}
        <YAxis tickFormatter={formatCompact} width={56} />
        <Line dataKey="icpa" stroke="var(--color-icpa)" strokeWidth={2} dot={false} connectNulls={false} />
        <ChartTooltip content={<ChartTooltipContent labelFormatter={moneyLabel} />} />
      </ComposedChart>
    </ChartContainer>
  )
}

const revenueConfig = {
  revenue: { label: 'Receita', color: 'var(--chart-1)' },
  roas: { label: 'ROAS', color: 'var(--chart-3)' },
} satisfies ChartConfig

export function RevenueChart({ curve }: { curve: CurveRow[] }) {
  return (
    <ChartContainer config={revenueConfig} className="h-56 w-full">
      <ComposedChart data={curve}>
        <CartesianGrid vertical={false} />
        {investmentAxis}
        <YAxis yAxisId="revenue" tickFormatter={formatCompact} width={56} />
        <YAxis yAxisId="roas" orientation="right" width={40} />
        <Line yAxisId="revenue" dataKey="revenue" stroke="var(--color-revenue)" strokeWidth={2} dot={false} />
        <Line yAxisId="roas" dataKey="roas" stroke="var(--color-roas)" dot={false} />
        <ChartTooltip content={<ChartTooltipContent labelFormatter={moneyLabel} />} />
        <ChartLegend content={<ChartLegendContent />} />
      </ComposedChart>
    </ChartContainer>
  )
}

const mixConfig = {
  historical: { label: 'Histórico', color: 'var(--chart-2)' },
  optimized: { label: 'Otimizado', color: 'var(--chart-1)' },
  strategic: { label: 'Estratégico', color: 'var(--chart-4)' },
} satisfies ChartConfig

export function MixChart({ mix }: { mix: Partial<Mix> }) {
  const channels = Object.keys(mix.historical ?? mix.optimized ?? mix.strategic ?? {})
  const data = channels.map((channel) => ({
    channel,
    historical: mix.historical?.[channel] ?? null,
    optimized: mix.optimized?.[channel] ?? null,
    strategic: mix.strategic?.[channel] ?? null,
  }))
  return (
    <ChartContainer config={mixConfig} className="h-64 w-full">
      <BarChart data={data}>
        <CartesianGrid vertical={false} />
        <XAxis dataKey="channel" />
        <YAxis tickFormatter={formatCompact} width={56} />
        <Bar dataKey="historical" fill="var(--color-historical)" radius={4} />
        <Bar dataKey="optimized" fill="var(--color-optimized)" radius={4} />
        <Bar dataKey="strategic" fill="var(--color-strategic)" radius={4} />
        <ChartTooltip content={<ChartTooltipContent />} />
        <ChartLegend content={<ChartLegendContent />} />
      </BarChart>
    </ChartContainer>
  )
}
