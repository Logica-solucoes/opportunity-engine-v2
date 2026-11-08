import { keepPreviousData, queryOptions } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { api } from './api'

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

// FastAPI's 422 body: {detail: [{msg: "Value error, o orçamento mínimo passa do máximo", ...}]}
export const filterErrors = (body: Record<string, unknown>) =>
  Array.isArray(body.detail)
    ? body.detail.map((d: { msg?: string }) => String(d.msg ?? '').replace(/^Value error, /, ''))
    : []
