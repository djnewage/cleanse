import { useState } from 'react'
import type { HistoryEntry } from '../types'

interface HistoryItemProps {
  entry: HistoryEntry
  onDelete: (id: string) => void
}

function formatDate(timestamp: number): string {
  const date = new Date(timestamp)
  return date.toLocaleDateString(undefined, {
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit'
  })
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.round(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

function truncateFilename(name: string, maxLen = 40): string {
  if (name.length <= maxLen) return name
  const ext = name.lastIndexOf('.')
  if (ext > 0) {
    const base = name.slice(0, ext)
    const extension = name.slice(ext)
    const available = maxLen - extension.length - 3
    if (available > 0) return base.slice(0, available) + '...' + extension
  }
  return name.slice(0, maxLen - 3) + '...'
}

export default function HistoryItem({ entry, onDelete }: HistoryItemProps): React.JSX.Element {
  const [expanded, setExpanded] = useState(false)

  return (
    <div className="bg-zinc-900/50 border border-zinc-800 rounded-lg overflow-hidden">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full text-left px-4 py-3 hover:bg-zinc-800/50 transition-colors flex items-center gap-3"
      >
        <span className="text-lg">{expanded ? '▾' : '▸'}</span>
        <div className="flex-1 min-w-0">
          <p className="font-medium text-sm truncate">
            {truncateFilename(entry.originalFileName)}
          </p>
          <div className="flex items-center gap-3 text-xs text-zinc-500 mt-0.5">
            <span>{formatDate(entry.dateCreated)}</span>
            <span>{formatDuration(entry.duration)}</span>
            <span>{entry.profanityCount} words censored</span>
          </div>
        </div>
        <span
          onClick={(e) => {
            e.stopPropagation()
            onDelete(entry.id)
          }}
          className="text-zinc-600 hover:text-red-400 transition-colors p-1 text-sm"
          title="Remove from history"
        >
          &times;
        </span>
      </button>
      {expanded && (
        <div className="px-4 pb-3 border-t border-zinc-800/50">
          <audio
            controls
            preload="auto"
            className="w-full mt-2"
            src={`media://${entry.censoredFilePath}`}
          />
        </div>
      )}
    </div>
  )
}
