import * as Sentry from '@sentry/react'
import { createContext, useContext, useEffect, useState, useCallback, ReactNode } from 'react'
import {
  User,
  onAuthStateChanged,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  signOut as firebaseSignOut,
  sendPasswordResetEmail
} from 'firebase/auth'
import { doc, onSnapshot } from 'firebase/firestore'
import { auth, db, incrementUsage, canProcessSong, createCheckoutSession, createPortalSession } from '../lib/firebase'
import { logLogin, logSignUp, logSignOut, logCheckoutInitiated } from '../lib/analytics'
import type { UserData, UsageInfo } from '../types'

interface AuthContextType {
  // Auth state
  user: User | null
  userData: UserData | null
  isLoading: boolean
  error: string | null

  // Auth methods
  signIn: (email: string, password: string) => Promise<void>
  signUp: (email: string, password: string) => Promise<void>
  signOut: () => Promise<void>
  resetPassword: (email: string) => Promise<void>
  clearError: () => void

  // Usage/subscription methods
  checkCanProcess: () => Promise<UsageInfo>
  recordUsage: () => Promise<void>
  openCheckout: () => Promise<void>
  openCustomerPortal: () => Promise<void>

  // Computed values
  isAuthenticated: boolean
  isSubscribed: boolean
  songsRemaining: number
}

const AuthContext = createContext<AuthContextType | null>(null)

export function useAuth(): AuthContextType {
  const context = useContext(AuthContext)
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider')
  }
  return context
}

function friendlyAuthError(err: unknown): string {
  const message = err instanceof Error ? err.message : ''
  const match = message.match(/auth\/([a-z-]+)/)
  const code = match?.[1]
  switch (code) {
    case 'invalid-credential':
    case 'wrong-password':
    case 'user-not-found':
      return 'Invalid email or password'
    case 'invalid-email':
      return 'Please enter a valid email address'
    case 'email-already-in-use':
      return 'An account with this email already exists'
    case 'weak-password':
      return 'Password must be at least 6 characters'
    case 'too-many-requests':
      return 'Too many attempts. Please try again later'
    case 'network-request-failed':
      return 'Network error. Please check your connection'
    case 'user-disabled':
      return 'This account has been disabled'
    default:
      return message || 'Something went wrong. Please try again'
  }
}

interface AuthProviderProps {
  children: ReactNode
}

