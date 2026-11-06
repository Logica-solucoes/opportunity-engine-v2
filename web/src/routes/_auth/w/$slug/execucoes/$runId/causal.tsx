import { useQuery } from '@tanstack/react-query'
import { Navigate, createFileRoute } from '@tanstack/react-router'
import { CausalTab } from '@/components/causal/CausalTab'
import { isPublishable, runQuery } from '@/lib/runs'

export const Route = createFileRoute('/_auth/w/$slug/execucoes/$runId/causal')({ component: CausalRoute })

function CausalRoute() {
  const { slug, runId } = Route.useParams()
  const { data: run } = useQuery(runQuery(slug, runId))
  // a /causal URL opened before the run ends would cache the results 404 for good (staleTime: Infinity)
  if (run && !isPublishable(run.status))
    return <Navigate to="/w/$slug/execucoes/$runId/detalhes" params={{ slug, runId }} replace />
  return <CausalTab slug={slug} runId={runId} />
}
