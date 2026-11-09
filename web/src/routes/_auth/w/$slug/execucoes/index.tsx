import { useQuery, useSuspenseQuery } from '@tanstack/react-query'
import { Link, createFileRoute, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import { LoadState } from '@/components/LoadState'
import { RunStatusBadge } from '@/components/RunStatusBadge'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
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
import { backLink, rowLink } from '@/lib/links'

const ALL = 'all'

export const Route = createFileRoute('/_auth/w/$slug/execucoes/')({
  validateSearch: parseRunFilters,
  component: HistoryPage,
})

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
        <h1 className="text-2xl font-semibold">Execuções</h1>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <Label htmlFor="filter-q">Simulação</Label>
          <Input
            id="filter-q"
            type="search"
            placeholder="Buscar pelo nome…"
            className="w-56"
            value={q}
            onChange={(e) => {
              setQ(e.target.value)
              set({ q: e.target.value || undefined })
            }}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="filter-status">Status</Label>
          <Select
            value={filters.status ?? ALL}
            onValueChange={(v) => set({ status: v === ALL ? undefined : (v as RunStatus) })}
          >
            <SelectTrigger id="filter-status" className="min-w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>Todos</SelectItem>
              {Object.entries(STATUS_LABELS).map(([value, label]) => (
                <SelectItem key={value} value={value}>
                  {label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="filter-author">Autor</Label>
          <Select value={filters.author ?? ALL} onValueChange={(v) => set({ author: v === ALL ? undefined : v })}>
            <SelectTrigger id="filter-author" className="min-w-36">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>Todos</SelectItem>
              {authors.map((name) => (
                <SelectItem key={name} value={name}>
                  {name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="space-y-1">
          <Label htmlFor="filter-from">De</Label>
          <Input
            id="filter-from"
            type="date"
            value={filters.from ?? ''}
            onChange={(e) => set({ from: e.target.value || undefined })}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="filter-to">Até</Label>
          <Input
            id="filter-to"
            type="date"
            value={filters.to ?? ''}
            onChange={(e) => set({ to: e.target.value || undefined })}
          />
        </div>
      </div>

      {!data ? (
        <LoadState query={query} />
      ) : data.length === 0 ? (
        <p className="text-muted-foreground">Nenhuma execução ainda.</p>
      ) : shown.length === 0 ? (
        <div className="flex flex-wrap items-center gap-3">
          <p className="text-muted-foreground">Nenhuma execução com esses filtros.</p>
          <Button variant="outline" size="sm" onClick={clear}>
            Limpar filtros
          </Button>
        </div>
      ) : (
        <HistoryTable slug={slug} runs={shown} />
      )}
    </div>
  )
}

function HistoryTable({ slug, runs }: { slug: string; runs: Run[] }) {
  return (
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
          <TableRow key={r.id}>
            <TableCell>
              <Link
                to="/w/$slug/execucoes/$runId"
                params={{ slug, runId: String(r.id) }}
                className={rowLink}
              >
                #{r.id}
              </Link>
            </TableCell>
            <TableCell>{r.simulation.name}</TableCell>
            <TableCell>
              <RunStatusBadge status={r.status} />
            </TableCell>
            <TableCell>{r.created_by_name}</TableCell>
            <TableCell>{formatDate(r.created_at)}</TableCell>
            <TableCell className="font-mono text-xs">{r.engine_version ?? '—'}</TableCell>
            <TableCell>{r.published_at ? <Badge variant="outline">Publicada</Badge> : '—'}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
