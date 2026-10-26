import { useQuery, useSuspenseQuery } from '@tanstack/react-query'
import { Link, createFileRoute } from '@tanstack/react-router'
import { meQuery, roleIn } from '@/lib/auth'
import { simulationQuery } from '@/lib/simulations'

export const Route = createFileRoute('/_auth/w/$slug/simulacoes/$id')({ component: SimulationPage })

function SimulationPage() {
  const { slug, id } = Route.useParams()
  const { data: me } = useSuspenseQuery(meQuery)
  if (roleIn(me, slug) === 'viewer') return <p>Sem permissão para editar simulações deste workspace.</p>
  return <SimulationDetail slug={slug} id={id} />
}

function SimulationDetail({ slug, id }: { slug: string; id: string }) {
  const { data: sim, isError } = useQuery(simulationQuery(slug, id))
  // 404 (another workspace or deleted) and 422 (non-numeric id) look the same to the user
  if (isError) return <p>Simulação não encontrada.</p>
  if (!sim) return null
  return (
    <div className="space-y-8">
      <div className="space-y-1">
        <Link to="/w/$slug" params={{ slug }} className="text-sm text-muted-foreground hover:text-primary">
          ← Simulações
        </Link>
        <h1 className="text-2xl font-semibold">{sim.name}</h1>
      </div>
    </div>
  )
}
