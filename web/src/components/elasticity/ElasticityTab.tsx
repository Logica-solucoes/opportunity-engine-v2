import { useQuery } from '@tanstack/react-query'
import { Warning } from '@phosphor-icons/react'
import { useState } from 'react'
import { BlockSkeleton } from '@/components/LoadState'
import { ExportBar } from '@/components/ExportBar'
import { NarrativeCard } from '@/components/NarrativeCard'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { ApiError } from '@/lib/api'
import { type Elasticity, formatDecimal, reasonLabel, resultsQuery } from '@/lib/results'
import {
  type Filters,
  type Scenario,
  filterErrors,
  scenarioCsvHref,
  scenarioQuery,
  scenarioRefused,
  useDebounced,
} from '@/lib/scenario'
import { ChannelCurves } from './ChannelCurves'
import { IcpaChart, MixChart, RevenueChart, SaturationChart } from './ElasticityCharts'
import { FiltersPanel, FiltersSummary } from './FiltersPanel'
import { ScenarioTable } from './ScenarioTable'

export function ElasticityTab({ slug, runId }: { slug: string; runId: string }) {
  const query = useQuery(resultsQuery(slug, runId))
  if (query.isPending) return <BlockSkeleton className="h-64" />
  if (query.isError)
    return (
      <p role="alert" className="text-sm text-destructive">
        Não foi possível carregar o resultado.
      </p>
    )
  const elasticity = query.data.elasticity
  const report = query.data.reports?.global
  return (
    <section aria-label="Elasticidade">
      {report && (
        <div className="mb-6">
          <NarrativeCard
            report={report}
            paragraphs={[report.summary, ...report.scenarios.map((s) => `${s.name}: ${s.analysis}`)]}
            items={report.recommendations}
          />
        </div>
      )}
      {!elasticity ? (
        <p className="text-sm text-muted-foreground">Sem análise de elasticidade nesta execução.</p>
      ) : scenarioRefused(elasticity) ? (
        <Inconclusive
          title={elasticity.status === 'failed' ? 'Análise de elasticidade falhou' : undefined}
          lines={elasticity.reasons.map(reasonLabel)}
        />
      ) : (
        <div className="space-y-6">
          {elasticity.status !== 'ok' && (
            <Inconclusive title="Análise de elasticidade não validada" lines={elasticity.reasons.map(reasonLabel)} />
          )}
          {/* keyed by run: filters and the last good answer never cross to another run */}
          <Planner key={runId} slug={slug} runId={runId} elasticity={elasticity} />
        </div>
      )}
    </section>
  )
}

function Inconclusive({ title = 'Análise de elasticidade inconclusiva', lines }: { title?: string; lines: string[] }) {
  return (
    <Alert>
      <Warning />
      <AlertTitle>{title}</AlertTitle>
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
    if (query.isPending) return <BlockSkeleton className="h-64" />
    if (error?.status === 409) return <Inconclusive title="Sem cenário para simular" lines={[error.detail]} />
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
  const hidden = elasticity.channels.filter((c) => c.identifiable !== true)
  const metrics = elasticity.metrics

  return (
    <div className="space-y-4">
      <ExportBar
        links={
          // a filter the API rejects would download its 422
          error
            ? []
            : [
                ['Cenários CSV', scenarioCsvHref(slug, runId, 'scenario.csv', filters)],
                ['Curva CSV', scenarioCsvHref(slug, runId, 'curve.csv', filters)],
              ]
        }
      />
      <FiltersSummary filters={filters} />
      <div className="grid gap-6 md:grid-cols-[18rem_minmax(0,1fr)] print:block">
        <FiltersPanel
          filters={filters}
          onChange={setFilters}
          bounds={bounds}
          revenueMode={scenario.revenue_mode}
          errors={!error ? [] : error.status === 422 ? filterErrors(error.body) : ['Não foi possível atualizar o cenário.']}
        />
        <div className="min-w-0 space-y-8">
          {metrics?.low_confidence && (
            <Alert>
              <Warning />
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
          <div className={scenario.revenue_mode ? 'grid gap-6 lg:grid-cols-2' : undefined}>
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
          {mixRow.mix && Object.keys(mixRow.mix).length > 0 && (
            <section aria-label="Mix por canal" className="space-y-2">
              <h2 className="text-lg font-semibold">
                Mix por canal{scenario.recommended ? ' no ponto recomendado' : ' no ponto de saturação'}
              </h2>
              {metrics?.reallocation_suppressed && (
                <Alert>
                  <Warning />
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
    </div>
  )
}
