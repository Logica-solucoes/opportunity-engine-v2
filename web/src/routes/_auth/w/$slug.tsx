import { Outlet, createFileRoute, notFound } from '@tanstack/react-router'

export const Route = createFileRoute('/_auth/w/$slug')({
  beforeLoad: ({ context: { me }, params }) => {
    // same answer as the api: another workspace looks like one that doesn't exist
    if (!me.workspaces.some((w) => w.slug === params.slug)) throw notFound()
  },
  component: Outlet,
})
