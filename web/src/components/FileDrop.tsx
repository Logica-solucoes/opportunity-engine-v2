import { FileCsv, UploadSimple } from '@phosphor-icons/react'
import { type DragEvent, useRef, useState } from 'react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

// adapted from blocks.so file-upload-04: the whole zone opens the picker, not only a link inside it
export function FileDrop({
  id,
  label,
  disabled,
  uploading,
  hasFile,
  onFile,
}: {
  id: string
  label: string
  disabled?: boolean
  uploading?: boolean
  hasFile?: boolean
  onFile: (file: File) => void
}) {
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)

  function drop(e: DragEvent) {
    e.preventDefault()
    setOver(false)
    const file = e.dataTransfer.files[0]
    if (file && !disabled) onFile(file)
  }

  return (
    <div
      onClick={() => !disabled && input.current?.click()}
      onDragOver={(e) => {
        e.preventDefault()
        if (!disabled) setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={drop}
      className={cn(
        'flex cursor-pointer flex-col items-center gap-2 rounded-lg border border-dashed border-input px-4 text-center text-sm text-muted-foreground transition-colors hover:bg-muted/50',
        hasFile ? 'py-4' : 'py-8',
        over && 'border-primary bg-primary/5',
        disabled && 'pointer-events-none opacity-50',
      )}
    >
      {!hasFile && <FileCsv aria-hidden className="size-8" />}
      <p>{over ? 'Solte o arquivo aqui' : hasFile ? 'Arraste um CSV para substituir' : 'Arraste o CSV aqui'}</p>
      <Button type="button" variant="outline" size="sm" disabled={disabled}>
        <UploadSimple aria-hidden />
        {uploading ? 'Enviando…' : hasFile ? 'Substituir arquivo' : 'Escolher arquivo'}
      </Button>
      {!hasFile && <p className="text-xs">CSV de até 30 MB</p>}
      <input
        ref={input}
        id={id}
        type="file"
        accept=".csv"
        aria-label={label}
        tabIndex={-1}
        className="sr-only"
        disabled={disabled}
        // the zone's click handler already opens the picker for clicks on the button
        onClick={(e) => e.stopPropagation()}
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
