import { toast } from 'sonner'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, createFileRoute } from '@tanstack/react-router'
import { type FormEvent, useState } from 'react'
import { AddDialog } from '@/components/AddDialog'
import { DataTable } from '@/components/DataTable'
import { DeleteWorkspace } from '@/components/DeleteWorkspace'
import { LoadState } from '@/components/LoadState'
import { TrashedWorkspaces } from '@/components/TrashedWorkspaces'
import { type AdminWorkspace, GoogleConnectorDialog } from '@/components/GoogleConnectorDialog'
import { Plugs } from '@phosphor-icons/react'
import { Badge } from '@/components/ui/badge'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { DialogFooter } from '@/components/ui/dialog'
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { api } from '@/lib/api'
import { errorMessage, meQuery } from '@/lib/auth'
import { rowLink } from '@/lib/links'

export const Route = createFileRoute('/_auth/admin/workspaces')({ component: Workspaces })

const slugify = (name: string) =>
  name
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 40)

function Workspaces() {
  const queryClient = useQueryClient()
  const workspaces = useQuery({
    queryKey: ['admin', 'workspaces'],
    queryFn: () => api<AdminWorkspace[]>('/admin/workspaces'),
  })
  const active = workspaces.data?.filter((w) => !w.deleted_at) ?? []
  const trashed = workspaces.data?.filter((w) => w.deleted_at) ?? []
  const [open, setOpen] = useState(false)
  const [editing, setEditing] = useState<AdminWorkspace | null>(null)
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [slugTouched, setSlugTouched] = useState(false)
  const create = useMutation({
    mutationFn: (body: { name: string; slug: string }) => api<AdminWorkspace>('/admin/workspaces', { method: 'POST', body }),
    onSuccess: () => {
      toast.success('Workspace criado.')
      setOpen(false)
      setName('')
      setSlug('')
      setSlugTouched(false)
      queryClient.invalidateQueries({ queryKey: ['admin', 'workspaces'] })
      queryClient.invalidateQueries({ queryKey: meQuery.queryKey })
    },
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    create.mutate({ name, slug })
  }

  const addButton = (
    <AddDialog
      label="Novo workspace"
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) create.reset()
      }}
    >
      <form onSubmit={submit} className="space-y-4">
        <div className="grid gap-1.5">
          <Label htmlFor="ws-name">Nome</Label>
          <Input
            id="ws-name"
            value={name}
            required
            autoComplete="off"
            onChange={(e) => {
              setName(e.target.value)
              if (!slugTouched) setSlug(slugify(e.target.value))
            }}
          />
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="ws-slug">Slug</Label>
          <Input
            id="ws-slug"
            value={slug}
            required
            autoComplete="off"
            spellCheck={false}
            pattern="[a-z0-9\-]{2,40}"
            title="2 a 40 caracteres: letras minúsculas, números e hífen"
            onChange={(e) => {
              setSlug(e.target.value)
              setSlugTouched(true)
            }}
          />
        </div>
        {create.isError && (
          <Alert variant="destructive">
            <AlertDescription>{errorMessage(create.error)}</AlertDescription>
          </Alert>
        )}
        <DialogFooter>
          <Button type="submit" disabled={create.isPending}>
            Criar workspace
          </Button>
        </DialogFooter>
      </form>
    </AddDialog>
  )

  return (
    <TooltipProvider delayDuration={150}>
      <div className="space-y-6">
        <LoadState query={workspaces} />
        {workspaces.data && active.length === 0 && (
          <Empty className="border">
            <EmptyHeader>
              <EmptyTitle>Nenhum workspace</EmptyTitle>
              <EmptyDescription>Crie o primeiro.</EmptyDescription>
            </EmptyHeader>
            <EmptyContent>{addButton}</EmptyContent>
          </Empty>
        )}
        {active.length > 0 && (
          <DataTable
            id="workspaces"
            toolbar={addButton}
            rows={active}
            rowKey={(w) => w.id}
            columns={[
              { id: 'name', header: 'Nome', fixed: true, sort: (w) => w.name, className: 'font-medium', cell: (w) => w.name },
              { id: 'slug', header: 'Slug', sort: (w) => w.slug, className: 'font-mono text-xs text-muted-foreground', cell: (w) => w.slug },
              {
                id: 'created',
                header: 'Criado em',
                sort: (w) => w.created_at,
                className: 'tabular-nums',
                cell: (w) => new Date(w.created_at).toLocaleDateString('pt-BR'),
              },
              {
                id: 'google',
                header: 'Google',
                sort: (w) => (w.google ? 1 : 0),
                cell: (w) => (w.google ? <Badge variant="success">configurado</Badge> : <span className="text-muted-foreground">-</span>),
              },
              {
                id: 'actions',
                header: '',
                className: 'w-40',
                cell: (w) => (
                  <div className="flex items-center justify-center gap-3">
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <Button variant="ghost" size="icon-sm" aria-label="Conector Google" onClick={() => setEditing(w)}>
                          <Plugs aria-hidden />
                        </Button>
                      </TooltipTrigger>
                      <TooltipContent>Conector Google</TooltipContent>
                    </Tooltip>
                    <DeleteWorkspace workspace={w} />
                    <Link to="/w/$slug/membros" params={{ slug: w.slug }} className={rowLink}>
                      Membros
                    </Link>
                  </div>
                ),
              },
            ]}
          />
        )}
        <TrashedWorkspaces workspaces={trashed} />
        <GoogleConnectorDialog workspace={editing} onClose={() => setEditing(null)} />
      </div>
    </TooltipProvider>
  )
}
