import { Badge } from '@/components/ui/badge'
import { type RunStatus, STATUS_LABELS } from '@/lib/runs'

const VARIANTS: Record<RunStatus, 'default' | 'secondary' | 'destructive' | 'outline'> = {
  queued: 'secondary',
  running: 'default',
  succeeded: 'outline',
  inconclusive: 'secondary',
  failed: 'destructive',
}

export function RunStatusBadge({ status }: { status: RunStatus }) {
  return <Badge variant={VARIANTS[status]}>{STATUS_LABELS[status]}</Badge>
}
