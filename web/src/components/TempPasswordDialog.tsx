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
    try {
      await navigator.clipboard.writeText(password!)
      toast.success('Senha copiada.')
    } catch {
      toast.error('Não foi possível copiar. Selecione a senha e copie.')
    }
  }

  return (
    <Dialog open={password !== null} onOpenChange={(open) => !open && onClose()}>
      {/* the password is shown once: only the explicit button closes it */}
      <DialogContent
        showCloseButton={false}
        onInteractOutside={(e) => e.preventDefault()}
        onEscapeKeyDown={(e) => e.preventDefault()}
      >
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
