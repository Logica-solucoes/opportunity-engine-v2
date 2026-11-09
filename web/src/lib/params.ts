import { queryOptions } from '@tanstack/react-query'
import { ApiError, api } from './api'
import type { Simulation } from './simulations'

export type Suggestion = { value: unknown; reason: string; source: 'dados' | 'gemini' }
export type Suggestions = Record<string, Suggestion>
export type GeminiAnswer = { available: boolean; suggestions: Suggestions }

// the part of the JSON Schema pydantic emits for ParamsIn that the form reads
export type FieldSchema = {
  type?: 'number' | 'integer' | 'boolean' | 'string' | 'object' | 'null' | 'array'
  items?: FieldSchema
  enum?: string[]
  anyOf?: FieldSchema[]
  default?: unknown
  minimum?: number
  maximum?: number
  exclusiveMinimum?: number
  exclusiveMaximum?: number
  $ref?: string
  properties?: Record<string, FieldSchema>
}
export type ConfigSchema = FieldSchema & { $defs?: Record<string, FieldSchema> }

type FieldSpec = { path: string; label: string; help?: string; advanced?: boolean }
export type FormField = FieldSpec & { schema: FieldSchema; nullable: boolean }
export type FormGroup = { title: string; description: string; fields: FormField[] }
// numbers stay strings while typed ("1." and "0.0" are valid moments), and become numbers only in the PUT body
export type FormValue = string | boolean | string[]
export type FormState = { values: Record<string, FormValue>; origin: Suggestions; edited: Set<string> }

// which fields show, in which group and with which pt-BR label; type, limits and defaults come from the schema
const FORM_LAYOUT: { title: string; description: string; fields: FieldSpec[] }[] = [
  {
    title: 'Objetivo',
    description: 'O que o motor otimiza e como o KPI vira resultado de negócio.',
    fields: [
      { path: 'optimization_target', label: 'Otimizar para' },
      { path: 'kpi_is_monetary', label: 'KPI é valor em dinheiro' },
      { path: 'average_ticket', label: 'Ticket médio' },
      {
        path: 'conversion_rate_from_kpi_to_bo',
        label: 'Conversão do KPI em negócio',
        help: 'Fração do KPI que vira resultado de negócio (1 = tudo).',
      },
    ],
  },
  {
    title: 'Metas financeiras',
    description: 'Metas de eficiência usadas nos cenários. Campo vazio, meta desligada.',
    fields: [
      { path: 'financial_targets.target_cpa', label: 'CPA alvo', help: 'Deixe vazio para não usar esta meta.' },
      { path: 'financial_targets.target_icpa', label: 'iCPA alvo', help: 'Deixe vazio para não usar esta meta.' },
      { path: 'financial_targets.target_roas', label: 'ROAS alvo', help: 'Deixe vazio para não usar esta meta.' },
      { path: 'financial_targets.target_iroas', label: 'iROAS alvo', help: 'Deixe vazio para não usar esta meta.' },
    ],
  },
  {
    title: 'Orçamento',
    description: 'Quanto o planejador pode mexer no investimento.',
    fields: [
      { path: 'investment_limit_factor', label: 'Fator limite de investimento' },
      { path: 'max_budget_step', label: 'Passo máximo de orçamento', help: 'Maior variação por passo (0,2 = 20%).' },
    ],
  },
  {
    title: 'Causal',
    description: 'Critérios para aceitar um evento de investimento como efeito real.',
    fields: [
      { path: 'p_value_threshold', label: 'p-valor máximo' },
      { path: 'min_pre_period_days', label: 'Pré-período mínimo (dias)' },
      { path: 'post_event_days', label: 'Pós-evento (dias)', help: 'Janela medida depois de cada evento.' },
      { path: 'r_squared_threshold', label: 'R² mínimo', advanced: true },
      { path: 'increase_threshold_percent', label: 'Aumento mínimo para evento (%)', advanced: true },
      { path: 'decrease_threshold_percent', label: 'Queda mínima para evento (%)', advanced: true },
      { path: 'max_events_to_analyze', label: 'Máximo de eventos analisados', advanced: true },
      { path: 'require_statistical_significance', label: 'Exigir significância', advanced: true },
      {
        path: 'require_logical_direction',
        label: 'Exigir direção lógica',
        advanced: true,
        help: 'O efeito precisa ir na direção da mudança de investimento.',
      },
      { path: 'require_model_fit', label: 'Exigir bom ajuste', advanced: true },
      {
        path: 'controls',
        label: 'Controles macro (Banco Central)',
        advanced: true,
        help: 'Buscados na hora de rodar. Um controle que anda junto com o investimento do evento é descartado.',
      },
    ],
  },
]

