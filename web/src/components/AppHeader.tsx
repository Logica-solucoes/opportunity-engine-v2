import { useMutation, useQueryClient, useSuspenseQuery } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from '@tanstack/react-router'
import { Moon, Sun, User } from 'lucide-react'
import almapDark from '@/assets/logos/almap-negativo.png'
import almapLight from '@/assets/logos/almap-positivo.png'
import dashDark from '@/assets/logos/dash-negativo.png'
import dashLight from '@/assets/logos/dash-positivo.png'
import { NativeSelect } from '@/components/NativeSelect'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { api } from '@/lib/api'
import { meQuery, roleIn } from '@/lib/auth'
import { setTheme } from '@/lib/theme'

function Logo({ light, dark, alt }: { light: string; dark: string; alt: string }) {
  return (
    <>
      <img src={light} alt={alt} className="h-8 w-auto dark:hidden" />
      <img src={dark} alt={alt} className="hidden h-8 w-auto dark:block" />
    </>
  )
}

export function AppHeader() {
  const { data: me } = useSuspenseQuery(meQuery)
  const { slug } = useParams({ strict: false })
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const logout = useMutation({
    mutationFn: () => api('/auth/logout', { method: 'POST' }),
    onSettled: () => {
      queryClient.clear()
      navigate({ to: '/login', search: { redirect: undefined } })
    },
  })

  return (
    <header className="border-b bg-card">
      <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-4 gap-y-2 px-6 py-3">
        <Link to="/" className="flex shrink-0 items-center gap-3">
          <Logo light={dashLight} dark={dashDark} alt="DASH" />
          <span className="h-6 w-px bg-border" />
          <Logo light={almapLight} dark={almapDark} alt="AlmapBBDO" />
        </Link>

        {me.workspaces.length > 0 && (
          <NativeSelect
            aria-label="Workspace"
            value={slug ?? ''}
            onChange={(e) => navigate({ to: '/w/$slug', params: { slug: e.target.value } })}
          >
            {!slug && <option value="">Escolha um workspace</option>}
            {me.workspaces.map((w) => (
              <option key={w.slug} value={w.slug}>
                {w.name}
              </option>
            ))}
          </NativeSelect>
        )}

        <nav className="flex gap-4 text-sm">
          {slug && roleIn(me, slug) === 'admin' && (
            <Link to="/w/$slug/membros" params={{ slug }} className="hover:text-primary">
              Membros
            </Link>
          )}
          {me.is_platform_admin && (
            <Link to="/admin/workspaces" className="hover:text-primary">
              Admin
            </Link>
          )}
        </nav>

        <div className="ml-auto flex items-center gap-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" aria-label="Tema">
                <Sun className="dark:hidden" />
                <Moon className="hidden dark:block" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => setTheme('light')}>Claro</DropdownMenuItem>
              <DropdownMenuItem onClick={() => setTheme('dark')}>Escuro</DropdownMenuItem>
              <DropdownMenuItem onClick={() => setTheme('system')}>Sistema</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" aria-label="Conta">
                <User />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuLabel>
                {me.name}
                <div className="text-xs font-normal text-muted-foreground">{me.email}</div>
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => navigate({ to: '/trocar-senha' })}>Trocar senha</DropdownMenuItem>
              <DropdownMenuItem onClick={() => logout.mutate()}>Sair</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </header>
  )
}
