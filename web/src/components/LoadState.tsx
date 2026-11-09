import type { UseQueryResult } from '@tanstack/react-query'
import { Skeleton } from '@/components/ui/skeleton'
import { errorMessage } from '@/lib/auth'

export function BlockSkeleton({ className = 'h-24' }: { className?: string }) {
  return (
    <div role="status" aria-label="Carregando" className="space-y-2">
      <Skeleton className={`w-full ${className}`} />
    </div>
  )
}

// without it an empty table means three things: still loading, failed, or really empty
export function LoadState({ query }: { query: UseQueryResult<unknown> }) {
  if (query.isPending) return <BlockSkeleton />
  if (query.isError)
    return (
      <p role="alert" className="text-sm text-destructive">
        {errorMessage(query.error)}
      </p>
    )
  return null
}
