import type { UseQueryResult } from '@tanstack/react-query'
import { errorMessage } from '@/lib/auth'

// without it an empty table means three things: still loading, failed, or really empty
export function LoadState({ query }: { query: UseQueryResult<unknown> }) {
  if (query.isPending) return <p className="text-sm text-muted-foreground">Carregando…</p>
  if (query.isError)
    return (
      <p role="alert" className="text-sm text-destructive">
        {errorMessage(query.error)}
      </p>
    )
  return null
}
