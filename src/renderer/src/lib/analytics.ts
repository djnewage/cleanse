// GA4 Measurement Protocol — bypasses gtag.js which can't send events from
// the app:// protocol (cookies are unavailable so gtag.js silently drops everything).
//
// What this layer guarantees on every event:
//   - client_id   stable per machine (falls back to a per-install UUID)
//   - user_id     the Firebase uid while signed in, so GA4 can stitch a person
//                 across reinstalls and BigQuery can join to users/{uid}
//   - session_id  a real GA4-style session: new one after 30 min idle
//   - engagement_time_msec  time since the previous event, not a constant
//   - app_version / platform params, plus the same as user properties
// In dev builds events go to the validation endpoint and never reach the
// production property.

import pkg from '../../../../package.json'
import type { CensorType, ExportFormat } from '../types'

const MEASUREMENT_ID = import.meta.env.VITE_FIREBASE_MEASUREMENT_ID as string | undefined
const API_SECRET = import.meta.env.VITE_GA_API_SECRET as string | undefined
const IS_DEV = Boolean(import.meta.env.DEV)
const COLLECT_URL = IS_DEV
  ? 'https://www.google-analytics.com/debug/mp/collect'
  : 'https://www.google-analytics.com/mp/collect'
const ENDPOINT = `${COLLECT_URL}?measurement_id=${MEASUREMENT_ID}&api_secret=${API_SECRET}`

const APP_VERSION: string = pkg.version
const SESSION_TIMEOUT_MS = 30 * 60 * 1000 // GA4's own idle rule
const MAX_ENGAGEMENT_MS = 5 * 60 * 1000 // cap so a laptop left open doesn't count as engaged

// ---------------------------------------------------------------------------
// Event catalog. Adding an event means adding it here; call sites are typed.
// Names follow GA4 recommended events where one exists (login, sign_up,
// purchase, screen_view). Param names must be snake_case and ≤ 40 chars.
// ---------------------------------------------------------------------------

export type PaywallReason = 'limit_reached' | 'batch_truncated' | 'upgrade_click' | 'billing_issue'
export type PortalReason = 'manage' | 'past_due' | 'already_exists'
export type ProcessingStage = 'lyrics' | 'separation' | 'transcription' | 'export'
export type CensorScope = 'global' | 'song' | 'word' | 'word_reset'
export type ScreenName = 'help' | 'feedback' | 'custom_words' | 'paywall' | 'song_panel'
export type AuthAction = 'login' | 'sign_up' | 'reset_password'

type NoParams = Record<never, never>

export interface EventMap {
  app_opened: NoParams
  login: { method: 'email' }
  sign_up: { method: 'email' }
  logout: NoParams
  auth_failed: { action: AuthAction; code: string }
  password_reset_requested: NoParams

  songs_imported: { count: number }
  lyrics_fetched: { source: string; duration_mismatch: boolean; from_tags: boolean }
  separation_completed: { elapsed_ms: number; turbo: boolean }
  transcription_completed: {
    elapsed_ms: number
    audio_duration_s: number
    language: string
    word_count: number
    profanity_count: number
    turbo: boolean
    dual_pass: boolean
    language_low_confidence: boolean
  }
  song_failed: { stage: ProcessingStage; error_kind: string }
  song_retried: NoParams
  song_canceled: NoParams

  preview_played: NoParams
  manual_censor_added: NoParams
  word_toggled_off: { detection_source: string }
  word_removed: { detection_source: string }
  censor_style_changed: { style: CensorType | 'default'; scope: CensorScope }
  export_format_changed: { format: ExportFormat }
  custom_word_added: { list_size: number }
  custom_word_removed: { list_size: number }
  turbo_toggled: { enabled: boolean }
  dual_pass_toggled: { enabled: boolean }

  export_started: { count: number; format: ExportFormat; mode: 'single' | 'batch'; truncated_by_quota: boolean }
  export_completed: { count: number; failed: number; format: ExportFormat; mode: 'single' | 'batch' }

  paywall_shown: { reason: PaywallReason; songs_remaining: number }
  checkout_initiated: { songs_remaining: number }
  portal_opened: { reason: PortalReason }
  purchase: {
    value: number
    currency: 'USD'
    transaction_id: string
    items: Array<{ item_name: string; item_variant: string; price: number; quantity: number }>
  }

  screen_view: { screen_name: ScreenName }
  feedback_submitted: NoParams

