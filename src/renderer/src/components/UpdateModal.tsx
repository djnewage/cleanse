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

// Render inline markdown: currently only **bold** — plain spans otherwise.
function renderInline(text: string, keyPrefix: string): React.JSX.Element[] {
  const parts: React.JSX.Element[] = []
  const regex = /\*\*([^*]+?)\*\*/g
  let lastEnd = 0
  let match: RegExpExecArray | null
  let i = 0
  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastEnd) {
      parts.push(<span key={`${keyPrefix}-${i++}`}>{text.slice(lastEnd, match.index)}</span>)
    }
    parts.push(
      <strong key={`${keyPrefix}-${i++}`} className="font-semibold text-text-primary">
        {match[1]}
      </strong>
    )
    lastEnd = match.index + match[0].length
  }
  if (lastEnd < text.length) {
    parts.push(<span key={`${keyPrefix}-${i++}`}>{text.slice(lastEnd)}</span>)
  }
  return parts.length > 0 ? parts : [<span key={`${keyPrefix}-0`}>{text}</span>]
}

// Render release notes as a narrow subset of markdown: ## headings, - bullets,
// **bold** inline, blank lines as spacing. Anything else renders as plain text.
function renderReleaseNotes(notes: string): React.JSX.Element[] {
  const lines = notes.split('\n')
  const out: React.JSX.Element[] = []
  lines.forEach((raw, idx) => {
    const line = raw.trimEnd()
    if (!line) {
      out.push(<div key={idx} className="h-2" />)
      return
    }
    if (line.startsWith('## ')) {
      out.push(
        <h3 key={idx} className="text-sm font-semibold text-text-primary mt-2 mb-1 first:mt-0">
          {renderInline(line.slice(3), `h${idx}`)}
        </h3>
      )
      return
    }
    if (line.startsWith('- ')) {
      out.push(
        <div key={idx} className="flex gap-2 pl-1">
          <span className="text-text-tertiary" aria-hidden>•</span>
          <span className="flex-1">{renderInline(line.slice(2), `b${idx}`)}</span>
        </div>
      )
      return
    }
    out.push(<div key={idx}>{renderInline(line, `p${idx}`)}</div>)
  })
  return out
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
        className="absolute inset-0 bg-overlay backdrop-blur-sm"
        onClick={onClose}
      />

      {/* Modal */}
      <div className="relative bg-surface rounded-xl border border-border p-6 max-w-md w-full mx-4 shadow-2xl">
        {/* Close button */}
        <button
          onClick={onClose}
          className="absolute top-4 right-4 text-text-tertiary hover:text-text-primary text-lg"
        >
          ✕
        </button>

        {/* Title */}
        <h2 className="text-xl font-bold text-text-primary mb-1">
          Update Available
        </h2>
        <p className="text-sm text-text-secondary mb-4">
          Cleanse v{version} is ready
        </p>

        {/* Release notes */}
        {releaseNotes && (
          <div className="bg-elevated/50 rounded-lg p-4 mb-6 max-h-48 overflow-y-auto">
            <p className="text-xs font-medium text-text-tertiary uppercase tracking-wide mb-2">
              What's new
            </p>
            <div className="text-sm text-text-secondary space-y-0.5">
              {renderReleaseNotes(releaseNotes)}
            </div>
          </div>
        )}

        {/* Download progress */}
        {isDownloading && (
          <div className="mb-6">
            <div className="flex justify-between items-center text-sm mb-2">
              <span className="text-text-secondary">Downloading...</span>
              <span className="text-text-primary font-medium">{Math.round(downloadProgress)}%</span>
            </div>
            <div className="h-2 bg-muted rounded-full overflow-hidden">
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
              className="w-full mt-3 py-2 text-sm text-text-tertiary hover:text-text-secondary transition-colors"
            >
              Later
            </button>
          </>
        ) : isDownloading ? (
          <button
            onClick={onClose}
            className="w-full py-3 rounded-lg font-medium text-sm text-text-tertiary hover:text-text-secondary transition-colors"
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
              className="w-full mt-3 py-2 text-sm text-text-tertiary hover:text-text-secondary transition-colors"
            >
              Maybe later
            </button>
          </>
        )}
      </div>
    </div>
  )
}
