import { useQuery, useSuspenseQuery } from '@tanstack/react-query'
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router'
import { CalendarBlank, FunnelSimple, MagnifyingGlass, X } from '@phosphor-icons/react'
import { useState } from 'react'
import { ptBR } from 'react-day-picker/locale'
import { LoadState } from '@/components/LoadState'
import { RunStatusBadge } from '@/components/RunStatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Calendar } from '@/components/ui/calendar'
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { Input } from '@/components/ui/input'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { meQuery, roleIn } from '@/lib/auth'
import {
  type Run,
  type RunFilters,
  type RunStatus,
  STATUS_LABELS,
  filterRuns,
  parseRunFilters,
  workspaceRunsQuery,
} from '@/lib/runs'
import { formatDate } from '@/lib/simulations'
import { backLink } from '@/lib/links'

const ALL = 'all'

export const Route = createFileRoute('/_auth/w/$slug/execucoes/')({
  validateSearch: parseRunFilters,
  component: HistoryPage,
})

// the filters carry YYYY-MM-DD; Date only exists for the calendar
const parseDay = (v: string) => {
  const [y, m, d] = v.split('-').map(Number)
  return new Date(y, m - 1, d)
}
const toDay = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`

function DateFilter({
  label,
  value,
  onChange,
  disabled,
}: {
  label: string
  value?: string
  onChange: (v: string | undefined) => void
  disabled?: React.ComponentProps<typeof Calendar>['disabled']
}) {
  const [open, setOpen] = useState(false)
  const date = value ? parseDay(value) : undefined
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button variant="outline" aria-label={label} className="min-w-32 justify-start font-normal">
          <CalendarBlank aria-hidden className="text-muted-foreground" />
          {date ? (
            <span className="tabular-nums">{date.toLocaleDateString('pt-BR')}</span>
          ) : (
            <span className="text-muted-foreground">{label}</span>
          )}
        </Button>
      </PopoverTrigger>
      <PopoverContent align="start" className="w-auto p-0">
        <Calendar
          mode="single"
          locale={ptBR}
          selected={date}
          defaultMonth={date}
          disabled={disabled}
          onSelect={(d) => {
            onChange(d ? toDay(d) : undefined)
            setOpen(false)
          }}
        />
      </PopoverContent>
    </Popover>
  )
}

function HistoryPage() {
  const { slug } = Route.useParams()
  const filters = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const { data: me } = useSuspenseQuery(meQuery)
  const query = useQuery(workspaceRunsQuery(slug))
  const { data } = query
  // replace: typing in the search box must not push one history entry per key
  const set = (patch: RunFilters) => navigate({ search: (prev) => ({ ...prev, ...patch }), replace: true })
  // the box keeps its own text: fed from the URL, which updates a frame late, the caret jumped to the end
  const [q, setQ] = useState(filters.q ?? '')
  const clear = () => {
    setQ('')
    navigate({ search: {}, replace: true })
  }
  const hasFilters = Object.values(filters).some(Boolean)
  const authors = [...new Set(data?.map((r) => r.created_by_name))].sort((a, b) => a.localeCompare(b, 'pt-BR'))
  const shown = data ? filterRuns(data, filters) : []

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        {/* a viewer's workspace home redirects here, so the link would loop */}
        {roleIn(me, slug) !== 'viewer' && (
          <Link to="/w/$slug" params={{ slug }} className={backLink}>
            ← Simulações
          </Link>
        )}
        <h1 className="text-xl font-semibold text-balance">Execuções</h1>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative">
          <MagnifyingGlass aria-hidden className="pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            aria-label="Simulação"
            type="search"
            autoComplete="off"
            spellCheck={false}
            placeholder="Buscar simulação…"
            className="w-60 pl-8"
            value={q}
            onChange={(e) => {
              setQ(e.target.value)
              set({ q: e.target.value || undefined })
            }}
          />
        </div>
        <Select
          value={filters.status ?? ''}
          onValueChange={(v) => set({ status: v === ALL ? undefined : (v as RunStatus) })}
        >
          <SelectTrigger aria-label="Status" className="min-w-36">
            <SelectValue placeholder="Status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>Todos os status</SelectItem>
            {Object.entries(STATUS_LABELS).map(([value, label]) => (
              <SelectItem key={value} value={value}>
                {label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <Select value={filters.author ?? ''} onValueChange={(v) => set({ author: v === ALL ? undefined : v })}>
          <SelectTrigger aria-label="Autor" className="min-w-36">
            <SelectValue placeholder="Autor" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL}>Todos os autores</SelectItem>
            {authors.map((name) => (
              <SelectItem key={name} value={name}>
                {name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <DateFilter
          label="De"
          value={filters.from}
          onChange={(from) => set({ from })}
          disabled={filters.to ? { after: parseDay(filters.to) } : undefined}
        />
        <DateFilter
          label="Até"
          value={filters.to}
          onChange={(to) => set({ to })}
          disabled={filters.from ? { before: parseDay(filters.from) } : undefined}
        />
        {hasFilters && (
          <Button variant="ghost" size="sm" onClick={clear}>
            <X />
            Limpar
          </Button>
        )}
      </div>

      {!data ? (
        <LoadState query={query} />
      ) : data.length === 0 ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <FunnelSimple />
            </EmptyMedia>
            <EmptyTitle>Nenhuma execução ainda.</EmptyTitle>
            <EmptyDescription>As execuções aparecem aqui depois que uma simulação for rodada.</EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : shown.length === 0 ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyMedia variant="icon">
              <FunnelSimple />
            </EmptyMedia>
            <EmptyTitle>Nenhuma execução com esses filtros.</EmptyTitle>
            <EmptyDescription>Ajuste a busca ou remova algum filtro.</EmptyDescription>
          </EmptyHeader>
          <EmptyContent>
            <Button variant="outline" size="sm" onClick={clear}>
              Limpar filtros
            </Button>
          </EmptyContent>
        </Empty>
      ) : (
        <HistoryTable slug={slug} runs={shown} />
      )}
    </div>
  )
}

function HistoryTable({ slug, runs }: { slug: string; runs: Run[] }) {
  return (
    <div className="rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Execução</TableHead>
            <TableHead>Simulação</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Criada por</TableHead>
            <TableHead>Criada em</TableHead>
            <TableHead>Motor</TableHead>
            <TableHead>Publicação</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {runs.map((r) => (
            <TableRow key={r.id} className="relative">
              <TableCell>
                <Link
                  to="/w/$slug/execucoes/$runId"
                  params={{ slug, runId: String(r.id) }}
                  className="font-medium tabular-nums outline-none after:absolute after:inset-0 focus-visible:after:ring-2 focus-visible:after:ring-inset focus-visible:after:ring-ring"
                >
                  #{r.id}
                </Link>
              </TableCell>
              <TableCell className="font-medium">{r.simulation.name}</TableCell>
              <TableCell>
                <RunStatusBadge status={r.status} />
              </TableCell>
              <TableCell className="text-muted-foreground">{r.created_by_name}</TableCell>
              <TableCell className="text-muted-foreground tabular-nums">{formatDate(r.created_at)}</TableCell>
              <TableCell className="font-mono text-xs text-muted-foreground tabular-nums">
                {r.engine_version ?? '—'}
              </TableCell>
              <TableCell>
                {r.published_at ? <Badge variant="success">Publicada</Badge> : <span className="text-muted-foreground">—</span>}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
