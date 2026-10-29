import { queryOptions, useMutation, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { ApiError, api } from './api'

export type Role = 'admin' | 'analyst' | 'viewer'

export type Me = {
  id: number
  email: string
  name: string
  is_platform_admin: boolean
  must_change_password: boolean
  // google: the workspace has the Google connector; its datasets never reach non-admins
  workspaces: { slug: string; name: string; role: Role; google: boolean }[]
}

export const ROLE_LABELS: Record<Role, string> = { admin: 'Admin', analyst: 'Analista', viewer: 'Leitor' }

export const meQuery = queryOptions({
  queryKey: ['me'],
  queryFn: () => api<Me>('/me'),
  staleTime: Infinity,
  // the route guards handle a 401 on /me themselves
  meta: { skipAuthRedirect: true },
})

// same-site paths only: an absolute URL here would be an open redirect.
// Browsers strip control chars, so `/\t/x` would become `//x`.
export const safePath = (v: unknown) =>
  typeof v === 'string' && /^\/(?![/\\])[^\x00-\x1f\x7f]*$/.test(v) ? v : undefined

export const redirectSearch = (search: Record<string, unknown>): { redirect?: string } => ({
  redirect: safePath(search.redirect),
})

export function useLogout() {
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  return useMutation({
    mutationFn: () => api('/auth/logout', { method: 'POST' }),
    onSettled: () => {
      queryClient.clear()
      navigate({ to: '/login', search: { redirect: undefined } })
    },
  })
}

export const roleIn = (me: Me, slug: string) => me.workspaces.find((w) => w.slug === slug)?.role

const MESSAGES: Record<string, string> = {
  invalid_credentials: 'E-mail ou senha inválidos.',
  invalid_current_password: 'Senha atual incorreta.',
  password_unchanged: 'A nova senha precisa ser diferente da atual.',
  cannot_deactivate_self: 'Você não pode desativar a própria conta.',
  account_not_found: 'Essa conta não existe. Peça ao platform admin para criá-la.',
  name_required: 'Informe o nome para criar a conta.',
  last_admin: 'O workspace precisa de ao menos um admin.',
  busy: 'Muitos acessos agora. Tente de novo em instantes.',
}

export function errorMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return 'Falha de conexão. Tente de novo.'
  if (error.detail === 'locked') {
    const minutes = Math.max(1, Math.ceil(Number(error.body.retry_after_s) / 60))
    return `Conta bloqueada. Tente de novo em ${minutes} min.`
  }
  if (MESSAGES[error.detail]) return MESSAGES[error.detail]
  if (error.status === 403) return 'Sem permissão.'
  if (error.status === 404) return 'Não encontrado.'
  // a 413 from Cloud Run itself (over 32 MiB) comes as HTML, without our detail
  if (error.status === 413) return 'Arquivo maior que 30 MB.'
  // pydantic's 422 has a list in `detail`; ours (upload, mapping) is already a pt-BR sentence
  if (error.status === 422 && typeof error.body.detail !== 'string') return 'Dados inválidos.'
  // a 5xx with our own sentence (the 502 of the Google connector) says what failed; a bare one doesn't
  if (error.status >= 500 && typeof error.body.detail !== 'string') return 'Erro no servidor. Tente de novo.'
  // 409 and other domain errors already come in pt-BR
  return error.detail
}
