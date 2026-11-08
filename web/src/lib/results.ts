import { queryOptions } from '@tanstack/react-query'
import { api } from './api'

// the causal slice of results.json v1 (engine/results_schema.py) that the screen reads
export type Lift = { abs: number | null; ci: [number | null, number | null] | null; rel_pct: number | null }
export type Fit = { r2: number | null; mae: number | null; mape: number | null; wmape: number | null }
export type EventSeries = {
  line: { date: string; actual_kpi: number | null; investment: number | null; forecasted_kpi: number | null }[]
  accuracy: { date: string; kpi: number | null; predicted: number | null }[]
  investment: { period: string; investment: number | null }[]
  kpi: { category: string; kpi: number | null }[]
}
export type CausalEvent = {
  id: string
  channels: string[]
  status: 'published' | 'rejected'
  reasons: string[]
  start: string | null
  end: string | null
  lift: Lift | null
  p_value: number | null
  incremental_investment: number | null
  cpa_incremental: number | null
  fit: Fit | null
  series: EventSeries | null
}
export type Causal = {
  status: 'ok' | 'inconclusive' | 'failed'
  reasons: string[]
  events_detected: { date: string; channels: string[] }[]
  events: CausalEvent[]
}
export type ChannelFit = { name: string; identifiable: boolean | null; reasons: string[] }
export type Elasticity = {
  status: 'ok' | 'inconclusive' | 'failed'
  reasons: string[]
  metrics: { cv_r2: number | null; low_confidence: boolean | null; reallocation_suppressed: boolean | null } | null
  channels: ChannelFit[]
}
export type Grounding = { status: 'passed' | 'regenerated' | 'blocked'; issues: unknown[] }
export type ReportBase = { source: 'llm' | 'deterministic'; title: string; grounding: Grounding | null }
export type EventReport = ReportBase & { verdict: string; analysis: string; next_steps: string[] }
export type GlobalReport = ReportBase & {
  summary: string
  scenarios: { name: string; analysis: string }[]
  recommendations: string[]
}
export type Reports = { events: Record<string, EventReport>; global: GlobalReport | null; grounding: Grounding | null }
export type ExperimentCell = {
  channel: string
  test_type: 'on_off' | 'step_up'
  step: number | null
  spend_per_period: number
  budget_at_risk: number
}
export type ExperimentDesign = {
  status: 'ok' | 'insufficient_history'
  reasons: string[]
  period_days: number
  target_lift: number
  duration_days: number | null
  feasible: boolean | null
  mde_rel: number | null
  designs: ExperimentCell[]
  assumptions: string[]
}
export type Results = {
  status: 'succeeded' | 'inconclusive' | 'failed'
  experiment_design: ExperimentDesign | null
  causal: Causal | null
  elasticity: Elasticity | null
  // null only when the engine could not build them (A9); grounding is null when no report went through the LLM
  reports: Reports | null
}

export const resultsQuery = (slug: string, runId: string) =>
  queryOptions({
    queryKey: ['results', slug, runId],
    queryFn: () => api<Results>(`/w/${slug}/runs/${runId}/results`),
    // a finished run's results never change
    staleTime: Infinity,
  })

export const GROUNDING_LABELS: Record<Grounding['status'], string> = {
  passed: 'aprovado',
  regenerated: 'aprovado depois de regenerado',
  blocked: 'bloqueado',
}

export const eventsCsvHref = (slug: string, runId: string) => `/api/w/${slug}/runs/${runId}/events.csv`

