import { useMutation, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, redirect, useRouter } from '@tanstack/react-router'
import type { FormEvent } from 'react'
import { AuthCard } from '@/components/AuthCard'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import { type Me, errorMessage, meQuery, redirectSearch } from '@/lib/auth'

export const Route = createFileRoute('/login')({
  validateSearch: redirectSearch,
  beforeLoad: async ({ context, search }) => {
    const me = await context.queryClient.ensureQueryData(meQuery).catch(() => null)
    if (me) throw redirect({ href: search.redirect ?? '/' })
  },
  component: Login,
})

function Login() {
  const { redirect: next } = Route.useSearch()
  const router = useRouter()
  const queryClient = useQueryClient()
  const login = useMutation({
    mutationFn: (body: { email: string; password: string }) => api<Me>('/auth/login', { method: 'POST', body }),
    onSuccess: (me) => {
      queryClient.setQueryData(meQuery.queryKey, me)
      if (me.must_change_password) router.navigate({ to: '/trocar-senha', search: { redirect: next } })
      else router.history.push(next ?? '/')
    },
  })

  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    login.mutate({ email: String(form.get('email')), password: String(form.get('password')) })
  }

  return (
    <AuthCard title="Entrar">
      <form onSubmit={submit} className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="email">E-mail</Label>
          <Input id="email" name="email" type="email" autoComplete="username" required autoFocus />
        </div>
        <div className="space-y-2">
          <Label htmlFor="password">Senha</Label>
          <Input id="password" name="password" type="password" autoComplete="current-password" required />
        </div>
        {login.isError && (
          <p role="alert" className="text-sm text-destructive">
            {errorMessage(login.error)}
          </p>
        )}
        <Button type="submit" className="w-full" disabled={login.isPending}>
          Entrar
        </Button>
      </form>
    </AuthCard>
  )
}
