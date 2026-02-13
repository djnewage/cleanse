// GA4 Measurement Protocol — bypasses gtag.js which can't send events from
// the app:// protocol (cookies are unavailable so gtag.js silently drops everything).

const MEASUREMENT_ID = import.meta.env.VITE_FIREBASE_MEASUREMENT_ID as string | undefined
const API_SECRET = import.meta.env.VITE_GA_API_SECRET as string | undefined
const ENDPOINT = `https://www.google-analytics.com/mp/collect?measurement_id=${MEASUREMENT_ID}&api_secret=${API_SECRET}`

function getClientId(): string {
  const key = 'ga_client_id'
  let id = localStorage.getItem(key)
  if (!id) {
    id = crypto.randomUUID()
    localStorage.setItem(key, id)
  }
  return id
}

function getSessionId(): string {
  const key = 'ga_session_id'
  let id = sessionStorage.getItem(key)
  if (!id) {
    id = String(Date.now())
    sessionStorage.setItem(key, id)
  }
  return id
}

function log(event: string, params?: Record<string, string | number>) {
  if (!MEASUREMENT_ID || !API_SECRET) return
  const body = {
    client_id: getClientId(),
    events: [
      {
        name: event,
        params: {
          session_id: getSessionId(),
          engagement_time_msec: '100',
          ...params
        }
      }
    ]
  }
  fetch(ENDPOINT, {
    method: 'POST',
    body: JSON.stringify(body)
  }).catch(() => {})
}

export function logLogin() {
  log('login', { method: 'email' })
}

export function logSignUp() {
  log('sign_up', { method: 'email' })
}

export function logSignOut() {
  log('logout')
}

export function logSongsImported(count: number) {
  log('songs_imported', { count })
}

export function logExportStarted(count: number) {
  log('export_started', { count })
}

export function logExportCompleted(count: number) {
  log('export_completed', { count })
}

export function logCheckoutInitiated() {
  log('checkout_initiated')
}

export function logFeedbackSubmitted() {
  log('feedback_submitted')
}

export function logAppOpened() {
  log('app_opened')
}

export function logSeparationCompleted() {
  log('separation_completed')
}

export function logSeparationFailed() {
  log('separation_failed')
}

export function logTranscriptionCompleted() {
  log('transcription_completed')
}

export function logTranscriptionFailed() {
  log('transcription_failed')
}

export function logLyricsFetched() {
  log('lyrics_fetched')
}

export function logPreviewPlayed() {
  log('preview_played')
}

export function logManualCensorAdded() {
  log('manual_censor_added')
}

export function logUpdateDownloaded() {
  log('update_downloaded')
}