const REASON_LABELS: Record<string, string> = {
  not_significant: 'Não significativo',
  illogical_direction: 'Direção ilógica (KPI contra o investimento)',
  poor_fit: 'Ajuste ruim no pré-período',
  analysis_failed: 'A análise do evento falhou',
  not_selected: 'Superado por outro evento do mesmo período',
  no_events_detected: 'Nenhum evento de investimento detectado',
  no_eligible_events: 'Nenhum evento com dados suficientes para análise',
  no_event_passed_gates: 'Nenhum evento passou nos critérios de publicação',
  placebo_failed: 'Reprovado no placebo: o modelo acha efeito numa data sem intervenção',
  insufficient_run: 'Os dados desta execução não sustentam publicar lift',
  model_dependent: 'O efeito só aparece com as variáveis de mídia do modelo',
  control_rejected: 'Um controle foi descartado por acompanhar o investimento do canal',
  no_validated_event: 'Nenhum evento validado',
  low_spend_variation: 'O investimento varia pouco para medir efeito',
  high_oos_wmape: 'O contrafactual erra demais fora da amostra',
  cv_in_sample: 'Histórico curto: o modelo de elasticidade não foi validado fora da amostra',
  no_identifiable_channel: 'Nenhum canal com efeito identificável',
  model_failed: 'O modelo de elasticidade falhou',
  coef_ci_includes_zero: 'O intervalo do efeito inclui zero',
  coef_ci_too_wide: 'O intervalo do efeito é largo demais',
  collinearity: 'Investimento colinear com outro canal',
  short_history: 'Histórico curto demais para desenhar um experimento (menos de 30 períodos)',
  degenerate_kpi: 'O KPI não varia o bastante para estimar o ruído',
  duration_capped: 'Nem no prazo máximo o teste detecta o efeito-alvo',
}

// a reason the engine adds later shows as its code instead of breaking the screen
export const reasonLabel = (reason: string) => REASON_LABELS[reason] ?? reason

// reasons that annotate an event without being why it was rejected
const NOTE_REASONS = new Set(['control_rejected'])
export const rejectionReasons = (e: CausalEvent) => e.reasons.filter((r) => !NOTE_REASONS.has(r))
export const eventNotes = (e: CausalEvent) => e.reasons.filter((r) => NOTE_REASONS.has(r))

// the engine's English series labels
const SERIES_LABELS: Record<string, string> = {
  'Pre-Event': 'Pré-evento',
  Event: 'Evento',
  Forecasted: 'Previsto',
  Actual: 'Real',
}
export const seriesLabel = (label: string) => SERIES_LABELS[label] ?? label

const fmt = (options: Intl.NumberFormatOptions) => new Intl.NumberFormat('pt-BR', options)
const integer = fmt({ maximumFractionDigits: 0 })
const signedInteger = fmt({ maximumFractionDigits: 0, signDisplay: 'exceptZero' })
const signedPct = fmt({ minimumFractionDigits: 1, maximumFractionDigits: 1, signDisplay: 'exceptZero' })
const pct = fmt({ minimumFractionDigits: 1, maximumFractionDigits: 1 })
const money = fmt({ style: 'currency', currency: 'BRL', minimumFractionDigits: 2, maximumFractionDigits: 2 })
const decimal = fmt({ minimumFractionDigits: 2, maximumFractionDigits: 2 })
const compact = fmt({ notation: 'compact', maximumFractionDigits: 1 })
const pValue = fmt({ maximumFractionDigits: 3 })
const share = fmt({ style: 'percent', minimumFractionDigits: 1, maximumFractionDigits: 1 })

type Num = number | null | undefined
const or = (v: Num, f: (n: number) => string) => (v == null ? '—' : f(v))

export const formatInteger = (v: Num) => or(v, integer.format)
export const formatSigned = (v: Num) => or(v, signedInteger.format)
export const formatSignedPct = (v: Num) => or(v, (n) => `${signedPct.format(n)}%`)
export const formatPct = (v: Num) => or(v, (n) => `${pct.format(n)}%`)
export const formatMoney = (v: Num) => or(v, money.format)
export const formatDecimal = (v: Num) => or(v, decimal.format)
export const formatCompact = (v: Num) => or(v, compact.format)
export const formatPValue = (v: Num) => or(v, (n) => (n < 0.001 ? '< 0,001' : `= ${pValue.format(n)}`))

export const formatShare = (v: Num) => or(v, share.format)
export const TEST_TYPE_LABELS: Record<ExperimentCell['test_type'], string> = {
  on_off: 'Desligar o canal',
  step_up: 'Aumentar o orçamento',
}

export const formatDay =(iso: string) => {
  const [y, m, d] = iso.slice(0, 10).split('-')
  return `${d}/${m}/${y}`
}

export const channelsLabel = (channels: string[]) =>
  channels.length <= 2 ? channels.join(', ') : `${channels.length} canais`

// an analysis_failed event comes with start null; the engine builds its id as {advertiser}_{channels}_{YYYY-MM-DD}
export const eventPeriod = (e: CausalEvent) =>
  e.start && e.end ? `${formatDay(e.start)} a ${formatDay(e.end)}` : formatDay(e.id.slice(-10))
