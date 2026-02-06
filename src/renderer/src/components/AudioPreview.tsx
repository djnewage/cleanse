import { useCallback } from 'react'

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
  // The primary audio element is censored if available, else original.
  // We use a combined ref callback to attach the external audioRef to the primary element.
  const primaryPath = censoredPath ?? originalPath
  const secondaryPath = censoredPath ? originalPath : null

  const primaryRefCallback = useCallback(
    (node: HTMLAudioElement | null) => {
      audioRef?.(node)
    },
    [audioRef]
  )

  return (
    <div className="flex flex-col gap-4">
      {secondaryPath && (
        <div>
          <label className="block text-sm font-medium text-zinc-400 mb-1">Original</label>
          <audio key={secondaryPath} controls preload="auto" className="w-full" src={`media://${secondaryPath}`} />
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