export const ENUM_LABELS: Record<string, string> = {
  REVENUE: 'Receita',
  CONVERSIONS: 'Conversões',
  bcb_ipca: 'IPCA',
  bcb_selic: 'Selic',
  bcb_ibc_br: 'IBC-Br',
}

// read-only display of a saved value (run page); "—" for a field the run's config doesn't have
export function displayValue(field: FormField, value: unknown): string {
  if (value == null) return '—'
  if (Array.isArray(value)) return value.length ? value.map((v) => ENUM_LABELS[String(v)] ?? String(v)).join(', ') : 'Nenhum'
  if (field.schema.type === 'boolean') return value ? 'Sim' : 'Não'
  if (field.schema.enum) return ENUM_LABELS[String(value)] ?? String(value)
  // the default rounds to 3 decimals, and a p-value of 0.0001 would read "0"
  return typeof value === 'number' ? value.toLocaleString('pt-BR', { maximumFractionDigits: 20 }) : String(value)
}

export const configSchemaQuery = queryOptions({
  queryKey: ['engine', 'config-schema'],
  queryFn: () => api<ConfigSchema>('/engine/config-schema'),
  staleTime: Infinity,
})

export const suggestionsQuery = (slug: string, id: string, version: string) =>
  queryOptions({
    queryKey: ['simulations', slug, id, 'suggestions', version],
    queryFn: () => api<Suggestions>(`/w/${slug}/simulations/${id}/suggestions`),
  })

// `financial_targets.target_cpa` goes through pydantic's $ref, and `X | None` (anyOf with null) becomes X
function resolve(schema: ConfigSchema, path: string): { schema: FieldSchema; nullable: boolean } | null {
  let node: FieldSchema | undefined = schema
  for (const key of path.split('.')) {
    if (node?.$ref) node = schema.$defs?.[node.$ref.split('/').pop()!]
    node = node?.properties?.[key]
  }
  if (!node) return null
  const options = node.anyOf ?? [node]
  const main = options.find((o) => o.type !== 'null')
  if (!main) return null
  return { schema: { ...main, default: node.default }, nullable: options.some((o) => o.type === 'null') }
}

// a layout field the schema no longer has (renamed by the A0) is skipped instead of breaking the form
export function visibleLayout(schema: ConfigSchema): FormGroup[] {
  return FORM_LAYOUT.map((group) => ({
    title: group.title,
    description: group.description,
    fields: group.fields.flatMap((spec) => {
      const found = resolve(schema, spec.path)
      return found ? [{ ...spec, ...found }] : []
    }),
  })).filter((group) => group.fields.length > 0)
}

export const getPath = (obj: unknown, path: string): unknown =>
  path
    .split('.')
    .reduce<unknown>((node, key) => (node && typeof node === 'object' ? (node as Record<string, unknown>)[key] : undefined), obj)

const toForm = (field: FormField, value: unknown): FormValue => {
  if (field.schema.type === 'array') return Array.isArray(value) ? value.map(String) : []
  return field.schema.type === 'boolean' ? value === true : value == null ? '' : String(value)
}

function fromForm(field: FormField, value: FormValue): unknown {
  if (field.schema.type === 'boolean' || field.schema.enum || field.schema.type === 'array') return value
  return value === '' ? null : Number(value)
}

// a number field holding text that is not a number (the input is text, so the browser does not catch it)
export const invalidNumbers = (layout: FormGroup[], values: Record<string, FormValue>) =>
  allFields(layout)
    .filter((f) => !f.schema.enum && f.schema.type !== 'boolean' && f.schema.type !== 'array')
    .filter((f) => {
      const v = String(values[f.path])
      return v !== '' && !Number.isFinite(Number(v))
    })
    .map((f) => f.path)

// "0.2" is stored, "0,2" is shown
export const toDisplay = (value: string) => value.replace('.', ',')
export const fromDisplay = (text: string) => text.replace(',', '.')

const allFields = (layout: FormGroup[]) => layout.flatMap((group) => group.fields)

