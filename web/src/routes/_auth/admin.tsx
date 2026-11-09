import { Link, Outlet, createFileRoute, notFound, useRouterState } from '@tanstack/react-router'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'

export const Route = createFileRoute('/_auth/admin')({
  beforeLoad: ({ context: { me } }) => {
    if (!me.is_platform_admin) throw notFound()
  },
  component: AdminLayout,
})

const TABS = [
  ['workspaces', 'Workspaces'],
  ['usuarios', 'Usuários'],
  ['uso', 'Uso'],
] as const

function AdminLayout() {
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const current = TABS.find(([key]) => pathname.endsWith(`/${key}`))?.[0]
  return (
    <div className="space-y-5">
      <h1 className="text-xl font-semibold text-balance">Administração</h1>
      <Tabs value={current ?? ''} className="gap-5">
        <TabsList variant="line" aria-label="Seções da administração">
          {TABS.map(([key, label]) => (
            <TabsTrigger key={key} value={key} asChild>
              <Link to={`/admin/${key}`}>{label}</Link>
            </TabsTrigger>
          ))}
        </TabsList>
        <Outlet />
      </Tabs>
    </div>
  )
}
