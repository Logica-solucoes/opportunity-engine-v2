import { useSuspenseQuery } from '@tanstack/react-query'
import { Link, useNavigate, useParams } from '@tanstack/react-router'
import { Moon, Sun, User } from '@phosphor-icons/react'
import almapDark from '@/assets/logos/almap-negativo.png'
import almapLight from '@/assets/logos/almap-positivo.png'
import dashDark from '@/assets/logos/dash-negativo.png'
import dashLight from '@/assets/logos/dash-positivo.png'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { meQuery, roleIn, useLogout } from '@/lib/auth'
import { setTheme } from '@/lib/theme'

// data-status (set by the router) beats the base color; activeProps className would lose to text-muted-foreground
const navLink =
  '-mb-3 border-b-2 border-transparent pb-3 text-muted-foreground transition-colors hover:text-foreground data-[status=active]:border-primary data-[status=active]:font-medium data-[status=active]:text-foreground'

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
  const logout = useLogout()

  return (
    <header className="border-b bg-card print:hidden">
      <div className="mx-auto flex max-w-5xl flex-wrap items-center gap-x-4 gap-y-2 px-6 py-3">
        <Link to="/" className="flex shrink-0 items-center gap-3">
          <Logo light={dashLight} dark={dashDark} alt="DASH" />
          <span className="h-6 w-px bg-border" />
          <Logo light={almapLight} dark={almapDark} alt="AlmapBBDO" />
        </Link>

        {me.workspaces.length > 0 && (
          <Select value={slug ?? ''} onValueChange={(s) => navigate({ to: '/w/$slug', params: { slug: s } })}>
            <SelectTrigger aria-label="Workspace" size="sm" className="min-w-40">
              <SelectValue placeholder="Escolha um workspace" />
            </SelectTrigger>
            <SelectContent>
              {me.workspaces.map((w) => (
                <SelectItem key={w.slug} value={w.slug}>
                  {w.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}

        <nav className="flex gap-4 text-sm">
          {slug && roleIn(me, slug) === 'admin' && (
            <Link to="/w/$slug/membros" params={{ slug }} className={navLink}>
              Membros
            </Link>
          )}
          {me.is_platform_admin && (
            <Link to="/admin/workspaces" className={navLink}>
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
              <DropdownMenuItem onClick={() => navigate({ to: '/trocar-senha', search: { redirect: undefined } })}>
                Trocar senha
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => logout.mutate()}>Sair</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </header>
  )
}
