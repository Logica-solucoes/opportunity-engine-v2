import { Link, Outlet, createFileRoute, notFound } from '@tanstack/react-router'

export const Route = createFileRoute('/_auth/admin')({
  beforeLoad: ({ context: { me } }) => {
    if (!me.is_platform_admin) throw notFound()
  },
  component: AdminLayout,
})

const tab = 'border-b-2 border-transparent pb-2 hover:text-primary'

function AdminLayout() {
  return (
    <div className="space-y-6">
      <nav className="flex gap-6 border-b text-sm">
        <Link to="/admin/workspaces" className={tab} activeProps={{ className: 'border-primary! text-primary' }}>
          Workspaces
        </Link>
        <Link to="/admin/usuarios" className={tab} activeProps={{ className: 'border-primary! text-primary' }}>
          Usuários
        </Link>
        <Link to="/admin/uso" className={tab} activeProps={{ className: 'border-primary! text-primary' }}>
          Uso
        </Link>
      </nav>
      <Outlet />
    </div>
  )
}