  update_available: { version: string }
  update_downloaded: { version: string }
  update_install_clicked: { version: string }
  update_dismissed: { version: string; downloaded: boolean }
  update_check_clicked: NoParams

  model_download_started: NoParams
  model_download_completed: { elapsed_ms: number }
  model_download_failed: { elapsed_ms: number }
}

export type AnalyticsEventName = keyof EventMap

// ---------------------------------------------------------------------------
// Identity and context
// ---------------------------------------------------------------------------

type Primitive = string | number | boolean
type ParamValue = Primitive | Array<Record<string, Primitive>>

let userId: string | null = null
let userProps: Record<string, Primitive> = {}
let platformArch: 'arm64' | 'x64' | 'unknown' = 'unknown'

function osFamily(): 'mac' | 'win' | 'linux' | 'other' {
  const ua = navigator.userAgent
  if (/Macintosh|Mac OS X/i.test(ua)) return 'mac'
  if (/Windows/i.test(ua)) return 'win'
  if (/Linux/i.test(ua)) return 'linux'
  return 'other'
}

/** e.g. mac_arm64, mac_x64, win_x64 — arch is known once device info arrives. */
export function currentPlatform(): string {
  const os = osFamily()
  return platformArch === 'unknown' ? os : `${os}_${platformArch}`
}

export function setAnalyticsUser(uid: string | null): void {
  userId = uid
}

/** Merge user properties; they ride along on every subsequent event. */
export function setAnalyticsUserProperties(props: Record<string, Primitive | null | undefined>): void {
  for (const [k, v] of Object.entries(props)) {
    if (v === null || v === undefined) delete userProps[k]
    else userProps[k] = v
  }
}

/** Called once the backend reports the compute device. Fixes the arch half of
 *  `platform`: Apple Silicon reports `mps`, Intel Macs fall back to `cpu`. */
export function setAnalyticsDevice(info: { device_type: string; turbo_supported: boolean }): void {
  if (osFamily() === 'mac') platformArch = info.device_type === 'mps' ? 'arm64' : 'x64'
  else if (osFamily() === 'win') platformArch = 'x64'
  setAnalyticsUserProperties({
    device_type: info.device_type,
    turbo_supported: info.turbo_supported,
    platform: currentPlatform()
  })
}

// ---------------------------------------------------------------------------
// client_id: machine id from the main process when available, else a UUID
// that lives as long as localStorage does.
// ---------------------------------------------------------------------------

function fallbackClientId(): string {
  const key = 'ga_client_id'
  try {
    let id = localStorage.getItem(key)
    if (!id) {
      id = crypto.randomUUID()
      localStorage.setItem(key, id)
    }
    return id
  } catch {
    return crypto.randomUUID()
  }
}

const clientIdPromise: Promise<string> = (async () => {
  try {
    const id = await window.electronAPI?.getMachineId?.()
    if (id && typeof id === 'string') return id
  } catch {
    /* fall through */
  }
  return fallbackClientId()
})()

// ---------------------------------------------------------------------------
// Sessions and engagement
// ---------------------------------------------------------------------------

interface SessionState {
  id: string
  number: number
  lastEventAt: number
}

function readSession(): SessionState | null {
  try {
    const raw = localStorage.getItem('ga_session')
    if (!raw) return null
    const s = JSON.parse(raw) as Partial<SessionState>
    if (typeof s.id === 'string' && typeof s.number === 'number' && typeof s.lastEventAt === 'number') {
      return s as SessionState
    }
  } catch {
    /* ignore */
  }
  return null
}

function writeSession(s: SessionState): void {
  try {
    localStorage.setItem('ga_session', JSON.stringify(s))
  } catch {
    /* ignore quota errors */
  }
}

/** Returns the session to stamp on this event and the engagement time since
 *  the previous event. Starts a fresh session after 30 minutes of silence. */
function touchSession(now: number): { sessionId: string; sessionNumber: number; engagementMs: number } {
  const prev = readSession()
  if (!prev || now - prev.lastEventAt > SESSION_TIMEOUT_MS) {
    const next: SessionState = { id: String(now), number: (prev?.number ?? 0) + 1, lastEventAt: now }
    writeSession(next)
    // First event of a session: GA4 needs a positive engagement time to count
    // the user as active, and there is no "previous event" to measure from.
    return { sessionId: next.id, sessionNumber: next.number, engagementMs: 100 }
  }
  const engagementMs = Math.max(1, Math.min(now - prev.lastEventAt, MAX_ENGAGEMENT_MS))
  writeSession({ ...prev, lastEventAt: now })
  return { sessionId: prev.id, sessionNumber: prev.number, engagementMs }
}

