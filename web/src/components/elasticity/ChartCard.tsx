import type { ReactNode } from 'react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'

// aria-label on the card, so each chart stays a named region for tests and screen readers
export function ChartCard({ title, label = title, children }: { title: string; label?: string; children: ReactNode }) {
  return (
    <Card role="region" aria-label={label} size="sm" className="break-inside-avoid">
      <CardHeader>
        <CardTitle className="text-sm">{title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">{children}</CardContent>
    </Card>
  )
}
