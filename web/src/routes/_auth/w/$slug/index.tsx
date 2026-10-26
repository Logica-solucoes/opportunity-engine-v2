import { useQuery, useSuspenseQuery } from '@tanstack/react-query'
import { Link, createFileRoute } from '@tanstack/react-router'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { meQuery } from '@/lib/auth'
import { formatDate, simulationsQuery } from '@/lib/simulations'

export const Route = createFileRoute('/_auth/w/$slug/')({ component: WorkspaceHome })

function WorkspaceHome() {
  const { slug } = Route.useParams()
  const { data: me } = useSuspenseQuery(meQuery)
  const workspace = me.workspaces.find((w) => w.slug === slug)!
  // the list route is analyst+ in the api, so a viewer never asks for it
  const canEdit = workspace.role !== 'viewer'
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold">{workspace.name}</h1>
        {canEdit && (
          <Button asChild>
            <Link to="/w/$slug/simulacoes/nova" params={{ slug }}>
              Nova simulação
            </Link>
          </Button>
        )}
      </div>
      {canEdit ? <SimulationList slug={slug} /> : <p className="text-muted-foreground">Nenhuma simulação ainda.</p>}
    </div>
  )
}

function SimulationList({ slug }: { slug: string }) {
  const { data } = useQuery(simulationsQuery(slug))
  if (!data) return null
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
