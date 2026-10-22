import { Outlet, createFileRoute, redirect } from '@tanstack/react-router'
import { AppHeader } from '@/components/AppHeader'
import { ApiError } from '@/lib/api'
import { meQuery } from '@/lib/auth'

export const Route = createFileRoute('/_auth')({
  beforeLoad: async ({ context, location }) => {
    try {
      const me = await context.queryClient.ensureQueryData(meQuery)
      if (me.must_change_password) throw redirect({ to: '/trocar-senha' })
      return { me }
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) throw redirect({ to: '/login', search: { redirect: location.href } })
      throw e
    }
  },
  component: AuthLayout,
})

function AuthLayout() {
  return (
    <div className="min-h-screen">
      <AppHeader />
      <main className="mx-auto max-w-5xl p-6">
        <Outlet />
      </main>
    </div>
  )
}
