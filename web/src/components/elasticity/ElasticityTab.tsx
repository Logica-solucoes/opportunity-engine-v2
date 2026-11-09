import { useQuery } from '@tanstack/react-query'
import { Warning } from '@phosphor-icons/react'
import { useState } from 'react'
import { BlockSkeleton } from '@/components/LoadState'
import { ExportBar } from '@/components/ExportBar'
import { NarrativeCard } from '@/components/NarrativeCard'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty'
import { ChartCard } from './ChartCard'
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
      <Alert variant="destructive">
        <Warning />
        <AlertDescription>Não foi possível carregar o resultado.</AlertDescription>
      </Alert>
    )
  const elasticity = query.data.elasticity
  const report = query.data.reports?.global
  const refused = !!elasticity && scenarioRefused(elasticity)
  return (
    <section aria-label="Elasticidade" className="space-y-5">
      {/* a refused run says it once, with the labeled reasons: the default narrative would repeat it */}
      {report && !refused && (
        <NarrativeCard
          report={report}
          paragraphs={[report.summary, ...report.scenarios.map((s) => `${s.name}: ${s.analysis}`)]}
          items={report.recommendations}
        />
      )}
      {!elasticity ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyTitle>Sem análise de elasticidade</EmptyTitle>
            <EmptyDescription>Esta execução não trouxe análise de elasticidade.</EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : refused ? (
        <Inconclusive
          title={elasticity.status === 'failed' ? 'Análise de elasticidade falhou' : undefined}
          lines={elasticity.reasons.map(reasonLabel)}
        />
      ) : (
        <div className="space-y-5">
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
    <Alert variant="warning">
      <Warning />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>
        <ul className="list-disc pl-4">
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
      <Alert variant="destructive">
        <Warning />
        <AlertDescription>Não foi possível carregar o cenário.</AlertDescription>
      </Alert>
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
      <div className="grid items-start gap-5 md:grid-cols-[17rem_minmax(0,1fr)] print:block">
        <FiltersPanel
          filters={filters}
          onChange={setFilters}
          bounds={bounds}
          revenueMode={scenario.revenue_mode}
          errors={!error ? [] : error.status === 422 ? filterErrors(error.body) : ['Não foi possível atualizar o cenário.']}
        />
        <div className="min-w-0 space-y-5">
          {metrics?.low_confidence && (
            <Alert variant="warning">
              <Warning />
              <AlertTitle>Baixa confiança</AlertTitle>
              <AlertDescription>
                O modelo explica pouco fora da amostra (CV R² {formatDecimal(metrics.cv_r2)}). Use as curvas como
                direção, não como meta.
              </AlertDescription>
            </Alert>
          )}
          <ScenarioTable scenario={scenario} />
          <ChartCard title="Curva de saturação">
            <SaturationChart scenario={scenario} />
          </ChartCard>
          <div className={scenario.revenue_mode ? 'grid gap-5 lg:grid-cols-2' : undefined}>
            <ChartCard title="iCPA">
              <IcpaChart curve={scenario.curve} />
            </ChartCard>
            {scenario.revenue_mode && (
              <ChartCard title="Receita e ROAS">
                <RevenueChart curve={scenario.curve} />
              </ChartCard>
            )}
          </div>
          {mixRow.mix && Object.keys(mixRow.mix).length > 0 && (
            <ChartCard
              title={`Mix por canal${scenario.recommended ? ' no ponto recomendado' : ' no ponto de saturação'}`}
              label="Mix por canal"
            >
              {metrics?.reallocation_suppressed && (
                <Alert variant="warning">
                  <Warning />
                  <AlertDescription>
                    O motor não confia na redistribuição entre canais desta execução: leia o otimizado e o estratégico
                    como hipótese, não como recomendação.
                  </AlertDescription>
                </Alert>
              )}
              <MixChart mix={mixRow.mix} />
            </ChartCard>
          )}
          <ChannelCurves channels={scenario.channels} hidden={hidden} />
        </div>
      </div>
    </div>
  )
}
