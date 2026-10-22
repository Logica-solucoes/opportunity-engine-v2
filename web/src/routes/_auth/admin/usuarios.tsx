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
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
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

function status(u: User) {
  if (!u.active) return 'Inativo'
  if (u.locked_until && new Date(u.locked_until) > new Date()) return 'Bloqueado'
  return 'Ativo'
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
    onSuccess: () => queryClient.invalidateQueries({ queryKey: USERS }),
    onError: (e) => toast.error(errorMessage(e)),
  })

  return (
    <>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>E-mail</TableHead>
            <TableHead>Nome</TableHead>
            <TableHead>Status</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {users.data?.map((u) => (
            <TableRow key={u.id}>
              <TableCell>
                {u.email}
                {u.is_platform_admin && <span className="ml-2 text-xs text-primary">platform admin</span>}
              </TableCell>
              <TableCell>{u.name}</TableCell>
              <TableCell>{status(u)}</TableCell>
              <TableCell className="space-x-2 text-right">
                {/* resetting your own password drops your own session; use "Trocar senha" instead */}
                {u.id !== me.id && (
                  <>
                    <AlertDialog>
                      <AlertDialogTrigger asChild>
                        <Button variant="outline" size="sm">
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
                    <Button variant="outline" size="sm" onClick={() => setActive.mutate(u)}>
                      {u.active ? 'Desativar' : 'Ativar'}
                    </Button>
                  </>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <TempPasswordDialog password={temp?.password ?? null} email={temp?.email ?? ''} onClose={() => setTemp(null)} />
    </>
  )
}
