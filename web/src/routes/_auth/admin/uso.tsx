import { useQuery } from '@tanstack/react-query'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { DownloadSimple } from '@phosphor-icons/react'
import { LoadState } from '@/components/LoadState'
import { Button } from '@/components/ui/button'
import { Empty, EmptyDescription, EmptyHeader, EmptyTitle } from '@/components/ui/empty'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
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

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-end gap-3">
        <div className="grid gap-1.5">
          <Label htmlFor="usage-month">Mês</Label>
          <Select value={monthNumber ?? ''} onValueChange={changeMonthNumber}>
            <SelectTrigger id="usage-month" className="w-40">
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
        </div>
        <div className="grid gap-1.5">
          <Label htmlFor="usage-year">Ano</Label>
          <Select value={year ?? ''} onValueChange={changeYear}>
            <SelectTrigger id="usage-year" className="w-28">
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
        </div>
        {month && (
          <Button variant="ghost" onClick={() => goTo('todos')}>
            Todos os meses
          </Button>
        )}
        <Button asChild variant="outline" className="ml-auto">
          <a href={`/api/admin/usage.csv${qs}`} download>
            <DownloadSimple aria-hidden />
            Exportar CSV
          </a>
        </Button>
      </div>

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
        <Table>
          <TableHeader className="[&_th]:text-muted-foreground">
            <TableRow>
              <TableHead>Mês</TableHead>
              <TableHead>Workspace</TableHead>
              <TableHead>Usuário</TableHead>
              <TableHead className="text-right">Concluídas</TableHead>
              <TableHead className="text-right">Inconclusivas</TableHead>
              <TableHead className="text-right">Falharam</TableHead>
              <TableHead className="text-right">Em andamento</TableHead>
              <TableHead className="text-right">Total</TableHead>
              <TableHead className="text-right">Tempo de execução</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {usage.data.map((r) => (
              <TableRow key={`${r.month}-${r.workspace_id}-${r.user_id}`}>
                <TableCell className="tabular-nums">{formatMonth(r.month)}</TableCell>
                <TableCell>{r.workspace_name}</TableCell>
                <TableCell title={r.user_email}>{r.user_name}</TableCell>
                <TableCell className="text-right tabular-nums">{r.succeeded}</TableCell>
                <TableCell className="text-right tabular-nums">{r.inconclusive}</TableCell>
                <TableCell className="text-right tabular-nums">{r.failed}</TableCell>
                <TableCell className="text-right tabular-nums">{r.active}</TableCell>
                <TableCell className="text-right tabular-nums">{r.total}</TableCell>
                <TableCell className="text-right tabular-nums">{formatDuration(r.run_seconds)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
