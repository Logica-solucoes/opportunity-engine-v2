import { useQuery, useSuspenseQuery } from '@tanstack/react-query'
import { Link, createFileRoute, redirect } from '@tanstack/react-router'
import { PageHeader } from '@/components/PageHeader'
import { Flask, Plus } from '@phosphor-icons/react'
import { DataTable } from '@/components/DataTable'
import { NewSimulationDialog } from '@/components/NewSimulationDialog'
import { LoadState } from '@/components/LoadState'
import { Button } from '@/components/ui/button'
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
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
      <PageHeader slug={slug} trail={[{ label: 'Simulações' }]} title={workspace.name} icon={Flask} hideTitle />
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
  const newSimulation = (
    <NewSimulationDialog slug={slug}>
      <Button size="sm">
        <Plus />
        Nova simulação
      </Button>
    </NewSimulationDialog>
  )
  const runs = (
    <Button asChild variant="outline" size="sm">
      <Link to="/w/$slug/execucoes" params={{ slug }}>
        Execuções
      </Link>
    </Button>
  )
  const query = useQuery(simulationsQuery(slug))
  const { data } = query
  if (!data) return <LoadState query={query} />
  if (data.length === 0)
    return (
      <>
      <div className="flex justify-end gap-3">{runs}</div>
      <Empty className="border">
        <EmptyHeader>
          <EmptyMedia variant="icon">
            <Flask />
          </EmptyMedia>
          <EmptyTitle>Nenhuma simulação ainda.</EmptyTitle>
          <EmptyDescription>Envie os arquivos de investimento e desempenho para rodar a primeira análise.</EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <NewSimulationDialog slug={slug}>
            <Button>
              <Plus />
              Nova simulação
            </Button>
          </NewSimulationDialog>
        </EmptyContent>
      </Empty>
      </>
    )
  return (
    <DataTable
      id="simulacoes"
      toolbar={newSimulation}
      actions={runs}
      rows={data}
      rowKey={(s) => s.id}
      rowClassName="relative"
      columns={[
        {
          id: 'name',
          header: 'Nome',
          fixed: true,
          sort: (s) => s.name,
          cell: (s) => (
            <Link
              to="/w/$slug/simulacoes/$id"
              params={{ slug, id: String(s.id) }}
              className="font-medium outline-none after:absolute after:inset-0 focus-visible:after:ring-2 focus-visible:after:ring-inset focus-visible:after:ring-ring"
            >
              {s.name}
            </Link>
          ),
        },
        { id: 'author', header: 'Criada por', sort: (s) => s.created_by_name, className: 'text-muted-foreground', cell: (s) => s.created_by_name },
        {
          id: 'updated',
          header: 'Atualizada',
          sort: (s) => s.updated_at,
          className: 'text-muted-foreground tabular-nums',
          cell: (s) => <span title={formatDate(s.updated_at)}>{formatRelative(s.updated_at)}</span>,
        },
      ]}
    />
  )
}
