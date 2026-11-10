import { useQuery, useSuspenseQuery } from '@tanstack/react-query'
import { useNavigate, useParams } from '@tanstack/react-router'
import { Buildings, Flask, ListChecks, MagnifyingGlass, UsersThree } from '@phosphor-icons/react'
import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import {
  Command,
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandShortcut,
} from '@/components/ui/command'
import { meQuery, roleIn } from '@/lib/auth'
import { STATUS_LABELS, workspaceRunsQuery } from '@/lib/runs'
import { simulationsQuery } from '@/lib/simulations'

export function CommandMenu() {
  const { data: me } = useSuspenseQuery(meQuery)
  const { slug } = useParams({ strict: false })
  const navigate = useNavigate()
  const [open, setOpen] = useState(false)
  const role = slug ? roleIn(me, slug) : undefined

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key.toLowerCase() === 'k' && (e.metaKey || e.ctrlKey)) {
        e.preventDefault()
        setOpen((o) => !o)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // the simulations list is analyst+ in the api: a viewer never asks for it
  const sims = useQuery({ ...simulationsQuery(slug ?? ''), enabled: open && !!slug && role !== undefined && role !== 'viewer' })
  const runs = useQuery({ ...workspaceRunsQuery(slug ?? ''), enabled: open && !!slug && role !== undefined })

  const go = (fn: () => void) => () => {
    setOpen(false)
    fn()
  }

  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)} aria-label="Buscar" className="text-muted-foreground">
        <MagnifyingGlass aria-hidden />
        <span className="hidden lg:inline">Buscar…</span>
        <kbd className="hidden rounded border bg-muted px-1 font-mono text-[0.7rem] lg:inline">Ctrl + K</kbd>
      </Button>
      <CommandDialog open={open} onOpenChange={setOpen} title="Buscar" description="Salte para uma simulação, execução ou workspace." className="sm:max-w-2xl">
        <Command>
          <CommandInput placeholder="Buscar simulação, execução ou workspace…" />
          <CommandList>
            <CommandEmpty>Nada encontrado.</CommandEmpty>
            {slug && sims.data && sims.data.length > 0 && (
              <CommandGroup heading="Simulações">
                {sims.data.map((s) => (
                  <CommandItem
                    key={s.id}
                    value={`simulação ${s.name} ${s.id}`}
                    onSelect={go(() => navigate({ to: '/w/$slug/simulacoes/$id', params: { slug, id: String(s.id) } }))}
                  >
                    <Flask aria-hidden />
                    {s.name}
                  </CommandItem>
                ))}
              </CommandGroup>
            )}
            {slug && runs.data && runs.data.length > 0 && (
              <CommandGroup heading="Execuções">
                {runs.data.slice(0, 50).map((r) => (
                  <CommandItem
                    key={r.id}
                    value={`execução ${r.id} ${r.simulation.name} ${STATUS_LABELS[r.status]}`}
                    onSelect={go(() => navigate({ to: '/w/$slug/execucoes/$runId', params: { slug, runId: String(r.id) } }))}
                  >
                    <ListChecks aria-hidden />
                    <span>
                      #{r.id} · {r.simulation.name}
                    </span>
                    <CommandShortcut>{STATUS_LABELS[r.status]}</CommandShortcut>
                  </CommandItem>
                ))}
              </CommandGroup>
            )}
            <CommandGroup heading="Workspaces">
              {me.workspaces.map((w) => (
                <CommandItem
                  key={w.slug}
                  value={`workspace ${w.name}`}
                  onSelect={go(() => navigate({ to: '/w/$slug', params: { slug: w.slug } }))}
                >
                  <Buildings aria-hidden />
                  {w.name}
                </CommandItem>
              ))}
            </CommandGroup>
            {me.is_platform_admin && (
              <CommandGroup heading="Ir para">
                <CommandItem value="admin workspaces" onSelect={go(() => navigate({ to: '/admin/workspaces' }))}>
                  <UsersThree aria-hidden />
                  Administração
                </CommandItem>
              </CommandGroup>
            )}
          </CommandList>
        </Command>
      </CommandDialog>
    </>
  )
}
