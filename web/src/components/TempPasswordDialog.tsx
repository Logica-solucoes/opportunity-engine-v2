import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'

type Props = { password: string | null; email: string; onClose: () => void }

export function TempPasswordDialog({ password, email, onClose }: Props) {
  async function copy() {
    await navigator.clipboard.writeText(password!)
    toast.success('Senha copiada.')
  }

  return (
    <Dialog open={password !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Senha temporária</DialogTitle>
          <DialogDescription>
            Envie para {email} por um canal seguro. Ela não será mostrada de novo e precisa ser trocada no primeiro
            login.
          </DialogDescription>
        </DialogHeader>
        <code data-testid="temp-password" className="block rounded-md bg-muted p-3 text-center font-mono text-lg">
          {password}
        </code>
        <DialogFooter>
          <Button variant="outline" onClick={copy}>
            Copiar
          </Button>
          <Button onClick={onClose}>Fechar</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