export function AuthProvider({ children }: AuthProviderProps): React.JSX.Element {
  const [user, setUser] = useState<User | null>(null)
  const [userData, setUserData] = useState<UserData | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  // Listen to auth state changes
  useEffect(() => {
    const unsubscribe = onAuthStateChanged(auth, (firebaseUser) => {
      setUser(firebaseUser)
      if (!firebaseUser) {
        setUserData(null)
        setIsLoading(false)
      }
    })

    return unsubscribe
  }, [])

  // Listen to user document changes when authenticated
  useEffect(() => {
    if (!user) return

    const userDocRef = doc(db, 'users', user.uid)
    const unsubscribe = onSnapshot(
      userDocRef,
      (docSnapshot) => {
        if (docSnapshot.exists()) {
          const data = docSnapshot.data()
          setUserData({
            email: data.email,
            createdAt: data.createdAt?.toMillis?.() || Date.now(),
            songsProcessed: data.songsProcessed || 0,
            subscription: {
              status: data.subscription?.status || 'none',
              lifetime: data.subscription?.lifetime || false,
              stripeCustomerId: data.subscription?.stripeCustomerId || null,
              stripeSubscriptionId: data.subscription?.stripeSubscriptionId || null,
              currentPeriodEnd: data.subscription?.currentPeriodEnd?.toMillis?.() || null
            }
          })
        }
        setIsLoading(false)
      },
      (err) => {
        console.error('Error fetching user data:', err)
        setIsLoading(false)
      }
    )

    return unsubscribe
  }, [user])

  // Sign in with email/password
  const signIn = useCallback(async (email: string, password: string) => {
    setError(null)
    setIsLoading(true)
    try {
      await signInWithEmailAndPassword(auth, email, password)
      logLogin()
    } catch (err) {
      setError(friendlyAuthError(err))
      throw err
    } finally {
      setIsLoading(false)
    }
  }, [])

  // Sign up with email/password
  const signUp = useCallback(async (email: string, password: string) => {
    setError(null)
    setIsLoading(true)
    try {
      await createUserWithEmailAndPassword(auth, email, password)
      logSignUp()
      // User document will be created by Cloud Function trigger
    } catch (err) {
      setError(friendlyAuthError(err))
      throw err
    } finally {
      setIsLoading(false)
    }
  }, [])

  // Sign out
  const signOut = useCallback(async () => {
    setError(null)
    try {
      await firebaseSignOut(auth)
      logSignOut()
      setUserData(null)
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Sign out failed'
      setError(message)
      throw err
    }
  }, [])

  // Reset password
  const resetPassword = useCallback(async (email: string) => {
    setError(null)
    try {
      await sendPasswordResetEmail(auth, email)
    } catch (err) {
      setError(friendlyAuthError(err))
      throw err
    }
  }, [])

  // Clear error
  const clearError = useCallback(() => {
    setError(null)
  }, [])

  // Check if user can process a song
  const checkCanProcess = useCallback(async (): Promise<UsageInfo> => {
    if (!user) {
      return { canProcess: false, songsProcessed: 0, songsRemaining: 0, isSubscribed: false }
    }

    try {
      const result = await canProcessSong()
      return result.data
    } catch (err) {
      console.error('Error checking usage:', err)
      // Fallback to local data
      if (userData) {
        const isSubscribed = userData.subscription.lifetime || userData.subscription.status === 'active'
        const canProcess = isSubscribed || userData.songsProcessed < 5
        return {
          canProcess,
          songsProcessed: userData.songsProcessed,
          songsRemaining: isSubscribed ? -1 : Math.max(0, 5 - userData.songsProcessed),
          isSubscribed
        }
      }
      return { canProcess: false, songsProcessed: 0, songsRemaining: 0, isSubscribed: false }
    }
  }, [user, userData])

  // Record usage after successful export
  const recordUsage = useCallback(async () => {
    if (!user) return

    try {
      await incrementUsage()
    } catch (err) {
      console.error('Error recording usage:', err)
      // Don't throw - the export succeeded, we just failed to record it
    }
  }, [user])

  // Open Stripe Checkout
  const openCheckout = useCallback(async () => {
    if (!user) return

    try {
      const result = await createCheckoutSession({})
      logCheckoutInitiated()
      if (result.data.url) {
        // Open in system browser
        window.electronAPI?.openExternal?.(result.data.url) ||
          window.open(result.data.url, '_blank')
      }
    } catch (err) {
      Sentry.captureException(err)
      const message = err instanceof Error ? err.message : 'Failed to open checkout'
      setError(message)
      throw err
    }
  }, [user])

  // Open Stripe Customer Portal
  const openCustomerPortal = useCallback(async () => {
    if (!user) return

    try {
      const result = await createPortalSession({})
      if (result.data.url) {
        window.electronAPI?.openExternal?.(result.data.url) ||
          window.open(result.data.url, '_blank')
      }
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to open portal'
      setError(message)
      throw err
    }
  }, [user])

  // Computed values
  const isAuthenticated = !!user
  const isSubscribed = userData?.subscription.lifetime || userData?.subscription.status === 'active'
  const songsRemaining = isSubscribed ? -1 : Math.max(0, 5 - (userData?.songsProcessed || 0))

  const value: AuthContextType = {
    user,
    userData,
    isLoading,
    error,
    signIn,
    signUp,
    signOut,
    resetPassword,
    clearError,
    checkCanProcess,
    recordUsage,
    openCheckout,
    openCustomerPortal,
    isAuthenticated,
    isSubscribed,
    songsRemaining
  }

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}
