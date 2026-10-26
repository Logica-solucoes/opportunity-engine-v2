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
  // FormData sets its own multipart Content-Type with the boundary
  const json = init.body !== undefined && !(init.body instanceof FormData)
  const r = await fetch(`/api${path}`, {
    method: init.method ?? 'GET',
    headers: json ? { 'Content-Type': 'application/json' } : undefined,
    body: json ? JSON.stringify(init.body) : (init.body as FormData | undefined),
  })
  if (r.status === 204) return undefined as T
  const body = await r.json().catch(() => ({}))
  if (!r.ok) throw new ApiError(r.status, body)
  return body as T
}
