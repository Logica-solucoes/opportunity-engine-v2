import { useQuery } from '@tanstack/react-query'
import { Navigate, createFileRoute } from '@tanstack/react-router'
import { ElasticityTab } from '@/components/elasticity/ElasticityTab'
import { isPublishable, runQuery } from '@/lib/runs'

export const Route = createFileRoute('/_auth/w/$slug/execucoes/$runId/elasticidade')({ component: ElasticityRoute })

function ElasticityRoute() {
  const { slug, runId } = Route.useParams()
  const { data: run } = useQuery(runQuery(slug, runId))
  // same as causal: a URL opened before the run ends would cache the results 404 for good
  if (run && !isPublishable(run.status))
    return <Navigate to="/w/$slug/execucoes/$runId/detalhes" params={{ slug, runId }} replace />
  return <ElasticityTab slug={slug} runId={runId} />
}
