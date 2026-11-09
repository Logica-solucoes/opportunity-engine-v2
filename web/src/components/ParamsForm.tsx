import { useMutation, useQuery } from '@tanstack/react-query'
import { useBlocker } from '@tanstack/react-router'
import { CaretDown, Info, Sparkle } from '@phosphor-icons/react'
import { type FormEvent, type ReactNode, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { LoadState } from '@/components/LoadState'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
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
  fromDisplay,
  initialState,
  invalidNumbers,
  paramsBody,
  suggestionsQuery,
  toDisplay,
  unsavedParams,
  visibleLayout,
} from '@/lib/params'
import { FILES, type Simulation } from '@/lib/simulations'

type Props = {
  slug: string
  sim: Simulation
  busy: boolean
  onSaved: (sim: Simulation) => void
  onDirty: (dirty: boolean) => void
}

export function ParamsForm(props: Props) {
  const { slug, sim } = props
  const schema = useQuery(configSchemaQuery)
  // the suggestions depend on the files and the mapping: a new version refetches instead of reusing the cache
  const version = `${FILES.map((f) => sim.files[f.kind]?.sha256).join()}|${JSON.stringify(sim.config.column_mapping)}`
  const suggestions = useQuery(suggestionsQuery(slug, String(sim.id), version))

  return (
    <section>
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
  onDirty,
  schema,
  suggestions,
}: Props & { schema: ConfigSchema; suggestions: Suggestions }) {
  const layout = visibleLayout(schema)
  const [state, setState] = useState(() => initialState(layout, sim.config, suggestions))
  // Rodar runs the saved config, so an edit still on screen blocks it
  const dirty = unsavedParams(layout, state.values, sim.config)
  useEffect(() => onDirty(dirty), [dirty, onDirty])
  useEffect(() => () => onDirty(false), [onDirty])
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
  // suggestions and defaults also make the form differ from the saved config; only the user's edits are worth a warning
  const userEdited = dirty && state.edited.size > 0
  const blocker = useBlocker({
    shouldBlockFn: ({ current, next }) => userEdited && current.pathname !== next.pathname,
    enableBeforeUnload: userEdited,
    withResolver: true,
  })

  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    // a text that is not a number would save an optional target as "no target"
    const bad = invalidNumbers(layout, state.values)
    setBadInput(bad)
    if (bad.length === 0) save.mutate(paramsBody(layout, state.values))
  }

  const fieldProps = (field: FormField) => ({
    field,
    value: state.values[field.path],
    origin: state.origin[field.path],
    error: badInput.includes(field.path) ? 'Informe um número.' : errors?.[field.path],
    disabled: busy,
    onChange: (v: FormValue) => setState((s) => edit(s, field.path, v)),
  })

  return (
    <TooltipProvider>
      {/* noValidate: the API is the one that validates, and its 422 lands on each field */}
      <form onSubmit={submit} noValidate className="space-y-4">
        {layout.map((group) => (
          <GroupCard
            key={group.title}
            title={group.title}
            fields={group.fields}
            hasIssue={(f) => Boolean(state.origin[f.path] || errors?.[f.path] || badInput.includes(f.path))}
            render={(f) => <ParamField key={f.path} {...fieldProps(f)} />}
          />
        ))}
        {general && (
          <p role="alert" className="text-sm text-destructive">
            {stray.length > 0
              ? stray.map(([path, message]) => (path ? `${path}: ${message}` : message)).join(' ')
              : errorMessage(save.error)}
          </p>
        )}
        <div className="sticky bottom-0 -mx-1 flex flex-wrap items-center gap-3 border-t bg-background/90 px-1 py-3 backdrop-blur">
          <Button type="submit" disabled={busy}>
            Salvar parâmetros
          </Button>
          <Button type="button" variant="outline" disabled={busy} onClick={() => gemini.mutate()}>
            <Sparkle aria-hidden />
            {gemini.isPending ? 'Consultando o Gemini…' : 'Sugerir com Gemini'}
          </Button>
          {dirty && <Badge variant="warning">Alterações não salvas</Badge>}
        </div>
      </form>
      <AlertDialog open={blocker.status === 'blocked'} onOpenChange={(open) => !open && blocker.reset?.()}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Sair sem salvar os parâmetros?</AlertDialogTitle>
            <AlertDialogDescription>As alterações feitas no formulário serão perdidas.</AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Continuar editando</AlertDialogCancel>
            <AlertDialogAction onClick={() => blocker.proceed?.()}>Sair sem salvar</AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </TooltipProvider>
  )
}

