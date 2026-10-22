import { queryOptions } from '@tanstack/react-query'
import { ApiError, api } from './api'

export type Role = 'admin' | 'analyst' | 'viewer'

export type Me = {
  id: number
  email: string
  name: string
  is_platform_admin: boolean
  must_change_password: boolean
  workspaces: { slug: string; name: string; role: Role }[]
}

export const ROLE_LABELS: Record<Role, string> = { admin: 'Admin', analyst: 'Analista', viewer: 'Leitor' }

export const meQuery = queryOptions({
  queryKey: ['me'],
  queryFn: () => api<Me>('/me'),
  staleTime: Infinity,
  // the route guards handle a 401 on /me themselves
  meta: { skipAuthRedirect: true },
})

export const roleIn = (me: Me, slug: string) => me.workspaces.find((w) => w.slug === slug)?.role

const MESSAGES: Record<string, string> = {
  invalid_credentials: 'E-mail ou senha inválidos.',
  invalid_current_password: 'Senha atual incorreta.',
  password_unchanged: 'A nova senha precisa ser diferente da atual.',
  cannot_deactivate_self: 'Você não pode desativar a própria conta.',
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
  if (error.status === 422) return 'Dados inválidos.'
  if (error.status >= 500) return 'Erro no servidor. Tente de novo.'
  // 409 and other domain errors already come in pt-BR
  return error.detail
}
