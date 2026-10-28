import { useQuery } from '@tanstack/react-query'
import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import { LoadState } from '@/components/LoadState'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
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

const formatMonth = (month: string) => `${month.slice(5)}/${month.slice(0, 4)}`

function Usage() {
  const search = Route.useSearch()
  const navigate = useNavigate({ from: Route.fullPath })
  const month = search.month === 'todos' ? undefined : (search.month ?? thisMonth())
  const qs = month ? `?month=${month}` : ''
  // the field keeps its own text: Safari/Firefox render type=month as a text box, and a half-typed
  // value (or Chrome's '' mid-edit) must not round-trip through the URL
  const [draft, setDraft] = useState(month ?? '')
  const changeMonth = (value: string) => {
    setDraft(value)
    if (value === '') navigate({ search: { month: 'todos' }, replace: true })
    else if (MONTH.test(value)) navigate({ search: { month: value }, replace: true })
  }
  const usage = useQuery({
    queryKey: ['admin', 'usage', month ?? 'todos'],
    queryFn: () => api<UsageRow[]>(`/admin/usage${qs}`),
  })

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <Label htmlFor="usage-month">Mês</Label>
          <Input
            id="usage-month"
            type="month"
            className="w-44"
            value={draft}
            onChange={(e) => changeMonth(e.target.value)}
          />
        </div>
        {month && (
          <Button variant="outline" size="sm" onClick={() => changeMonth('')}>
            Todos os meses
          </Button>
        )}
        <Button asChild variant="outline" size="sm" className="ml-auto">
          <a href={`/api/admin/usage.csv${qs}`} download>
            Exportar CSV
          </a>
        </Button>
      </div>

      {!usage.data ? (
        <LoadState query={usage} />
      ) : usage.data.length === 0 ? (
        <p className="text-muted-foreground">Nenhuma execução neste período.</p>
      ) : (
        <Table>
          <TableHeader>
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
                <TableCell>{formatMonth(r.month)}</TableCell>
                <TableCell>{r.workspace_name}</TableCell>
                <TableCell title={r.user_email}>{r.user_name}</TableCell>
                <TableCell className="text-right">{r.succeeded}</TableCell>
                <TableCell className="text-right">{r.inconclusive}</TableCell>
                <TableCell className="text-right">{r.failed}</TableCell>
                <TableCell className="text-right">{r.active}</TableCell>
                <TableCell className="text-right">{r.total}</TableCell>
                <TableCell className="text-right">{formatDuration(r.run_seconds)}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
