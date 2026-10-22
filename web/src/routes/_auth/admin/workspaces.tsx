import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, createFileRoute } from '@tanstack/react-router'
import { type FormEvent, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api } from '@/lib/api'
import { errorMessage, meQuery } from '@/lib/auth'

type Workspace = { id: number; name: string; slug: string; created_at: string }

export const Route = createFileRoute('/_auth/admin/workspaces')({ component: Workspaces })

const slugify = (name: string) =>
  name
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 40)

function Workspaces() {
  const queryClient = useQueryClient()
  const workspaces = useQuery({ queryKey: ['admin', 'workspaces'], queryFn: () => api<Workspace[]>('/admin/workspaces') })
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [slugTouched, setSlugTouched] = useState(false)
  const create = useMutation({
    mutationFn: (body: { name: string; slug: string }) => api<Workspace>('/admin/workspaces', { method: 'POST', body }),
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
    <div className="space-y-6">
      <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
        <div className="space-y-2">
          <Label htmlFor="ws-name">Nome</Label>
          <Input
            id="ws-name"
            value={name}
            required
            onChange={(e) => {
              setName(e.target.value)
              if (!slugTouched) setSlug(slugify(e.target.value))
            }}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="ws-slug">Slug</Label>
          <Input
            id="ws-slug"
            value={slug}
            required
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
      {create.isError && <p className="text-sm text-destructive">{errorMessage(create.error)}</p>}

      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Nome</TableHead>
            <TableHead>Slug</TableHead>
            <TableHead>Criado em</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {workspaces.data?.map((w) => (
            <TableRow key={w.id}>
              <TableCell>{w.name}</TableCell>
              <TableCell>{w.slug}</TableCell>
              <TableCell>{new Date(w.created_at).toLocaleDateString('pt-BR')}</TableCell>
              <TableCell className="text-right">
                <Link to="/w/$slug/membros" params={{ slug: w.slug }} className="text-primary underline">
                  Membros
                </Link>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
