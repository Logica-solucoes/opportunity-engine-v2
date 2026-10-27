import { queryOptions } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from './api'

export type RunStatus = 'queued' | 'running' | 'succeeded' | 'inconclusive' | 'failed'

export type Run = {
  id: number
  status: RunStatus
  simulation: { id: number; name: string }
  created_by_name: string
  created_at: string
  started_at: string | null
  finished_at: string | null
  error: string | null
  summary: Record<string, unknown> | null
  engine_version: string | null
}

export type LogLine = { id: number; ts: string; level: 'info' | 'warning' | 'error'; message: string }

export const STATUS_LABELS: Record<RunStatus, string> = {
  queued: 'Na fila',
  running: 'Rodando',
  succeeded: 'Concluída',
  inconclusive: 'Inconclusiva',
  failed: 'Falhou',
}

export const isActive = (status: RunStatus) => status === 'queued' || status === 'running'

const MAX_LINES = 300

export const runQuery = (slug: string, runId: string) =>
  queryOptions({
    queryKey: ['runs', slug, runId],
    queryFn: () => api<Run>(`/w/${slug}/runs/${runId}`),
    // queued → running has no event of its own; the log stream's `end` covers the last change
    refetchInterval: (q) => (q.state.data && isActive(q.state.data.status) ? 2000 : false),
  })

export const simulationRunsQuery = (slug: string, simulationId: number) =>
  queryOptions({
    queryKey: ['runs', slug, 'simulation', simulationId],
    queryFn: () => api<Run[]>(`/w/${slug}/simulations/${simulationId}/runs`),
    refetchInterval: (q) => (q.state.data?.some((r) => isActive(r.status)) ? 3000 : false),
  })

export type LogState = 'open' | 'ended' | 'lost'

export function useRunLog(slug: string, runId: string) {
  const [lines, setLines] = useState<LogLine[]>([])
  const [state, setState] = useState<LogState>('open')

  useEffect(() => {
    const source = new EventSource(`/api/w/${slug}/runs/${runId}/logs/stream`)
    source.onmessage = (e) => {
      const line: LogLine = { id: Number(e.lastEventId), ...JSON.parse(e.data) }
      // a reconnect resumes after Last-Event-ID, but a Fast Refresh reopens the stream and replays the backlog onto the kept lines
      setLines((prev) => (prev.length && prev[prev.length - 1].id >= line.id ? prev : [...prev, line].slice(-MAX_LINES)))
    }
    source.addEventListener('end', () => {
      setState('ended')
      source.close()
    })
    // a dropped connection is retried by the browser; CLOSED means an answer it won't retry (401, 404)
    source.onerror = () => {
      if (source.readyState === EventSource.CLOSED) setState('lost')
    }
    return () => source.close()
  }, [slug, runId])

  return { lines, state }
}
