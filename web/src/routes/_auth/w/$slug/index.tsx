import { useQuery, useSuspenseQuery } from '@tanstack/react-query'
import { Link, createFileRoute, redirect, useNavigate } from '@tanstack/react-router'
import { Flask, Plus } from '@phosphor-icons/react'
import { LoadState } from '@/components/LoadState'
import { Button } from '@/components/ui/button'
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { meQuery, roleIn } from '@/lib/auth'
import { formatDate, simulationsQuery } from '@/lib/simulations'
import { textLink } from '@/lib/links'

export const Route = createFileRoute('/_auth/w/$slug/')({
  // the run history is all a viewer sees in a workspace
  beforeLoad: ({ context: { me }, params }) => {
    if (roleIn(me, params.slug) === 'viewer') throw redirect({ to: '/w/$slug/execucoes', params })
  },
  component: WorkspaceHome,
})

const relative = new Intl.RelativeTimeFormat('pt-BR', { numeric: 'auto' })
const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ['day', 86_400_000],
  ['hour', 3_600_000],
  ['minute', 60_000],
]

function formatRelative(iso: string) {
  const diff = new Date(iso).getTime() - Date.now()
  if (Math.abs(diff) > 30 * 86_400_000) return formatDate(iso)
  const [unit, ms] = UNITS.find(([, ms]) => Math.abs(diff) >= ms) ?? UNITS[2]
  return relative.format(Math.round(diff / ms), unit)
}

function WorkspaceHome() {
  const { slug } = Route.useParams()
  const { data: me } = useSuspenseQuery(meQuery)
  const workspace = me.workspaces.find((w) => w.slug === slug)
  // access can drop mid-session: a 404 elsewhere refetches /me
  if (!workspace) return <p>Não encontrado.</p>
  // the list route is analyst+ in the api, so a viewer never asks for it
  const canEdit = workspace.role !== 'viewer'
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold text-balance">{workspace.name}</h1>
        {canEdit && (
          <div className="flex flex-wrap gap-2">
            <Button asChild variant="outline">
              <Link to="/w/$slug/execucoes" params={{ slug }}>
                Execuções
              </Link>
            </Button>
            <Button asChild>
              <Link to="/w/$slug/simulacoes/nova" params={{ slug }}>
                <Plus />
                Nova simulação
              </Link>
            </Button>
          </div>
        )}
      </div>
      {/* a viewer only lands here when demoted mid-session, before beforeLoad runs again */}
      {canEdit ? (
        <SimulationList slug={slug} />
      ) : (
        <Link to="/w/$slug/execucoes" params={{ slug }} className={textLink}>
          Ver execuções publicadas
        </Link>
      )}
    </div>
  )
}

function SimulationList({ slug }: { slug: string }) {
  const query = useQuery(simulationsQuery(slug))
  const navigate = useNavigate()
  const { data } = query
  if (!data) return <LoadState query={query} />
  if (data.length === 0)
    return (
      <Empty className="border">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <Flask />
          </EmptyMedia>
          <EmptyTitle>Nenhuma simulação ainda.</EmptyTitle>
          <EmptyDescription>Envie os arquivos de investimento e desempenho para rodar a primeira análise.</EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          {/* a button, not a link: the header already has the "Nova simulação" link */}
          <Button onClick={() => navigate({ to: '/w/$slug/simulacoes/nova', params: { slug } })}>
            <Plus />
            Nova simulação
          </Button>
        </EmptyContent>
      </Empty>
    )
  return (
    <div className="rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Nome</TableHead>
            <TableHead>Criada por</TableHead>
            <TableHead>Atualizada</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {data.map((s) => (
            <TableRow key={s.id} className="relative">
              <TableCell>
                <Link
                  to="/w/$slug/simulacoes/$id"
                  params={{ slug, id: String(s.id) }}
                  className="font-medium outline-none after:absolute after:inset-0 focus-visible:after:ring-2 focus-visible:after:ring-inset focus-visible:after:ring-ring"
                >
                  {s.name}
                </Link>
              </TableCell>
              <TableCell className="text-muted-foreground">{s.created_by_name}</TableCell>
              <TableCell className="text-muted-foreground tabular-nums" title={formatDate(s.updated_at)}>
                {formatRelative(s.updated_at)}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
