import { FileSpreadsheet } from 'lucide-react'
import type { DragEvent } from 'react'
import { cn } from '@/lib/utils'

// drag & drop area adapted from blocks.so file-upload-04, minus its fake progress bar
export function FileDrop({
  id,
  label,
  disabled,
  onFile,
}: {
  id: string
  label: string
  disabled?: boolean
  onFile: (file: File) => void
}) {
  function drop(e: DragEvent) {
    e.preventDefault()
    const file = e.dataTransfer.files[0]
    if (file && !disabled) onFile(file)
  }

  return (
    <div
      onDragOver={(e) => e.preventDefault()}
      onDrop={drop}
      className={cn(
        // the input is sr-only, so the ring is the only sign of keyboard focus
        'flex flex-col items-center gap-2 rounded-md border border-dashed border-input px-4 py-6 text-center text-sm text-muted-foreground has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring',
        disabled && 'opacity-50',
      )}
    >
      <FileSpreadsheet aria-hidden className="size-8" />
      <p>
        Arraste o CSV ou{' '}
        <label htmlFor={id} className="cursor-pointer font-medium text-primary hover:underline">
          escolha o arquivo
        </label>
      </p>
      <p className="text-xs">Até 30 MB</p>
      <input
        id={id}
        type="file"
        accept=".csv"
        aria-label={label}
        className="sr-only"
        disabled={disabled}
        onChange={(e) => {
          const file = e.target.files?.[0]
          // lets the same file be picked again after a failed upload
          e.target.value = ''
          if (file) onFile(file)
        }}
      />
    </div>
  )
}
