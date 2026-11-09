import { useMutation, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router'
import type { FormEvent } from 'react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { XCircle } from '@phosphor-icons/react'
import { api } from '@/lib/api'
import { errorMessage, meQuery, roleIn } from '@/lib/auth'
import { type Simulation, simulationQuery, simulationsQuery } from '@/lib/simulations'

export const Route = createFileRoute('/_auth/w/$slug/simulacoes/nova')({ component: NewSimulation })

function NewSimulation() {
  const { slug } = Route.useParams()
  const { data: me } = useSuspenseQuery(meQuery)
  if (roleIn(me, slug) === 'viewer')
    return (
      <Alert variant="destructive">
        <XCircle />
        <AlertDescription>Sem permissão para editar simulações deste workspace.</AlertDescription>
      </Alert>
    )
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
    <form onSubmit={submit} className="mx-auto max-w-md pt-6">
      <Card>
        <CardHeader>
          <CardTitle role="heading" aria-level={1} className="text-xl">
            Nova simulação
          </CardTitle>
          <CardDescription>Dê um nome. Os arquivos e os parâmetros vêm no passo seguinte.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-2">
          <Label htmlFor="sim-name">Nome</Label>
          <Input id="sim-name" name="name" required maxLength={120} autoFocus />
          {create.isError && (
            <p role="alert" className="text-sm text-destructive">
              {errorMessage(create.error)}
            </p>
          )}
        </CardContent>
        <CardFooter className="justify-end gap-2">
          <Button asChild variant="ghost">
            <Link to="/w/$slug" params={{ slug }}>
              Cancelar
            </Link>
          </Button>
          <Button type="submit" disabled={create.isPending}>
            Criar
          </Button>
        </CardFooter>
      </Card>
    </form>
  )
}
