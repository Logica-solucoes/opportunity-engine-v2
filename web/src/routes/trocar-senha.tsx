import { useMutation, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { createFileRoute, redirect, useRouter } from '@tanstack/react-router'
import { type FormEvent, useState } from 'react'
import { Info } from '@phosphor-icons/react'
import { AuthCard } from '@/components/AuthCard'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { PasswordInput } from '@/components/PasswordInput'
import { Label } from '@/components/ui/label'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
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

const LEVELS = [
  { label: 'Fraca', bar: 'bg-destructive', text: 'text-destructive' },
  { label: 'Média', bar: 'bg-warning', text: 'text-warning' },
  { label: 'Forte', bar: 'bg-success', text: 'text-success' },
]

// only a hint: the server enforces the 8-character minimum, nothing else blocks
function strengthLevel(password: string) {
  const points = [/[a-z]/, /[A-Z]/, /\d/].filter((re) => re.test(password)).length
  if (password.length < 8 || points <= 1) return 0
  return points === 2 ? 1 : 2
}

function PasswordStrength({ password }: { password: string }) {
  if (!password) return null
  const level = strengthLevel(password)
  const { label, bar, text } = LEVELS[level]
  return (
    <div className="flex items-center gap-2" aria-live="polite">
      <div className="flex flex-1 gap-1" aria-hidden>
        {LEVELS.map((_, i) => (
          <span key={i} className={`h-1.5 flex-1 rounded-full ${i <= level ? bar : 'bg-muted'}`} />
        ))}
      </div>
      <span className={`w-10 text-xs font-medium ${text}`}>{label}</span>
    </div>
  )
}

function ChangePassword() {
  const { data: me } = useSuspenseQuery(meQuery)
  const queryClient = useQueryClient()
  const { redirect: next } = Route.useSearch()
  const router = useRouter()
  const logout = useLogout()
  const [mismatch, setMismatch] = useState(false)
  const [typed, setTyped] = useState('')
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
    <AuthCard
      title={me.must_change_password ? 'Defina sua senha' : 'Trocar senha'}
      description={me.must_change_password ? 'Sua senha atual é temporária e precisa ser trocada.' : undefined}
    >
      <form onSubmit={submit} className="space-y-4">
        <div className="space-y-1.5">
          <Label htmlFor="current">Senha atual</Label>
          <PasswordInput id="current" name="current" autoComplete="current-password" required autoFocus />
        </div>
        <div className="space-y-1.5">
          <div className="flex items-center gap-1.5">
            <Label htmlFor="new">Nova senha</Label>
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <button type="button" aria-label="Requisitos da senha" className="rounded-full text-muted-foreground hover:text-foreground">
                    <Info aria-hidden className="size-3.5" />
                  </button>
                </TooltipTrigger>
                <TooltipContent className="max-w-64">
                  Mínimo de 8 caracteres. Uma senha forte tem pelo menos uma letra maiúscula, uma minúscula e um número.
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
          <PasswordInput id="new" name="new" autoComplete="new-password" minLength={8} required onChange={(e) => setTyped(e.target.value)} />
          <PasswordStrength password={typed} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="confirm">Confirme a nova senha</Label>
          <PasswordInput id="confirm" name="confirm" autoComplete="new-password" required />
        </div>
        {mismatch && (
          <Alert variant="destructive">
            <AlertDescription>As senhas não conferem.</AlertDescription>
          </Alert>
        )}
        {change.isError && (
          <Alert variant="destructive">
            <AlertDescription>{errorMessage(change.error)}</AlertDescription>
          </Alert>
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
