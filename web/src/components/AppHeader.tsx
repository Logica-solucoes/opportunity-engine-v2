import { useQuery, useSuspenseQuery } from '@tanstack/react-query'
import { useEffect } from 'react'
import { Link, useNavigate, useParams, useRouterState } from '@tanstack/react-router'
import { ClockCounterClockwise, Desktop, Flask, GearSix, Key, Moon, SignOut, Sun, User, UsersThree } from '@phosphor-icons/react'
import almapDark from '@/assets/logos/almap-negativo.png'
import almapLight from '@/assets/logos/almap-positivo.png'
import dashDark from '@/assets/logos/dash-negativo.png'
import dashLight from '@/assets/logos/dash-positivo.png'
import { CommandMenu } from '@/components/CommandMenu'
import { Badge } from '@/components/ui/badge'
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
import { isActive, workspaceRunsQuery } from '@/lib/runs'
import { cn } from '@/lib/utils'
import { setTheme } from '@/lib/theme'

const LAST_WORKSPACE = 'lastWorkspace'

const divider = <span aria-hidden className="hidden h-6 w-px shrink-0 bg-border xl:block" />

const navLink = (active: boolean) =>
  cn(
    'flex shrink-0 items-center gap-1.5 border-b-2 px-2.5 py-2 whitespace-nowrap transition-colors hover:text-foreground xl:px-3 xl:py-0',
    active ? 'border-primary font-medium text-foreground' : 'border-transparent text-muted-foreground',
  )

function Logo({ light, dark, alt }: { light: string; dark: string; alt: string }) {
  return (
    <>
      <img src={light} alt={alt} className="h-5.5 w-auto sm:h-7 dark:hidden" />
      <img src={dark} alt={alt} className="hidden h-5.5 w-auto sm:h-7 dark:block" />
    </>
  )
}

// polls only while something runs (workspaceRunsQuery); the link goes straight to the run being followed
function RunningBadge({ slug }: { slug: string }) {
  const { data: runs } = useQuery(workspaceRunsQuery(slug))
  const active = runs?.filter((r) => isActive(r.status)) ?? []
  if (active.length === 0) return null
  return (
    <Link to="/w/$slug/execucoes/$runId" params={{ slug, runId: String(active[0].id) }} aria-label="Acompanhar execução em andamento">
      <Badge variant="info" className="gap-1.5">
        <span aria-hidden className="size-1.5 animate-pulse rounded-full bg-current motion-reduce:animate-none" />
        {active.length === 1 ? '1 rodando' : `${active.length} rodando`}
      </Badge>
    </Link>
  )
}

export function AppHeader() {
  const { data: me } = useSuspenseQuery(meQuery)
  const { slug: urlSlug } = useParams({ strict: false })
  // outside /w/$slug (admin, home) the tabs keep pointing at the last workspace instead of vanishing
  useEffect(() => {
    if (urlSlug) localStorage.setItem(LAST_WORKSPACE, urlSlug)
  }, [urlSlug])
  const saved = localStorage.getItem(LAST_WORKSPACE)
  const slug = urlSlug ?? (me.workspaces.some((w) => w.slug === saved) ? saved! : me.workspaces[0]?.slug)
  const navigate = useNavigate()
  const logout = useLogout()
  const pathname = useRouterState({ select: (s) => s.location.pathname })
  const role = slug ? roleIn(me, slug) : undefined
  const base = `/w/${slug}`

  return (
    <header className="z-30 border-b bg-card xl:sticky xl:top-0 print:hidden">
      {/* below xl: logo + actions, then workspace, then scrollable tabs; xl: one row */}
      <div className="mx-auto flex max-w-460 flex-wrap items-center gap-x-3 gap-y-2 px-4 pt-2 sm:gap-x-4 sm:px-12 xl:h-14 xl:flex-nowrap xl:px-14 xl:py-0">
        <Link to="/" className="flex shrink-0 items-center gap-2 sm:gap-3">
          <Logo light={dashLight} dark={dashDark} alt="DASH" />
          <span className="h-6 w-px bg-border" />
          <Logo light={almapLight} dark={almapDark} alt="AlmapBBDO" />
        </Link>

        {divider}

        {me.workspaces.length > 0 && (
          <Select value={slug ?? ''} onValueChange={(s) => navigate({ to: '/w/$slug', params: { slug: s } })}>
            <SelectTrigger aria-label="Workspace" size="sm" className="order-3 w-full min-w-40 sm:w-64 md:order-1 md:w-auto xl:order-none">
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

        {me.workspaces.length > 0 && divider}

        <nav className="order-4 -mx-4 flex w-[calc(100%+2rem)] gap-1 self-stretch overflow-x-auto px-2 text-sm [scrollbar-width:none] sm:mx-0 sm:w-full sm:px-0 xl:order-none xl:w-auto xl:overflow-visible max-sm:[&_svg]:hidden xl:max-2xl:[&_svg]:hidden">
          {slug && role && role !== 'viewer' && (
            <Link to="/w/$slug" params={{ slug }} className={navLink(pathname === base || pathname.startsWith(`${base}/simulacoes`))}>
              <Flask aria-hidden />
              Simulações
            </Link>
          )}
          {slug && role && (
            <Link to="/w/$slug/execucoes" params={{ slug }} className={navLink(pathname.startsWith(`${base}/execucoes`))}>
              <ClockCounterClockwise aria-hidden />
              Execuções
            </Link>
          )}
          {slug && role === 'admin' && (
            <Link to="/w/$slug/membros" params={{ slug }} className={navLink(pathname.startsWith(`${base}/membros`))}>
              <UsersThree aria-hidden />
              Membros
            </Link>
          )}
          {me.is_platform_admin && (
            <Link to="/admin/workspaces" className={navLink(pathname.startsWith('/admin'))}>
              <GearSix aria-hidden />
              Admin
            </Link>
          )}
        </nav>

        <div className="order-2 ml-auto flex items-center gap-1 sm:gap-2 xl:order-none">
          {slug && role && <RunningBadge slug={slug} />}
          <CommandMenu />
          {divider}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" aria-label="Tema">
                <Sun className="dark:hidden" />
                <Moon className="hidden dark:block" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => setTheme('light')}>
                <Sun aria-hidden />
                Claro
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => setTheme('dark')}>
                <Moon aria-hidden />
                Escuro
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => setTheme('system')}>
                <Desktop aria-hidden />
                Sistema
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" aria-label="Conta">
                <User />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-auto min-w-60">
              <DropdownMenuLabel>
                {me.name}
                <div className="font-normal break-all text-muted-foreground">{me.email}</div>
              </DropdownMenuLabel>
              <DropdownMenuSeparator />
              <DropdownMenuItem onClick={() => navigate({ to: '/trocar-senha', search: { redirect: undefined } })}>
                <Key aria-hidden />
                Trocar senha
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => logout.mutate()}>
                <SignOut aria-hidden />
                Sair
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </header>
  )
}
