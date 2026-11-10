import { toast } from 'sonner'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { Trash } from '@phosphor-icons/react'
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
import { Label } from '@/components/ui/label'
import { PasswordInput } from '@/components/PasswordInput'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { api } from '@/lib/api'
import { errorMessage, meQuery } from '@/lib/auth'
import type { AdminWorkspace } from '@/components/GoogleConnectorDialog'

export function DeleteWorkspace({ workspace }: { workspace: AdminWorkspace }) {
  const queryClient = useQueryClient()
  const [open, setOpen] = useState(false)
  const [password, setPassword] = useState('')
  const remove = useMutation({
    mutationFn: () => api<void>(`/admin/workspaces/${workspace.id}`, { method: 'DELETE', body: { password } }),
    onSuccess: () => {
      toast.success('Workspace excluído.')
      setOpen(false)
      queryClient.invalidateQueries({ queryKey: ['admin', 'workspaces'] })
      queryClient.invalidateQueries({ queryKey: meQuery.queryKey })
    },
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    remove.mutate()
  }

  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) {
          setPassword('')
          remove.reset()
        }
      }}
    >
      <Tooltip>
        <TooltipTrigger asChild>
          <AlertDialogTrigger asChild>
            <Button variant="ghost" size="icon-sm" aria-label="Excluir workspace" className="text-destructive hover:text-destructive">
              <Trash aria-hidden />
            </Button>
          </AlertDialogTrigger>
        </TooltipTrigger>
        <TooltipContent>Excluir workspace</TooltipContent>
      </Tooltip>
      <AlertDialogContent>
        <form onSubmit={submit} className="space-y-4">
          <AlertDialogHeader>
            <AlertDialogTitle>Excluir {workspace.name}?</AlertDialogTitle>
            <AlertDialogDescription>
              Apaga também simulações, execuções, arquivos enviados e vínculos dos membros, sem como desfazer. As contas dos usuários
              continuam. Digite a sua senha para confirmar.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <div className="grid gap-1.5">
            <Label htmlFor={`delete-ws-password-${workspace.id}`}>Sua senha</Label>
            <PasswordInput
              id={`delete-ws-password-${workspace.id}`}
              autoComplete="current-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          {remove.isError && (
            <p role="alert" className="text-sm text-destructive">
              {errorMessage(remove.error)}
            </p>
          )}
          <AlertDialogFooter>
            <AlertDialogCancel disabled={remove.isPending}>Cancelar</AlertDialogCancel>
            <Button type="submit" variant="destructive" disabled={!password || remove.isPending}>
              Excluir
            </Button>
          </AlertDialogFooter>
        </form>
      </AlertDialogContent>
    </AlertDialog>
  )
}
