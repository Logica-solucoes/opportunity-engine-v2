import { createFileRoute, redirect } from '@tanstack/react-router'
import { isPublishable, runQuery } from '@/lib/runs'

export const Route = createFileRoute('/_auth/w/$slug/execucoes/$runId/')({
  beforeLoad: async ({ context, params }) => {
    // a run that is missing for this user lands on Detalhes, whose layout says "não encontrada";
    // fetchQuery, not ensureQueryData: a cached "running" from before the run ended would pick the wrong tab
    const run = await context.queryClient.fetchQuery(runQuery(params.slug, params.runId)).catch(() => null)
    throw redirect({
      to: run && isPublishable(run.status) ? '/w/$slug/execucoes/$runId/causal' : '/w/$slug/execucoes/$runId/detalhes',
      params,
      replace: true,
    })
  },
})
