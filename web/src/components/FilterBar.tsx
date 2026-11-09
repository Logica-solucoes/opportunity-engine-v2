import { FunnelSimple } from '@phosphor-icons/react'
import type { ReactNode } from 'react'
import { Label } from '@/components/ui/label'

// one look for every list's filters: a compact bar sized to its content, labels inline, actions go beside it (DataTable's `actions` or a plain flex row)
export function FilterBar({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-center gap-x-2 gap-y-2 rounded-lg border bg-card p-2">
      <FunnelSimple aria-hidden className="mx-1 size-4 shrink-0 text-muted-foreground" />
      {children}
    </div>
  )
}

export function FilterField({ label, htmlFor, children }: { label: string; htmlFor: string; children: ReactNode }) {
  return (
    <div className="flex items-center gap-2.5">
      <Label htmlFor={htmlFor} className="text-muted-foreground">
        {label}
      </Label>
      {children}
    </div>
  )
}
