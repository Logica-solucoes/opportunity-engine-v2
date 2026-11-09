import { CaretDown } from '@phosphor-icons/react'
import { type ReactNode, useState } from 'react'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { FieldDescription, FieldLegend, FieldSet } from '@/components/ui/field'
import { cn } from '@/lib/utils'

// one foldable block of a long form: title with a rule to the edge, a line of context, then the fields.
// The content stays mounted when folded, so uncontrolled inputs still reach FormData.
export function FormSection({
  title,
  description,
  forceOpen,
  children,
}: {
  title: string
  description?: ReactNode
  // an error inside must not stay folded
  forceOpen?: boolean
  children: ReactNode
}) {
  const [open, setOpen] = useState(true)
  return (
    // a required field that blocks the submit unfolds its section
    <Collapsible open={open || forceOpen} onOpenChange={setOpen} onInvalidCapture={() => setOpen(true)}>
      <FieldSet className="gap-0">
        <FieldLegend variant="label" className="mb-0 w-full">
          <CollapsibleTrigger asChild>
            <button
              type="button"
              className="group/section flex w-full items-center gap-4 rounded-md py-1 text-sm font-semibold outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              {title}
              <span aria-hidden className="h-px flex-1 bg-border" />
              <CaretDown
                aria-hidden
                className="size-4 text-muted-foreground transition-transform group-data-[state=closed]/section:-rotate-90"
              />
            </button>
          </CollapsibleTrigger>
        </FieldLegend>
        <CollapsibleContent forceMount className="flex flex-col gap-5 pt-2 data-[state=closed]:hidden">
          {description && <FieldDescription className="-mb-3">{description}</FieldDescription>}
          {children}
        </CollapsibleContent>
      </FieldSet>
    </Collapsible>
  )
}

// same column widths in every section, so fields line up from one section to the next
export function FieldGrid({ className, children }: { className?: string; children: ReactNode }) {
  return (
    <div className={cn('grid grid-cols-[repeat(auto-fill,minmax(13rem,1fr))] items-start gap-x-4 gap-y-5', className)}>
      {children}
    </div>
  )
}
