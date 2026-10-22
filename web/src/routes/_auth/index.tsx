import { useSuspenseQuery } from '@tanstack/react-query'
import { Link, createFileRoute, redirect } from '@tanstack/react-router'
import { Card, CardHeader, CardTitle } from '@/components/ui/card'
import { ROLE_LABELS, meQuery } from '@/lib/auth'

export const Route = createFileRoute('/_auth/')({
  beforeLoad: ({ context: { me } }) => {
    if (!me.is_platform_admin && me.workspaces.length === 1) {
      throw redirect({ to: '/w/$slug', params: { slug: me.workspaces[0].slug } })
    }
  },
  component: Home,
})

function Home() {
  const { data: me } = useSuspenseQuery(meQuery)
  return (
    <div className="space-y-4">
      <h1 className="text-2xl font-semibold">Workspaces</h1>
      {me.workspaces.length === 0 &&
        (me.is_platform_admin ? (
          <p>
            Nenhum workspace ainda.{' '}
            <Link to="/admin/workspaces" className="text-primary underline">
              Criar o primeiro
            </Link>
          </p>
        ) : (
          <p>Você ainda não tem acesso a nenhum workspace. Fale com o administrador.</p>
        ))}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {me.workspaces.map((w) => (
          <Link key={w.slug} to="/w/$slug" params={{ slug: w.slug }}>
            <Card className="transition hover:border-primary hover:shadow-md">
              <CardHeader>
                <CardTitle>{w.name}</CardTitle>
                <p className="text-sm text-muted-foreground">{ROLE_LABELS[w.role]}</p>
              </CardHeader>
            </Card>
          </Link>
        ))}
      </div>
    </div>
  )
}
