export class ApiError extends Error {
  status: number
  detail: string
  body: Record<string, unknown>

  constructor(status: number, body: Record<string, unknown>) {
    const detail = typeof body.detail === 'string' ? body.detail : `HTTP ${status}`
    super(detail)
    this.status = status
    this.detail = detail
    this.body = body
  }
}

export async function api<T>(path: string, init: { method?: string; body?: unknown } = {}): Promise<T> {
  const hasBody = init.body !== undefined
  const r = await fetch(`/api${path}`, {
    method: init.method ?? 'GET',
    headers: hasBody ? { 'Content-Type': 'application/json' } : undefined,
    body: hasBody ? JSON.stringify(init.body) : undefined,
  })
  if (r.status === 204) return undefined as T
  const body = await r.json().catch(() => ({}))
  if (!r.ok) throw new ApiError(r.status, body)
  return body as T
}
