import React, { useCallback } from 'react'
import type { TranscribedWord, CensorType } from '../types'

export type PlaybackStatus = 'upcoming' | 'active' | 'played'

const CENSOR_CYCLE: CensorType[] = ['mute', 'beep', 'reverse', 'tape_stop']
const CENSOR_LABEL: Record<CensorType, string> = { mute: 'M', beep: 'B', reverse: 'R', tape_stop: 'T' }

interface WordItemProps {
  word: TranscribedWord
  index: number
  defaultCensorType: CensorType
  onToggle: (index: number) => void
  onSetCensorType: (index: number, type: CensorType) => void
  playbackStatus?: PlaybackStatus
  itemRef?: React.Ref<HTMLButtonElement>
}

function WordItemInner({
  word,
  index,
  defaultCensorType,
  onToggle,
  onSetCensorType,
  playbackStatus,
  itemRef
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

  // Determine styling based on playback status
  let statusClasses: string
  if (playbackStatus === 'active') {
    statusClasses = word.is_profanity
      ? 'bg-amber-500/70 text-white ring-1 ring-amber-400/60 shadow-[0_0_8px_rgba(245,158,11,0.4)] scale-105 karaoke-active'
      : 'bg-sky-500/60 text-white shadow-[0_0_8px_rgba(56,189,248,0.35)] scale-105 karaoke-active'
  } else if (playbackStatus === 'played') {
    statusClasses = word.is_profanity
      ? 'bg-red-900/40 text-red-400/70 ring-1 ring-red-500/30'
      : 'bg-sky-900/30 text-sky-300/50'
  } else {
    // upcoming or undefined (no playback)
    statusClasses = word.is_profanity
      ? 'bg-red-900/60 text-red-300 hover:bg-red-800/60 ring-1 ring-red-500/50'
      : 'bg-zinc-800/40 text-zinc-300 hover:bg-zinc-700/50'
  }

  return (
    <button
      ref={itemRef}
      onClick={handleClick}
      onContextMenu={handleContextMenu}
      title={`${formatTime(word.start)} - ${formatTime(word.end)} (${Math.round(word.confidence * 100)}%)${word.is_profanity ? `\nCensor: ${effectiveType}${hasOverride ? '' : ' (default)'}\nRight-click to change` : ''}`}
      className={`
        inline-flex items-baseline gap-0.5 px-1.5 py-0.5 m-0.5 rounded text-sm font-mono
        transition-all duration-200 ease-out
        ${statusClasses}
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
      {word.detection_source === 'adlib' && (
        <span className="text-[8px] leading-none font-sans font-semibold text-amber-400 ml-0.5">
          AD
        </span>
      )}
      {word.detection_source === 'lyrics' && (
        <span className="text-[8px] leading-none font-sans font-semibold text-cyan-400 ml-0.5">
          LY
        </span>
      )}
      {word.detection_source === 'manual' && (
        <span className="text-[8px] leading-none font-sans font-semibold text-purple-400 ml-0.5">
          MN
        </span>
      )}
    </button>
  )
}

const WordItem = React.memo(WordItemInner, (prev, next) => {
  return (
    prev.word === next.word &&
    prev.index === next.index &&
    prev.defaultCensorType === next.defaultCensorType &&
    prev.onToggle === next.onToggle &&
    prev.onSetCensorType === next.onSetCensorType &&
    prev.playbackStatus === next.playbackStatus
  )
})

export default WordItem
