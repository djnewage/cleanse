import { logEvent } from 'firebase/analytics'
import { analytics } from './firebase'

function log(event: string, params?: Record<string, string | number>) {
  if (analytics) {
    logEvent(analytics, event, params)
  }
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
