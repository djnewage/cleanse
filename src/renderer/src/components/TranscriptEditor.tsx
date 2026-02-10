import { useRef, useEffect, useCallback, useState } from 'react'
import type { TranscribedWord, CensorType } from '../types'
import type { PlaybackStatus } from './WordItem'
import WordItem from './WordItem'
import AddCensorForm from './AddCensorForm'
import { useActiveWordIndex } from '../hooks/useActiveWordIndex'

interface TranscriptEditorProps {
  words: TranscribedWord[]
  onToggleProfanity: (index: number) => void
  onSetCensorType: (index: number, type: CensorType) => void
  onAddManualWord: (word: TranscribedWord) => void
  defaultCensorType: CensorType
  language: string
  duration: number
  currentTime?: number
  isPlaying?: boolean
}

export default function TranscriptEditor({
  words,
  onToggleProfanity,
  onSetCensorType,
  onAddManualWord,
  defaultCensorType,
  language,
  duration,
  currentTime = 0,
  isPlaying = false
}: TranscriptEditorProps): React.JSX.Element {
  const profanityCount = words.filter((w) => w.is_profanity).length
  const activeIndex = useActiveWordIndex(words, currentTime)
  const wordRefsMap = useRef<Map<number, HTMLButtonElement>>(new Map())
  const [showAddForm, setShowAddForm] = useState(false)

  const handleAddManualWord = (word: TranscribedWord): void => {
    onAddManualWord(word)
    setShowAddForm(false)
  }

  const formatDuration = (seconds: number): string => {
    const m = Math.floor(seconds / 60)
    const s = Math.floor(seconds % 60)
    return `${m}:${s.toString().padStart(2, '0')}`
  }

  // Auto-scroll to active word
  useEffect(() => {
    if (activeIndex < 0 || !isPlaying) return
    const el = wordRefsMap.current.get(activeIndex)
    if (el) {
      el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
    }
  }, [activeIndex, isPlaying])

  const setWordRef = useCallback((index: number, node: HTMLButtonElement | null) => {
    if (node) {
      wordRefsMap.current.set(index, node)
    } else {
      wordRefsMap.current.delete(index)
    }
  }, [])

  const getPlaybackStatus = (word: TranscribedWord, idx: number): PlaybackStatus | undefined => {
    // Only compute playback status when audio has started (currentTime > 0 or is playing)
    if (currentTime <= 0 && !isPlaying) return undefined

    if (idx === activeIndex) return 'active'
    if (word.end <= currentTime) return 'played'
    return 'upcoming'
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
          <button
            onClick={() => setShowAddForm(true)}
            className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-blue-900/50 text-blue-300 hover:bg-blue-800/50 transition-colors"
          >
            + Add Censor
          </button>
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
        Use &quot;Add Censor&quot; to manually mark missed words.
      </p>

      {showAddForm && (
        <AddCensorForm
          currentTime={currentTime}
          duration={duration}
          onConfirm={handleAddManualWord}
          onCancel={() => setShowAddForm(false)}
        />
      )}

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
              playbackStatus={getPlaybackStatus(word, idx)}
              itemRef={(node) => setWordRef(idx, node)}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
