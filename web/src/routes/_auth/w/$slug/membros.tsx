import { useMutation, useQuery, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { type FormEvent, useState } from 'react'
import { UsersThree } from '@phosphor-icons/react'
import { toast } from 'sonner'
import { PageHeader } from '@/components/PageHeader'
import { AddDialog } from '@/components/AddDialog'
import { LoadState } from '@/components/LoadState'
import { DataTable } from '@/components/DataTable'
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
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { DialogFooter } from '@/components/ui/dialog'
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { api } from '@/lib/api'
import { type Me, ROLE_LABELS, type Role, errorMessage, meQuery, roleIn } from '@/lib/auth'

type Member = { user_id: number; email: string; name: string; role: Role; active: boolean }
type NewMember = Member & { temp_password: string | null }

export const Route = createFileRoute('/_auth/w/$slug/membros')({ component: Members })

const ROLES = Object.entries(ROLE_LABELS) as [Role, string][]

function Members() {
  const { slug } = Route.useParams()
  const { data: me } = useSuspenseQuery(meQuery)
  if (roleIn(me, slug) !== 'admin')
    return (
      <Empty className="border">
        <EmptyHeader>
          <EmptyTitle>Sem permissão</EmptyTitle>
          <EmptyDescription>Sem permissão para gerenciar membros deste workspace.</EmptyDescription>
        </EmptyHeader>
      </Empty>
    )
  return <MemberAdmin slug={slug} me={me} />
}

function MemberAdmin({ slug, me }: { slug: string; me: Me }) {
  const queryClient = useQueryClient()
  const key = ['members', slug]
  const base = `/w/${slug}/members`
  const members = useQuery({ queryKey: key, queryFn: () => api<Member[]>(base) })
  const [open, setOpen] = useState(false)
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
    onSuccess: () => {
      refresh()
      toast.success('Papel atualizado.')
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const remove = useMutation({
    mutationFn: (id: number) => api(`${base}/${id}`, { method: 'DELETE' }),
    onSuccess: () => {
      refresh()
      toast.success('Membro removido.')
    },
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
          setOpen(false)
          formEl.reset()
          setNewRole('analyst')
        },
      },
    )
  }

  const addButton = (
    <AddDialog
      label="Adicionar membro"
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) add.reset()
      }}
    >
      <form onSubmit={submit} className="space-y-4">
        <div className="grid gap-1.5">
          <Label htmlFor="m-email">E-mail</Label>
          <Input id="m-email" name="email" type="email" autoComplete="off" spellCheck={false} required />
        </div>
        {/* only the platform admin creates accounts; a workspace admin links existing ones */}
        {me.is_platform_admin && (
          <div className="grid gap-1.5">
            <Label htmlFor="m-name">Nome</Label>
            <Input id="m-name" name="name" autoComplete="off" placeholder="Só para conta nova…" />
          </div>
        )}
        <div className="grid gap-1.5">
          <Label htmlFor="m-role">Papel</Label>
          <Select value={newRole} onValueChange={(v) => setNewRole(v as Role)}>
            <SelectTrigger id="m-role" className="w-full">
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
        {add.isError && (
          <Alert variant="destructive">
            <AlertDescription>{errorMessage(add.error)}</AlertDescription>
          </Alert>
        )}
        <DialogFooter>
          <Button type="submit" disabled={add.isPending}>
            Adicionar
          </Button>
        </DialogFooter>
      </form>
    </AddDialog>
  )

  return (
    <div className="space-y-6">
      <PageHeader slug={slug} trail={[{ label: 'Membros' }]} title="Membros" icon={UsersThree} hideTitle />
      <LoadState query={members} />
      {members.data?.length === 0 && (
        <Empty className="border">
          <EmptyHeader>
            <EmptyTitle>Nenhum membro</EmptyTitle>
            <EmptyDescription>Adicione alguém pelo e-mail.</EmptyDescription>
          </EmptyHeader>
          <EmptyContent>{addButton}</EmptyContent>
        </Empty>
      )}
      {!!members.data?.length && (
        <DataTable
          id="membros"
          toolbar={addButton}
          rows={members.data}
          rowKey={(m) => m.user_id}
          columns={[
            {
              id: 'email',
              header: 'E-mail',
              fixed: true,
              sort: (m) => m.email,
              cell: (m) => (
                <>
                  {m.email}
                  {!m.active && (
                    <Badge variant="neutral" className="ml-2">
                      inativo
                    </Badge>
                  )}
                </>
              ),
            },
            { id: 'name', header: 'Nome', sort: (m) => m.name, cell: (m) => m.name },
            {
              id: 'role',
              header: 'Papel',
              sort: (m) => ROLE_LABELS[m.role],
              // demoting or removing yourself would leave this screen stale and forbidden; another admin does it
              cell: (m) => (
                <div className="flex justify-center">
                  {m.user_id === me.id ? (
                    <span className="px-2.5">{ROLE_LABELS[m.role]}</span>
                  ) : (
                    <Select
                      value={m.role}
                      disabled={changeRole.isPending}
                      onValueChange={(v) => changeRole.mutate({ id: m.user_id, role: v as Role })}
                    >
                      <SelectTrigger aria-label="Papel" size="sm" className="w-32">
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
                </div>
              ),
            },
            {
              id: 'actions',
              header: '',
              cell: (m) => (
                <>
                  {m.user_id !== me.id && (
                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <Button variant="ghost" size="sm" className="text-destructive hover:text-destructive">
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
                </>
              ),
            },
          ]}
        />
      )}
      <TempPasswordDialog password={temp?.password ?? null} email={temp?.email ?? ''} onClose={() => setTemp(null)} />
    </div>
  )
}
