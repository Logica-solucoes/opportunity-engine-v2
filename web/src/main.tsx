import './index.css'
import '@fontsource-variable/inter'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { Link, RouterProvider, createRouter } from '@tanstack/react-router'
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ApiError } from './lib/api'
import { errorMessage } from './lib/auth'
import { applyTheme } from './lib/theme'
import { routeTree } from './routeTree.gen'

// mutations show their own failure inline or in a toast, so only failed loads get the generic one
function onApiError(error: unknown, { fromQuery = false, skipAuthRedirect = false } = {}) {
  const href = router.state.location.href
  if (error instanceof ApiError && error.status === 401 && !skipAuthRedirect && error.detail === 'not_authenticated') {
    queryClient.clear()
    router.navigate({ to: '/login', search: { redirect: href } })
  } else if (error instanceof ApiError && error.detail === 'password_change_required') {
    router.navigate({ to: '/trocar-senha', search: { redirect: href } })
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
    <div className="p-10 text-center">
      <p className="mb-4 text-lg">Página não encontrada.</p>
      <Link to="/" className="text-primary underline">
        Voltar ao início
      </Link>
    </div>
  ),
  defaultErrorComponent: () => (
    <div className="p-10 text-center">
      <p className="mb-4 text-lg">Algo deu errado.</p>
      <button type="button" onClick={() => window.location.reload()} className="text-primary underline">
        Recarregar a página
      </button>
    </div>
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
