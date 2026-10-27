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
        <ParamsFields key={version} {...props} schema={schema.data} suggestions={suggestions.data ?? {}} />
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
    onSuccess: (saved) => {
      setState((s) => ({ ...s, origin: {} }))
      onSaved(saved)
    },
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
  const [badInput, setBadInput] = useState<string[]>([])
  const errors = fieldErrors(save.error)
  const paths = new Set(layout.flatMap((group) => group.fields.map((f) => f.path)))
  const stray = errors ? Object.entries(errors).filter(([path]) => !paths.has(path)) : []
  const general = save.isError && (!errors || stray.length > 0)

  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    // a number input with garbage reports value "", which would save an optional target as "no target"
    const bad = Array.from(e.currentTarget.querySelectorAll('input'))
      .filter((input) => input.validity.badInput)
      .map((input) => input.name)
    setBadInput(bad)
    if (bad.length === 0) save.mutate(paramsBody(layout, state.values))
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
                error={badInput.includes(field.path) ? 'Informe um número.' : errors?.[field.path]}
                disabled={busy}
                onChange={(v) => setState((s) => edit(s, field.path, v))}
              />
            ))}
          </div>
        </fieldset>
      ))}
      {general && (
        <p role="alert" className="text-sm text-destructive">
          {stray.length > 0
            ? stray.map(([path, message]) => (path ? `${path}: ${message}` : message)).join(' ')
            : errorMessage(save.error)}
        </p>
      )}
      <div className="flex flex-wrap gap-3">
        <Button type="button" variant="outline" disabled={busy} onClick={() => gemini.mutate()}>
          {gemini.isPending ? 'Consultando o Gemini…' : 'Sugerir com Gemini'}
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
  const describedBy = [note && `${id}-note`, error && `${id}-error`].filter(Boolean).join(' ') || undefined

  return (
    <div className="space-y-1">
      <div className="flex flex-wrap items-center gap-2">
        {schema.type === 'boolean' && (
          <Checkbox
            id={id}
            checked={value === true}
            disabled={disabled}
            aria-describedby={describedBy}
            onCheckedChange={(v) => onChange(v === true)}
          />
        )}
        <Label htmlFor={id}>{field.label}</Label>
      </div>
      {schema.enum ? (
        <NativeSelect
          id={id}
          className="w-full"
          value={String(value)}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
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
            name={field.path}
            type="number"
            step={schema.type === 'integer' ? 1 : 'any'}
            min={schema.minimum ?? schema.exclusiveMinimum}
            max={schema.maximum ?? schema.exclusiveMaximum}
            placeholder={field.nullable ? 'Opcional' : undefined}
            value={String(value)}
            aria-invalid={error ? true : undefined}
            aria-describedby={describedBy}
            disabled={disabled}
            onChange={(e) => onChange(e.target.value)}
          />
        )
      )}
      {(origin || note) && (
        <div className="space-y-1">
          {origin && (
            <Badge variant="secondary">{origin.source === 'gemini' ? 'Sugerido pelo Gemini' : 'Sugerido pelos dados'}</Badge>
          )}
          {note && (
            <p id={`${id}-note`} className="text-xs text-muted-foreground">
              {note}
            </p>
          )}
        </div>
      )}
      {error && (
        <p id={`${id}-error`} role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  )
}
