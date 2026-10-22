import { useMutation, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { createFileRoute, redirect, useRouter } from '@tanstack/react-router'
import { type FormEvent, useState } from 'react'
import { AuthCard } from '@/components/AuthCard'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import { errorMessage, meQuery, redirectSearch, useLogout } from '@/lib/auth'

export const Route = createFileRoute('/trocar-senha')({
  validateSearch: redirectSearch,
  beforeLoad: async ({ context, location }) => {
    const me = await context.queryClient.ensureQueryData(meQuery).catch(() => null)
    if (!me) throw redirect({ to: '/login', search: { redirect: location.href } })
  },
  component: ChangePassword,
})

function ChangePassword() {
  const { data: me } = useSuspenseQuery(meQuery)
  const queryClient = useQueryClient()
  const { redirect: next } = Route.useSearch()
  const router = useRouter()
  const logout = useLogout()
  const [mismatch, setMismatch] = useState(false)
  const change = useMutation({
    mutationFn: (body: { current: string; new: string }) => api('/auth/password', { method: 'POST', body }),
    onSuccess: () => {
      queryClient.setQueryData(meQuery.queryKey, { ...me, must_change_password: false })
      router.history.push(next ?? '/')
    },
  })

  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    const next = String(form.get('new'))
    setMismatch(next !== form.get('confirm'))
    if (next !== form.get('confirm')) return
    change.mutate({ current: String(form.get('current')), new: next })
  }

  return (
    <AuthCard title={me.must_change_password ? 'Defina sua senha' : 'Trocar senha'}>
      <form onSubmit={submit} className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="current">Senha atual</Label>
          <Input id="current" name="current" type="password" autoComplete="current-password" required />
        </div>
        <div className="space-y-2">
          <Label htmlFor="new">Nova senha</Label>
          <Input id="new" name="new" type="password" autoComplete="new-password" minLength={12} required />
          <p className="text-xs text-muted-foreground">Mínimo de 12 caracteres.</p>
        </div>
        <div className="space-y-2">
          <Label htmlFor="confirm">Confirme a nova senha</Label>
          <Input id="confirm" name="confirm" type="password" autoComplete="new-password" required />
        </div>
        {mismatch && (
          <p role="alert" className="text-sm text-destructive">
            As senhas não conferem.
          </p>
        )}
        {change.isError && (
          <p role="alert" className="text-sm text-destructive">
            {errorMessage(change.error)}
          </p>
        )}
        <Button type="submit" className="w-full" disabled={change.isPending}>
          Salvar
        </Button>
        {/* this screen has no header, so this is the only way out, e.g. on a shared machine */}
        <Button type="button" variant="ghost" className="w-full" onClick={() => logout.mutate()}>
          Sair
        </Button>
      </form>
    </AuthCard>
  )
}
