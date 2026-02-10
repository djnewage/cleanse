import type { DeviceInfo } from '../types'

interface TurboToggleProps {
  turboEnabled: boolean
  deviceInfo: DeviceInfo | null
  isProcessing: boolean
  onToggle: (enabled: boolean) => void
}

export default function TurboToggle(
  _props: TurboToggleProps
): React.JSX.Element | null {
  // Temporarily hidden — turbo mode not working correctly
  return null
}
