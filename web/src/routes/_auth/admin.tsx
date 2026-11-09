import { Link, Outlet, createFileRoute, notFound, useRouterState } from '@tanstack/react-router'
import { ShieldCheck } from '@phosphor-icons/react'
import { PageHeader } from '@/components/PageHeader'
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
  const tab = TABS.find(([key]) => pathname.endsWith(`/${key}`))
  const current = tab?.[0]
  return (
    <div className="space-y-6">
      <PageHeader trail={[{ label: 'Admin', link: { to: '/admin/workspaces' } }, { label: tab?.[1] ?? 'Administração' }]} title="Administração" icon={ShieldCheck} hideTitle />
      <Tabs value={current ?? ''} className="gap-6">
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
