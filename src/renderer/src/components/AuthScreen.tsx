import { useState, useCallback, FormEvent } from 'react'
import { useAuth } from '../contexts/AuthContext'

type AuthMode = 'signin' | 'signup' | 'reset'

export default function AuthScreen(): React.JSX.Element {
  const { signIn, signUp, resetPassword, error, clearError, isLoading } = useAuth()

  const [mode, setMode] = useState<AuthMode>('signin')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [localError, setLocalError] = useState<string | null>(null)
  const [resetSent, setResetSent] = useState(false)

  const handleSubmit = useCallback(
    async (e: FormEvent) => {
      e.preventDefault()
      setLocalError(null)
      clearError()

      if (mode === 'signup' && password !== confirmPassword) {
        setLocalError('Passwords do not match')
        return
      }

      if (mode === 'signup' && password.length < 6) {
        setLocalError('Password must be at least 6 characters')
        return
      }

      try {
        if (mode === 'signin') {
          await signIn(email, password)
        } else if (mode === 'signup') {
          await signUp(email, password)
        } else if (mode === 'reset') {
          await resetPassword(email)
          setResetSent(true)
        }
      } catch {
        // Error is already set in context
      }
    },
    [mode, email, password, confirmPassword, signIn, signUp, resetPassword, clearError]
  )

  const switchMode = (newMode: AuthMode) => {
    setMode(newMode)
    setLocalError(null)
    clearError()
    setResetSent(false)
  }

  const displayError = localError || error

  return (
    <div className="min-h-screen bg-zinc-950 flex flex-col items-center justify-center px-4">
      <div className="w-full max-w-sm">
        {/* Logo/Title */}
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-white mb-2">Cleanse</h1>
          <p className="text-zinc-400 text-sm">Censor profanity in audio files</p>
        </div>

        {/* Auth form */}
        <div className="bg-zinc-900 rounded-xl border border-zinc-800 p-6">
          <h2 className="text-lg font-semibold text-white mb-4">
            {mode === 'signin' && 'Sign In'}
            {mode === 'signup' && 'Create Account'}
            {mode === 'reset' && 'Reset Password'}
          </h2>

          {/* Error message */}
          {displayError && (
            <div className="mb-4 p-3 bg-red-950/50 border border-red-800 rounded-lg">
              <p className="text-sm text-red-300">{displayError}</p>
            </div>
          )}

          {/* Reset sent message */}
          {resetSent && (
            <div className="mb-4 p-3 bg-green-950/50 border border-green-800 rounded-lg">
              <p className="text-sm text-green-300">
                Password reset email sent. Check your inbox.
              </p>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Email field */}
            <div>
              <label htmlFor="email" className="block text-sm font-medium text-zinc-400 mb-1">
                Email
              </label>
              <input
                type="email"
                id="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                placeholder="you@example.com"
              />
            </div>

            {/* Password field */}
            {mode !== 'reset' && (
              <div>
                <label htmlFor="password" className="block text-sm font-medium text-zinc-400 mb-1">
                  Password
                </label>
                <input
                  type="password"
                  id="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  minLength={6}
                  className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                  placeholder="••••••••"
                />
              </div>
            )}

            {/* Confirm password field (signup only) */}
            {mode === 'signup' && (
              <div>
                <label htmlFor="confirmPassword" className="block text-sm font-medium text-zinc-400 mb-1">
                  Confirm Password
                </label>
                <input
                  type="password"
                  id="confirmPassword"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  required
                  minLength={6}
                  className="w-full px-3 py-2 bg-zinc-800 border border-zinc-700 rounded-lg text-white placeholder-zinc-500 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
                  placeholder="••••••••"
                />
              </div>
            )}

            {/* Submit button */}
            <button
              type="submit"
              disabled={isLoading}
              className={`
                w-full py-2.5 rounded-lg font-medium text-sm transition-colors
                ${
                  isLoading
                    ? 'bg-zinc-700 text-zinc-500 cursor-not-allowed'
                    : 'bg-blue-600 text-white hover:bg-blue-500 active:bg-blue-700'
                }
              `}
            >
              {isLoading ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  {mode === 'signin' && 'Signing in...'}
                  {mode === 'signup' && 'Creating account...'}
                  {mode === 'reset' && 'Sending...'}
                </span>
              ) : (
                <>
                  {mode === 'signin' && 'Sign In'}
                  {mode === 'signup' && 'Create Account'}
                  {mode === 'reset' && 'Send Reset Email'}
                </>
              )}
            </button>
          </form>

          {/* Mode switchers */}
          <div className="mt-4 pt-4 border-t border-zinc-800 text-center text-sm">
            {mode === 'signin' && (
              <>
                <p className="text-zinc-400">
                  Don't have an account?{' '}
                  <button
                    onClick={() => switchMode('signup')}
                    className="text-blue-400 hover:text-blue-300"
                  >
                    Sign up
                  </button>
                </p>
                <p className="text-zinc-500 mt-2">
                  <button
                    onClick={() => switchMode('reset')}
                    className="text-zinc-400 hover:text-zinc-300"
                  >
                    Forgot password?
                  </button>
                </p>
              </>
            )}

            {mode === 'signup' && (
              <p className="text-zinc-400">
                Already have an account?{' '}
                <button
                  onClick={() => switchMode('signin')}
                  className="text-blue-400 hover:text-blue-300"
                >
                  Sign in
                </button>
              </p>
            )}

            {mode === 'reset' && (
              <p className="text-zinc-400">
                Remember your password?{' '}
                <button
                  onClick={() => switchMode('signin')}
                  className="text-blue-400 hover:text-blue-300"
                >
                  Sign in
                </button>
              </p>
            )}
          </div>
        </div>

        {/* Free tier info */}
        <p className="text-center text-xs text-zinc-500 mt-6">
          Start with 5 free songs. Subscribe for unlimited access.
        </p>
      </div>
    </div>
  )
}
