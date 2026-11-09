import { Outlet, createFileRoute, redirect } from '@tanstack/react-router'
import { AppHeader } from '@/components/AppHeader'
import { StripedPattern } from '@/components/magicui/striped-pattern'
import { ApiError } from '@/lib/api'
import { meQuery } from '@/lib/auth'

export const Route = createFileRoute('/_auth')({
  beforeLoad: async ({ context, location }) => {
    try {
      const me = await context.queryClient.ensureQueryData(meQuery)
      if (me.must_change_password) throw redirect({ to: '/trocar-senha', search: { redirect: location.href } })
      return { me }
    } catch (e) {
      if (e instanceof ApiError && e.status === 401)
        throw redirect({ to: '/login', search: { redirect: location.href } })
      throw e
    }
  },
  component: AuthLayout,
})

// narrow striped rails at the viewport edges; they only widen past the 115rem content
const rail =
  'pointer-events-none fixed inset-y-0 -z-10 w-[max(2rem,calc((100vw-115rem)/2))] border-border/60 max-sm:hidden print:hidden'

function Rail({ side }: { side: 'left' | 'right' }) {
  return (
    <div aria-hidden className={`${rail} ${side === 'left' ? 'left-0 border-r' : 'right-0 border-l'}`}>
      <StripedPattern className="text-border" />
    </div>
  )
}

function AuthLayout() {
  return (
    <div className="flex min-h-svh flex-col">
      <Rail side="left" />
      <Rail side="right" />
      <AppHeader />
      <main className="mx-auto w-full max-w-460 flex-1 px-4 pt-6 pb-12 sm:px-12 xl:px-14">
        <Outlet />
      </main>
      {/* mirrors the header and closes short pages at the bottom; in the flow, so it never covers content */}
      <footer className="h-14 border-t bg-card print:hidden" />
    </div>
  )
}
