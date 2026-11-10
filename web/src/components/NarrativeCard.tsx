import type { ReactNode } from 'react'
import { Info } from '@phosphor-icons/react'
import { GeminiIcon } from '@/components/GeminiIcon'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import type { ReportBase } from '@/lib/results'

// "Cenário Atual: ..." gets its lead-in in bold; short and without digits, so a number never gets split
function Paragraph({ text }: { text: string }) {
  const at = text.indexOf(': ')
  const lead = at > 0 && at <= 40 && !/\d/.test(text.slice(0, at)) ? at : -1
  return (
    <p className="text-pretty">
      {lead > 0 ? <strong className="font-medium">{text.slice(0, lead + 1)}</strong> : null}
      {lead > 0 ? text.slice(lead + 1) : text}
    </p>
  )
}

// plain text only: React escapes it, so an LLM answer never becomes markup
export function NarrativeCard({
  report,
  paragraphs,
  items,
  children,
}: {
  report: ReportBase
  paragraphs: string[]
  items: string[]
  children?: ReactNode
}) {
  return (
    <Card role="region" aria-label="Análise" size="sm" className="break-inside-avoid">
      <CardHeader>
        <CardTitle className="flex items-start gap-2 text-balance">
          {report.source === 'llm' && <GeminiIcon className="mt-0.5 size-4 shrink-0" />}
          <span className="min-w-0">{report.title}</span>
          {report.source === 'deterministic' && (
            <Tooltip>
              <TooltipTrigger asChild>
                <button type="button" aria-label="Texto padrão" className="mt-0.5 shrink-0 text-muted-foreground hover:text-foreground">
                  <Info className="size-4" />
                  <span className="sr-only">Texto padrão</span>
                </button>
              </TooltipTrigger>
              <TooltipContent>Texto padrão do motor, sem revisão da IA</TooltipContent>
            </Tooltip>
          )}
          {report.grounding?.status === 'blocked' && <Badge variant="warning">Bloqueado pelo grounding</Badge>}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 text-sm leading-relaxed">
        {paragraphs.filter(Boolean).map((p, n) => (
          <Paragraph key={`${n}-${p}`} text={p} />
        ))}
        {children}
        {items.length > 0 && (
          <ul className="list-disc space-y-1 pl-5">
            {items.map((i, n) => (
              <li key={`${n}-${i}`}>{i}</li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
