import { FlaskConical } from 'lucide-react'
import {
  type ExperimentDesign,
  TEST_TYPE_LABELS,
  formatInteger,
  formatMoney,
  formatShare,
  reasonLabel,
} from '@/lib/results'

export function ExperimentCard({ design }: { design: ExperimentDesign }) {
  return (
    <section aria-label="Desenho de experimento" className="break-inside-avoid space-y-3 rounded-md border p-4">
      <h3 className="flex items-center gap-2 font-medium">
        <FlaskConical className="size-4" /> Desenho de experimento
      </h3>
      {design.status !== 'ok' ? (
        <p className="text-sm text-muted-foreground">{design.reasons.map(reasonLabel).join(' ')}</p>
      ) : (
        <>
          <p className="text-sm">
            Um teste de <strong>{formatInteger(design.duration_days)} dias</strong> detecta um efeito a partir de{' '}
            <strong>{formatShare(design.mde_rel)}</strong> do KPI (95% de confiança, 80% de poder).
          </p>
          {design.feasible === false && (
            <p role="alert" className="text-sm text-destructive">
              {reasonLabel('duration_capped')}: o alvo era {formatShare(design.target_lift)}.
            </p>
          )}
          <table className="w-full text-sm">
            <thead className="text-left text-muted-foreground">
              <tr>
                <th className="font-normal">Canal</th>
                <th className="font-normal">Teste</th>
                <th className="text-right font-normal">Investimento por período</th>
                <th className="text-right font-normal">Orçamento em risco</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {design.designs.map((c) => (
                <tr key={`${c.channel}-${c.test_type}`}>
                  <td>{c.channel}</td>
                  <td>
                    {TEST_TYPE_LABELS[c.test_type]}
                    {c.step != null && ` (+${formatShare(c.step)})`}
                  </td>
                  <td className="text-right">{formatMoney(c.spend_per_period)}</td>
                  <td className="text-right">{formatMoney(c.budget_at_risk)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </>
      )}
      <ul className="list-disc pl-5 text-xs text-muted-foreground">
        {design.assumptions.map((a) => (
          <li key={a}>{a}</li>
        ))}
      </ul>
    </section>
  )
}
