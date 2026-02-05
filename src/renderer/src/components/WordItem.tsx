import { useCallback } from 'react'
import type { TranscribedWord, CensorType } from '../types'

const CENSOR_CYCLE: CensorType[] = ['mute', 'beep', 'reverse']
const CENSOR_LABEL: Record<CensorType, string> = { mute: 'M', beep: 'B', reverse: 'R' }

interface WordItemProps {
  word: TranscribedWord
  index: number
  defaultCensorType: CensorType
  onToggle: (index: number) => void
  onSetCensorType: (index: number, type: CensorType) => void
}

export default function WordItem({
  word,
  index,
  defaultCensorType,
  onToggle,
  onSetCensorType
}: WordItemProps): React.JSX.Element {
  const handleClick = useCallback(() => {
    onToggle(index)
  }, [index, onToggle])

  const handleContextMenu = useCallback(
    (e: React.MouseEvent) => {
      if (!word.is_profanity) return
      e.preventDefault()
      const current = word.censor_type ?? defaultCensorType
      const nextIdx = (CENSOR_CYCLE.indexOf(current) + 1) % CENSOR_CYCLE.length
      onSetCensorType(index, CENSOR_CYCLE[nextIdx])
    },
    [index, word.is_profanity, word.censor_type, defaultCensorType, onSetCensorType]
  )

  const formatTime = (seconds: number): string => {
    const m = Math.floor(seconds / 60)
    const s = Math.floor(seconds % 60)
    return `${m}:${s.toString().padStart(2, '0')}`
  }

  const effectiveType = word.censor_type ?? defaultCensorType
  const hasOverride = word.censor_type !== undefined

  return (
    <button
      onClick={handleClick}
      onContextMenu={handleContextMenu}
      title={`${formatTime(word.start)} - ${formatTime(word.end)} (${Math.round(word.confidence * 100)}%)${word.is_profanity ? `\nCensor: ${effectiveType}${hasOverride ? '' : ' (default)'}\nRight-click to change` : ''}`}
      className={`
        inline-flex items-baseline gap-0.5 px-1.5 py-0.5 m-0.5 rounded text-sm font-mono transition-colors
        ${
          word.is_profanity
            ? 'bg-red-900/60 text-red-300 hover:bg-red-800/60 ring-1 ring-red-500/50'
            : 'bg-zinc-800/40 text-zinc-300 hover:bg-zinc-700/50'
        }
      `}
    >
      {word.word}
      {word.is_profanity && (
        <span
          className={`text-[9px] leading-none font-sans font-bold ${
            hasOverride ? 'text-blue-400' : 'text-zinc-500'
          }`}
        >
          {CENSOR_LABEL[effectiveType]}
        </span>
      )}
    </button>
  )
}
