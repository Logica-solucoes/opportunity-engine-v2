import './index.css'
import '@fontsource-variable/geist'
import '@fontsource-variable/geist-mono'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { Link, RouterProvider, createRouter } from '@tanstack/react-router'
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Compass, WarningCircle } from '@phosphor-icons/react'
import { toast } from 'sonner'
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty'
import { ApiError } from './lib/api'
import { errorMessage, meQuery } from './lib/auth'
import { applyTheme } from './lib/theme'
import { routeTree } from './routeTree.gen'
import { textLink } from '@/lib/links'

// mutations show their own failure inline or in a toast, so only failed loads get the generic one
function onApiError(error: unknown, { fromQuery = false, skipAuthRedirect = false } = {}) {
  const href = router.state.location.href
  if (error instanceof ApiError && error.status === 401 && !skipAuthRedirect && error.detail === 'not_authenticated') {
    queryClient.clear()
    router.navigate({ to: '/login', search: { redirect: href } })
  } else if (error instanceof ApiError && error.detail === 'password_change_required') {
    router.navigate({ to: '/trocar-senha', search: { redirect: href } })
  } else if (fromQuery && error instanceof ApiError && (error.status === 403 || error.status === 404)) {
    // /me is cached forever: access may have changed since (removed from the workspace, demoted)
    queryClient.invalidateQueries({ queryKey: meQuery.queryKey })
  } else if (fromQuery && !(error instanceof ApiError && error.status < 500)) {
    const message = errorMessage(error)
    toast.error(message, { id: message })
  }
}

const queryClient = new QueryClient({
  queryCache: new QueryCache({
    onError: (e, query) => onApiError(e, { fromQuery: true, skipAuthRedirect: Boolean(query.meta?.skipAuthRedirect) }),
  }),
  mutationCache: new MutationCache({ onError: (e) => onApiError(e) }),
  defaultOptions: {
    queries: { retry: (count, e) => !(e instanceof ApiError && e.status < 500) && count < 2 },
  },
})

const router = createRouter({
  routeTree,
  context: { queryClient },
  defaultNotFoundComponent: () => (
    <Empty className="mx-auto mt-10 max-w-3xl border">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <Compass />
        </EmptyMedia>
        <EmptyTitle>Página não encontrada</EmptyTitle>
        <EmptyDescription>
          <Link to="/" className={textLink}>
            Voltar ao início
          </Link>
        </EmptyDescription>
      </EmptyHeader>
    </Empty>
  ),
  defaultErrorComponent: () => (
    <Empty className="mx-auto mt-10 max-w-3xl border">
      <EmptyHeader>
        <EmptyMedia variant="icon">
          <WarningCircle />
        </EmptyMedia>
        <EmptyTitle>Algo deu errado</EmptyTitle>
        <EmptyDescription>
          <button type="button" onClick={() => window.location.reload()} className={textLink}>
            Recarregar a página
          </button>
        </EmptyDescription>
      </EmptyHeader>
    </Empty>
  ),
})

declare module '@tanstack/react-router' {
  interface Register {
    router: typeof router
  }
}

applyTheme()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </StrictMode>,
)
