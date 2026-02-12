import { initializeApp } from 'firebase/app'
import { initializeAnalytics, type Analytics } from 'firebase/analytics'
import { getAuth, connectAuthEmulator } from 'firebase/auth'
import { getFirestore, connectFirestoreEmulator } from 'firebase/firestore'
import { getFunctions, connectFunctionsEmulator, httpsCallable } from 'firebase/functions'

// Firebase configuration
// In production, these values should come from environment variables
const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY || 'demo-api-key',
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN || 'demo-project.firebaseapp.com',
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID || 'demo-project',
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET || 'demo-project.appspot.com',
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID || '000000000000',
  appId: import.meta.env.VITE_FIREBASE_APP_ID || '1:000000000000:web:0000000000000000000000',
  measurementId: import.meta.env.VITE_FIREBASE_MEASUREMENT_ID || undefined
}

// Initialize Firebase
const app = initializeApp(firebaseConfig)

// Initialize services
export const auth = getAuth(app)
export const db = getFirestore(app)
export const functions = getFunctions(app)

// Initialize Analytics when measurementId is configured
// cookie_domain: 'none' is required because the production app runs at app:// protocol
// which has no valid cookie domain — without this, gtag.js silently drops all events
export const analyticsReady: Promise<Analytics | null> = firebaseConfig.measurementId
  ? Promise.resolve(
      initializeAnalytics(app, {
        config: {
          cookie_domain: 'none',
          send_page_view: false
        }
      })
    ).catch(() => null)
  : Promise.resolve(null)

// Connect to emulators in development
if (import.meta.env.DEV && import.meta.env.VITE_USE_FIREBASE_EMULATORS === 'true') {
  connectAuthEmulator(auth, 'http://localhost:9099', { disableWarnings: true })
  connectFirestoreEmulator(db, 'localhost', 8080)
  connectFunctionsEmulator(functions, 'localhost', 5001)
}

// Cloud Function wrappers
export const incrementUsage = httpsCallable<void, { success: boolean }>(functions, 'incrementUsage')

export const canProcessSong = httpsCallable<void, {
  canProcess: boolean
  songsProcessed: number
  songsRemaining: number
  isSubscribed: boolean
}>(functions, 'canProcessSong')

export const createCheckoutSession = httpsCallable<
  { successUrl?: string; cancelUrl?: string },
  { sessionId: string; url: string }
>(functions, 'createCheckoutSession')

export const createPortalSession = httpsCallable<
  { returnUrl?: string },
  { url: string }
>(functions, 'createPortalSession')

export const submitFeedback = httpsCallable<{ message: string }, { success: boolean }>(functions, 'submitFeedback')

export default app
