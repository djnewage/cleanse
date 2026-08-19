import { useAuth } from '../contexts/AuthContext'

interface UsageIndicatorProps {
  onManageSubscription?: () => void
}

/**
 * Always-visible free-quota readout.
 *
 * The same count exists in UserMenu, but only inside a dropdown behind a 28px
 * avatar -- so a free user got no warning they were on their last song and the
 * paywall arrived unannounced. Keeping the number on screen turns a limit into
 * something you can see coming.
 *
 * The email / sign-out half this component used to carry has been dropped:
 * UserMenu owns that now, and rendering both duplicated it.
 */
export default function UsageIndicator({
  onManageSubscription
}: UsageIndicatorProps): React.JSX.Element | null {
  const { isSubscribed, songsRemaining, freeSongsLimit } = useAuth()

  // Nothing to count for subscribers; UserMenu carries the Pro badge.
  if (isSubscribed) return null

  const used = Math.max(0, freeSongsLimit - songsRemaining)
  const pct = freeSongsLimit > 0 ? Math.min(100, (used / freeSongsLimit) * 100) : 0

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-text-tertiary">
        {songsRemaining > 0 ? (
          <>
            <span className="text-text-secondary font-medium">{songsRemaining}</span> of{' '}
            {freeSongsLimit} free left
          </>
        ) : (
          <span className="text-amber-400">Limit reached</span>
        )}
      </span>

      <div className="w-12 h-1.5 bg-muted rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full ${songsRemaining === 0 ? 'bg-amber-500' : 'bg-blue-500'}`}
          style={{ width: `${pct}%` }}
        />
      </div>

      {onManageSubscription && (
        <button
          onClick={onManageSubscription}
          className="px-2 py-1 text-xs text-blue-400 hover:text-blue-300 transition-colors"
        >
          Upgrade
        </button>
      )}
    </div>
  )
}
