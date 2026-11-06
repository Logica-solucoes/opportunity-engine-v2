import { createFileRoute } from '@tanstack/react-router'

export const Route = createFileRoute('/_auth/w/$slug/execucoes/$runId/causal')({ component: CausalRoute })

function CausalRoute() {
  return <p className="text-sm text-muted-foreground">Carregando…</p>
}
