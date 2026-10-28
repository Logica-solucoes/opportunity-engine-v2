import { queryOptions } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from './api'
import type { Simulation } from './simulations'

export type RunStatus = 'queued' | 'running' | 'succeeded' | 'inconclusive' | 'failed'

export type RunInput = { filename: string; sha256: string } | null

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
  // snapshot of the simulation's config when the run was created, column_mapping included
  config: Simulation['config']
  // keyed like column_mapping: investment_file, performance_file, generic_trends_file
  inputs: Record<string, RunInput>
  published_at: string | null
  published_by_name: string | null
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

export const isPublishable = (status: RunStatus) => status === 'succeeded' || status === 'inconclusive'

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

export const workspaceRunsQuery = (slug: string) =>
  queryOptions({
    queryKey: ['runs', slug, 'workspace'],
    queryFn: () => api<Run[]>(`/w/${slug}/runs`),
    refetchInterval: (q) => (q.state.data?.some((r) => isActive(r.status)) ? 3000 : false),
  })

export type RunFilters = { q?: string; status?: RunStatus; author?: string; from?: string; to?: string }

const text = (v: unknown) => (typeof v === 'string' && v ? v : undefined)
const day = (v: unknown) => {
  const s = text(v)
  return s && /^\d{4}-\d{2}-\d{2}$/.test(s) ? s : undefined
}

// unknown or empty values drop out, so a hand-edited URL never breaks the page
export function parseRunFilters(search: Record<string, unknown>): RunFilters {
  const status = text(search.status)
  return {
    q: text(search.q),
    status: status && Object.hasOwn(STATUS_LABELS, status) ? (status as RunStatus) : undefined,
    author: text(search.author),
    from: day(search.from),
    to: day(search.to),
  }
}

// YYYY-MM-DD in the browser's timezone, the format <input type="date"> gives
function localDay(iso: string) {
  const d = new Date(iso)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

export function filterRuns(runs: Run[], f: RunFilters): Run[] {
  const q = f.q?.trim().toLocaleLowerCase('pt-BR')
  return runs.filter((r) => {
    const day = localDay(r.created_at)
    return (
      (!q || r.simulation.name.toLocaleLowerCase('pt-BR').includes(q)) &&
      (!f.status || r.status === f.status) &&
      (!f.author || r.created_by_name === f.author) &&
      (!f.from || day >= f.from) &&
      (!f.to || day <= f.to)
    )
  })
}

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
