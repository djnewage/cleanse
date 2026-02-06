interface UpdateModalProps {
  isOpen: boolean
  version: string
  releaseNotes: string
  downloadProgress: number | null
  downloaded: boolean
  onDownload: () => void
  onInstall: () => void
  onClose: () => void
}

export default function UpdateModal({
  isOpen,
  version,
  releaseNotes,
  downloadProgress,
  downloaded,
  onDownload,
  onInstall,
  onClose
}: UpdateModalProps): React.JSX.Element | null {
  if (!isOpen) return null

  const isDownloading = downloadProgress !== null && !downloaded

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/70 backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative bg-zinc-900 rounded-xl border border-zinc-800 p-6 max-w-md w-full mx-4 shadow-2xl">
        {/* Close button */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-zinc-500 hover:text-white text-lg"
        >
          ✕
        </button>

        {/* Title */}
        <h2 className="text-xl font-bold text-white mb-1">
          Update Available
        </h2>
        <p className="text-sm text-zinc-400 mb-4">
          Cleanse v{version} is ready
        </p>

        {/* Release notes */}
        {releaseNotes && (
          <div className="bg-zinc-800/50 rounded-lg p-4 mb-6 max-h-48 overflow-y-auto">
            <p className="text-xs font-medium text-zinc-500 uppercase tracking-wide mb-2">
              What's new
            </p>
            <div className="text-sm text-zinc-300 whitespace-pre-wrap">
              {releaseNotes}
            </div>
          </div>
        )}

        {/* Download progress */}
        {isDownloading && (
          <div className="mb-6">
            <div className="flex justify-between items-center text-sm mb-2">
              <span className="text-zinc-400">Downloading...</span>
              <span className="text-white font-medium">{Math.round(downloadProgress)}%</span>
            </div>
            <div className="h-2 bg-zinc-700 rounded-full overflow-hidden">
              <div
                className="h-full bg-blue-500 rounded-full transition-all duration-300"
                style={{ width: `${downloadProgress}%` }}
              />
            </div>
          </div>
        )}

        {/* Actions */}
        {downloaded ? (
          <>
            <button
              onClick={onInstall}
              className="w-full py-3 rounded-lg font-medium text-sm bg-blue-600 text-white hover:bg-blue-500 active:bg-blue-700 transition-colors"
            >
              Restart & Update
            </button>
            <button
              onClick={onClose}
              className="w-full mt-3 py-2 text-sm text-zinc-500 hover:text-zinc-300 transition-colors"
            >
              Later
            </button>
          </>
        ) : isDownloading ? (
          <button
            onClick={onClose}
            className="w-full py-3 rounded-lg font-medium text-sm text-zinc-500 hover:text-zinc-300 transition-colors"
          >
            Continue in background
          </button>
        ) : (
          <>
            <button
              onClick={onDownload}
              className="w-full py-3 rounded-lg font-medium text-sm bg-blue-600 text-white hover:bg-blue-500 active:bg-blue-700 transition-colors"
            >
              Download Update
            </button>
            <button
              onClick={onClose}
              className="w-full mt-3 py-2 text-sm text-zinc-500 hover:text-zinc-300 transition-colors"
            >
              Maybe later
            </button>
          </>
        )}
      </div>
    </div>
  )
}
