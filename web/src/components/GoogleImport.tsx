import { useMutation } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import { errorMessage } from '@/lib/auth'
import type { Simulation } from '@/lib/simulations'

// YYYY-MM-DD in the browser's time zone (sv-SE formats dates that way)
const daysAgo = (n: number) => {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return d.toLocaleDateString('sv-SE')
}

type Props = { slug: string; sim: Simulation; busy: boolean; onSaved: (sim: Simulation) => void }

export function GoogleImport({ slug, sim, busy, onSaved }: Props) {
  const [start, setStart] = useState(() => daysAgo(730))
  const [end, setEnd] = useState(() => daysAgo(1))
  const run = useMutation({
    mutationFn: () =>
      api<Simulation>(`/w/${slug}/simulations/${sim.id}/google-import`, { method: 'POST', body: { start, end } }),
    onSuccess: onSaved,
  })

  function submit(e: FormEvent) {
    e.preventDefault()
    run.mutate()
  }

  return (
    <form onSubmit={submit} className="space-y-2 rounded-md border p-4">
      <p className="text-sm">
        <span className="font-medium">Ou importe do Google:</span> investimento do Google Ads e KPI do GA4 do
        período, no lugar dos arquivos de investimento e performance.
      </p>
      <div className="flex flex-wrap items-end gap-3">
        <div className="space-y-1">
          <Label htmlFor="google-start">Início</Label>
          <Input
            id="google-start"
            type="date"
            className="w-40"
            required
            max={end}
            value={start}
            onChange={(e) => setStart(e.target.value)}
          />
        </div>
        <div className="space-y-1">
          <Label htmlFor="google-end">Fim</Label>
          <Input
            id="google-end"
            type="date"
            className="w-40"
            required
            min={start}
            max={daysAgo(0)}
            value={end}
            onChange={(e) => setEnd(e.target.value)}
          />
        </div>
        <Button type="submit" disabled={busy}>
          {run.isPending ? 'Consultando o BigQuery…' : 'Importar do Google'}
        </Button>
      </div>
      {run.isError && (
        <p role="alert" className="text-sm text-destructive">
          {errorMessage(run.error)}
        </p>
      )}
    </form>
  )
}
