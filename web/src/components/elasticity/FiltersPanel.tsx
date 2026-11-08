import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Slider } from '@/components/ui/slider'
import { formatMoney } from '@/lib/results'
import type { Filters } from '@/lib/scenario'

type Key = keyof Filters
const FIELDS: [Key, string, boolean][] = [
  ['target_cpa', 'CPA máximo', false],
  ['target_icpa', 'iCPA máximo', false],
  ['min_roas', 'ROAS mínimo', true],
  ['min_iroas', 'iROAS mínimo', true],
  ['min_kpi', 'KPI mínimo', false],
  ['min_incrementality_pct', '% de incrementalidade mínima', false],
]

type Props = {
  filters: Filters
  onChange: (filters: Filters) => void
  bounds: [number, number] | null
  revenueMode: boolean
  errors: string[]
}

export function FiltersPanel({ filters, onChange, bounds, revenueMode, errors }: Props) {
  const set = (key: Key, value: number | undefined) => onChange({ ...filters, [key]: value })
  const budget: [number, number] | null = bounds && [filters.min_budget ?? bounds[0], filters.max_budget ?? bounds[1]]

  return (
    <aside aria-label="Filtros" className="space-y-4">
      <h2 className="text-sm font-medium">Filtros (valores mensais)</h2>
      {bounds && budget && (
        <div className="space-y-2">
          <p className="text-sm font-medium">Orçamento</p>
          <Slider
            thumbLabels={['Orçamento mínimo', 'Orçamento máximo']}
            min={bounds[0]}
            max={bounds[1]}
            step={1}
            value={budget}
            onValueChange={([min, max]) => onChange({ ...filters, min_budget: min, max_budget: max })}
          />
          <p className="text-xs text-muted-foreground">
            {formatMoney(budget[0])} – {formatMoney(budget[1])}
          </p>
        </div>
      )}
      {FIELDS.filter(([, , revenueOnly]) => revenueMode || !revenueOnly).map(([key, label]) => (
        <div key={key} className="space-y-1">
          <Label htmlFor={key}>{label}</Label>
          <Input
            id={key}
            type="number"
            inputMode="decimal"
            min={0}
            value={filters[key] ?? ''}
            onChange={(e) => set(key, e.target.value === '' ? undefined : Number(e.target.value))}
          />
        </div>
      ))}
      <Button variant="outline" size="sm" onClick={() => onChange({})}>
        Limpar
      </Button>
      {errors.length > 0 && (
        <ul role="alert" className="text-sm text-destructive">
          {errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
    </aside>
  )
}
