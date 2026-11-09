import { CaretDown, CaretLeft, CaretRight, CaretUp, CaretUpDown, Columns } from '@phosphor-icons/react'
import { type ReactNode, useMemo, useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

export type Column<T> = {
  id: string
  // '' marks an action column: no sorting, always shown
  header: string
  cell: (row: T) => ReactNode
  sort?: (row: T) => string | number | null
  className?: string
  // hidden at first; the user's choice is kept in localStorage
  hidden?: boolean
  // can't be hidden (the one that carries the row link)
  fixed?: boolean
}

const PAGE_SIZES = [10, 25, 50, 100]

// one choice for every table, kept in localStorage
function loadPageSize() {
  const saved = Number(localStorage.getItem('table:pageSize'))
  return PAGE_SIZES.includes(saved) ? saved : PAGE_SIZES[0]
}

type Sort = { id: string; dir: 'asc' | 'desc' } | null

const collator = new Intl.Collator('pt-BR', { numeric: true, sensitivity: 'base' })

function compare(a: string | number, b: string | number) {
  return typeof a === 'number' && typeof b === 'number' ? a - b : collator.compare(String(a), String(b))
}

function loadHidden<T>(id: string, columns: Column<T>[]): string[] {
  try {
    const saved = JSON.parse(localStorage.getItem(`table:${id}`) ?? 'null')
    if (Array.isArray(saved)) return saved
  } catch {
    // unreadable value: fall back to the defaults
  }
  return columns.filter((c) => c.hidden).map((c) => c.id)
}

export function DataTable<T>({
  id,
  columns,
  rows,
  rowKey,
  rowClassName,
  toolbar,
  actions,
}: {
  id: string
  columns: Column<T>[]
  rows: T[]
  rowKey: (row: T) => string | number
  rowClassName?: string
  // filters or an AddDialog on the left and extra buttons on the right, on the same line as "Colunas"
  toolbar?: ReactNode
  actions?: ReactNode
}) {
  const [sort, setSort] = useState<Sort>(null)
  const [pageSize, setPageSize] = useState(loadPageSize)
  const [page, setPage] = useState(0)
  const [hidden, setHidden] = useState(() => loadHidden(id, columns))
  const visible = columns.filter((c) => !hidden.includes(c.id))
  const toggleable = columns.filter((c) => c.header && !c.fixed)

  const sorted = useMemo(() => {
    const by = columns.find((c) => c.id === sort?.id)?.sort
    if (!sort || !by) return rows
    const sign = sort.dir === 'asc' ? 1 : -1
    // empty values go last whichever the direction
    return [...rows].sort((a, b) => {
      const x = by(a)
      const y = by(b)
      if (x == null || y == null) return x == null ? (y == null ? 0 : 1) : -1
      return sign * compare(x, y)
    })
  }, [rows, columns, sort])

  const pages = Math.max(1, Math.ceil(sorted.length / pageSize))
  // rows can shrink under the current page (filter, delete)
  const current = Math.min(page, pages - 1)
  const shown = sorted.slice(current * pageSize, (current + 1) * pageSize)
  const first = sorted.length === 0 ? 0 : current * pageSize + 1

  // none -> ascending -> descending -> none
  const cycle = (col: string) =>
    setSort((s) => (s?.id !== col ? { id: col, dir: 'asc' } : s.dir === 'asc' ? { id: col, dir: 'desc' } : null))


  const setVisible = (col: string, on: boolean) => {
    const next = on ? hidden.filter((h) => h !== col) : [...hidden, col]
    setHidden(next)
    localStorage.setItem(`table:${id}`, JSON.stringify(next))
  }

  const setAll = (on: boolean) => {
    const next = on ? [] : toggleable.map((c) => c.id)
    setHidden(next)
    localStorage.setItem(`table:${id}`, JSON.stringify(next))
  }

  return (
    <div className="space-y-4">
      {(toolbar || actions || toggleable.length > 1) && (
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-3">
            {toolbar}
          </div>
          <div className="ml-auto flex items-center gap-3">
            {actions}
            {toggleable.length > 1 && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="sm">
                  <Columns aria-hidden />
                  Colunas
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-auto min-w-48">
                <DropdownMenuLabel>Mostrar colunas</DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuCheckboxItem
                  checked={toggleable.every((c) => !hidden.includes(c.id))}
                  onCheckedChange={setAll}
                  onSelect={(e) => e.preventDefault()}
                  className="font-semibold text-foreground"
                >
                  Todas
                </DropdownMenuCheckboxItem>
                <DropdownMenuSeparator />
                {toggleable.map((c) => (
                  <DropdownMenuCheckboxItem
                    key={c.id}
                    checked={!hidden.includes(c.id)}
                    onCheckedChange={(on) => setVisible(c.id, on)}
                    onSelect={(e) => e.preventDefault()}
                  >
                    {c.header}
                  </DropdownMenuCheckboxItem>
                ))}
              </DropdownMenuContent>
            </DropdownMenu>
            )}
          </div>
        </div>
      )}
      <div className="rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow>
              {visible.map((c) => {
                const active = sort?.id === c.id ? sort.dir : null
                const Icon = active === 'asc' ? CaretUp : active === 'desc' ? CaretDown : CaretUpDown
                return (
                  <TableHead key={c.id} aria-sort={active === 'asc' ? 'ascending' : active === 'desc' ? 'descending' : undefined}>
                    {c.sort ? (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => cycle(c.id)}
                        className={`-mx-2 font-medium hover:text-foreground ${active ? 'text-foreground' : ''}`}
                      >
                        {c.header}
                        <Icon aria-hidden className={active ? '' : 'opacity-50'} />
                      </Button>
                    ) : (
                      c.header
                    )}
                  </TableHead>
                )
              })}
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.map((row) => (
              <TableRow key={rowKey(row)} className={rowClassName}>
                {visible.map((c) => (
                  <TableCell key={c.id} className={c.className}>
                    {c.cell(row)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
      {sorted.length > PAGE_SIZES[0] && (
        <div className="flex flex-wrap items-center justify-between gap-3 text-sm text-muted-foreground">
          <div className="flex items-center gap-2">
            <span>Linhas por página</span>
            <Select
              value={String(pageSize)}
              onValueChange={(v) => {
                setPageSize(Number(v))
                localStorage.setItem('table:pageSize', v)
                setPage(0)
              }}
            >
              <SelectTrigger aria-label="Linhas por página" size="sm">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {PAGE_SIZES.map((n) => (
                  <SelectItem key={n} value={String(n)}>
                    {n}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="flex items-center gap-3">
            <span className="tabular-nums">
              {first}–{Math.min((current + 1) * pageSize, sorted.length)} de {sorted.length}
            </span>
            <div className="flex gap-1">
              <Button variant="outline" size="icon-sm" aria-label="Página anterior" disabled={current === 0} onClick={() => setPage(current - 1)}>
                <CaretLeft aria-hidden />
              </Button>
              <Button
                variant="outline"
                size="icon-sm"
                aria-label="Próxima página"
                disabled={current >= pages - 1}
                onClick={() => setPage(current + 1)}
              >
                <CaretRight aria-hidden />
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
