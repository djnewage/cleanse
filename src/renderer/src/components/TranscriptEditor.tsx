import type { TranscribedWord, CensorType } from '../types'
import WordItem from './WordItem'

interface TranscriptEditorProps {
  words: TranscribedWord[]
  onToggleProfanity: (index: number) => void
  onSetCensorType: (index: number, type: CensorType) => void
  defaultCensorType: CensorType
  language: string
  duration: number
}

export default function TranscriptEditor({
  words,
  onToggleProfanity,
  onSetCensorType,
  defaultCensorType,
  language,
  duration
}: TranscriptEditorProps): React.JSX.Element {
  const profanityCount = words.filter((w) => w.is_profanity).length

  const formatDuration = (seconds: number): string => {
    const m = Math.floor(seconds / 60)
    const s = Math.floor(seconds % 60)
    return `${m}:${s.toString().padStart(2, '0')}`
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center justify-between text-sm text-zinc-400">
        <div className="flex gap-4">
          <span>Duration: {formatDuration(duration)}</span>
          <span>Language: {language.toUpperCase()}</span>
          <span>Words: {words.length}</span>
        </div>
        <div className="flex items-center gap-2">
          <span
            className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
              profanityCount > 0
                ? 'bg-red-900/50 text-red-300'
                : 'bg-green-900/50 text-green-300'
            }`}
          >
            {profanityCount > 0 ? `${profanityCount} flagged` : 'No profanity detected'}
          </span>
        </div>
      </div>

      <p className="text-xs text-zinc-500">
        Click a word to toggle its profanity flag. Right-click a flagged word to cycle censor type.
      </p>

      <div className="bg-zinc-900/50 rounded-lg p-4 max-h-80 overflow-y-auto border border-zinc-800">
        <div className="flex flex-wrap">
          {words.map((word, idx) => (
            <WordItem
              key={idx}
              word={word}
              index={idx}
              defaultCensorType={defaultCensorType}
              onToggle={onToggleProfanity}
              onSetCensorType={onSetCensorType}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
