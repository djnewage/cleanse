import { useCallback, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { FREE_SONGS_LIMIT } from '../types'

interface PaywallModalProps {
  isOpen: boolean
  onClose: () => void
}

export default function PaywallModal({ isOpen, onClose }: PaywallModalProps): React.JSX.Element | null {
  const { openCheckout, userData, isLoading } = useAuth()
  const [checkoutLoading, setCheckoutLoading] = useState(false)
  const [checkoutError, setCheckoutError] = useState<string | null>(null)

  const handleSubscribe = useCallback(async () => {
    setCheckoutLoading(true)
    setCheckoutError(null)
    try {
      await openCheckout()
      // Don't close modal - user needs to complete checkout in browser
    } catch (err) {
      console.error('Checkout error:', err)
      setCheckoutError('Unable to open checkout. Please try again or contact support.')
    } finally {
      setCheckoutLoading(false)
    }
  }, [openCheckout])

  if (!isOpen) return null

  const songsProcessed = userData?.songsProcessed ?? 0

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative bg-zinc-900 rounded-xl border border-zinc-800 p-6 max-w-md w-full mx-4 shadow-2xl">
        {/* Close button */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-zinc-500 hover:text-white text-lg"
        >
          ✕
        </button>

        {/* Icon */}
        <div className="text-center mb-4">
          <span className="text-5xl">🎵</span>
        </div>

        {/* Title */}
        <h2 className="text-xl font-bold text-white text-center mb-2">
          Free Tier Limit Reached
        </h2>

        {/* Description */}
        <p className="text-zinc-400 text-center mb-6">
          You've used all {FREE_SONGS_LIMIT} of your free songs.
          Subscribe to continue cleansing unlimited songs!
        </p>

        {/* Usage stats */}
        <div className="bg-zinc-800/50 rounded-lg p-4 mb-6">
          <div className="flex justify-between items-center text-sm">
            <span className="text-zinc-400">Songs processed</span>
            <span className="text-white font-medium">{songsProcessed} / {FREE_SONGS_LIMIT}</span>
          </div>
          <div className="mt-2 h-2 bg-zinc-700 rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 rounded-full"
              style={{ width: `${Math.min(100, (songsProcessed / FREE_SONGS_LIMIT) * 100)}%` }}
            />
          </div>
        </div>

        {/* Features list */}
        <div className="mb-6">
          <p className="text-sm font-medium text-white mb-3">What you get with Pro:</p>
          <ul className="space-y-2 text-sm text-zinc-300">
            <li className="flex items-center gap-2">
              <span className="text-green-400">✓</span>
              Unlimited song processing
            </li>
            <li className="flex items-center gap-2">
              <span className="text-green-400">✓</span>
              Batch processing support
            </li>
            <li className="flex items-center gap-2">
              <span className="text-green-400">✓</span>
              Turbo Processing (GPU acceleration)
            </li>
            <li className="flex items-center gap-2">
              <span className="text-green-400">✓</span>
              Priority support
            </li>
            <li className="flex items-center gap-2">
              <span className="text-green-400">✓</span>
              Cancel anytime
            </li>
          </ul>
        </div>

        {/* Error message */}
        {checkoutError && (
          <div className="mb-4 p-3 bg-red-900/30 border border-red-800 rounded-lg text-red-300 text-sm">
            {checkoutError}
          </div>
        )}

        {/* Subscribe button */}
        <button
          onClick={handleSubscribe}
          disabled={checkoutLoading || isLoading}
          className={`
            w-full py-3 rounded-lg font-medium text-sm transition-colors
            ${
              checkoutLoading || isLoading
                ? 'bg-zinc-700 text-zinc-500 cursor-not-allowed'
                : 'bg-blue-600 text-white hover:bg-blue-500 active:bg-blue-700'
            }
          `}
        >
          {checkoutLoading ? (
            <span className="flex items-center justify-center gap-2">
              <span className="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              Opening checkout...
            </span>
          ) : (
            'Subscribe Now'
          )}
        </button>

        {/* Cancel link */}
        <button
          onClick={onClose}
          className="w-full mt-3 py-2 text-sm text-zinc-500 hover:text-zinc-300 transition-colors"
        >
          Maybe later
        </button>
      </div>
    </div>
  )
}
