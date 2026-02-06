import { useAuth } from '../contexts/AuthContext'
import type { DeviceInfo } from '../types'

interface TurboToggleProps {
  turboEnabled: boolean
  deviceInfo: DeviceInfo | null
  isProcessing: boolean
  onToggle: (enabled: boolean) => void
}

export default function TurboToggle({
  turboEnabled,
  deviceInfo,
  isProcessing,
  onToggle
}: TurboToggleProps): React.JSX.Element | null {
  // Temporarily hidden — turbo mode not working correctly
  return null
  const { isSubscribed } = useAuth()

  if (!isSubscribed) return null

  const noGpu = !deviceInfo || !deviceInfo.gpu_available
  const disabled = noGpu || isProcessing

  let tooltip = ''
  if (noGpu) {
    tooltip = 'No compatible GPU detected'
  } else if (isProcessing) {
    tooltip = 'Cannot change while processing'
  }

  return (
    <div className="flex items-center gap-2" title={tooltip}>
      <button
        onClick={() => onToggle(!turboEnabled)}
        disabled={disabled}
        className={`
          relative inline-flex h-5 w-9 items-center rounded-full transition-colors
          ${disabled ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}
          ${turboEnabled && !disabled ? 'bg-blue-600' : 'bg-zinc-600'}
        `}
      >
        <span
          className={`
            inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform
            ${turboEnabled && !disabled ? 'translate-x-4.5' : 'translate-x-0.5'}
          `}
        />
      </button>
      <span className="text-xs text-zinc-400">Turbo</span>
      {turboEnabled && deviceInfo && !noGpu && (
        <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-600/20 text-blue-400 font-medium">
          {deviceInfo.device_type.toUpperCase()}
        </span>
      )}
    </div>
  )
}
