import './index.css'
import '@fontsource-variable/inter'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { Link, RouterProvider, createRouter } from '@tanstack/react-router'
import { MutationCache, QueryCache, QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ApiError } from './lib/api'
import { applyTheme } from './lib/theme'
import { routeTree } from './routeTree.gen'

function onApiError(error: unknown, skipAuthRedirect = false) {
  if (!(error instanceof ApiError)) return
  if (error.status === 401 && !skipAuthRedirect && error.detail === 'not_authenticated') {
    queryClient.clear()
    router.navigate({ to: '/login', search: { redirect: router.state.location.href } })
  } else if (error.detail === 'password_change_required') {
    router.navigate({ to: '/trocar-senha' })
  } else if (error.status >= 500) {
    toast.error('Erro no servidor. Tente de novo.')
  }
}

const queryClient = new QueryClient({
  queryCache: new QueryCache({ onError: (e, query) => onApiError(e, Boolean(query.meta?.skipAuthRedirect)) }),
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
