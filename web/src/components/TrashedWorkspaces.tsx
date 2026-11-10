import { toast } from 'sonner'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ArrowCounterClockwise } from '@phosphor-icons/react'
import { DataTable } from '@/components/DataTable'
import type { AdminWorkspace } from '@/components/GoogleConnectorDialog'
import { Button } from '@/components/ui/button'
import { api } from '@/lib/api'
import { errorMessage, meQuery } from '@/lib/auth'

const date = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString('pt-BR') : '-')

function RestoreButton({ workspace }: { workspace: AdminWorkspace }) {
  const queryClient = useQueryClient()
  const restore = useMutation({
    mutationFn: () => api<AdminWorkspace>(`/admin/workspaces/${workspace.id}/restore`, { method: 'POST' }),
    onSuccess: () => {
      toast.success('Workspace restaurado.')
      queryClient.invalidateQueries({ queryKey: ['admin', 'workspaces'] })
      queryClient.invalidateQueries({ queryKey: meQuery.queryKey })
    },
    onError: (error) => toast.error(errorMessage(error)),
  })
  return (
    <Button variant="outline" size="sm" disabled={restore.isPending} onClick={() => restore.mutate()}>
      <ArrowCounterClockwise aria-hidden />
      Restaurar
    </Button>
  )
}

export function TrashedWorkspaces({ workspaces }: { workspaces: AdminWorkspace[] }) {
  if (workspaces.length === 0) return null
  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-sm font-medium">Lixeira</h2>
        <p className="text-sm text-muted-foreground">Some para os membros agora e é apagado de vez na data indicada.</p>
      </div>
      <DataTable
        id="workspaces-lixeira"
        rows={workspaces}
        rowKey={(w) => w.id}
        columns={[
          { id: 'name', header: 'Nome', fixed: true, sort: (w) => w.name, className: 'font-medium', cell: (w) => w.name },
          { id: 'slug', header: 'Slug', sort: (w) => w.slug, className: 'font-mono text-xs text-muted-foreground', cell: (w) => w.slug },
          { id: 'deleted', header: 'Excluído em', sort: (w) => w.deleted_at ?? '', className: 'tabular-nums', cell: (w) => date(w.deleted_at) },
          { id: 'purge', header: 'Exclusão definitiva', sort: (w) => w.purge_at ?? '', className: 'tabular-nums', cell: (w) => date(w.purge_at) },
          { id: 'actions', header: '', className: 'w-32', cell: (w) => <RestoreButton workspace={w} /> },
        ]}
      />
    </section>
  )
}
