import { useMutation, useQuery, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'
import { toast } from 'sonner'
import { TempPasswordDialog } from '@/components/TempPasswordDialog'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { DataTable } from '@/components/DataTable'
import { LoadState } from '@/components/LoadState'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty'
import { api } from '@/lib/api'
import { errorMessage, meQuery } from '@/lib/auth'

type User = {
  id: number
  email: string
  name: string
  active: boolean
  is_platform_admin: boolean
  locked_until: string | null
}

export const Route = createFileRoute('/_auth/admin/usuarios')({ component: Users })

const USERS = ['admin', 'users']

function StatusBadge({ u }: { u: User }) {
  if (!u.active) return <Badge variant="neutral">Inativo</Badge>
  if (u.locked_until && new Date(u.locked_until) > new Date()) return <Badge variant="warning">Bloqueado</Badge>
  return <Badge variant="success">Ativo</Badge>
}

function Users() {
  const { data: me } = useSuspenseQuery(meQuery)
  const queryClient = useQueryClient()
  const users = useQuery({ queryKey: USERS, queryFn: () => api<User[]>('/admin/users') })
  const [temp, setTemp] = useState<{ password: string; email: string } | null>(null)

  const reset = useMutation({
    mutationFn: (u: User) => api<{ temp_password: string }>(`/admin/users/${u.id}/reset-password`, { method: 'POST' }),
    onSuccess: (r, u) => {
      setTemp({ password: r.temp_password, email: u.email })
      queryClient.invalidateQueries({ queryKey: USERS })
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const setActive = useMutation({
    mutationFn: (u: User) => api<User>(`/admin/users/${u.id}`, { method: 'PATCH', body: { active: !u.active } }),
    onSuccess: (u) => {
      queryClient.invalidateQueries({ queryKey: USERS })
      toast.success(u.active ? 'Usuário reativado.' : 'Usuário desativado.')
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  return (
    <>
      <LoadState query={users} />
      {users.data?.length === 0 && (
        <Empty className="border">
          <EmptyHeader>
            <EmptyTitle>Nenhum usuário</EmptyTitle>
            <EmptyDescription>Crie usuários ao adicionar membros em um workspace.</EmptyDescription>
          </EmptyHeader>
        </Empty>
      )}
      {!!users.data?.length && (
        <DataTable
          id="usuarios"
          rows={users.data}
          rowKey={(u) => u.id}
          columns={[
            {
              id: 'email',
              header: 'E-mail',
              fixed: true,
              sort: (u) => u.email,
              cell: (u) => (
                <>
                  {u.email}
                  {u.is_platform_admin && (
                    <Badge variant="info" className="ml-2">
                      platform admin
                    </Badge>
                  )}
                </>
              ),
            },
            { id: 'name', header: 'Nome', sort: (u) => u.name, cell: (u) => u.name },
            { id: 'status', header: 'Status', sort: (u) => (u.active ? 'Ativo' : 'Inativo'), cell: (u) => <StatusBadge u={u} /> },
            {
              id: 'actions',
              header: '',
              className: 'space-x-1',
              cell: (u) => (
                <>
                  {/* resetting your own password drops your own session; use "Trocar senha" instead */}
                  {u.id !== me.id && (
                    <>
                      <AlertDialog>
                        <AlertDialogTrigger asChild>
                          <Button variant="ghost" size="sm">
                            Resetar senha
                          </Button>
                        </AlertDialogTrigger>
                        <AlertDialogContent>
                          <AlertDialogHeader>
                            <AlertDialogTitle>Resetar a senha de {u.email}?</AlertDialogTitle>
                            <AlertDialogDescription>
                              As sessões dessa pessoa caem e ela terá de trocar a senha no próximo login.
                            </AlertDialogDescription>
                          </AlertDialogHeader>
                          <AlertDialogFooter>
                            <AlertDialogCancel>Cancelar</AlertDialogCancel>
                            <AlertDialogAction onClick={() => reset.mutate(u)}>Resetar</AlertDialogAction>
                          </AlertDialogFooter>
                        </AlertDialogContent>
                      </AlertDialog>
                      <Button variant="ghost" size="sm" onClick={() => setActive.mutate(u)}>
                        {u.active ? 'Desativar' : 'Ativar'}
                      </Button>
                    </>
                  )}
                </>
              ),
            },
          ]}
        />
      )}
      <TempPasswordDialog password={temp?.password ?? null} email={temp?.email ?? ''} onClose={() => setTemp(null)} />
    </>
  )
}
