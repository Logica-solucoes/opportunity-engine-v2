import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import { errorMessage } from '@/lib/auth'
import { type Simulation, simulationQuery, simulationsQuery } from '@/lib/simulations'

export function DeleteSimulation({ slug, sim }: { slug: string; sim: Simulation }) {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const [typed, setTyped] = useState('')
  const remove = useMutation({
    mutationFn: () => api<void>(`/w/${slug}/simulations/${sim.id}`, { method: 'DELETE' }),
    onSuccess: async () => {
      // leave first: dropping the query while the page is mounted would refetch it into a 404
      await navigate({ to: '/w/$slug', params: { slug } })
      queryClient.removeQueries({ queryKey: simulationQuery(slug, String(sim.id)).queryKey })
      queryClient.invalidateQueries({ queryKey: simulationsQuery(slug).queryKey })
      queryClient.invalidateQueries({ queryKey: ['runs', slug] })
    },
  })

  return (
    <section className="space-y-2 border-t pt-6">
      <h2 className="text-lg font-medium">Apagar simulação</h2>
      <p className="text-sm text-muted-foreground">
        Apaga a simulação, todas as execuções dela e os arquivos enviados. Não dá para desfazer.
      </p>
      <AlertDialog
        onOpenChange={(open) => {
          if (!open) {
            setTyped('')
            remove.reset()
          }
        }}
      >
        <AlertDialogTrigger asChild>
          <Button variant="destructive">Apagar simulação</Button>
        </AlertDialogTrigger>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Apagar {sim.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              As execuções e os arquivos somem junto. Digite o nome da simulação para confirmar.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="space-y-1">
            <Label htmlFor="confirm-name">Nome da simulação</Label>
            <Input id="confirm-name" autoComplete="off" value={typed} onChange={(e) => setTyped(e.target.value)} />
          </div>
          {remove.isError && (
            <p role="alert" className="text-sm text-destructive">
              {errorMessage(remove.error)}
            </p>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel>Cancelar</AlertDialogCancel>
            {/* a plain Button: AlertDialogAction would close the dialog before a 409 could show */}
            <Button
              variant="destructive"
              disabled={typed !== sim.name || remove.isPending}
              onClick={() => remove.mutate()}
            >
              Apagar
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </section>
  )
}
