import { useSuspenseQuery } from '@tanstack/react-query'
import { Link, type LinkProps } from '@tanstack/react-router'
import type { Icon } from '@phosphor-icons/react'
import { Fragment, type ReactNode } from 'react'
import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb'
import { meQuery } from '@/lib/auth'

export type Crumb = { label: string; link?: { to: string; params?: Record<string, string> } }

// trail (workspace first when `slug` is given) + title with an icon tile; `children` sit beside the title (badge, meta)
export function PageHeader({
  slug,
  trail,
  title,
  icon: TitleIcon,
  hideTitle,
  children,
}: {
  slug?: string
  trail: Crumb[]
  title: string
  icon: Icon
  // the last crumb already says it: keep the h1 for screen readers only
  hideTitle?: boolean
  children?: ReactNode
}) {
  const { data: me } = useSuspenseQuery(meQuery)
  const workspace = slug ? me.workspaces.find((w) => w.slug === slug) : undefined
  const crumbs: Crumb[] = [
    ...(slug ? [{ label: 'Workspaces', link: { to: '/' } }, { label: workspace?.name ?? slug, link: { to: '/w/$slug', params: { slug } } }] : []),
    ...trail,
  ]

  return (
    <header className="space-y-3 print:hidden">
      <Breadcrumb>
        <BreadcrumbList>
          {crumbs.map((c, i) => (
            <Fragment key={`${i}-${c.label}`}>
              {i > 0 && <BreadcrumbSeparator />}
              <BreadcrumbItem>
                {c.link && i < crumbs.length - 1 ? (
                  <BreadcrumbLink asChild>
                    <Link {...(c.link as LinkProps)}>{c.label}</Link>
                  </BreadcrumbLink>
                ) : (
                  <BreadcrumbPage>{c.label}</BreadcrumbPage>
                )}
              </BreadcrumbItem>
            </Fragment>
          ))}
        </BreadcrumbList>
      </Breadcrumb>
      {hideTitle ? (
        <h1 className="sr-only">{title}</h1>
      ) : (
        <div className="flex flex-wrap items-center gap-x-2.5 gap-y-1">
          <TitleIcon aria-hidden className="size-5 shrink-0 text-primary" />
          <h1 className="text-xl font-semibold text-balance">{title}</h1>
          {children}
        </div>
      )}
    </header>
  )
}
