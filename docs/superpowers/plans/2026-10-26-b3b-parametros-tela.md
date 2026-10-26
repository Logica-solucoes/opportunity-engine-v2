# B3b · Parâmetros com sugestão do Gemini (tela) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Na página da simulação, o analista vê o formulário de parâmetros já preenchido com as sugestões dos dados (com selo e explicação), pode pedir sugestões ao Gemini, aceita ou edita, e salva.

**Architecture:** O formulário é gerado do JSON Schema do `ParamsIn` (`GET /api/engine/config-schema`). Um `FORM_LAYOUT` em `web/src/lib/params.ts` diz quais campos aparecem, em que grupo e com qual rótulo; tipo, limites e defaults vêm do schema. O estado do formulário guarda strings para os números (input controlado sem perder "1." ou "0.0" no meio da digitação) e volta a número só no corpo do `PUT`. O componente `ParamsForm` entra dentro do `ValidationBlock`, entre o report e o botão Rodar.

**Tech Stack:** React 19, TypeScript, TanStack Query 5, shadcn (`Badge`, `Button`, `Checkbox`, `Input`, `Label`), `sonner`, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-26-b3-parametros-gemini-design.md` (seção B3b). **Depende do B3a** (`docs/superpowers/plans/2026-10-26-b3a-parametros-backend.md`) já mergeado: as rotas `config-schema`, `suggestions`, `suggestions/gemini` e `params` precisam existir.

**Antes de começar:** leia `CLAUDE.md` (seções "UI stack" e "Verificar mudanças no frontend"), `web/src/routes/_auth/w/$slug/simulacoes/$id.tsx` e `web/src/lib/simulations.ts`. `docker compose up -d` antes do E2E. Comandos de `bun` rodam em `web/`.

**Seams de teste:** só E2E (o `web/` não tem runner unitário). O caminho de sucesso do Gemini fica coberto pelo pytest do B3a; o E2E roda com `GEMINI_API_KEY` vazio e testa o caminho indisponível.

---

## Mapa de arquivos

| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `web/e2e/env.ts` | modificar | `GEMINI_API_KEY: ''` no servidor do E2E |
| `web/e2e/simulations.spec.ts` | modificar | 2 testes de parâmetros |
| `web/src/lib/params.ts` | criar | tipos, `FORM_LAYOUT`, queries, schema → campos, estado do form, corpo do PUT, erros do pydantic em pt-BR |
| `web/src/lib/simulations.ts` | modificar | `config` aceita os parâmetros; `runBlockReason` sabe se foram salvos |
| `web/src/components/ParamsForm.tsx` | criar | seção "Parâmetros" |
| `web/src/routes/_auth/w/$slug/simulacoes/$id.tsx` | modificar | encaixar o `ParamsForm` no `ValidationBlock` |
| docs | modificar | Task 2 |

---

### Task 1: Formulário de parâmetros

**Files:**
- Modify: `web/e2e/env.ts`, `web/e2e/simulations.spec.ts`, `web/src/lib/simulations.ts`, `web/src/routes/_auth/w/$slug/simulacoes/$id.tsx`
- Create: `web/src/lib/params.ts`, `web/src/components/ParamsForm.tsx`

- [ ] **Step 1: Escrever os testes E2E**

Em `web/e2e/env.ts`, dentro de `pyEnv`, acrescente depois de `STORAGE_DIR`:

```ts
  // the E2E never calls Gemini: an empty key takes the "unavailable" path even if the dev shell has one
  GEMINI_API_KEY: '',
