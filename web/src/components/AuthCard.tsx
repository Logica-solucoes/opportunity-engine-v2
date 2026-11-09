import type { ReactNode } from 'react'
import almapDark from '@/assets/logos/almap-negativo.png'
import almapLight from '@/assets/logos/almap-positivo.png'
import dashDark from '@/assets/logos/dash-negativo.png'
import dashLight from '@/assets/logos/dash-positivo.png'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'

function Logo({ light, dark, alt }: { light: string; dark: string; alt: string }) {
  return (
    <>
      <img src={light} alt={alt} translate="no" className="h-9 w-auto dark:hidden" />
      <img src={dark} alt={alt} translate="no" className="hidden h-9 w-auto dark:block" />
    </>
  )
}

export function AuthCard({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-6 p-4">
      <div className="flex items-center gap-3">
        <Logo light={dashLight} dark={dashDark} alt="DASH" />
        <span className="h-6 w-px bg-border" />
        <Logo light={almapLight} dark={almapDark} alt="AlmapBBDO" />
      </div>
      <Card className="w-full max-w-sm">
        <CardHeader>
          <CardTitle>
            <h1 className="text-base font-semibold text-balance">{title}</h1>
          </CardTitle>
          {description && <CardDescription>{description}</CardDescription>}
        </CardHeader>
        <CardContent>{children}</CardContent>
      </Card>
    </main>
  )
}
