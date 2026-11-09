import { useMutation, useQuery, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { type FormEvent, useState } from 'react'
import { toast } from 'sonner'
import { LoadState } from '@/components/LoadState'
import { TempPasswordDialog } from '@/components/TempPasswordDialog'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { api } from '@/lib/api'
import { type Me, ROLE_LABELS, type Role, errorMessage, meQuery, roleIn } from '@/lib/auth'

type Member = { user_id: number; email: string; name: string; role: Role; active: boolean }
type NewMember = Member & { temp_password: string | null }

export const Route = createFileRoute('/_auth/w/$slug/membros')({ component: Members })

const ROLES = Object.entries(ROLE_LABELS) as [Role, string][]

function Members() {
  const { slug } = Route.useParams()
  const { data: me } = useSuspenseQuery(meQuery)
  if (roleIn(me, slug) !== 'admin') return <p>Sem permissão para gerenciar membros deste workspace.</p>
  return <MemberAdmin slug={slug} me={me} />
}

function MemberAdmin({ slug, me }: { slug: string; me: Me }) {
  const queryClient = useQueryClient()
  const key = ['members', slug]
  const base = `/w/${slug}/members`
  const members = useQuery({ queryKey: key, queryFn: () => api<Member[]>(base) })
  const [newRole, setNewRole] = useState<Role>('analyst')
  const [temp, setTemp] = useState<{ password: string; email: string } | null>(null)
  const refresh = () => queryClient.invalidateQueries({ queryKey: key })

  const add = useMutation({
    mutationFn: (body: { email: string; name?: string; role: Role }) => api<NewMember>(base, { method: 'POST', body }),
    onSuccess: (m) => {
      refresh()
      if (m.temp_password) setTemp({ password: m.temp_password, email: m.email })
      else toast.success(`${m.email} adicionado.`)
    },
  })
  const changeRole = useMutation({
    mutationFn: ({ id, role }: { id: number; role: Role }) => api(`${base}/${id}`, { method: 'PATCH', body: { role } }),
    onSuccess: refresh,
    onError: (e) => toast.error(errorMessage(e)),
  })
  const remove = useMutation({
    mutationFn: (id: number) => api(`${base}/${id}`, { method: 'DELETE' }),
    onSuccess: refresh,
    onError: (e) => toast.error(errorMessage(e)),
  })

  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const formEl = e.currentTarget
    const form = new FormData(formEl)
    add.mutate(
      {
        email: String(form.get('email')),
        // blank means "link an existing account", and the api refuses an empty name
        name: String(form.get('name') ?? '').trim() || undefined,
        role: newRole,
      },
      {
        onSuccess: () => {
          formEl.reset()
          setNewRole('analyst')
        },
      },
    )
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Membros</h1>
      <form onSubmit={submit} className="flex flex-wrap items-end gap-3">
        <div className="space-y-2">
          <Label htmlFor="m-email">E-mail</Label>
          <Input id="m-email" name="email" type="email" autoComplete="off" spellCheck={false} required />
        </div>
        {/* only the platform admin creates accounts; a workspace admin links existing ones */}
        {me.is_platform_admin && (
          <div className="space-y-2">
            <Label htmlFor="m-name">Nome</Label>
            <Input id="m-name" name="name" placeholder="Só para conta nova" />
          </div>
        )}
        <div className="space-y-2">
          <Label htmlFor="m-role">Papel</Label>
          <Select value={newRole} onValueChange={(v) => setNewRole(v as Role)}>
            <SelectTrigger id="m-role">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ROLES.map(([value, label]) => (
                <SelectItem key={value} value={value}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <Button type="submit" disabled={add.isPending}>
          Adicionar
        </Button>
      </form>
      {add.isError && (
        <p role="alert" className="text-sm text-destructive">
          {errorMessage(add.error)}
        </p>
      )}

      <LoadState query={members} />
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>E-mail</TableHead>
            <TableHead>Nome</TableHead>
            <TableHead>Papel</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {members.data?.map((m) => (
            <TableRow key={m.user_id}>
              <TableCell>
                {m.email}
                {!m.active && <span className="ml-2 text-xs text-muted-foreground">inativo</span>}
              </TableCell>
              <TableCell>{m.name}</TableCell>
              {/* demoting or removing yourself would leave this screen stale and forbidden; another admin does it */}
              <TableCell>
                {m.user_id === me.id ? (
                  ROLE_LABELS[m.role]
                ) : (
                  <Select
                    value={m.role}
                    disabled={changeRole.isPending}
                    onValueChange={(v) => changeRole.mutate({ id: m.user_id, role: v as Role })}
                  >
                    <SelectTrigger aria-label="Papel" size="sm">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {ROLES.map(([value, label]) => (
                        <SelectItem key={value} value={value}>
                          {label}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              </TableCell>
              <TableCell className="text-right">
                {m.user_id !== me.id && (
                  <AlertDialog>
                    <AlertDialogTrigger asChild>
                      <Button variant="outline" size="sm">
                        Remover
                      </Button>
                    </AlertDialogTrigger>
                    <AlertDialogContent>
                      <AlertDialogHeader>
                        <AlertDialogTitle>Remover {m.email} deste workspace?</AlertDialogTitle>
                      </AlertDialogHeader>
                      <AlertDialogFooter>
                        <AlertDialogCancel>Cancelar</AlertDialogCancel>
                        <AlertDialogAction onClick={() => remove.mutate(m.user_id)}>Remover</AlertDialogAction>
                      </AlertDialogFooter>
                    </AlertDialogContent>
                  </AlertDialog>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <TempPasswordDialog password={temp?.password ?? null} email={temp?.email ?? ''} onClose={() => setTemp(null)} />
    </div>
  )
}
