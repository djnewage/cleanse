interface AudioPreviewProps {
  originalPath: string | null
  censoredPath: string | null
  onClearFile?: () => void
}

export default function AudioPreview({
  originalPath,
  censoredPath,
  onClearFile
}: AudioPreviewProps): React.JSX.Element {
  return (
    <div className="flex flex-col gap-4">
      {originalPath && (
        <div>
          <label className="block text-sm font-medium text-zinc-400 mb-1">Original</label>
          <audio key={originalPath} controls preload="auto" className="w-full" src={`media://${originalPath}`} />
        </div>
      )}
      {censoredPath && (
        <div>
          <label className="block text-sm font-medium text-green-400 mb-1">
            Censored Version
          </label>
          <audio key={censoredPath} controls preload="auto" className="w-full" src={`media://${censoredPath}`} />
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
