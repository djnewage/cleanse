import type { SongEntry, CensorType } from '../types'
import QueueItem from './QueueItem'

interface QueueListProps {
  songs: SongEntry[]
  expandedSongId: string | null
  globalCensorType: CensorType
  onToggleExpand: (id: string) => void
  onRemoveSong: (id: string) => void
  onRetrySong: (id: string) => void
}

export default function QueueList({
  songs,
  expandedSongId,
  globalCensorType,
  onToggleExpand,
  onRemoveSong,
  onRetrySong
}: QueueListProps): React.JSX.Element {
  if (songs.length === 0) {
    return <></>
  }

  const pendingCount = songs.filter((s) => s.status === 'pending').length
  const processingCount = songs.filter((s) => s.status === 'transcribing' || s.status === 'separating').length
  const readyCount = songs.filter((s) => s.status === 'ready').length
  const completedCount = songs.filter((s) => s.status === 'completed').length
  const errorCount = songs.filter((s) => s.status === 'error').length

  return (
    <div className="space-y-3">
      {/* Header with stats */}
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">Queue ({songs.length} files)</h2>
        <div className="flex items-center gap-3 text-xs text-zinc-500">
          {pendingCount > 0 && <span>{pendingCount} pending</span>}
          {processingCount > 0 && <span className="text-blue-400">{processingCount} processing</span>}
          {readyCount > 0 && <span className="text-green-400">{readyCount} ready</span>}
          {completedCount > 0 && <span className="text-emerald-400">{completedCount} completed</span>}
          {errorCount > 0 && <span className="text-red-400">{errorCount} failed</span>}
        </div>
      </div>

      {/* Song items */}
      <div className="space-y-2">
        {songs.map((song) => (
          <QueueItem
            key={song.id}
            song={song}
            isExpanded={expandedSongId === song.id}
            globalCensorType={globalCensorType}
            onToggleExpand={() => onToggleExpand(song.id)}
            onRemove={() => onRemoveSong(song.id)}
            onRetry={() => onRetrySong(song.id)}
          />
        ))}
      </div>
    </div>
  )
}
