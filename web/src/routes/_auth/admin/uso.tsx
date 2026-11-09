import { useQuery } from '@tanstack/react-query'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { DownloadSimple } from '@phosphor-icons/react'
import { DataTable } from '@/components/DataTable'
import { FilterBar, FilterField } from '@/components/FilterBar'
import { LoadState } from '@/components/LoadState'
import { Button } from '@/components/ui/button'
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { api } from '@/lib/api'

type UsageRow = {
  month: string
  workspace_id: number
  workspace_name: string
  user_id: number
  user_name: string
  user_email: string
  succeeded: number
  inconclusive: number
  failed: number
  active: number
  total: number
  run_seconds: number
}

// "todos" = every month; no param = this month
type UsageSearch = { month?: string }

const MONTH = /^\d{4}-(0[1-9]|1[0-2])$/

export const Route = createFileRoute('/_auth/admin/uso')({
  validateSearch: (search: Record<string, unknown>): UsageSearch => {
    const month = search.month
    return { month: typeof month === 'string' && (month === 'todos' || MONTH.test(month)) ? month : undefined }
  },
  component: Usage,
})

function thisMonth() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

// display only: the seconds come summed from the api
function formatDuration(seconds: number) {
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes} min`
  return `${Math.floor(minutes / 60)} h ${String(minutes % 60).padStart(2, '0')} min`
}

const MONTH_NAMES = Array.from({ length: 12 }, (_, i) => {
  const name = new Date(2000, i, 1).toLocaleDateString('pt-BR', { month: 'long' })
  return name[0].toUpperCase() + name.slice(1)
})

// the platform started in 2026; the selected year is added if it falls outside
function yearOptions(selected?: string) {
  const last = new Date().getFullYear()
  const years = Array.from({ length: last - 2026 + 1 }, (_, i) => String(2026 + i))
  return selected && !years.includes(selected) ? [...years, selected].sort() : years
}

const formatMonth = (month: string) => `${month.slice(5)}/${month.slice(0, 4)}`

function Usage() {
  const search = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const month = search.month === 'todos' ? undefined : (search.month ?? thisMonth())
  const qs = month ? `?month=${month}` : ''
  const [year, monthNumber] = (month ?? '').split('-')
  const goTo = (value: string) => navigate({ search: { month: value }, replace: true })
  // picking only one half fills the other from today
  const now = thisMonth()
  const changeYear = (y: string) => goTo(`${y}-${monthNumber ?? now.slice(5)}`)
  const changeMonthNumber = (m: string) => goTo(`${year ?? now.slice(0, 4)}-${m}`)
  const usage = useQuery({
    queryKey: ['admin', 'usage', month ?? 'todos'],
    queryFn: () => api<UsageRow[]>(`/admin/usage${qs}`),
  })

  const exportCsv = (
    <Button asChild variant="outline" size="sm">
      <a href={`/api/admin/usage.csv${qs}`} download>
        <DownloadSimple aria-hidden />
        Exportar CSV
      </a>
    </Button>
  )

  const filters = (
      <FilterBar>
        <FilterField label="Mês" htmlFor="usage-month">
          <Select value={monthNumber ?? ''} onValueChange={changeMonthNumber}>
            <SelectTrigger id="usage-month" className="gap-3 pl-4">
              <SelectValue placeholder="Todos" />
            </SelectTrigger>
            <SelectContent>
              {MONTH_NAMES.map((name, i) => (
                <SelectItem key={name} value={String(i + 1).padStart(2, '0')}>
                  {name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FilterField>
        <FilterField label="Ano" htmlFor="usage-year">
          <Select value={year ?? ''} onValueChange={changeYear}>
            <SelectTrigger id="usage-year" className="gap-3 pl-4">
              <SelectValue placeholder="Todos" />
            </SelectTrigger>
            <SelectContent>
              {yearOptions(year).map((y) => (
                <SelectItem key={y} value={y}>
                  {y}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FilterField>
        {month && (
          <Button variant="ghost" size="sm" onClick={() => goTo('todos')}>
            Todos os meses
          </Button>
        )}
      </FilterBar>
  )

  return (
    <div className="space-y-6">
      {!usage.data || usage.data.length === 0 ? (
        <div className="flex flex-wrap items-center justify-between gap-3">
          {filters}
          {exportCsv}
        </div>
      ) : null}

      {!usage.data ? (
        <LoadState query={usage} />
      ) : usage.data.length === 0 ? (
        <Empty className="border">
          <EmptyHeader>
            <EmptyTitle>Nenhuma execução neste período</EmptyTitle>
            <EmptyDescription>Escolha outro mês ou veja todos.</EmptyDescription>
          </EmptyHeader>
        </Empty>
      ) : (
        <DataTable
          id="uso"
          toolbar={filters}
          actions={exportCsv}
          rows={usage.data}
          rowKey={(r) => `${r.month}-${r.workspace_id}-${r.user_id}`}
          columns={[
            { id: 'month', header: 'Mês', sort: (r) => r.month, className: 'tabular-nums', cell: (r) => formatMonth(r.month) },
            { id: 'workspace', header: 'Workspace', sort: (r) => r.workspace_name, cell: (r) => r.workspace_name },
            { id: 'user', header: 'Usuário', sort: (r) => r.user_name, cell: (r) => <span title={r.user_email}>{r.user_name}</span> },
            { id: 'succeeded', header: 'Concluídas', sort: (r) => r.succeeded, className: 'tabular-nums', cell: (r) => r.succeeded },
            { id: 'inconclusive', header: 'Inconclusivas', sort: (r) => r.inconclusive, className: 'tabular-nums', cell: (r) => r.inconclusive },
            { id: 'failed', header: 'Falharam', sort: (r) => r.failed, className: 'tabular-nums', cell: (r) => r.failed },
            { id: 'active', header: 'Em andamento', sort: (r) => r.active, className: 'tabular-nums', cell: (r) => r.active },
            { id: 'total', header: 'Total', sort: (r) => r.total, className: 'tabular-nums', cell: (r) => r.total },
            { id: 'time', header: 'Tempo de execução', sort: (r) => r.run_seconds, className: 'tabular-nums', cell: (r) => formatDuration(r.run_seconds) },
          ]}
        />
      )}
    </div>
  )
}