```

Em `web/e2e/simulations.spec.ts`, depois da função `createSimulation`, acrescente:

```ts
async function uploadTemplatesAndValidate(page: Page) {
  await page.getByLabel('Arquivo de investimento').setInputFiles(template('investimento.csv'))
  await expect(page.getByText('investimento.csv', { exact: true })).toBeVisible()
  await page.getByLabel('Arquivo de performance').setInputFiles(template('performance.csv'))
  await expect(page.getByText('performance.csv', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Validar' }).click()
  await expect(page.getByText('Nenhum problema encontrado.')).toBeVisible()
}
```

O primeiro teste do arquivo (`analyst uploads the templates…`) esperava "Execução disponível em breve" logo depois de validar; agora o Rodar pede os parâmetros salvos. Nele, troque

```ts
  await expect(analystPage.getByText('Execução disponível em breve')).toBeVisible()
```

por

```ts
  await expect(analystPage.getByText('Salve os parâmetros antes de rodar.')).toBeVisible()
```

E no fim do arquivo:

```ts
test('parameters open with the data suggestions, save and persist', async ({ page, browser }) => {
  const { slug, analystPage } = await analystOnNewWorkspace(page, browser)
  await createSimulation(analystPage, slug, 'Parâmetros')
  await uploadTemplatesAndValidate(analystPage)

  // performance.csv has 3 days of history and a "conversoes" KPI
  await expect(analystPage.getByText('Mínimo para série diária: o histórico tem só 3 dias.')).toBeVisible()
  await expect(analystPage.getByLabel('Pré-período mínimo (dias)')).toHaveValue('28')
  await expect(analystPage.getByLabel('Otimizar para')).toHaveValue('CONVERSIONS')
  await expect(analystPage.getByText('Sugerido pelos dados')).toHaveCount(3)
  await expect(analystPage.getByText('Salve os parâmetros antes de rodar.')).toBeVisible()

  await analystPage.getByLabel('Fator limite de investimento').fill('2')
  await analystPage.getByRole('button', { name: 'Salvar parâmetros' }).click()
  await expect(analystPage.getByText('Execução disponível em breve')).toBeVisible()

  await analystPage.reload()
  await expect(analystPage.getByLabel('Fator limite de investimento')).toHaveValue('2')
  await expect(analystPage.getByLabel('Pré-período mínimo (dias)')).toHaveValue('28')
  await expect(analystPage.getByText('Sugerido pelos dados')).toHaveCount(0)
})

test('an invalid parameter shows its error and gemini unavailable keeps the form', async ({ page, browser }) => {
  const { slug, analystPage } = await analystOnNewWorkspace(page, browser)
  await createSimulation(analystPage, slug, 'Inválido')
  await uploadTemplatesAndValidate(analystPage)

  await analystPage.getByRole('button', { name: 'Sugerir com Gemini' }).click()
  await expect(analystPage.getByText('Sugestão do Gemini indisponível. Os demais campos seguem valendo.')).toBeVisible()
  await expect(analystPage.getByLabel('Pré-período mínimo (dias)')).toHaveValue('28')

  await analystPage.getByLabel('Fator limite de investimento').fill('1')
  await analystPage.getByRole('button', { name: 'Salvar parâmetros' }).click()
  await expect(analystPage.getByText('Deve ser maior que 1.')).toBeVisible()
  await expect(analystPage.getByText('Salve os parâmetros antes de rodar.')).toBeVisible()
})
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `bun run build && bunx playwright test -g "parameter"` (o E2E serve o `web/dist`, então o build vem antes)
Expected: os 2 testes falham em `getByText('Mínimo para série diária…')` / `getByRole('button', { name: 'Sugerir com Gemini' })`, porque a seção ainda não existe.

- [ ] **Step 3: Escrever `web/src/lib/params.ts`**

```ts
import { queryOptions } from '@tanstack/react-query'
import { ApiError, api } from './api'
import type { Simulation } from './simulations'

export type Suggestion = { value: unknown; reason: string; source: 'dados' | 'gemini' }
export type Suggestions = Record<string, Suggestion>
export type GeminiAnswer = { available: boolean; suggestions: Suggestions }

// the part of the JSON Schema pydantic emits for ParamsIn that the form reads
export type FieldSchema = {
  type?: 'number' | 'integer' | 'boolean' | 'string' | 'object' | 'null'
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

type FieldSpec = { path: string; label: string; help?: string }
export type FormField = FieldSpec & { schema: FieldSchema; nullable: boolean }
export type FormGroup = { title: string; fields: FormField[] }
// numbers stay strings while typed ("1." and "0.0" are valid moments), and become numbers only in the PUT body
export type FormValue = string | boolean
export type FormState = { values: Record<string, FormValue>; origin: Suggestions; edited: Set<string> }

// which fields show, in which group and with which pt-BR label; type, limits and defaults come from the schema
const FORM_LAYOUT: { title: string; fields: FieldSpec[] }[] = [
  {
    title: 'Objetivo',
    fields: [
      { path: 'optimization_target', label: 'Otimizar para' },
      { path: 'kpi_is_monetary', label: 'KPI é valor em dinheiro' },
      { path: 'average_ticket', label: 'Ticket médio' },
      {
        path: 'conversion_rate_from_kpi_to_bo',
        label: 'Taxa de conversão do KPI para o negócio',
        help: 'Fração do KPI que vira resultado de negócio (1 = tudo).',
      },
    ],
  },
  {
    title: 'Metas financeiras',
    fields: [
      { path: 'financial_targets.target_cpa', label: 'CPA alvo', help: 'Vazio = sem meta.' },
      { path: 'financial_targets.target_icpa', label: 'iCPA alvo', help: 'Vazio = sem meta.' },
      { path: 'financial_targets.target_roas', label: 'ROAS alvo', help: 'Vazio = sem meta.' },
      { path: 'financial_targets.target_iroas', label: 'iROAS alvo', help: 'Vazio = sem meta.' },
    ],
  },
  {
    title: 'Orçamento',
    fields: [
      { path: 'investment_limit_factor', label: 'Fator limite de investimento' },
      { path: 'max_budget_step', label: 'Passo máximo de orçamento', help: 'Maior variação por passo (0,2 = 20%).' },
    ],
  },
  {
    title: 'Causal',
    fields: [
      { path: 'p_value_threshold', label: 'p-valor máximo' },
      { path: 'min_pre_period_days', label: 'Pré-período mínimo (dias)' },
      { path: 'r_squared_threshold', label: 'R² mínimo' },
      { path: 'increase_threshold_percent', label: 'Aumento mínimo para evento (%)' },
      { path: 'decrease_threshold_percent', label: 'Queda mínima para evento (%)' },
      { path: 'require_significance', label: 'Exigir significância' },
      { path: 'require_good_fit', label: 'Exigir bom ajuste' },
    ],
  },
]

export const ENUM_LABELS: Record<string, string> = { REVENUE: 'Receita', CONVERSIONS: 'Conversões' }

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
    fields: group.fields.flatMap((spec) => {
      const found = resolve(schema, spec.path)
      return found ? [{ ...spec, ...found }] : []
    }),
  })).filter((group) => group.fields.length > 0)
}

const getPath = (obj: unknown, path: string): unknown =>
  path
    .split('.')
    .reduce<unknown>((node, key) => (node && typeof node === 'object' ? (node as Record<string, unknown>)[key] : undefined), obj)

const toForm = (field: FormField, value: unknown): FormValue =>
  field.schema.type === 'boolean' ? value === true : value == null ? '' : String(value)

function fromForm(field: FormField, value: FormValue): unknown {
  if (field.schema.type === 'boolean' || field.schema.enum) return value
  return value === '' ? null : Number(value)
}

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

type PydanticError = { type: string; loc: (string | number)[]; ctx?: Record<string, unknown> }

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
}

// pydantic's 422 lists one error per field at loc ["body", ...path]; our own 422 (no mapping) is a string
export function fieldErrors(error: unknown): Record<string, string> | null {
  if (!(error instanceof ApiError) || error.status !== 422 || !Array.isArray(error.body.detail)) return null
  return Object.fromEntries(
    (error.body.detail as PydanticError[]).map((e) => [
      e.loc.slice(1).join('.'),
      ERROR_MESSAGES[e.type]?.(e.ctx ?? {}) ?? 'Valor inválido.',
    ]),
  )
}

// PUT …/params writes every form field, so one of them present means the parameters were saved
export const paramsSaved = (sim: Simulation) => 'optimization_target' in sim.config
```

- [ ] **Step 4: Ajustar `web/src/lib/simulations.ts`**

Troque a linha `config: { column_mapping?: ColumnMapping }` do tipo `Simulation` por:

```ts
  // column_mapping from B2, the parameters from B3 (shape owned by the API's ParamsIn)
  config: { column_mapping?: ColumnMapping; [param: string]: unknown }
```

E troque `runBlockReason` por:

```ts
// display only: B4 creates the run and checks the same gate on the server
export function runBlockReason(report: ValidationReport | null, confirmed: Set<number>, paramsSaved: boolean): string {
  if (!report) return 'Valide os arquivos antes de rodar.'
  if (!report.ok) return 'Corrija os erros antes de rodar.'
  if (report.checks.some((c, i) => c.level === 'warning' && !confirmed.has(i))) return 'Confirme os avisos antes de rodar.'
  if (!paramsSaved) return 'Salve os parâmetros antes de rodar.'
  return 'Execução disponível em breve'
}
```

- [ ] **Step 5: Escrever `web/src/components/ParamsForm.tsx`**

```tsx
import { useMutation, useQuery } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { toast } from 'sonner'
import { LoadState } from '@/components/LoadState'
import { NativeSelect } from '@/components/NativeSelect'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import { errorMessage } from '@/lib/auth'
import {
  type ConfigSchema,
  ENUM_LABELS,
  type FormField,
  type FormValue,
  type GeminiAnswer,
  type Suggestion,
  type Suggestions,
  applySuggestions,
  configSchemaQuery,
  edit,
  fieldErrors,
  initialState,
  paramsBody,
  suggestionsQuery,
  visibleLayout,
} from '@/lib/params'
import { FILES, type Simulation } from '@/lib/simulations'

type Props = { slug: string; sim: Simulation; busy: boolean; onSaved: (sim: Simulation) => void }

export function ParamsForm(props: Props) {
  const { slug, sim } = props
  const schema = useQuery(configSchemaQuery)
  // the suggestions depend on the files and the mapping: a new version refetches instead of reusing the cache
  const version = `${FILES.map((f) => sim.files[f.kind]?.sha256).join()}|${JSON.stringify(sim.config.column_mapping)}`
  const suggestions = useQuery(suggestionsQuery(slug, String(sim.id), version))

  return (
    <section className="space-y-3">
      <h2 className="text-lg font-medium">Parâmetros</h2>
      {!schema.data ? (
        <LoadState query={schema} />
      ) : suggestions.isPending ? (
        <LoadState query={suggestions} />
      ) : (
        // a failed suggestions call still opens the form, on the saved values and defaults
        <ParamsFields {...props} schema={schema.data} suggestions={suggestions.data ?? {}} />
      )}
    </section>
  )
}

function ParamsFields({
  slug,
  sim,
  busy,
  onSaved,
  schema,
  suggestions,
}: Props & { schema: ConfigSchema; suggestions: Suggestions }) {
  const layout = visibleLayout(schema)
  const [state, setState] = useState(() => initialState(layout, sim.config, suggestions))
  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api<Simulation>(`/w/${slug}/simulations/${sim.id}/params`, { method: 'PUT', body }),
    onSuccess: onSaved,
  })
  const gemini = useMutation({
    mutationFn: () => api<GeminiAnswer>(`/w/${slug}/simulations/${sim.id}/suggestions/gemini`, { method: 'POST' }),
    onSuccess: ({ available, suggestions: found }) => {
      if (!available) {
        toast.error('Sugestão do Gemini indisponível. Os demais campos seguem valendo.')
        return
      }
      if (Object.keys(found).length === 0) {
        toast.info('O Gemini não trouxe sugestões.')
        return
      }
      setState((s) => applySuggestions(layout, s, found))
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const errors = fieldErrors(save.error)

  function submit(e: FormEvent) {
    e.preventDefault()
    save.mutate(paramsBody(layout, state.values))
  }

  return (
    // noValidate: the API is the one that validates, and its 422 lands on each field
    <form onSubmit={submit} noValidate className="space-y-6">
      {layout.map((group) => (
        <fieldset key={group.title} className="space-y-3">
          <legend className="text-sm font-medium">{group.title}</legend>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {group.fields.map((field) => (
              <ParamField
                key={field.path}
                field={field}
                value={state.values[field.path]}
                origin={state.origin[field.path]}
                error={errors?.[field.path]}
                disabled={busy}
                onChange={(v) => setState((s) => edit(s, field.path, v))}
              />
            ))}
          </div>
        </fieldset>
      ))}
      {save.isError && !errors && (
        <p role="alert" className="text-sm text-destructive">
          {errorMessage(save.error)}
        </p>
      )}
      <div className="flex flex-wrap gap-3">
        <Button type="button" variant="outline" disabled={busy} onClick={() => gemini.mutate()}>
          Sugerir com Gemini
        </Button>
        <Button type="submit" disabled={busy}>
          Salvar parâmetros
        </Button>
      </div>
    </form>
  )
}

function ParamField({
  field,
  value,
  origin,
  error,
  disabled,
  onChange,
}: {
  field: FormField
  value: FormValue
  origin?: Suggestion
  error?: string
  disabled: boolean
  onChange: (value: FormValue) => void
}) {
  const id = `param-${field.path}`
  const { schema } = field
  const note = origin?.reason ?? field.help

  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-2">
        {schema.type === 'boolean' && (
          <Checkbox id={id} checked={value === true} disabled={disabled} onCheckedChange={(v) => onChange(v === true)} />
        )}
        <Label htmlFor={id}>{field.label}</Label>
        {origin && (
          <Badge variant="secondary">{origin.source === 'gemini' ? 'Sugerido pelo Gemini' : 'Sugerido pelos dados'}</Badge>
        )}
      </div>
      {schema.enum ? (
        <NativeSelect
          id={id}
          className="w-full"
          value={String(value)}
          disabled={disabled}
          onChange={(e) => onChange(e.target.value)}
        >
          {schema.enum.map((option) => (
            <option key={option} value={option}>
              {ENUM_LABELS[option] ?? option}
            </option>
          ))}
        </NativeSelect>
      ) : (
        schema.type !== 'boolean' && (
          <Input
            id={id}
            type="number"
            step={schema.type === 'integer' ? 1 : 'any'}
            min={schema.minimum ?? schema.exclusiveMinimum}
            max={schema.maximum ?? schema.exclusiveMaximum}
            placeholder={field.nullable ? 'Opcional' : undefined}
            value={String(value)}
            aria-invalid={error ? true : undefined}
            disabled={disabled}
            onChange={(e) => onChange(e.target.value)}
          />
        )
      )}
      {note && <p className="text-xs text-muted-foreground">{note}</p>}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  )
}
```

- [ ] **Step 6: Encaixar na página da simulação**

Em `web/src/routes/_auth/w/$slug/simulacoes/$id.tsx`:

1. Imports: troque `import { type FormEvent, useState } from 'react'` por `import { type FormEvent, type ReactNode, useState } from 'react'`; acrescente `import { ParamsForm } from '@/components/ParamsForm'` (depois do import do `NativeSelect`) e `import { paramsSaved } from '@/lib/params'` (depois do import de `@/lib/auth`).

2. Em `SimulationDetail`, troque `<ValidationBlock key={JSON.stringify(sim.validation)} report={sim.validation} />` por:

```tsx
      {/* a new report (new mapping or file) remounts the parameters too: their data suggestions changed */}
      <ValidationBlock key={JSON.stringify(sim.validation)} report={sim.validation} saved={paramsSaved(sim)}>
        {sim.validation && <ParamsForm slug={slug} sim={sim} busy={busy} onSaved={saved} />}
      </ValidationBlock>
```

3. Troque a assinatura do `ValidationBlock` por:

```tsx
function ValidationBlock({
  report,
  saved,
  children,
}: {
  report: ValidationReport | null
  saved: boolean
  children?: ReactNode
}) {
```

4. No mesmo componente, logo antes de `<div className="flex flex-wrap items-center gap-3 border-t pt-4">`, acrescente `{children}`, e troque `{runBlockReason(report, confirmed)}` por `{runBlockReason(report, confirmed, saved)}`.

- [ ] **Step 7: Build, lint e E2E**

Run: `bun run build && bun run lint`
Expected: build sem erro de tipo; lint com 0 erros (os avisos `only-export-components` das rotas já existem).

Run: `bun run e2e`
Expected: todos passam (22 testes; ~2 min).

- [ ] **Step 8: Commit**

```bash
git add web/e2e/env.ts web/e2e/simulations.spec.ts web/src/lib/params.ts web/src/lib/simulations.ts web/src/components/ParamsForm.tsx "web/src/routes/_auth/w/\$slug/simulacoes/\$id.tsx"
git commit -m "feat(web): add the parameters form with data and gemini suggestions"
```

---

### Task 2: Conferência visual e documentação

**Files:**
- Modify: `docs/decisoes/parametros-e-gemini.md`, `docs/m2/trilha-b-plataforma.md`, `CLAUDE.md`

- [ ] **Step 1: Screenshot nos dois temas**

Com `mise run api` e `mise run web` no ar, crie pelo app um workspace, um analista e uma simulação com os templates de `web/public/templates/`, clique em Validar e, com o MCP `playwright`:
1. `browser_navigate` para `http://localhost:5173/w/<slug>/simulacoes/<id>`;
2. `browser_take_screenshot` da seção "Parâmetros" (tema claro);
3. troque para o tema escuro pelo menu "Tema" e tire outro screenshot;
4. `browser_resize` para 390×844 e confira que os campos quebram em uma coluna, sem rolagem horizontal.

Expected: selos e explicações legíveis nos dois temas; grupos com legenda; botões "Sugerir com Gemini" e "Salvar parâmetros" visíveis. Corrija o que estiver quebrado antes de seguir.

- [ ] **Step 2: Decisões da tela**

No fim de `docs/decisoes/parametros-e-gemini.md`, acrescente:

```markdown
## Tela (B3b)

- **Formulário gerado do schema, com layout no front.** `FORM_LAYOUT` (`web/src/lib/params.ts`) diz quais campos aparecem, em que grupo e com qual rótulo; tipo, limites e defaults vêm do `GET /api/engine/config-schema`. Campo novo do A0 não aparece sem rótulo, e campo do layout que sumiu do schema é ignorado.
- **Valor inicial:** o salvo, depois a sugestão dos dados, depois o default. Só o que veio de sugestão ganha selo e explicação; editar tira os dois.
- **Gemini só nos campos não editados**, inclusive os salvos; nada é gravado até "Salvar parâmetros".
- **Números como texto no estado.** Input controlado com `Number()` a cada tecla engolia o "1." ou o "0.0" do meio da digitação; a conversão acontece só no corpo do `PUT`.
- **`noValidate` no form.** A API valida, e o 422 do pydantic cai em cada campo pelo `loc`, com mensagem pt-BR pelo `type`.
- **O formulário remonta a cada report novo.** Novo mapeamento ou arquivo muda as sugestões dos dados; edições não salvas se perdem nesse caso, como no mapeamento.
```

- [ ] **Step 3: Status e estado atual**

Em `docs/m2/trilha-b-plataforma.md`, troque a linha `- **Status:** 🟡 B3a …` do B3 por:

```markdown
- **Status:** ✅ feito. B3a (backend) em <data B3a>, verificado por `tests/api/test_params.py` e `tests/api/test_rbac.py`; B3b (tela) em <data>, verificado por `web/e2e/simulations.spec.ts` (sugestões dos dados, salvar e recarregar, erro de campo, Gemini indisponível) e screenshots nos dois temas. Fora até a Trilha A: `channel_groups` (A3), `controls` (A4), `gate_thresholds` (A0). Desvios em `docs/decisoes/parametros-e-gemini.md`.
```

(mantenha a data do B3a que já estava na linha e troque `<data>` pela de hoje, formato `26/out/2026`).

Em `CLAUDE.md` › "Estado atual", depois da frase do B3a, acrescente `**B3b (tela de parâmetros) concluído em <data>**: formulário gerado do schema com layout no front, selos de sugestão, "Sugerir com Gemini", erros do pydantic por campo, Rodar pede parâmetros salvos.`; troque `Faltam, em ordem: B3b (tela de parâmetros), B4 (jobs)` por `Faltam, em ordem: B4 (jobs)`; e no bloco `## Estrutura`, na linha de `src/lib/`, acrescente `params.ts (layout e estado do formulário de parâmetros)`.

- [ ] **Step 4: Commit**

```bash
git add docs/decisoes/parametros-e-gemini.md docs/m2/trilha-b-plataforma.md CLAUDE.md
git commit -m "docs: record b3b params screen and close b3"
```
