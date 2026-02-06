import type { HistoryEntry } from '../types'
import HistoryItem from './HistoryItem'

interface HistoryListProps {
  history: HistoryEntry[]
  onDelete: (id: string) => void
}

export default function HistoryList({ history, onDelete }: HistoryListProps): React.JSX.Element | null {
  if (history.length === 0) return null

  return (
    <div className="flex flex-col gap-3">
      <h2 className="text-sm font-semibold text-zinc-400 uppercase tracking-wider">
        Recently Cleansed
      </h2>
      <div className="flex flex-col gap-2">
        {history.map((entry) => (
          <HistoryItem key={entry.id} entry={entry} onDelete={onDelete} />
        ))}
      </div>
    </div>
  )
}
