import { useQuery, useSuspenseQuery } from '@tanstack/react-query'
import { Link, createFileRoute, redirect } from '@tanstack/react-router'
import { LoadState } from '@/components/LoadState'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { meQuery, roleIn } from '@/lib/auth'
import { formatDate, simulationsQuery } from '@/lib/simulations'

export const Route = createFileRoute('/_auth/w/$slug/')({
  // the run history is all a viewer sees in a workspace
  beforeLoad: ({ context: { me }, params }) => {
    if (roleIn(me, params.slug) === 'viewer') throw redirect({ to: '/w/$slug/execucoes', params })
  },
  component: WorkspaceHome,
})

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
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold">{workspace.name}</h1>
        {canEdit && (
          <div className="flex flex-wrap gap-2">
            <Button asChild variant="outline">
              <Link to="/w/$slug/execucoes" params={{ slug }}>
                Execuções
              </Link>
            </Button>
            <Button asChild>
              <Link to="/w/$slug/simulacoes/nova" params={{ slug }}>
                Nova simulação
              </Link>
            </Button>
          </div>
        )}
      </div>
      {canEdit ? <SimulationList slug={slug} /> : <p className="text-muted-foreground">Nenhuma simulação ainda.</p>}
    </div>
  )
}

function SimulationList({ slug }: { slug: string }) {
  const query = useQuery(simulationsQuery(slug))
  const { data } = query
  if (!data) return <LoadState query={query} />
  if (data.length === 0) return <p className="text-muted-foreground">Nenhuma simulação ainda.</p>
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Nome</TableHead>
          <TableHead>Criada por</TableHead>
          <TableHead>Atualizada em</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.map((s) => (
          <TableRow key={s.id}>
            <TableCell>
              <Link
                to="/w/$slug/simulacoes/$id"
                params={{ slug, id: String(s.id) }}
                className="font-medium hover:text-primary"
              >
                {s.name}
              </Link>
            </TableCell>
            <TableCell>{s.created_by_name}</TableCell>
            <TableCell>{formatDate(s.updated_at)}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
