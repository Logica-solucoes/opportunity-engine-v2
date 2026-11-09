import type { ReactNode } from 'react'
import { Info } from '@phosphor-icons/react'
import { GeminiIcon } from '@/components/GeminiIcon'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import type { ReportBase } from '@/lib/results'

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
        <CardTitle className="flex flex-wrap items-center gap-2">
          {report.source === 'llm' && <GeminiIcon />}
          {report.title}
          {report.source === 'deterministic' && (
            <Tooltip>
              <TooltipTrigger asChild>
                <button type="button" aria-label="Texto padrão" className="text-muted-foreground hover:text-foreground">
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
      <CardContent className="space-y-2 leading-relaxed">
        {paragraphs.filter(Boolean).map((p, n) => (
          <p key={`${n}-${p}`}>{p}</p>
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
