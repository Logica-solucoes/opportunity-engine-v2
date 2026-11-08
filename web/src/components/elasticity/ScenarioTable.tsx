import { useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow as Row } from '@/components/ui/table'
import { formatDecimal, formatInteger, formatMoney, formatSigned } from '@/lib/results'
import type { Scenario, TableRow } from '@/lib/scenario'

type Line = [string, (r: TableRow) => string, boolean]
const LINES: Line[] = [
  ['Investimento', (r) => formatMoney(r.investment), false],
  ['KPI', (r) => formatInteger(r.kpi), false],
  ['KPI p5–p95', (r) => (r.kpi_lo == null || r.kpi_hi == null ? '—' : `${formatInteger(r.kpi_lo)} – ${formatInteger(r.kpi_hi)}`), false],
  ['CPA', (r) => formatMoney(r.cpa), false],
  ['iCPA', (r) => formatMoney(r.icpa), false],
  ['ROAS', (r) => formatDecimal(r.roas), true],
  ['iROAS', (r) => formatDecimal(r.iroas), true],
  ['Investimento incremental', (r) => formatMoney(r.incremental_investment), false],
  ['KPI incremental', (r) => formatSigned(r.incremental_kpi), false],
]

export function ScenarioTable({ scenario }: { scenario: Scenario }) {
  const [open, setOpen] = useState<string | null>(null)
  const columns: [string, TableRow | null][] = [
    ['Atual', scenario.current],
    ['Recomendado', scenario.recommended],
    ['Saturação', scenario.saturation],
  ]
  const lines = LINES.filter(([, , revenueOnly]) => scenario.revenue_mode || !revenueOnly)
  const notes = [...new Set(columns.flatMap(([, r]) => r?.notes ?? []))]
  const ramp = columns.find(([name]) => name === open)?.[1]?.ramp

  return (
    <section aria-label="Cenários" className="space-y-3">
      <Table>
        <TableHeader>
          <Row>
            <TableHead />
            {columns.map(([name, r]) => (
              <TableHead key={name} className="text-right">
                {name} {r?.extrapolated && <Badge variant="outline">extrapolado</Badge>}
              </TableHead>
            ))}
          </Row>
        </TableHeader>
        <TableBody>
          {lines.map(([label, show]) => (
            <Row key={label}>
              <TableCell className="text-muted-foreground">{label}</TableCell>
              {columns.map(([name, r]) => (
                <TableCell key={name} className="text-right tabular-nums">
                  {r ? show(r) : label === 'Investimento' ? 'Nenhum ponto da curva atende aos filtros' : ''}
                </TableCell>
              ))}
            </Row>
          ))}
          <Row>
            <TableCell className="text-muted-foreground">Rampa</TableCell>
            {columns.map(([name, r]) => (
              <TableCell key={name} className="text-right">
                {r?.ramp && (
                  <Button variant="link" size="sm" aria-expanded={open === name} onClick={() => setOpen(open === name ? null : name)}>
                    {r.ramp.length} degraus
                  </Button>
                )}
              </TableCell>
            ))}
          </Row>
        </TableBody>
      </Table>
      {ramp && (
        <ol aria-label={`Degraus até ${open}`} className="space-y-1 text-sm">
          {ramp.map((s) => (
            <li key={s.step} className="tabular-nums">
              {s.step}. {formatMoney(s.investment)} → KPI {formatInteger(s.kpi)}
              {s.kpi_lo != null && s.kpi_hi != null && ` (${formatInteger(s.kpi_lo)} – ${formatInteger(s.kpi_hi)})`}
            </li>
          ))}
        </ol>
      )}
      {notes.map((n) => (
        <p key={n} className="text-sm text-muted-foreground">
          {n}
        </p>
      ))}
    </section>
  )
}
