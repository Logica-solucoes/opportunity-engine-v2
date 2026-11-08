import { Badge } from '@/components/ui/badge'
import type { ReportBase } from '@/lib/results'

// plain text only: React escapes it, so an LLM answer never becomes markup
export function NarrativeCard({
  report,
  paragraphs,
  items,
}: {
  report: ReportBase
  paragraphs: string[]
  items: string[]
}) {
  return (
    <section aria-label="Análise" className="break-inside-avoid space-y-2 rounded-md border p-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="font-medium">{report.title}</h3>
        {report.source === 'deterministic' && <Badge variant="outline">Texto padrão</Badge>}
        {report.grounding?.status === 'blocked' && <Badge variant="outline">Bloqueado pelo grounding</Badge>}
      </div>
      {paragraphs.filter(Boolean).map((p) => (
        <p key={p}>{p}</p>
      ))}
      {items.length > 0 && (
        <ul className="list-disc space-y-1 pl-5">
          {items.map((i) => (
            <li key={i}>{i}</li>
          ))}
        </ul>
      )}
    </section>
  )
}
