import { Download, Printer } from 'lucide-react'
import { Button } from '@/components/ui/button'

// a plain link: the browser downloads with the session cookie and the API's file name, no fetch or Blob
export function ExportBar({ links }: { links: [label: string, href: string][] }) {
  return (
    <div className="flex flex-wrap justify-end gap-2 print:hidden">
      {links.map(([label, href]) => (
        <Button key={label} asChild variant="outline" size="sm">
          <a href={href} download>
            <Download />
            {label}
          </a>
        </Button>
      ))}
      <Button variant="outline" size="sm" onClick={() => window.print()}>
        <Printer />
        Imprimir / PDF
      </Button>
    </div>
  )
}
