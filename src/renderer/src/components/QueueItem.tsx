import type { SongEntry, SongStatus } from '../types'

interface QueueItemProps {
  song: SongEntry
  isExpanded: boolean
  onToggleExpand: () => void
  onRemove: () => void
  onRetry: () => void
}

function getStatusBadge(status: SongStatus, errorMessage: string | null) {
  const badges: Record<SongStatus, { label: string; className: string }> = {
    pending: { label: 'Pending', className: 'bg-zinc-700 text-zinc-300' },
    transcribing: { label: 'Transcribing', className: 'bg-blue-600 text-blue-100' },
    separating: { label: 'Separating', className: 'bg-purple-600 text-purple-100' },
    ready: { label: 'Ready', className: 'bg-green-600 text-green-100' },
    exporting: { label: 'Exporting', className: 'bg-yellow-600 text-yellow-100' },
    completed: { label: 'Completed', className: 'bg-emerald-600 text-emerald-100' },
    error: { label: 'Error', className: 'bg-red-600 text-red-100' }
  }

  const badge = badges[status]
  return (
    <span
      className={`px-2 py-0.5 rounded text-xs font-medium ${badge.className}`}
      title={status === 'error' ? errorMessage || 'Unknown error' : undefined}
    >
      {badge.label}
    </span>
  )
}

function formatDuration(seconds: number): string {
  const mins = Math.floor(seconds / 60)
  const secs = Math.floor(seconds % 60)
  return `${mins}:${secs.toString().padStart(2, '0')}`
}

export default function QueueItem({
  song,
  isExpanded,
  onToggleExpand,
  onRemove,
  onRetry
}: QueueItemProps): React.JSX.Element {
  const isProcessing = song.status === 'transcribing' || song.status === 'separating' || song.status === 'exporting'
  const canExpand = song.status === 'ready' || song.status === 'completed' || song.status === 'error'
  const profanityCount = song.words.filter((w) => w.is_profanity).length

  return (
    <div
      className={`
        border rounded-lg transition-all
        ${isExpanded ? 'border-blue-500 bg-zinc-900' : 'border-zinc-800 bg-zinc-900/50 hover:border-zinc-700'}
        ${song.status === 'error' ? 'border-red-800' : ''}
      `}
    >
      {/* Main row */}
      <div
        className={`flex items-center gap-3 px-4 py-3 ${canExpand ? 'cursor-pointer' : ''}`}
        onClick={canExpand ? onToggleExpand : undefined}
      >
        {/* Expand/collapse indicator */}
        <span className={`text-zinc-500 transition-transform ${isExpanded ? 'rotate-90' : ''}`}>
          {canExpand ? '▶' : '○'}
        </span>

        {/* File info */}
        <div className="flex-1 min-w-0">
          <p className="font-medium truncate">{song.fileName}</p>
          <div className="flex items-center gap-3 text-xs text-zinc-500">
            {song.duration > 0 && <span>{formatDuration(song.duration)}</span>}
            {song.language && <span>{song.language.toUpperCase()}</span>}
            {song.words.length > 0 && (
              <span>
                {profanityCount} profan{profanityCount === 1 ? 'e' : 'ities'} / {song.words.length} words
              </span>
            )}
            {song.userReviewed && (
              <span className="text-green-500">Reviewed</span>
            )}
          </div>
        </div>

        {/* Status badge */}
        <div className="flex items-center gap-2">
          {getStatusBadge(song.status, song.errorMessage)}
        </div>

        {/* Actions */}
        <div className="flex items-center gap-2">
          {song.status === 'error' && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onRetry()
              }}
              className="px-2 py-1 text-xs bg-zinc-700 hover:bg-zinc-600 rounded transition-colors"
            >
              Retry
            </button>
          )}
          {!isProcessing && (
            <button
              onClick={(e) => {
                e.stopPropagation()
                onRemove()
              }}
              className="p-1 text-zinc-500 hover:text-red-400 transition-colors"
              title="Remove from queue"
            >
              ✕
            </button>
          )}
        </div>
      </div>

      {/* Progress bar for processing states */}
      {song.status === 'separating' && song.separationProgress && (
        <div className="px-4 pb-3">
          <div className="flex items-center justify-between mb-1 text-xs text-zinc-500">
            <span>{song.separationProgress.message}</span>
            <span>{Math.round(song.separationProgress.progress)}%</span>
          </div>
          <div className="w-full h-1.5 bg-zinc-800 rounded-full overflow-hidden">
            <div
              className="h-full bg-purple-500 rounded-full transition-all duration-300"
              style={{ width: `${song.separationProgress.progress}%` }}
            />
          </div>
        </div>
      )}

      {/* Processing indicator */}
      {song.status === 'transcribing' && (
        <div className="px-4 pb-3">
          <div className="flex items-center gap-2 text-xs text-zinc-500">
            <div className="w-3 h-3 border-2 border-zinc-600 border-t-blue-400 rounded-full animate-spin" />
            <span>Transcribing audio...</span>
          </div>
        </div>
      )}

      {/* Error message */}
      {song.status === 'error' && song.errorMessage && (
        <div className="px-4 pb-3">
          <p className="text-xs text-red-400">{song.errorMessage}</p>
        </div>
      )}
    </div>
  )
}
