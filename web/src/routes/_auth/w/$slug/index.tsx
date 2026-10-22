import { useSuspenseQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { meQuery } from '@/lib/auth'

export const Route = createFileRoute('/_auth/w/$slug/')({ component: WorkspaceHome })

function WorkspaceHome() {
  const { slug } = Route.useParams()
  const { data: me } = useSuspenseQuery(meQuery)
  const workspace = me.workspaces.find((w) => w.slug === slug)!
  return (
    <div className="space-y-2">
      <h1 className="text-2xl font-semibold">{workspace.name}</h1>
      <p className="text-muted-foreground">Nenhuma simulação ainda.</p>
    </div>
  )
}
