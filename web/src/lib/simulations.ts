import { queryOptions } from '@tanstack/react-query'
import { api } from './api'

export type FileKind = 'investment' | 'performance' | 'trends'

export type SimulationFile = {
  filename: string
  size_bytes: number
  sha256: string
  columns: string[]
  suggested: Record<string, string | null>
  uploaded_at: string
}

export type Check = { id: string; level: 'error' | 'warning' | 'info'; message: string; details?: unknown }

export type ValidationReport = {
  ok: boolean
  cadence: string | null
  period_days: number | null
  date_range: [string, string] | null
  channels: string[]
  checks: Check[]
  collinearity: unknown
}

// EngineConfig.column_mapping: {investment_file: {date_col: "data", ...}, ...}
export type ColumnMapping = Record<string, Record<string, string>>

export type Simulation = {
  id: number
  name: string
  config: { column_mapping?: ColumnMapping }
  validation: ValidationReport | null
  files: Record<FileKind, SimulationFile | null>
}

export type SimulationSummary = {
  id: number
  name: string
  created_by_name: string
  created_at: string
  updated_at: string
}

export type FileSpec = { kind: FileKind; key: string; label: string; template: string; optional: boolean }

// key = the column_mapping key the API expects for that file
export const FILES: FileSpec[] = [
  { kind: 'investment', key: 'investment_file', label: 'Investimento', template: '/templates/investimento.csv', optional: false },
  { kind: 'performance', key: 'performance_file', label: 'Performance', template: '/templates/performance.csv', optional: false },
  { kind: 'trends', key: 'generic_trends_file', label: 'Trends', template: '/templates/trends.csv', optional: true },
]

// the fields of each file come from the API (keys of `suggested`); only their labels live here
export const FIELD_LABELS: Record<string, string> = {
  date_col: 'Data',
  channel_col: 'Canal',
  investment_col: 'Investimento',
  kpi_col: 'KPI',
  trends_col: 'Trends',
}

export const LEVEL_LABELS: Record<Check['level'], string> = { error: 'Erro', warning: 'Aviso', info: 'Informação' }

export const simulationsQuery = (slug: string) =>
  queryOptions({
    queryKey: ['simulations', slug],
    queryFn: () => api<SimulationSummary[]>(`/w/${slug}/simulations`),
  })

export const simulationQuery = (slug: string, id: string) =>
  queryOptions({
    queryKey: ['simulations', slug, id],
    queryFn: () => api<Simulation>(`/w/${slug}/simulations/${id}`),
  })

// a re-upload keeps the saved mapping, which may point at a column the new file no longer has
export function initialColumn(sim: Simulation, spec: FileSpec, field: string): string {
  const file = sim.files[spec.kind]!
  const saved = sim.config.column_mapping?.[spec.key]?.[field]
  return saved && file.columns.includes(saved) ? saved : (file.suggested[field] ?? '')
}

// display only: B4 creates the run and checks the same gate on the server
export function runBlockReason(report: ValidationReport | null, confirmed: Set<number>): string {
  if (!report) return 'Valide os arquivos antes de rodar.'
  if (!report.ok) return 'Corrija os erros antes de rodar.'
  if (report.checks.some((c, i) => c.level === 'warning' && !confirmed.has(i))) return 'Confirme os avisos antes de rodar.'
  return 'Execução disponível em breve'
}

export const formatDate = (iso: string) =>
  new Date(iso).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })

export const formatSize = (bytes: number) =>
  bytes < 1024 * 1024
    ? `${Math.max(1, Math.round(bytes / 1024))} KB`
    : `${(bytes / 1024 / 1024).toLocaleString('pt-BR', { maximumFractionDigits: 1 })} MB`
