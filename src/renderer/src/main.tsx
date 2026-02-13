import './assets/main.css'

import * as Sentry from '@sentry/react'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { logAppOpened } from './lib/analytics'

Sentry.init({
  dsn: 'https://c27473b596f92b07557b89836e8e0941@o4510700679593984.ingest.us.sentry.io/4510875528921088',
  release: 'cleanse@1.5.2'
})

logAppOpened()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Sentry.ErrorBoundary fallback={<div className="p-8 text-red-400">Something went wrong. Please restart the app.</div>}>
      <App />
    </Sentry.ErrorBoundary>
  </StrictMode>
)