function GroupCard({
  title,
  fields,
  hasIssue,
  render,
}: {
  title: string
  fields: FormField[]
  hasIssue: (field: FormField) => boolean
  render: (field: FormField) => ReactNode
}) {
  const basic = fields.filter((f) => !f.advanced)
  const advanced = fields.filter((f) => f.advanced)
  const [open, setOpen] = useState(false)
  // an error or a suggestion inside the collapsed part must not stay hidden
  const forced = advanced.some(hasIssue)

  return (
    <Card size="sm">
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <Fields fields={basic} render={render} />
        {advanced.length > 0 && (
          <Collapsible open={open || forced} onOpenChange={setOpen} className="space-y-4">
            <CollapsibleTrigger asChild>
              <Button type="button" variant="ghost" size="sm" className="group/adv -ml-2">
                <CaretDown aria-hidden className="transition-transform group-data-[state=open]/adv:rotate-180" />
                Avançado
              </Button>
            </CollapsibleTrigger>
            <CollapsibleContent className="space-y-4">
              <Fields fields={advanced} render={render} />
            </CollapsibleContent>
          </Collapsible>
        )}
      </CardContent>
    </Card>
  )
}

// inputs share a 3-column grid; switches and checkbox groups get rows of their own below
function Fields({ fields, render }: { fields: FormField[]; render: (field: FormField) => ReactNode }) {
  const isSwitch = (f: FormField) => f.schema.type === 'boolean'
  const isGroup = (f: FormField) => f.schema.type === 'array'
  const inputs = fields.filter((f) => !isSwitch(f) && !isGroup(f))
  const switches = fields.filter(isSwitch)
  const groups = fields.filter(isGroup)
  return (
    <>
      {inputs.length > 0 && <div className="grid items-start gap-4 sm:grid-cols-2 lg:grid-cols-3">{inputs.map(render)}</div>}
      {switches.length > 0 && <div className="divide-y rounded-lg border px-3">{switches.map(render)}</div>}
      {groups.map(render)}
    </>
  )
}

function Help({ text, label }: { text: string; label: string }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <button
          type="button"
          aria-label={`Ajuda sobre ${label}`}
          className="rounded-full text-muted-foreground hover:text-foreground"
        >
          <Info aria-hidden className="size-3.5" />
        </button>
      </TooltipTrigger>
      <TooltipContent className="max-w-64">{text}</TooltipContent>
    </Tooltip>
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
  const reason = origin?.reason
  const describedBy = [reason && `${id}-note`, error && `${id}-error`].filter(Boolean).join(' ') || undefined
  const details = (
    <>
      {origin && (
        <Badge variant="info">{origin.source === 'gemini' ? 'Sugerido pelo Gemini' : 'Sugerido pelos dados'}</Badge>
      )}
      {reason && (
        <p id={`${id}-note`} className="text-xs text-muted-foreground">
          {reason}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
    </>
  )
  const label = (
    <div className="flex items-center gap-1.5">
      <Label htmlFor={id}>{field.label}</Label>
      {field.help && <Help text={field.help} label={field.label} />}
    </div>
  )

  if (schema.type === 'array') {
    const selected = Array.isArray(value) ? value : []
    const options = schema.items?.enum ?? []
    return (
      <div className="space-y-2">
        <div className="flex items-center gap-1.5">
          <p id={id} className="text-sm font-medium">
            {field.label}
          </p>
          {field.help && <Help text={field.help} label={field.label} />}
        </div>
        <div role="group" aria-labelledby={id} aria-describedby={describedBy} className="flex flex-wrap gap-x-6 gap-y-2">
          {options.map((option) => (
            <div key={option} className="flex items-center gap-2">
              <Checkbox
                id={`${id}-${option}`}
                checked={selected.includes(option)}
                disabled={disabled}
                onCheckedChange={(on) =>
                  onChange(on === true ? options.filter((o) => o === option || selected.includes(o)) : selected.filter((o) => o !== option))
                }
              />
              <Label htmlFor={`${id}-${option}`}>{ENUM_LABELS[option] ?? option}</Label>
            </div>
          ))}
        </div>
        {details}
      </div>
    )
  }

  if (schema.type === 'boolean') {
    return (
      <div className="py-2.5">
        <div className="flex items-center justify-between gap-4">
          {label}
          <Switch id={id} checked={value === true} disabled={disabled} aria-describedby={describedBy} onCheckedChange={onChange} />
        </div>
        {(origin || error) && <div className="mt-1 space-y-1">{details}</div>}
      </div>
    )
  }

  return (
    <div className="space-y-1.5">
      {label}
      {schema.enum ? (
        <Select value={String(value)} disabled={disabled} onValueChange={onChange}>
          <SelectTrigger id={id} className="w-full" aria-invalid={error ? true : undefined} aria-describedby={describedBy}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {schema.enum.map((option) => (
              <SelectItem key={option} value={option}>
                {ENUM_LABELS[option] ?? option}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      ) : (
        <Input
          id={id}
          name={field.path}
          type="text"
          inputMode="decimal"
          autoComplete="off"
          className="tabular-nums"
          placeholder={field.nullable ? (field.path.startsWith('financial_targets') ? 'Sem meta' : 'Opcional') : undefined}
          value={toDisplay(String(value))}
          aria-invalid={error ? true : undefined}
          aria-describedby={describedBy}
          disabled={disabled}
          onChange={(e) => onChange(fromDisplay(e.target.value))}
        />
      )}
      {details}
    </div>
  )
}
