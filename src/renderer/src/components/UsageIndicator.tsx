import { useAuth } from '../contexts/AuthContext'
import { FREE_SONGS_LIMIT } from '../types'

interface UsageIndicatorProps {
  onManageSubscription?: () => void
}

export default function UsageIndicator({ onManageSubscription }: UsageIndicatorProps): React.JSX.Element {
  const { userData, isSubscribed, songsRemaining, signOut, openCustomerPortal } = useAuth()

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
        <span className="px-2 py-1 text-xs font-medium bg-emerald-900/50 text-emerald-300 rounded-full">
          Pro
        </span>
      ) : (
        <div className="flex items-center gap-2">
          <span className="text-xs text-zinc-500">
            {songsRemaining > 0 ? (
              <>
                <span className="text-zinc-300 font-medium">{songsRemaining}</span> of {FREE_SONGS_LIMIT} free
              </>
            ) : (
              <span className="text-amber-400">Limit reached</span>
            )}
          </span>
          {/* Mini progress bar */}
          <div className="w-12 h-1.5 bg-zinc-700 rounded-full overflow-hidden">
            <div
              className={`h-full rounded-full ${
                songsRemaining === 0 ? 'bg-amber-500' : 'bg-blue-500'
              }`}
              style={{ width: `${((FREE_SONGS_LIMIT - songsRemaining) / FREE_SONGS_LIMIT) * 100}%` }}
            />
          </div>
        </div>
      )}

      {/* User menu */}
      <div className="flex items-center gap-2">
        {/* Email display */}
        <span className="text-xs text-zinc-500 hidden sm:block">
          {userData?.email}
        </span>

        {/* Manage/Upgrade button */}
        <button
          onClick={handleManageClick}
          className="px-2 py-1 text-xs text-zinc-400 hover:text-white transition-colors"
        >
          {isSubscribed ? 'Manage' : 'Upgrade'}
        </button>

        {/* Sign out button */}
        <button
          onClick={signOut}
          className="px-2 py-1 text-xs text-zinc-500 hover:text-zinc-300 transition-colors"
        >
          Sign out
        </button>
      </div>
    </div>
  )
}
