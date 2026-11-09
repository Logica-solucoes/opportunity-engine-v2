import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, createFileRoute } from '@tanstack/react-router'
import { type FormEvent, useState } from 'react'
import { LoadState } from '@/components/LoadState'
import { type AdminWorkspace, GoogleConnectorDialog } from '@/components/GoogleConnectorDialog'
import { Plugs } from '@phosphor-icons/react'
import { Badge } from '@/components/ui/badge'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
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
  const [editing, setEditing] = useState<AdminWorkspace | null>(null)
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [slugTouched, setSlugTouched] = useState(false)
  const create = useMutation({
    mutationFn: (body: { name: string; slug: string }) => api<AdminWorkspace>('/admin/workspaces', { method: 'POST', body }),
    onSuccess: () => {
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

  return (
    <TooltipProvider delayDuration={150}>
      <div className="space-y-5">
        <Card>
          <CardHeader>
            <CardTitle>Novo workspace</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
              <div className="grid w-64 gap-1.5">
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
              <div className="grid w-56 gap-1.5">
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
              <Button type="submit" disabled={create.isPending}>
                Criar workspace
              </Button>
            </form>
            {create.isError && (
              <Alert variant="destructive">
                <AlertDescription>{errorMessage(create.error)}</AlertDescription>
              </Alert>
            )}
          </CardContent>
        </Card>

        <LoadState query={workspaces} />
        {workspaces.data?.length === 0 && (
          <Empty className="border">
            <EmptyHeader>
              <EmptyTitle>Nenhum workspace</EmptyTitle>
              <EmptyDescription>Crie o primeiro acima.</EmptyDescription>
            </EmptyHeader>
          </Empty>
        )}
        {!!workspaces.data?.length && (
          <Table>
            <TableHeader className="[&_th]:text-muted-foreground">
              <TableRow>
                <TableHead>Nome</TableHead>
                <TableHead>Slug</TableHead>
                <TableHead>Criado em</TableHead>
                <TableHead>Google</TableHead>
                <TableHead className="w-40" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {workspaces.data.map((w) => (
                <TableRow key={w.id}>
                  <TableCell className="font-medium">{w.name}</TableCell>
                  <TableCell className="font-mono text-xs text-muted-foreground">{w.slug}</TableCell>
                  <TableCell className="tabular-nums">{new Date(w.created_at).toLocaleDateString('pt-BR')}</TableCell>
                  <TableCell>
                    {w.google ? <Badge variant="success">configurado</Badge> : <span className="text-muted-foreground">-</span>}
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center justify-end gap-3">
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <Button variant="ghost" size="icon-sm" aria-label="Conector Google" onClick={() => setEditing(w)}>
                            <Plugs aria-hidden />
                          </Button>
                        </TooltipTrigger>
                        <TooltipContent>Conector Google</TooltipContent>
                      </Tooltip>
                      <Link to="/w/$slug/membros" params={{ slug: w.slug }} className={rowLink}>
                        Membros
                      </Link>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
        <GoogleConnectorDialog workspace={editing} onClose={() => setEditing(null)} />
      </div>
    </TooltipProvider>
  )
}
