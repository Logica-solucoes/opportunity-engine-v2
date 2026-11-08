import { useQuery } from '@tanstack/react-query'
import { TriangleAlert } from 'lucide-react'
import { useState } from 'react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { ApiError } from '@/lib/api'
import { type Elasticity, formatDecimal, reasonLabel, resultsQuery } from '@/lib/results'
import { type Filters, type Scenario, filterErrors, scenarioQuery, useDebounced } from '@/lib/scenario'
import { ChannelCurves } from './ChannelCurves'
import { IcpaChart, MixChart, RevenueChart, SaturationChart } from './ElasticityCharts'
import { FiltersPanel } from './FiltersPanel'
import { ScenarioTable } from './ScenarioTable'

export function ElasticityTab({ slug, runId }: { slug: string; runId: string }) {
  const query = useQuery(resultsQuery(slug, runId))
  if (query.isPending) return <p className="text-sm text-muted-foreground">Carregando…</p>
  if (query.isError)
    return (
      <p role="alert" className="text-sm text-destructive">
        Não foi possível carregar o resultado.
      </p>
    )
  const elasticity = query.data.elasticity
  return (
    <section aria-label="Elasticidade">
      {!elasticity ? (
        <p className="text-sm text-muted-foreground">Sem análise de elasticidade nesta execução.</p>
      ) : elasticity.status !== 'ok' ? (
        <Inconclusive lines={elasticity.reasons.map(reasonLabel)} />
      ) : (
        <Planner slug={slug} runId={runId} elasticity={elasticity} />
      )}
    </section>
  )
}

function Inconclusive({ lines }: { lines: string[] }) {
  return (
    <Alert>
      <TriangleAlert />
      <AlertTitle>Análise de elasticidade inconclusiva</AlertTitle>
      <AlertDescription>
        <ul className="list-disc pl-5">
          {lines.map((l) => (
            <li key={l}>{l}</li>
          ))}
        </ul>
      </AlertDescription>
    </Alert>
  )
}

function Planner({ slug, runId, elasticity }: { slug: string; runId: string; elasticity: Elasticity }) {
  const [filters, setFilters] = useState<Filters>({})
  const debounced = useDebounced(filters)
  const query = useQuery(scenarioQuery(slug, runId, debounced))
  // the slider's range is the whole curve, so it comes from the unfiltered answer (cached by its key)
  const unfiltered = useQuery(scenarioQuery(slug, runId, {})).data
  // a 422 on a bad filter keeps the last good answer on screen
  const [last, setLast] = useState<Scenario>()
  if (query.data && query.data !== last) setLast(query.data)
  const scenario = query.data ?? last

  const error = query.error instanceof ApiError ? query.error : null
  if (!scenario) {
    if (query.isPending) return <p className="text-sm text-muted-foreground">Carregando…</p>
    if (error?.status === 409) return <Inconclusive lines={[error.detail]} />
    return (
      <p role="alert" className="text-sm text-destructive">
        Não foi possível carregar o cenário.
      </p>
    )
  }

  const curve = unfiltered?.curve
  const bounds: [number, number] | null = curve?.length
    ? [Math.floor(curve[0].investment), Math.ceil(curve[curve.length - 1].investment)]
    : null
  const mixRow = scenario.recommended ?? scenario.saturation
  const hidden = elasticity.channels.filter((c) => c.identifiable === false)
  const metrics = elasticity.metrics

  return (
    <div className="grid gap-6 md:grid-cols-[18rem_minmax(0,1fr)]">
      <FiltersPanel
        filters={filters}
        onChange={setFilters}
        bounds={bounds}
        revenueMode={scenario.revenue_mode}
        errors={error?.status === 422 ? filterErrors(error.body) : []}
      />
      <div className="min-w-0 space-y-8">
        {metrics?.low_confidence && (
          <Alert>
            <TriangleAlert />
            <AlertTitle>Baixa confiança</AlertTitle>
            <AlertDescription>
              O modelo explica pouco fora da amostra (CV R² {formatDecimal(metrics.cv_r2)}). Use as curvas como
              direção, não como meta.
            </AlertDescription>
          </Alert>
        )}
        <ScenarioTable scenario={scenario} />
        <section aria-label="Curva de saturação" className="space-y-2">
          <h2 className="text-lg font-semibold">Curva de saturação</h2>
          <SaturationChart scenario={scenario} />
        </section>
        <div className="grid gap-6 lg:grid-cols-2">
          <section aria-label="iCPA" className="space-y-2">
            <h2 className="text-lg font-semibold">iCPA</h2>
            <IcpaChart curve={scenario.curve} />
          </section>
          {scenario.revenue_mode && (
            <section aria-label="Receita e ROAS" className="space-y-2">
              <h2 className="text-lg font-semibold">Receita e ROAS</h2>
              <RevenueChart curve={scenario.curve} />
            </section>
          )}
        </div>
        {mixRow.mix && (
          <section aria-label="Mix por canal" className="space-y-2">
            <h2 className="text-lg font-semibold">Mix por canal</h2>
            {metrics?.reallocation_suppressed && (
              <Alert>
                <TriangleAlert />
                <AlertDescription>
                  O motor não confia na redistribuição entre canais desta execução: leia o otimizado e o estratégico
                  como hipótese, não como recomendação.
                </AlertDescription>
              </Alert>
            )}
            <MixChart mix={mixRow.mix} />
          </section>
        )}
        <ChannelCurves channels={scenario.channels} hidden={hidden} />
      </div>
    </div>
  )
}