// ---------------------------------------------------------------------------
// Transport
// ---------------------------------------------------------------------------

// GA4 accepts strings and numbers; booleans are sent as 1/0 so they can be
// used as metrics and filtered as dimensions.
function coerce(v: ParamValue): string | number | Array<Record<string, string | number>> {
  if (typeof v === 'boolean') return v ? 1 : 0
  if (Array.isArray(v)) {
    return v.map((item) => {
      const out: Record<string, string | number> = {}
      for (const [k, iv] of Object.entries(item)) out[k] = typeof iv === 'boolean' ? (iv ? 1 : 0) : iv
      return out
    })
  }
  return v
}

async function send(name: string, params: Record<string, ParamValue>): Promise<void> {
  if (!MEASUREMENT_ID || !API_SECRET) return

  const now = Date.now()
  const { sessionId, sessionNumber, engagementMs } = touchSession(now)
  const clientId = await clientIdPromise

  const eventParams: Record<string, string | number | Array<Record<string, string | number>>> = {
    session_id: sessionId,
    session_number: sessionNumber,
    engagement_time_msec: engagementMs,
    app_version: APP_VERSION,
    platform: currentPlatform()
  }
  for (const [k, v] of Object.entries(params)) eventParams[k] = coerce(v)
  if (IS_DEV) eventParams.debug_mode = 1

  const userProperties: Record<string, { value: string | number }> = {
    app_version: { value: APP_VERSION },
    platform: { value: currentPlatform() }
  }
  for (const [k, v] of Object.entries(userProps)) {
    userProperties[k] = { value: typeof v === 'boolean' ? (v ? 1 : 0) : v }
  }

  const body: Record<string, unknown> = {
    client_id: clientId,
    timestamp_micros: now * 1000,
    user_properties: userProperties,
    events: [{ name, params: eventParams }]
  }
  if (userId) body.user_id = userId

  try {
    const res = await fetch(ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      // Survive the window closing mid-request (e.g. logout right before quit).
      keepalive: true
    })
    if (IS_DEV) {
      const validation = (await res.json().catch(() => null)) as { validationMessages?: unknown[] } | null
      const messages = validation?.validationMessages ?? []
      if (messages.length) console.warn(`[analytics] ${name} rejected by GA4:`, messages)
      else console.debug(`[analytics] ${name}`, eventParams)
    }
  } catch {
    // Analytics must never affect the app.
  }
}

/** The one entry point. `params` is checked against the catalog at compile time. */
export function track<N extends AnalyticsEventName>(
  name: N,
  ...rest: keyof EventMap[N] extends never ? [] : [params: EventMap[N]]
): void {
  const params = (rest[0] ?? {}) as Record<string, ParamValue>
  void send(name, params)
}

/** Reduce an arbitrary error message to a short, low-cardinality bucket that is
 *  safe to use as a GA4 dimension (no file paths, no user text). */
export function errorKind(message: string): string {
  const m = message.toLowerCase()
  if (m.includes('aborted')) return 'aborted'
  if (m.includes('timeout') || m.includes('timed out')) return 'timeout'
  if (m.includes('crashed')) return 'backend_crashed'
  if (m.includes('no longer exists') || m.includes('not found')) return 'file_missing'
  if (m.includes('memory')) return 'out_of_memory'
  if (m.includes('did not respond')) return 'backend_unresponsive'
  if (m.includes('network') || m.includes('fetch')) return 'network'
  if (m.includes('permission') || m.includes('eacces')) return 'permission'
  return 'other'
}

// ---------------------------------------------------------------------------
// Thin named helpers kept for existing call sites. New code can call track().
// ---------------------------------------------------------------------------

export function logLogin(): void {
  track('login', { method: 'email' })
}

export function logSignUp(): void {
  track('sign_up', { method: 'email' })
}

export function logSignOut(): void {
  track('logout')
}

export function logSongsImported(count: number): void {
  track('songs_imported', { count })
}

export function logFeedbackSubmitted(): void {
  track('feedback_submitted')
}

export function logAppOpened(): void {
  track('app_opened')
}

export function logPreviewPlayed(): void {
  track('preview_played')
}

export function logManualCensorAdded(): void {
  track('manual_censor_added')
}
