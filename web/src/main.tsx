import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { Toaster } from 'sonner'

import App from './App.tsx'
import './index.css'

const consultas = new QueryClient({
  defaultOptions: { queries: { staleTime: 10_000, refetchOnWindowFocus: true, retry: 1 } },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={consultas}>
      <BrowserRouter>
        <App />
        <Toaster richColors position="bottom-right" />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
