import { useCallback, useState } from 'react'
import { useAuth } from '../contexts/AuthContext'
import SupportLink from './SupportLink'

interface PaywallModalProps {
  isOpen: boolean
  onClose: () => void
}

function isAlreadySubscribedError(err: unknown): err is Error {
  return (
    err instanceof Error &&
    'code' in err &&
    typeof (err as { code: unknown }).code === 'string' &&
    (err as { code: string }).code.includes('already-exists')
  )
}

export default function PaywallModal({ isOpen, onClose }: PaywallModalProps): React.JSX.Element | null {
  const { openCheckout, openCustomerPortal, userData, freeSongsLimit, proPriceLabel, isLoading } =
    useAuth()
  const [checkoutLoading, setCheckoutLoading] = useState(false)
  const [portalLoading, setPortalLoading] = useState(false)
  const [checkoutError, setCheckoutError] = useState<string | null>(null)
  const [checkoutBlocked, setCheckoutBlocked] = useState(false)

  const handleSubscribe = useCallback(async () => {
    setCheckoutLoading(true)
    setCheckoutError(null)
    try {
      await openCheckout()
      // Don't close modal - user needs to complete checkout in browser
    } catch (err) {
      console.error('Checkout error:', err)
      if (isAlreadySubscribedError(err)) {
        setCheckoutError(err.message)
        setCheckoutBlocked(true)
      } else {
        setCheckoutError('Unable to open checkout. Please try again or contact support.')
      }
    } finally {
      setCheckoutLoading(false)
    }
  }, [openCheckout])

  const handleOpenPortal = useCallback(async () => {
    setPortalLoading(true)
    setCheckoutError(null)
    try {
      await openCustomerPortal()
      // Don't close modal - user completes the payment update in browser
    } catch (err) {
      console.error('Portal error:', err)
      setCheckoutError('Unable to open billing portal. Please try again or contact support.')
    } finally {
      setPortalLoading(false)
    }
  }, [openCustomerPortal])

  if (!isOpen) return null

  const hasBillingIssue = userData?.subscription.status === 'past_due'
  const songsProcessed = userData?.songsProcessed ?? 0

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-overlay backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative bg-surface rounded-xl border border-border p-6 max-w-md w-full mx-4 shadow-2xl">
        {/* Close button */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-text-tertiary hover:text-text-primary text-lg"
        >
          ✕
        </button>

        {hasBillingIssue ? (
          <>
            {/* Icon */}
            <div className="text-center mb-4">
              <span className="text-5xl">💳</span>
            </div>

            {/* Title */}
            <h2 className="text-xl font-bold text-text-primary text-center mb-2">
              Payment Issue
            </h2>

            {/* Description */}
            <p className="text-text-secondary text-center mb-6">
              There's a problem with your subscription payment — your card on file
              may have expired or been declined. Update your payment method to
              restore unlimited access.
            </p>

            {/* Error message */}
            {checkoutError && (
              <div className="mb-4 p-3 bg-red-900/30 border border-red-800 rounded-lg text-red-300 text-sm">
                {checkoutError}
              </div>
            )}

            {/* Update payment button */}
            <button
              onClick={handleOpenPortal}
              disabled={portalLoading || isLoading}
              className={`
                w-full py-3 rounded-lg font-medium text-sm transition-colors
                ${
                  portalLoading || isLoading
                    ? 'bg-muted text-text-tertiary cursor-not-allowed'
                    : 'bg-blue-600 text-white hover:bg-blue-500 active:bg-blue-700'
                }
              `}
            >
              {portalLoading ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Opening billing portal...
                </span>
              ) : (
                'Update Payment Method'
              )}
            </button>
          </>
        ) : (
          <>
            {/* Icon */}
            <div className="text-center mb-4">
              <span className="text-5xl">🎵</span>
            </div>

            {/* Title */}
            <h2 className="text-xl font-bold text-text-primary text-center mb-2">
              Free Tier Limit Reached
            </h2>

            {/* Description */}
            <p className="text-text-secondary text-center mb-6">
              You've used all {freeSongsLimit} of your free songs.
              Subscribe to continue cleansing unlimited songs!
            </p>

            {/* Usage stats */}
            <div className="bg-elevated/50 rounded-lg p-4 mb-6">
              <div className="flex justify-between items-center text-sm">
                <span className="text-text-secondary">Songs processed</span>
                <span className="text-text-primary font-medium">
                  {Math.min(songsProcessed, freeSongsLimit)} / {freeSongsLimit}
                </span>
              </div>
              <div className="mt-2 h-2 bg-muted rounded-full overflow-hidden">
                <div
                  className="h-full bg-blue-500 rounded-full"
                  style={{ width: `${Math.min(100, (songsProcessed / freeSongsLimit) * 100)}%` }}
                />
              </div>
            </div>

            {/* Features list.
                Only claim what Pro actually changes. Everything Cleanse does --
                per-word control, all four censor styles, format choice, batch --
                is identical for free and paid accounts; the export limit is the
                sole difference. Listing free features as "Pro" reads as a lie
                the first time someone checks. */}
            <div className="mb-6">
              <p className="text-sm font-medium text-text-primary mb-3">Pro removes the limit:</p>
              <ul className="space-y-2 text-sm text-text-secondary">
                <li className="flex items-center gap-2">
                  <span className="text-green-400">✓</span>
                  Unlimited exports
                </li>
                <li className="flex items-center gap-2">
                  <span className="text-green-400">✓</span>
                  Every censor style, per word — mute, beep, reverse, tape stop
                </li>
                <li className="flex items-center gap-2">
                  <span className="text-green-400">✓</span>
                  Export as MP3, WAV or FLAC at source quality
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

            {/* Price, shown before checkout rather than first revealed on Stripe's page */}
            {!checkoutBlocked && (
              <p className="text-center text-sm text-text-secondary mb-3">
                <span className="text-text-primary font-medium">{proPriceLabel}</span>
              </p>
            )}

            {checkoutBlocked ? (
              /* Existing subscription found - checkout is blocked, send them to billing */
              <button
                onClick={handleOpenPortal}
                disabled={portalLoading || isLoading}
                className={`
                  w-full py-3 rounded-lg font-medium text-sm transition-colors
                  ${
                    portalLoading || isLoading
                      ? 'bg-muted text-text-tertiary cursor-not-allowed'
                      : 'bg-blue-600 text-white hover:bg-blue-500 active:bg-blue-700'
                  }
                `}
              >
                {portalLoading ? (
                  <span className="flex items-center justify-center gap-2">
                    <span className="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    Opening billing portal...
                  </span>
                ) : (
                  'Open Manage Billing'
                )}
              </button>
            ) : (
              /* Subscribe button */
              <button
                onClick={handleSubscribe}
                disabled={checkoutLoading || isLoading}
                className={`
                  w-full py-3 rounded-lg font-medium text-sm transition-colors
                  ${
                    checkoutLoading || isLoading
                      ? 'bg-muted text-text-tertiary cursor-not-allowed'
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
            )}
          </>
        )}

        {/* Cancel link */}
        <button
          onClick={onClose}
          className="w-full mt-3 py-2 text-sm text-text-tertiary hover:text-text-secondary transition-colors"
        >
          Maybe later
        </button>

        <p className="text-center text-xs text-text-tertiary">
          Questions? <SupportLink />
        </p>
      </div>
    </div>
  )
}