// saved value first (the analyst decided it), then the data suggestion, then the schema default
export function initialState(layout: FormGroup[], config: Record<string, unknown>, suggestions: Suggestions): FormState {
  const values: Record<string, FormValue> = {}
  const origin: Suggestions = {}
  for (const field of allFields(layout)) {
    const saved = getPath(config, field.path)
    const suggestion = suggestions[field.path]
    if (saved !== undefined) {
      values[field.path] = toForm(field, saved)
    } else if (suggestion) {
      values[field.path] = toForm(field, suggestion.value)
      origin[field.path] = suggestion
    } else {
      values[field.path] = toForm(field, field.schema.default)
    }
  }
  return { values, origin, edited: new Set() }
}

// a field the analyst edited on this screen keeps their value
export function applySuggestions(layout: FormGroup[], state: FormState, suggestions: Suggestions): FormState {
  const values = { ...state.values }
  const origin = { ...state.origin }
  for (const field of allFields(layout)) {
    const suggestion = suggestions[field.path]
    if (!suggestion || state.edited.has(field.path)) continue
    values[field.path] = toForm(field, suggestion.value)
    origin[field.path] = suggestion
  }
  return { ...state, values, origin }
}

export function edit(state: FormState, path: string, value: FormValue): FormState {
  const origin = { ...state.origin }
  delete origin[path]
  return { values: { ...state.values, [path]: value }, origin, edited: new Set(state.edited).add(path) }
}

// the PUT body: dotted paths back to nested objects, form strings back to numbers
export function paramsBody(layout: FormGroup[], values: Record<string, FormValue>): Record<string, unknown> {
  const body: Record<string, unknown> = {}
  for (const field of allFields(layout)) {
    const keys = field.path.split('.')
    let node = body
    for (const key of keys.slice(0, -1)) node = (node[key] ??= {}) as Record<string, unknown>
    node[keys[keys.length - 1]] = fromForm(field, values[field.path])
  }
  return body
}

function changed(field: FormField, value: unknown, saved: unknown): boolean {
  if (field.schema.type === 'array') {
    const sorted = (list: unknown) => JSON.stringify([...(list as unknown[])].sort())
    return sorted(value) !== sorted(saved ?? [])
  }
  return value !== (saved ?? null)
}

// compared as the PUT body would carry it, so "0.20" on screen equals a saved 0.2
export const unsavedParams = (layout: FormGroup[], values: Record<string, FormValue>, config: Record<string, unknown>) =>
  allFields(layout).some((field) => changed(field, fromForm(field, values[field.path]), getPath(config, field.path)))

export type PydanticError = { type: string; loc: (string | number)[]; msg?: string; ctx?: Record<string, unknown> }

const num = (v: unknown) => (typeof v === 'number' ? v.toLocaleString('pt-BR') : String(v))

const ERROR_MESSAGES: Record<string, (ctx: Record<string, unknown>) => string> = {
  greater_than: (c) => `Deve ser maior que ${num(c.gt)}.`,
  greater_than_equal: (c) => `Deve ser no mínimo ${num(c.ge)}.`,
  less_than: (c) => `Deve ser menor que ${num(c.lt)}.`,
  less_than_equal: (c) => `Deve ser no máximo ${num(c.le)}.`,
  int_parsing: () => 'Informe um número inteiro.',
  int_from_float: () => 'Informe um número inteiro.',
  int_type: () => 'Informe um número inteiro.',
  float_parsing: () => 'Informe um número.',
  float_type: () => 'Informe um número.',
  literal_error: () => 'Escolha uma das opções.',
  revenue_needs_ticket: () => 'Obrigatório para otimizar por receita.',
}

export const pydanticMessage = (e: PydanticError) => ERROR_MESSAGES[e.type]?.(e.ctx ?? {}) ?? 'Valor inválido.'

// pydantic's 422 lists one error per field at loc ["body", ...path]; our own 422 (no mapping) is a string
export function fieldErrors(error: unknown): Record<string, string> | null {
  if (!(error instanceof ApiError) || error.status !== 422 || !Array.isArray(error.body.detail)) return null
  return Object.fromEntries(
    (error.body.detail as PydanticError[]).map((e) => [
      e.loc.slice(1).join('.'),
      pydanticMessage(e),
    ]),
  )
}

// PUT …/params writes every form field, so one of them present means the parameters were saved
export const paramsSaved = (sim: Simulation) => 'optimization_target' in sim.config
