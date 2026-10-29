import { useMutation, useQueryClient } from '@tanstack/react-query'
import { type FormEvent, useState } from 'react'
import { NativeSelect } from '@/components/NativeSelect'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { api } from '@/lib/api'
import { errorMessage, meQuery } from '@/lib/auth'
import { fieldErrors } from '@/lib/params'

export type GoogleConfig = {
  ads: { dataset: string; customer_ids: string[] }
  ga4: { dataset: string; event: string; metric: 'count' | 'revenue' }
}

export type AdminWorkspace = { id: number; name: string; slug: string; created_at: string; google: GoogleConfig | null }

// same rules as GoogleConfig in api/google_import.py; the server checks again
const DATASET = '[a-z][a-z0-9\\-]{4,28}[a-z0-9]\\.[A-Za-z0-9_]{1,1024}'
const DATASET_HINT = 'projeto.dataset, como meu-projeto.google_ads'

// the server's pydantic error is per field; the hint says what the field needs
const HINTS: Record<string, string> = {
  'ads.dataset': `Use ${DATASET_HINT}.`,
  'ads.customer_ids': 'Cada customer id tem 10 dígitos, sem repetir.',
  'ga4.dataset': 'Use projeto.dataset, como meu-projeto.analytics_123456.',
  'ga4.event': 'Nome de evento do GA4: letras, números e _, começando por letra.',
}

const splitIds = (text: string) => text.split(/[\s,;]+/).map((id) => id.replace(/-/g, '')).filter(Boolean)

type Props = { workspace: AdminWorkspace | null; onClose: () => void }

export function GoogleConnectorDialog({ workspace, onClose }: Props) {
  return (
    <Dialog open={workspace !== null} onOpenChange={(open) => !open && onClose()}>
      {/* keyed: each workspace opens with its own saved values */}
      {workspace && <ConnectorForm key={workspace.id} workspace={workspace} onClose={onClose} />}
    </Dialog>
  )
}

function ConnectorForm({ workspace, onClose }: { workspace: AdminWorkspace; onClose: () => void }) {
  const queryClient = useQueryClient()
  const google = workspace.google
  const [confirmRemove, setConfirmRemove] = useState(false)
  const done = () => {
    queryClient.invalidateQueries({ queryKey: ['admin', 'workspaces'] })
    queryClient.invalidateQueries({ queryKey: meQuery.queryKey })
    onClose()
  }
  const save = useMutation({
    mutationFn: (body: GoogleConfig) => api(`/admin/workspaces/${workspace.id}/google`, { method: 'PUT', body }),
    onSuccess: done,
  })
  const remove = useMutation({
    mutationFn: () => api<void>(`/admin/workspaces/${workspace.id}/google`, { method: 'DELETE' }),
    onSuccess: done,
  })
  const errors = fieldErrors(save.error)
  const hint = (path: string) =>
    errors && Object.keys(errors).some((k) => k.startsWith(path)) ? (
      <p className="text-sm text-destructive">{HINTS[path]}</p>
    ) : null

  function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault()
    const form = new FormData(e.currentTarget)
    const text = (name: string) => String(form.get(name)).trim()
    save.mutate({
      ads: { dataset: text('ads.dataset'), customer_ids: splitIds(text('ads.customer_ids')) },
      ga4: { dataset: text('ga4.dataset'), event: text('ga4.event'), metric: text('ga4.metric') as 'count' | 'revenue' },
    })
  }

  return (
    <DialogContent>
      <DialogHeader>
        <DialogTitle>Conector Google · {workspace.name}</DialogTitle>
        <DialogDescription>
          Datasets do BigQuery que a service account da plataforma lê: o do Data Transfer do Google Ads e o do export
          do GA4.
        </DialogDescription>
      </DialogHeader>
      <form id="google-connector" onSubmit={submit} className="space-y-4">
        <fieldset className="space-y-3">
          <legend className="text-sm font-medium">Google Ads</legend>
          <div className="space-y-1">
            <Label htmlFor="ads.dataset">Dataset do Google Ads</Label>
            <Input
              id="ads.dataset"
              name="ads.dataset"
              required
              pattern={DATASET}
              title={DATASET_HINT}
              defaultValue={google?.ads.dataset}
            />
            {hint('ads.dataset')}
          </div>
          <div className="space-y-1">
            <Label htmlFor="ads.customer_ids">Customer ids</Label>
            <Input
              id="ads.customer_ids"
              name="ads.customer_ids"
              required
              placeholder="123-456-7890, 987-654-3210"
              defaultValue={google?.ads.customer_ids.join(', ')}
            />
            <p className="text-xs text-muted-foreground">Separados por vírgula; o spend das contas é somado.</p>
            {hint('ads.customer_ids')}
          </div>
        </fieldset>
        <fieldset className="space-y-3">
          <legend className="text-sm font-medium">GA4</legend>
          <div className="space-y-1">
            <Label htmlFor="ga4.dataset">Dataset do GA4</Label>
            <Input
              id="ga4.dataset"
              name="ga4.dataset"
              required
              pattern={DATASET}
              title={DATASET_HINT}
              defaultValue={google?.ga4.dataset}
            />
            {hint('ga4.dataset')}
          </div>
          <div className="flex flex-wrap gap-4">
            <div className="space-y-1">
              <Label htmlFor="ga4.event">Evento do KPI</Label>
              <Input
                id="ga4.event"
                name="ga4.event"
                required
                pattern="[A-Za-z][A-Za-z0-9_]{0,39}"
                placeholder="purchase"
                defaultValue={google?.ga4.event}
              />
              {hint('ga4.event')}
            </div>
            <div className="space-y-1">
              <Label htmlFor="ga4.metric">Métrica</Label>
              <NativeSelect id="ga4.metric" name="ga4.metric" defaultValue={google?.ga4.metric ?? 'count'}>
                <option value="count">Contagem de eventos</option>
                <option value="revenue">Receita (purchase_revenue)</option>
              </NativeSelect>
            </div>
          </div>
        </fieldset>
      </form>
      {(save.isError && !errors) || remove.isError ? (
        <p role="alert" className="text-sm text-destructive">
          {errorMessage(save.error ?? remove.error)}
        </p>
      ) : null}
      <DialogFooter className="sm:justify-between">
        {google &&
          (confirmRemove ? (
            <div className="flex items-center gap-2">
              <span className="text-sm">Remover o conector?</span>
              <Button variant="destructive" size="sm" disabled={remove.isPending} onClick={() => remove.mutate()}>
                Remover
              </Button>
              <Button variant="ghost" size="sm" onClick={() => setConfirmRemove(false)}>
                Cancelar
              </Button>
            </div>
          ) : (
            <Button variant="outline" onClick={() => setConfirmRemove(true)}>
              Remover conector
            </Button>
          ))}
        <Button type="submit" form="google-connector" disabled={save.isPending}>
          Salvar
        </Button>
      </DialogFooter>
    </DialogContent>
  )
}
