import { keepPreviousData, queryOptions } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from './api'
import type { Elasticity } from './results'
import { type PydanticError, pydanticMessage } from './params'

// the engine.scenario answer (engine/scenario.py), monthly values
type Num = number | null
export type Mix = Record<'historical' | 'optimized' | 'strategic', Record<string, Num>>
export type RampStep = { step: number; investment: number; kpi: Num; kpi_lo: Num; kpi_hi: Num }
export type TableRow = {
  investment: number
  kpi: Num
  kpi_lo: Num
  kpi_hi: Num
  revenue: Num
  cpa: Num
  roas: Num
  incremental_investment: Num
  incremental_kpi: Num
  icpa: Num
  iroas: Num
  extrapolated: boolean | null
  ramp: RampStep[] | null
  notes: string[]
  mix: Partial<Mix> | null
}
export type CurveRow = {
  investment: number
  kpi: number
  kpi_lo: Num
  kpi_hi: Num
  revenue: Num
  cpa: Num
  icpa: Num
  roas: Num
  iroas: Num
  incremental_investment: Num
  incremental_kpi: Num
  pct_incrementality: number
  extrapolated: boolean | null
  in_filter: boolean
  mix: Partial<Mix> | null
}
export type ChannelPoint = { investment: number; kpi: number; kpi_lo: Num; kpi_hi: Num; extrapolated: boolean | null }
export type ChannelCurve = {
  name: string
  curve: ChannelPoint[]
  observed_range: [number, number] | null
  current: Num
  saturation: Num
}
export type Scenario = {
  unit: 'month'
  revenue_mode: boolean
  current: TableRow
  recommended: TableRow | null
  saturation: TableRow
  curve: CurveRow[]
  channels: ChannelCurve[]
}

export const FILTER_KEYS = [
  'min_budget',
  'max_budget',
  'target_cpa',
  'target_icpa',
  'min_roas',
  'min_iroas',
  'min_kpi',
  'min_incrementality_pct',
] as const
export type Filters = Partial<Record<(typeof FILTER_KEYS)[number], number>>

const toQuery = (filters: Filters) => {
  const params = new URLSearchParams()
  for (const key of FILTER_KEYS) if (filters[key] != null) params.set(key, String(filters[key]))
  const query = params.toString()
  return query ? `?${query}` : ''
}

export const scenarioQuery = (slug: string, runId: string, filters: Filters) =>
  queryOptions({
    queryKey: ['scenario', slug, runId, filters],
    queryFn: () => api<Scenario>(`/w/${slug}/runs/${runId}/scenario${toQuery(filters)}`),
    // same run and filters, same answer
    staleTime: Infinity,
    placeholderData: keepPreviousData,
    // 409 and 422 are answers, not hiccups
    retry: false,
  })

export function useDebounced<T>(value: T, ms = 200) {
  const [debounced, setDebounced] = useState(value)
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), ms)
    return () => clearTimeout(timer)
  }, [value, ms])
  return debounced
}

// the first extrapolated point also closes the observed line, so the solid and dashed segments meet
export const splitExtrapolated = <T extends { kpi: number | null; extrapolated: boolean | null }>(points: T[]) =>
  points.map((p, i) => ({
    observed: [points[i - 1], p, points[i + 1]].some((q) => q && !q.extrapolated) ? p.kpi : null,
    extrapolated: p.extrapolated ? p.kpi : null,
  }))

// the engine.scenario gate (engine/scenario.py REFUSED_REASONS): these answer 409, a short history alone does not
export const scenarioRefused = (e: Elasticity) =>
  e.status === 'failed' || e.reasons.some((r) => r === 'no_identifiable_channel' || r === 'model_failed')

export const FILTER_LABELS: Record<keyof Filters, string> = {
  min_budget: 'Orçamento mínimo',
  max_budget: 'Orçamento máximo',
  target_cpa: 'CPA máximo',
  target_icpa: 'iCPA máximo',
  min_roas: 'ROAS mínimo',
  min_iroas: 'iROAS mínimo',
  min_kpi: 'KPI mínimo',
  min_incrementality_pct: '% de incrementalidade mínima',
}

// FastAPI's 422 body: a per-field pydantic error at loc ["query", field], or our own value_error, already in pt-BR
export const filterErrors = (body: Record<string, unknown>) =>
  Array.isArray(body.detail)
    ? (body.detail as PydanticError[]).map((e) => {
        if (e.type === 'value_error') return String(e.msg ?? '').replace(/^Value error, /, '')
        const label = FILTER_LABELS[e.loc.at(-1) as keyof Filters]
        return label ? `${label}: ${pydanticMessage(e)}` : pydanticMessage(e)
      })
    : []
