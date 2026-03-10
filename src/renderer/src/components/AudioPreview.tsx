import { useCallback, useRef } from 'react'
import { logPreviewPlayed } from '../lib/analytics'

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

  // Attach audioRef to whichever element starts playing, pause the other
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
    if (secondaryNodeRef.current && !secondaryNodeRef.current.paused) {
      secondaryNodeRef.current.pause()
    }
    activateElement(primaryNodeRef.current)
    if (!loggedRef.current) {
      logPreviewPlayed()
      loggedRef.current = true
    }
  }, [activateElement])

  const handleSecondaryPlay = useCallback(() => {
    // Pause the other player and switch karaoke tracking to this one
    if (primaryNodeRef.current && !primaryNodeRef.current.paused) {
      primaryNodeRef.current.pause()
    }
    activateElement(secondaryNodeRef.current)
    if (!loggedRef.current) {
      logPreviewPlayed()
      loggedRef.current = true
    }
  }, [activateElement])

  return (
    <div className="flex flex-col gap-4">
      {secondaryPath && (
        <div>
          <label className="block text-sm font-medium text-zinc-400 mb-1">Original</label>
          <audio
            ref={secondaryRefCallback}
            key={secondaryPath}
            controls
            preload="auto"
            className="w-full"
            src={`media://${secondaryPath}`}
            onPlay={handleSecondaryPlay}
          />
        </div>
      )}
      {primaryPath && (
        <div>
          <label className={`block text-sm font-medium mb-1 ${censoredPath ? 'text-green-400' : 'text-zinc-400'}`}>
            {censoredPath ? 'Censored Version' : 'Original'}
          </label>
          <audio
            ref={primaryRefCallback}
            key={primaryPath}
            controls
            preload="auto"
            className="w-full"
            src={`media://${primaryPath}`}
            onPlay={handlePrimaryPlay}
          />
        </div>
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
