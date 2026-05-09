import './assets/main.css'

import * as Sentry from '@sentry/react'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { logAppOpened } from './lib/analytics'
import pkg from '../../../package.json'

// IPC errors from the main process are re-thrown here (e.g. "File no longer
// exists on disk" rejections from invoke()), so the same noise shows up in the
// renderer. Drop them before sending to Sentry — keep filter in sync with main.
const USER_FACING_ERROR_PATTERNS = [
  /File no longer exists on disk/i,
  /File not found:/i
]

Sentry.init({
  dsn: 'https://c27473b596f92b07557b89836e8e0941@o4510700679593984.ingest.us.sentry.io/4510875528921088',
  release: `cleanse@${pkg.version}`,
  beforeSend(event) {
    const msg = event.exception?.values?.[0]?.value ?? event.message
    if (msg && USER_FACING_ERROR_PATTERNS.some((re) => re.test(msg))) return null
    return event
  }
})

logAppOpened()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <Sentry.ErrorBoundary fallback={<div className="p-8 text-red-400">Something went wrong. Please restart the app.</div>}>
      <App />
    </Sentry.ErrorBoundary>
  </StrictMode>
)
