import { useQuery, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { Link, createFileRoute } from '@tanstack/react-router'
import { CircleX } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { RunDetails } from '@/components/RunDetails'
import { RunStatusBadge } from '@/components/RunStatusBadge'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { meQuery, roleIn } from '@/lib/auth'
import { type LogLine, isActive, runQuery, useRunLog } from '@/lib/runs'
import { formatDate } from '@/lib/simulations'

export const Route = createFileRoute('/_auth/w/$slug/execucoes/$runId')({ component: RunRoute })

// the router keeps the component when only runId changes; log ids are global, so the old lines would also hide the new ones
function RunRoute() {
  return <RunPage key={Route.useParams().runId} />
}

const LEVEL_CLASS: Record<LogLine['level'], string> = {
  info: '',
  warning: 'text-amber-600 dark:text-amber-400',
  error: 'text-destructive',
}

const formatTime = (iso: string) => new Date(iso).toLocaleTimeString('pt-BR')

function RunPage() {
  const { slug, runId } = Route.useParams()
  const queryClient = useQueryClient()
  const { data: run, isError } = useQuery(runQuery(slug, runId))
  const log = useRunLog(slug, runId)
  const { data: me } = useSuspenseQuery(meQuery)
  const canEdit = roleIn(me, slug) !== 'viewer'

  // the key is rebuilt inside: a fresh array in the deps would re-run this after every refetch
  useEffect(() => {
    if (log.state === 'ended') queryClient.invalidateQueries({ queryKey: runQuery(slug, runId).queryKey })
  }, [log.state, queryClient, slug, runId])

  // 404 covers another workspace, a run a viewer can't see yet and a non-numeric id
  if (!run) return isError ? <p>Execução não encontrada.</p> : null
  const active = isActive(run.status) && log.state !== 'ended'

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <Link
          to="/w/$slug/simulacoes/$id"
          params={{ slug, id: String(run.simulation.id) }}
          className="text-sm text-muted-foreground hover:text-primary"
        >
          ← {run.simulation.name}
        </Link>
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold">Execução #{run.id}</h1>
          <RunStatusBadge status={run.status} />
        </div>
        <p className="text-sm text-muted-foreground">
          {run.created_by_name} · {formatDate(run.created_at)} · motor {run.engine_version ?? '—'}
        </p>
      </div>

      {run.status === 'failed' && run.error && (
        <Alert variant="destructive">
          <CircleX />
          <AlertTitle>Falhou</AlertTitle>
          <AlertDescription>{run.error}</AlertDescription>
        </Alert>
      )}
      {(run.status === 'succeeded' || run.status === 'inconclusive') && (
        <p>Execução concluída. Os dashboards chegam em breve.</p>
      )}
      <RunDetails slug={slug} run={run} canEdit={canEdit} />

      <LogPanel lines={log.lines} active={active} ended={log.state === 'ended'} />
      {log.state === 'lost' && (
        <p role="alert" className="text-sm text-destructive">
          Não foi possível acompanhar o log.
        </p>
      )}
    </div>
  )
}

function LogPanel({ lines, active, ended }: { lines: LogLine[]; active: boolean; ended: boolean }) {
  const box = useRef<HTMLDivElement>(null)
  // follow new lines only while the reader is at the bottom; scrolling up to read stops it
  const atEnd = useRef(true)

  useEffect(() => {
    const el = box.current
    if (el && atEnd.current) el.scrollTop = el.scrollHeight
  }, [lines])

  const last = lines.at(-1)
  return (
    <section className="space-y-2">
      <div className="flex flex-wrap items-baseline justify-between gap-4">
        <h2 className="text-lg font-medium">Log</h2>
        {active && last && <Elapsed since={last.ts} />}
      </div>
      <div
        ref={box}
        role="log"
        aria-label="Log da execução"
        onScroll={(e) => {
          const el = e.currentTarget
          atEnd.current = el.scrollHeight - el.scrollTop - el.clientHeight < 8
        }}
        className="h-96 overflow-auto rounded-md border bg-muted/30 p-3 font-mono text-xs leading-relaxed"
      >
        {/* a finished run's backlog may arrive after the run itself: "no lines" waits for the stream's end */}
        {lines.length === 0 && (active || ended) && (
          <p className="text-muted-foreground">{active ? 'Aguardando o início da execução…' : 'Nenhuma linha de log.'}</p>
        )}
        {lines.map((line) => (
          <div key={line.id} className={LEVEL_CLASS[line.level]}>
            <span className="text-muted-foreground">{formatTime(line.ts)}</span> {line.message}
          </div>
        ))}
      </div>
    </section>
  )
}

function Elapsed({ since }: { since: string }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(timer)
  }, [])
  // the browser's clock and the server's can disagree by a few seconds; never show a negative time
  const seconds = Math.max(0, Math.round((now - Date.parse(since)) / 1000))
  return <p className="text-sm text-muted-foreground">Etapa em andamento há {seconds} s</p>
}
