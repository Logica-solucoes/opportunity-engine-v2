import { Badge } from '@/components/ui/badge'
import { type RunStatus, STATUS_LABELS } from '@/lib/runs'

const VARIANTS: Record<RunStatus, 'success' | 'warning' | 'destructive' | 'info'> = {
  queued: 'info',
  running: 'info',
  succeeded: 'success',
  inconclusive: 'warning',
  failed: 'destructive',
}

export function RunStatusBadge({ status }: { status: RunStatus }) {
  return <Badge variant={VARIANTS[status]}>{STATUS_LABELS[status]}</Badge>
}
