import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { type FormEvent, type ReactNode, useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import { errorMessage } from '@/lib/auth'
import { type Simulation, simulationQuery, simulationsQuery } from '@/lib/simulations'

export function NewSimulationDialog({ slug, children }: { slug: string; children: ReactNode }) {
  const [open, setOpen] = useState(false)
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const create = useMutation({
    mutationFn: (name: string) => api<Simulation>(`/w/${slug}/simulations`, { method: 'POST', body: { name } }),
    onSuccess: (sim) => {
      const id = String(sim.id)
      queryClient.setQueryData(simulationQuery(slug, id).queryKey, sim)
      queryClient.invalidateQueries({ queryKey: simulationsQuery(slug).queryKey, exact: true })
      setOpen(false)
      navigate({ to: '/w/$slug/simulacoes/$id', params: { slug, id } })
    },
  })

  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    create.mutate(String(new FormData(e.currentTarget).get('name')))
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) create.reset()
      }}
    >
      <DialogTrigger asChild>{children}</DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <form onSubmit={submit} className="space-y-4">
          <DialogHeader>
            <DialogTitle>Nova simulação</DialogTitle>
            <DialogDescription>Dê um nome. Os arquivos e os parâmetros vêm no passo seguinte.</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor="sim-name">Nome</Label>
            <Input id="sim-name" name="name" required maxLength={120} autoFocus />
            {create.isError && (
              <p role="alert" className="text-sm text-destructive">
                {errorMessage(create.error)}
              </p>
            )}
          </div>
          <DialogFooter>
            <DialogClose asChild>
              <Button type="button" variant="ghost">
                Cancelar
              </Button>
            </DialogClose>
            <Button type="submit" disabled={create.isPending}>
              Criar
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
