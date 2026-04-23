import { useCallback, useRef } from 'react'
import { logPreviewPlayed } from '../lib/analytics'
import WaveformPlayer from './WaveformPlayer'

interface AudioPreviewProps {
  originalPath: string | null
  censoredPath: string | null
  onClearFile?: () => void
  audioRef?: (node: HTMLAudioElement | null) => void
}

export default function AudioPreview({
  originalPath,
  censoredPath,
  onClearFile,
  audioRef
}: AudioPreviewProps): React.JSX.Element {
  const primaryPath = censoredPath ?? originalPath
  const secondaryPath = censoredPath ? originalPath : null

  const loggedRef = useRef(false)
  const primaryNodeRef = useRef<HTMLAudioElement | null>(null)
  const secondaryNodeRef = useRef<HTMLAudioElement | null>(null)
  const primaryPauseRef = useRef<(() => void) | null>(null)
  const secondaryPauseRef = useRef<(() => void) | null>(null)

  // Attach audioRef to whichever element starts playing
  const activateElement = useCallback(
    (node: HTMLAudioElement | null) => {
      audioRef?.(node)
    },
    [audioRef]
  )

  const primaryRefCallback = useCallback(
    (node: HTMLAudioElement | null) => {
      primaryNodeRef.current = node
      // Default: attach ref to primary on mount
      activateElement(node)
    },
    [activateElement]
  )

  const secondaryRefCallback = useCallback(
    (node: HTMLAudioElement | null) => {
      secondaryNodeRef.current = node
    },
    []
  )

  const handlePrimaryPlay = useCallback(() => {
    // Pause the other player and switch karaoke tracking to this one
    secondaryPauseRef.current?.()
    activateElement(primaryNodeRef.current)
    if (!loggedRef.current) {
      logPreviewPlayed()
      loggedRef.current = true
    }
  }, [activateElement])

  const handleSecondaryPlay = useCallback(() => {
    // Pause the other player and switch karaoke tracking to this one
    primaryPauseRef.current?.()
    activateElement(secondaryNodeRef.current)
    if (!loggedRef.current) {
      logPreviewPlayed()
      loggedRef.current = true
    }
  }, [activateElement])

  return (
    <div className="flex flex-col gap-4">
      {secondaryPath && (
        <WaveformPlayer
          key={`secondary-${secondaryPath}`}
          src={`media://${encodeURIComponent(secondaryPath)}`}
          label="Original"
          onPlay={handleSecondaryPlay}
          audioRef={secondaryRefCallback}
          externalPauseRef={secondaryPauseRef}
        />
      )}
      {primaryPath && (
        <WaveformPlayer
          key={`primary-${primaryPath}`}
          src={`media://${encodeURIComponent(primaryPath)}`}
          label={censoredPath ? 'Censored Version' : 'Original'}
          labelColor={censoredPath ? 'text-green-400' : 'text-text-secondary'}
          onPlay={handlePrimaryPlay}
          audioRef={primaryRefCallback}
          externalPauseRef={primaryPauseRef}
        />
      )}
      {censoredPath && onClearFile && (
        <button
          onClick={onClearFile}
          className="mt-2 w-full py-3 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-semibold transition-colors"
        >
          Cleanse Another Song
        </button>
      )}
    </div>
  )
}
