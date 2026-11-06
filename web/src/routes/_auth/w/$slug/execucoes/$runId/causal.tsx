import { createFileRoute } from '@tanstack/react-router'
import { CausalTab } from '@/components/causal/CausalTab'

export const Route = createFileRoute('/_auth/w/$slug/execucoes/$runId/causal')({ component: CausalRoute })

function CausalRoute() {
  const { slug, runId } = Route.useParams()
  return <CausalTab slug={slug} runId={runId} />
}
