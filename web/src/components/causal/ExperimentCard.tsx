import { Flask, Warning } from '@phosphor-icons/react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import {
  type ExperimentCell,
  type ExperimentDesign,
  formatInteger,
  formatMoney,
  formatShare,
  reasonLabel,
} from '@/lib/results'

function byChannel(designs: ExperimentCell[]) {
  const rows = new Map<string, Partial<Record<ExperimentCell['test_type'], ExperimentCell>>>()
  for (const d of designs) rows.set(d.channel, { ...rows.get(d.channel), [d.test_type]: d })
  return [...rows]
}

function Cell({ cell }: { cell?: ExperimentCell }) {
  if (!cell) return <TableCell className="text-muted-foreground">—</TableCell>
  return (
    <TableCell className="tabular-nums max-sm:whitespace-normal">
      <div>{formatMoney(cell.budget_at_risk)}</div>
      <div className="text-xs text-muted-foreground max-sm:text-[10px]">
        {cell.step != null && `+${formatShare(cell.step)} · `}
        {formatMoney(cell.spend_per_period)} por período
      </div>
    </TableCell>
  )
}

export function ExperimentCard({ design }: { design: ExperimentDesign }) {
  const ok = design.status === 'ok'
  return (
    <Card aria-label="Desenho de experimento" role="region" className="break-inside-avoid">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <Flask className="size-4 text-muted-foreground" /> Desenho de experimento
        </CardTitle>
        <CardDescription>
          {ok ? (
            <>
              Um teste de <strong className="font-medium text-foreground">{formatInteger(design.duration_days)} dias</strong>{' '}
              detecta um efeito a partir de{' '}
              <strong className="font-medium text-foreground">{formatShare(design.mde_rel)}</strong> do KPI (95% de
              confiança, 80% de poder).
            </>
          ) : (
            design.reasons.map(reasonLabel).join(' ')
          )}
        </CardDescription>
      </CardHeader>
      {ok && (
        <CardContent className="space-y-3">
          {design.feasible === false && (
            <Alert variant="warning">
              <Warning />
              <AlertDescription>
                {reasonLabel('duration_capped')}: o alvo era {formatShare(design.target_lift)}.
              </AlertDescription>
            </Alert>
          )}
          <Table className="max-sm:text-xs max-sm:[&_td]:px-1 max-sm:[&_th]:px-1 max-sm:[&_th]:whitespace-normal">
            <TableHeader>
              <TableRow>
                <TableHead>Canal</TableHead>
                <TableHead>Desligar canal</TableHead>
                <TableHead>Aumentar orçamento</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {byChannel(design.designs).map(([channel, tests]) => (
                <TableRow key={channel}>
                  <TableCell className="font-medium max-sm:whitespace-normal">{channel}</TableCell>
                  <Cell cell={tests.on_off} />
                  <Cell cell={tests.step_up} />
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <p className="text-xs text-muted-foreground">Valores em orçamento em risco no teste.</p>
        </CardContent>
      )}
      {design.assumptions.length > 0 && (
        <CardFooter className="flex-col items-start gap-1 text-xs text-muted-foreground">
          {design.assumptions.map((a) => (
            <p key={a}>{a}</p>
          ))}
        </CardFooter>
      )}
    </Card>
  )
}
