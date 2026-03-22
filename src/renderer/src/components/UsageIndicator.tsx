import { useAuth } from '../contexts/AuthContext'

interface UsageIndicatorProps {
  onManageSubscription?: () => void
}

export default function UsageIndicator({ onManageSubscription }: UsageIndicatorProps): React.JSX.Element {
  const { userData, isSubscribed, songsRemaining, freeSongsLimit, signOut, openCustomerPortal } = useAuth()

  const handleManageClick = async () => {
    if (isSubscribed) {
      await openCustomerPortal()
    } else if (onManageSubscription) {
      onManageSubscription()
    }
  }

  return (
    <div className="flex items-center gap-3">
      {/* Usage badge */}
      {isSubscribed ? (
        <div className="flex items-center gap-2">
          <span className="px-2 py-1 text-xs font-medium bg-emerald-900/50 text-emerald-300 rounded-full">
            Pro
          </span>
          <span className="text-xs text-text-tertiary">
            {userData?.subscription.lifetime
              ? 'Lifetime'
              : userData?.subscription.currentPeriodEnd
                ? `Renews ${new Date(userData.subscription.currentPeriodEnd).toLocaleDateString()}`
                : ''}
          </span>
        </div>
      ) : (
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-tertiary">
            {songsRemaining > 0 ? (
              <>
                <span className="text-text-secondary font-medium">{songsRemaining}</span> of {freeSongsLimit} free
              </>
            ) : (
              <span className="text-amber-400">Limit reached</span>
            )}
          </span>
          {/* Mini progress bar */}
          <div className="w-12 h-1.5 bg-muted rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full ${
                songsRemaining === 0 ? 'bg-amber-500' : 'bg-blue-500'
              }`}
              style={{ width: `${((freeSongsLimit - songsRemaining) / freeSongsLimit) * 100}%` }}
            />
          </div>
        </div>
      )}

      {/* User menu */}
      <div className="flex items-center gap-2">
        {/* Email display */}
        <span className="text-xs text-text-tertiary hidden sm:block">
          {userData?.email}
        </span>

        {/* Manage/Upgrade button */}
        <button
          onClick={handleManageClick}
          className="px-2 py-1 text-xs text-text-secondary hover:text-text-primary transition-colors"
        >
          {isSubscribed ? 'Manage' : 'Upgrade'}
        </button>

        {/* Sign out button */}
        <button
          onClick={signOut}
          className="px-2 py-1 text-xs text-text-tertiary hover:text-text-secondary transition-colors"
        >
          Sign out
        </button>
      </div>
    </div>
  )
}
