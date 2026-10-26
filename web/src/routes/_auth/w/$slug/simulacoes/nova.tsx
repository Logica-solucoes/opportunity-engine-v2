import { useMutation, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import type { FormEvent } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import { errorMessage, meQuery, roleIn } from '@/lib/auth'
import { type Simulation, simulationQuery, simulationsQuery } from '@/lib/simulations'

export const Route = createFileRoute('/_auth/w/$slug/simulacoes/nova')({ component: NewSimulation })

function NewSimulation() {
  const { slug } = Route.useParams()
  const { data: me } = useSuspenseQuery(meQuery)
  if (roleIn(me, slug) === 'viewer') return <p>Sem permissão para editar simulações deste workspace.</p>
  return <NewSimulationForm slug={slug} />
}

function NewSimulationForm({ slug }: { slug: string }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const create = useMutation({
    mutationFn: (name: string) => api<Simulation>(`/w/${slug}/simulations`, { method: 'POST', body: { name } }),
    onSuccess: (sim) => {
      const id = String(sim.id)
      queryClient.setQueryData(simulationQuery(slug, id).queryKey, sim)
      queryClient.invalidateQueries({ queryKey: simulationsQuery(slug).queryKey, exact: true })
      navigate({ to: '/w/$slug/simulacoes/$id', params: { slug, id } })
    },
  })

  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    create.mutate(String(new FormData(e.currentTarget).get('name')))
  }

  return (
    <form onSubmit={submit} className="max-w-md space-y-4">
      <h1 className="text-2xl font-semibold">Nova simulação</h1>
      <div className="space-y-2">
        <Label htmlFor="sim-name">Nome</Label>
        <Input id="sim-name" name="name" required maxLength={120} />
      </div>
      {create.isError && (
        <p role="alert" className="text-sm text-destructive">
          {errorMessage(create.error)}
        </p>
      )}
      <Button type="submit" disabled={create.isPending}>
        Criar
      </Button>
    </form>
  )
}
