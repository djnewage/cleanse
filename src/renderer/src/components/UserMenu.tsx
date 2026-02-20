import { useState, useRef, useEffect } from 'react'
import { useAuth } from '../contexts/AuthContext'
import { FREE_SONGS_LIMIT } from '../types'

interface UserMenuProps {
  onManageSubscription?: () => void
}

export default function UserMenu({ onManageSubscription }: UserMenuProps): React.JSX.Element {
  const { userData, isSubscribed, songsRemaining, signOut, openCustomerPortal } = useAuth()
  const [isOpen, setIsOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)

  // Close on click outside
  useEffect(() => {
    if (!isOpen) return

    const handleClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        setIsOpen(false)
      }
    }

    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [isOpen])

  const handleManageClick = async () => {
    setIsOpen(false)
    if (isSubscribed) {
      await openCustomerPortal()
    } else if (onManageSubscription) {
      onManageSubscription()
    }
  }

  const handleSignOut = () => {
    setIsOpen(false)
    signOut()
  }

  return (
    <div className="relative flex items-center" ref={menuRef}>
      {/* Pro badge (always visible) */}
      {isSubscribed && (
        <span className="px-2 py-1 text-xs font-medium bg-emerald-900/50 text-emerald-300 rounded-full mr-2">
          Pro
        </span>
      )}

      {/* User icon button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-7 h-7 rounded-full bg-zinc-700 hover:bg-zinc-600 text-zinc-300 text-xs font-medium transition-colors flex items-center justify-center"
        title={userData?.email || 'Account'}
      >
        {userData?.email?.charAt(0).toUpperCase() || '?'}
      </button>

      {/* Dropdown */}
      {isOpen && (
        <div className="absolute right-0 top-full mt-2 w-64 bg-zinc-800 border border-zinc-700 rounded-lg shadow-xl z-50 py-2">
          {/* Email */}
          <div className="px-4 py-2 border-b border-zinc-700">
            <p className="text-xs text-zinc-400 truncate">{userData?.email}</p>
          </div>

          {/* Subscription info */}
          <div className="px-4 py-3 border-b border-zinc-700">
            {isSubscribed ? (
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="px-2 py-0.5 text-xs font-medium bg-emerald-900/50 text-emerald-300 rounded-full">
                    Pro
                  </span>
                  <span className="text-xs text-zinc-400">
                    {userData?.subscription.lifetime
                      ? 'Lifetime'
                      : userData?.subscription.currentPeriodEnd
                        ? `Renews ${new Date(userData.subscription.currentPeriodEnd).toLocaleDateString()}`
                        : ''}
                  </span>
                </div>
              </div>
            ) : (
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-zinc-400">
                    {songsRemaining > 0 ? (
                      <>
                        <span className="text-zinc-300 font-medium">{songsRemaining}</span> of {FREE_SONGS_LIMIT} free songs
                      </>
                    ) : (
                      <span className="text-amber-400">Limit reached</span>
                    )}
                  </span>
                </div>
                <div className="w-full h-1.5 bg-zinc-700 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full ${
                      songsRemaining === 0 ? 'bg-amber-500' : 'bg-blue-500'
                    }`}
                    style={{ width: `${((FREE_SONGS_LIMIT - songsRemaining) / FREE_SONGS_LIMIT) * 100}%` }}
                  />
                </div>
              </div>
            )}
          </div>

          {/* Actions */}
          <div className="py-1">
            <button
              onClick={handleManageClick}
              className="w-full text-left px-4 py-2 text-sm text-zinc-300 hover:bg-zinc-700 transition-colors"
            >
              {isSubscribed ? 'Manage subscription' : 'Upgrade to Pro'}
            </button>
            <button
              onClick={handleSignOut}
              className="w-full text-left px-4 py-2 text-sm text-zinc-400 hover:bg-zinc-700 hover:text-zinc-300 transition-colors"
            >
              Sign out
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
