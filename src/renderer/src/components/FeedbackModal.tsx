import { useCallback, useState } from 'react'
import { submitFeedback } from '../lib/firebase'
import { logFeedbackSubmitted } from '../lib/analytics'

interface FeedbackModalProps {
  isOpen: boolean
  onClose: () => void
}

export default function FeedbackModal({ isOpen, onClose }: FeedbackModalProps): React.JSX.Element | null {
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  const handleSubmit = useCallback(async () => {
    if (!message.trim()) return

    setLoading(true)
    setError(null)
    try {
      await submitFeedback({ message: message.trim() })
      logFeedbackSubmitted()
      setSuccess(true)
      setMessage('')
    } catch (err) {
      console.error('Feedback error:', err)
      setError(err instanceof Error ? err.message : 'Failed to submit feedback')
    } finally {
      setLoading(false)
    }
  }, [message])

  const handleClose = useCallback(() => {
    setMessage('')
    setError(null)
    setSuccess(false)
    setLoading(false)
    onClose()
  }, [onClose])

  if (!isOpen) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={handleClose}
      />

      {/* Modal */}
      <div className="relative bg-zinc-900 rounded-xl border border-zinc-800 p-6 max-w-md w-full mx-4 shadow-2xl">
        {/* Close button */}
        <button
          onClick={handleClose}
          className="absolute top-4 right-4 text-zinc-500 hover:text-white text-lg"
        >
          ✕
        </button>

        {success ? (
          <>
            <div className="text-center mb-4">
              <span className="text-5xl">✓</span>
            </div>
            <h2 className="text-xl font-bold text-white text-center mb-2">
              Thanks for your feedback!
            </h2>
            <p className="text-zinc-400 text-center mb-6">
              We appreciate you taking the time to share your thoughts.
            </p>
            <button
              onClick={handleClose}
              className="w-full py-3 rounded-lg font-medium text-sm bg-blue-600 text-white hover:bg-blue-500 active:bg-blue-700 transition-colors"
            >
              Close
            </button>
          </>
        ) : (
          <>
            <h2 className="text-xl font-bold text-white text-center mb-2">
              Send Feedback
            </h2>
            <p className="text-zinc-400 text-center mb-6">
              Let us know how we can improve Cleanse.
            </p>

            <textarea
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="What's on your mind?"
              rows={4}
              className="w-full bg-zinc-800 border border-zinc-700 rounded-lg p-3 text-sm text-white placeholder-zinc-500 resize-none focus:outline-none focus:border-blue-500 mb-4"
            />

            {error && (
              <div className="mb-4 p-3 bg-red-900/30 border border-red-800 rounded-lg text-red-300 text-sm">
                {error}
              </div>
            )}

            <button
              onClick={handleSubmit}
              disabled={loading || !message.trim()}
              className={`
                w-full py-3 rounded-lg font-medium text-sm transition-colors
                ${
                  loading || !message.trim()
                    ? 'bg-zinc-700 text-zinc-500 cursor-not-allowed'
                    : 'bg-blue-600 text-white hover:bg-blue-500 active:bg-blue-700'
                }
              `}
            >
              {loading ? (
                <span className="flex items-center justify-center gap-2">
                  <span className="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                  Sending...
                </span>
              ) : (
                'Submit Feedback'
              )}
            </button>

            <button
              onClick={handleClose}
              className="w-full mt-3 py-2 text-sm text-zinc-500 hover:text-zinc-300 transition-colors"
            >
              Cancel
            </button>
          </>
        )}
      </div>
    </div>
  )
}
