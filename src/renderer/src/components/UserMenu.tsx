import { useState, useRef, useEffect, useCallback } from 'react'
import { useAuth } from '../contexts/AuthContext'

interface UserMenuProps {
  onManageSubscription?: () => void
}

export default function UserMenu({ onManageSubscription }: UserMenuProps): React.JSX.Element {
  const { userData, isSubscribed, songsRemaining, freeSongsLimit, signOut, openCustomerPortal } = useAuth()
  const [isOpen, setIsOpen] = useState(false)
  const [updateStatus, setUpdateStatus] = useState<'idle' | 'checking' | 'up-to-date' | 'error'>('idle')
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

  // Listen for update-not-available and error events
  useEffect(() => {
    const unsubNotAvailable = window.electronAPI.onUpdateNotAvailable(() => {
      setUpdateStatus('up-to-date')
      setTimeout(() => setUpdateStatus('idle'), 3000)
    })
    const unsubError = window.electronAPI.onUpdateError(() => {
      setUpdateStatus('error')
      setTimeout(() => setUpdateStatus('idle'), 3000)
    })
    return () => { unsubNotAvailable(); unsubError() }
  }, [])

  const handleManageClick = async () => {
    setIsOpen(false)
    if (isSubscribed) {
      await openCustomerPortal()
    } else if (onManageSubscription) {
      onManageSubscription()
    }
  }

  const handleCheckForUpdates = useCallback(() => {
    setUpdateStatus('checking')
    window.electronAPI.checkForUpdates()
    // update-available event will trigger the UpdateModal in App.tsx
    // update-not-available event will show "up to date" here
  }, [])

  const handleSignOut = () => {
    setIsOpen(false)
    signOut()
  }

  const updateLabel = updateStatus === 'checking'
    ? 'Checking...'
    : updateStatus === 'up-to-date'
      ? 'You\'re up to date!'
      : updateStatus === 'error'
        ? 'Check failed'
        : 'Check for updates'

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
        className="w-7 h-7 rounded-full bg-muted hover:bg-muted text-text-secondary text-xs font-medium transition-colors flex items-center justify-center"
        title={userData?.email || 'Account'}
      >
        {userData?.email?.charAt(0).toUpperCase() || '?'}
      </button>

      {/* Dropdown */}
      {isOpen && (
        <div className="absolute right-0 top-full mt-2 w-64 bg-elevated border border-border-strong rounded-lg shadow-xl z-50 py-2">
          {/* Email */}
          <div className="px-4 py-2 border-b border-border-strong">
            <p className="text-xs text-text-secondary truncate">{userData?.email}</p>
          </div>

          {/* Subscription info */}
          <div className="px-4 py-3 border-b border-border-strong">
            {isSubscribed ? (
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <span className="px-2 py-0.5 text-xs font-medium bg-emerald-900/50 text-emerald-300 rounded-full">
                    Pro
                  </span>
                  <span className="text-xs text-text-secondary">
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
                  <span className="text-xs text-text-secondary">
                    {songsRemaining > 0 ? (
                      <>
                        <span className="text-text-secondary font-medium">{songsRemaining}</span> of {freeSongsLimit} free songs
                      </>
                    ) : (
                      <span className="text-amber-400">Limit reached</span>
                    )}
                  </span>
                </div>
                <div className="w-full h-1.5 bg-muted rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full ${
                      songsRemaining === 0 ? 'bg-amber-500' : 'bg-blue-500'
                    }`}
                    style={{ width: `${((freeSongsLimit - songsRemaining) / freeSongsLimit) * 100}%` }}
                  />
                </div>
              </div>
            )}
          </div>

          {/* Actions */}
          <div className="py-1">
            <button
              onClick={handleManageClick}
              className="w-full text-left px-4 py-2 text-sm text-text-secondary hover:bg-muted transition-colors"
            >
              {isSubscribed ? 'Manage subscription' : 'Upgrade to Pro'}
            </button>
            <button
              onClick={handleCheckForUpdates}
              disabled={updateStatus === 'checking'}
              className={`w-full text-left px-4 py-2 text-sm transition-colors ${
                updateStatus === 'up-to-date'
                  ? 'text-green-400'
                  : updateStatus === 'error'
                    ? 'text-red-400'
                    : updateStatus === 'checking'
                      ? 'text-text-disabled cursor-wait'
                      : 'text-text-secondary hover:bg-muted'
              }`}
            >
              {updateLabel}
            </button>
            <button
              onClick={handleSignOut}
              className="w-full text-left px-4 py-2 text-sm text-text-secondary hover:bg-muted hover:text-text-secondary transition-colors"
            >
              Sign out
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
