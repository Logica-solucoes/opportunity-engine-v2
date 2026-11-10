import { useSuspenseQuery } from '@tanstack/react-query'
import { Link, createFileRoute, redirect } from '@tanstack/react-router'
import { PageHeader } from '@/components/PageHeader'
import { ArrowRight, Buildings } from '@phosphor-icons/react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardTitle } from '@/components/ui/card'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { ROLE_LABELS, meQuery } from '@/lib/auth'
import { textLink } from '@/lib/links'

export const Route = createFileRoute('/_auth/')({
  // ?lista=1 is the breadcrumb: with a single workspace, `/` jumps straight into it unless the list was asked for
  validateSearch: (s: Record<string, unknown>): { lista?: true } => (s.lista ? { lista: true } : {}),
  beforeLoad: ({ context: { me }, search }) => {
    if (!search.lista && !me.is_platform_admin && me.workspaces.length === 1) {
      throw redirect({ to: '/w/$slug', params: { slug: me.workspaces[0].slug } })
    }
  },
  component: Home,
})

function Home() {
  const { data: me } = useSuspenseQuery(meQuery)
  return (
    <div className="space-y-6">
      <PageHeader trail={[{ label: 'Início', link: { to: '/' } }, { label: 'Workspaces' }]} title="Workspaces" icon={Buildings} hideTitle />
      {me.workspaces.length === 0 ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <Buildings />
            </EmptyMedia>
            <EmptyTitle>Nenhum workspace ainda</EmptyTitle>
            <EmptyDescription>
              {me.is_platform_admin ? (
                <Link to="/admin/workspaces" className={textLink}>
                  Criar o primeiro
                </Link>
              ) : (
                'Você ainda não tem acesso a nenhum workspace. Fale com o administrador.'
              )}
            </EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {me.workspaces.map((w) => (
            <Link
              key={w.slug}
              to="/w/$slug"
              params={{ slug: w.slug }}
              className="group rounded-xl outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
            >
              <Card className="transition-colors group-hover:bg-muted/50">
                <CardContent className="flex items-center justify-between gap-3">
                  <div className="min-w-0 space-y-1.5">
                    <CardTitle className="truncate">{w.name}</CardTitle>
                    <Badge variant="neutral">{ROLE_LABELS[w.role]}</Badge>
                  </div>
                  <ArrowRight aria-hidden className="size-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5" />
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
