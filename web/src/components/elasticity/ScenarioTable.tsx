import { Fragment, useState } from 'react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
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

// below sm every value row stacks the three scenarios, each with its name on the left
const scenarioLabel = (name: string, r: TableRow | null) => (r?.extrapolated ? `${name} (extrapolado)` : name)

const stacked =
  'max-sm:flex max-sm:justify-between max-sm:gap-3 max-sm:px-0 max-sm:text-right max-sm:before:text-left max-sm:before:text-muted-foreground max-sm:before:content-[attr(data-label)]'

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
    <Card role="region" aria-label="Cenários" size="sm" className="break-inside-avoid">
      <CardHeader>
        <CardTitle className="text-sm">Cenários</CardTitle>
        <CardDescription className="text-xs">Valores mensais</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* below sm the label gets its own row and the scenarios stack under it */}
        <Table className="tabular-nums [&_td]:px-2 [&_th]:px-2">
          <TableHeader className="max-sm:sr-only">
            <Row>
              <TableHead className="w-24 max-sm:hidden" />
              {columns.map(([name, r]) => (
                <TableHead key={name} className="whitespace-normal">
                  {name} {r?.extrapolated && <Badge variant="warning">extrapolado</Badge>}
                </TableHead>
              ))}
            </Row>
          </TableHeader>
          <TableBody>
            {lines.map(([label, show]) => (
              <Fragment key={label}>
              <Row className="border-b-0 sm:hidden">
                <TableCell colSpan={columns.length} className="pb-0 pt-3 text-left font-medium">
                  {label}
                </TableCell>
              </Row>
              <Row className="max-sm:block max-sm:py-1">
                <TableCell className="whitespace-normal text-muted-foreground max-sm:hidden">{label}</TableCell>
                {columns.map(([name, r]) => (
                  <TableCell key={name} data-label={scenarioLabel(name, r)} className={`whitespace-normal ${stacked}`}>
                    {r ? (
                      show(r)
                        .split(' – ')
                        .map((part, i) => (
                          <span key={i} className="block">
                            {i > 0 && '– '}
                            {part}
                          </span>
                        ))
                    ) : label === 'Investimento' ? (
                      'Nenhum ponto da curva atende aos filtros'
                    ) : (
                      ''
                    )}
                  </TableCell>
                ))}
              </Row>
              </Fragment>
            ))}
            <Row className="border-b-0 sm:hidden">
              <TableCell colSpan={columns.length} className="pb-0 pt-3 text-left font-medium">
                Rampa
              </TableCell>
            </Row>
            <Row className="max-sm:block max-sm:py-1">
              <TableCell className="text-muted-foreground max-sm:hidden">Rampa</TableCell>
              {columns.map(([name, r]) => (
                <TableCell key={name} data-label={scenarioLabel(name, r)} className={stacked}>
                  {r?.ramp && (
                    <Button
                      variant="link"
                      size="sm"
                      aria-expanded={open === name}
                      onClick={() => setOpen(open === name ? null : name)}
                    >
                      {r.ramp.length} degraus
                    </Button>
                  )}
                </TableCell>
              ))}
            </Row>
          </TableBody>
        </Table>
        {ramp && (
          <ol aria-label={`Degraus até ${open}`} className="space-y-1 rounded-lg bg-muted/50 p-3 text-sm">
            {ramp.map((s) => (
              <li key={s.step} className="tabular-nums">
                {s.step}. {formatMoney(s.investment)} → KPI {formatInteger(s.kpi)}
                {s.kpi_lo != null && s.kpi_hi != null && ` (${formatInteger(s.kpi_lo)} – ${formatInteger(s.kpi_hi)})`}
              </li>
            ))}
          </ol>
        )}
        {notes.map((n) => (
          <p key={n} className="text-xs text-muted-foreground">
            {n}
          </p>
        ))}
      </CardContent>
    </Card>
  )
}
