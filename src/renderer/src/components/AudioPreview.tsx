interface AudioPreviewProps {
  originalPath: string | null
  censoredPath: string | null
}

export default function AudioPreview({
  originalPath,
  censoredPath
}: AudioPreviewProps): React.JSX.Element {
  return (
    <div className="flex flex-col gap-4">
      {originalPath && (
        <div>
          <label className="block text-sm font-medium text-zinc-400 mb-1">Original</label>
          <audio controls className="w-full" src={`media://${originalPath}`} />
        </div>
      )}
      {censoredPath && (
        <div>
          <label className="block text-sm font-medium text-green-400 mb-1">
            Censored Version
          </label>
          <audio controls className="w-full" src={`media://${censoredPath}`} />
        </div>
      )}
    </div>
  )
}
