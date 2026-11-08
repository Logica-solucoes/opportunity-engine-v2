import { Area, Bar, BarChart, CartesianGrid, ComposedChart, Line, ReferenceArea, ReferenceLine, XAxis, YAxis } from 'recharts'
import { type ChartConfig, ChartContainer, ChartLegend, ChartLegendContent, ChartTooltip, ChartTooltipContent } from '@/components/ui/chart'
import { type ChannelFit, formatCompact, formatMoney, reasonLabel } from '@/lib/results'
import type { ChannelCurve } from '@/lib/scenario'

const curveConfig = {
  band: { label: 'Faixa p5–p95', color: 'var(--chart-2)' },
  observed: { label: 'KPI projetado', color: 'var(--chart-1)' },
  extrapolated: { label: 'Extrapolado', color: 'var(--chart-1)' },
} satisfies ChartConfig

function ChannelChart({ channel }: { channel: ChannelCurve }) {
  const data = channel.curve.map((p) => ({
    investment: p.investment,
    band: p.kpi_lo != null && p.kpi_hi != null ? [p.kpi_lo, p.kpi_hi] : null,
    observed: p.extrapolated ? null : p.kpi,
    extrapolated: p.extrapolated ? p.kpi : null,
  }))
  return (
    <figure className="space-y-1 rounded-lg border p-3">
      <figcaption className="text-sm font-medium">{channel.name}</figcaption>
      <ChartContainer config={curveConfig} className="h-44 w-full">
        <ComposedChart data={data}>
          <CartesianGrid vertical={false} />
          <XAxis dataKey="investment" type="number" domain={['dataMin', 'dataMax']} tickFormatter={formatCompact} minTickGap={24} />
          <YAxis tickFormatter={formatCompact} width={48} />
          {channel.observed_range && (
            <ReferenceArea x1={channel.observed_range[0]} x2={channel.observed_range[1]} fill="var(--muted-foreground)" fillOpacity={0.08} />
          )}
          <Area dataKey="band" stroke="none" fill="var(--color-band)" fillOpacity={0.2} isAnimationActive={false} />
          <Line dataKey="observed" stroke="var(--color-observed)" strokeWidth={2} dot={false} isAnimationActive={false} />
          <Line dataKey="extrapolated" stroke="var(--color-extrapolated)" strokeWidth={2} strokeDasharray="4 4" dot={false} isAnimationActive={false} />
          {channel.current != null && <ReferenceLine x={channel.current} stroke="var(--chart-3)" label={{ value: 'Atual', fontSize: 10 }} />}
          {channel.saturation != null && (
            <ReferenceLine x={channel.saturation} stroke="var(--chart-5)" label={{ value: 'Saturação', fontSize: 10 }} />
          )}
          <ChartTooltip content={<ChartTooltipContent labelFormatter={(_, p) => formatMoney(p[0]?.payload?.investment)} />} />
        </ComposedChart>
      </ChartContainer>
    </figure>
  )
}

const compareConfig = {
  current: { label: 'Atual', color: 'var(--chart-3)' },
  saturation: { label: 'Saturação', color: 'var(--chart-5)' },
} satisfies ChartConfig

export function ChannelCurves({ channels, hidden }: { channels: ChannelCurve[]; hidden: ChannelFit[] }) {
  return (
    <section aria-label="Canais" className="space-y-4">
      <h2 className="text-lg font-semibold">Canais</h2>
      {channels.length > 0 && (
        <>
          <div className="grid gap-3 lg:grid-cols-2">
            {channels.map((c) => (
              <ChannelChart key={c.name} channel={c} />
            ))}
          </div>
          <ChartContainer config={compareConfig} className="h-56 w-full">
            <BarChart data={channels.map((c) => ({ name: c.name, current: c.current, saturation: c.saturation }))}>
              <CartesianGrid vertical={false} />
              <XAxis dataKey="name" />
              <YAxis tickFormatter={formatCompact} width={56} />
              <Bar dataKey="current" fill="var(--color-current)" radius={4} />
              <Bar dataKey="saturation" fill="var(--color-saturation)" radius={4} />
              <ChartTooltip content={<ChartTooltipContent />} />
              <ChartLegend content={<ChartLegendContent />} />
            </BarChart>
          </ChartContainer>
        </>
      )}
      {hidden.length > 0 && (
        <div className="space-y-2">
          <h3 className="text-sm font-medium">Sem efeito identificável (fora das curvas, do mix e dos cenários)</h3>
          <ul className="space-y-1 text-sm">
            {hidden.map((c) => (
              <li key={c.name}>
                <span className="font-medium">{c.name}</span>
                <span className="text-muted-foreground"> — {c.reasons.map(reasonLabel).join('; ') || 'não identificável'}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  )
}
