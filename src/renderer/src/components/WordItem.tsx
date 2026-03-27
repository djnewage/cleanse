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
  onSetCensorType: (index: number, type: CensorType | undefined) => void
  onRemoveWord: (index: number) => void
  playbackStatus?: PlaybackStatus
  itemRef?: React.Ref<HTMLButtonElement>
}

function WordItemInner({
  word,
  index,
  defaultCensorType,
  onToggle,
  onSetCensorType,
  onRemoveWord,
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
      const currentIdx = CENSOR_CYCLE.indexOf(current)
      const nextIdx = currentIdx + 1
      if (nextIdx >= CENSOR_CYCLE.length) {
        // Cycled past last type — reset to song default
        onSetCensorType(index, undefined)
      } else {
        onSetCensorType(index, CENSOR_CYCLE[nextIdx])
      }
    },
    [index, word.is_profanity, word.censor_type, defaultCensorType, onSetCensorType]
  )

  const handleRemove = useCallback(
    (e: React.MouseEvent) => {
      e.stopPropagation()
      e.preventDefault()
      onRemoveWord(index)
    },
    [index, onRemoveWord]
  )

  const formatTime = (seconds: number): string => {
    const m = Math.floor(seconds / 60)
    const s = Math.floor(seconds % 60)
    return `${m}:${s.toString().padStart(2, '0')}`
  }

  const effectiveType = word.censor_type ?? defaultCensorType
  const hasOverride = word.censor_type !== undefined
  const isAdlib = word.detection_source === 'adlib'
  const isManual = word.detection_source === 'manual'

  // Determine styling based on playback status
  let statusClasses: string
  if (playbackStatus === 'active') {
    statusClasses = word.is_profanity
      ? 'bg-amber-500/70 text-white ring-1 ring-amber-400/60 shadow-[0_0_8px_rgba(245,158,11,0.4)] scale-105 karaoke-active'
      : 'bg-sky-500/60 text-white shadow-[0_0_8px_rgba(56,189,248,0.35)] scale-105 karaoke-active'
  } else if (playbackStatus === 'played') {
    if (word.is_profanity && isAdlib) {
      statusClasses = 'bg-adlib-bg-played text-adlib-text-played ring-1 ring-adlib-ring-played'
    } else {
      statusClasses = word.is_profanity
        ? 'bg-profanity-bg-played text-profanity-text-played ring-1 ring-profanity-ring-played'
        : 'bg-muted/60 text-text-disabled'
    }
  } else {
    // upcoming or undefined (no playback)
    if (word.is_profanity && isAdlib) {
      statusClasses = 'bg-adlib-bg text-adlib-text hover:bg-adlib-hover ring-1 ring-adlib-ring'
    } else {
      statusClasses = word.is_profanity
        ? 'bg-profanity-bg text-profanity-text hover:bg-profanity-hover ring-1 ring-profanity-ring'
        : 'bg-muted/50 text-text-primary hover:bg-muted'
    }
  }

  return (
    <button
      ref={itemRef}
      onClick={handleClick}
      onContextMenu={handleContextMenu}
      title={`${formatTime(word.start)} - ${formatTime(word.end)} (${Math.round(word.confidence * 100)}%)${word.is_profanity ? `\nCensor: ${effectiveType}${hasOverride ? '' : ' (default)'}\nRight-click to change` : ''}`}
      className={`
        group relative inline-flex items-baseline gap-0.5 px-1.5 py-0.5 m-0.5 rounded text-sm font-mono
        transition-all duration-200 ease-out outline-none
        focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-1 focus-visible:ring-offset-surface
        ${statusClasses}
      `}
    >
      {word.word}
      {word.is_profanity && (
        <span
          className={`text-[9px] leading-none font-sans font-bold ${
            hasOverride ? 'text-blue-400' : 'text-text-tertiary'
          }`}
        >
          {CENSOR_LABEL[effectiveType]}
        </span>
      )}
      {word.detection_source === 'manual' && (
        <span className="text-[8px] leading-none font-sans font-semibold text-purple-400 ml-0.5">
          MN
        </span>
      )}
      {isManual && (
        <span
          onClick={handleRemove}
          onContextMenu={(e) => e.stopPropagation()}
          className="absolute -top-1.5 -right-1.5 hidden group-hover:flex items-center justify-center w-3.5 h-3.5 rounded-full bg-muted hover:bg-red-600 text-text-secondary hover:text-white text-[9px] leading-none cursor-pointer transition-colors"
          title="Remove manual censor"
        >
          &times;
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
    prev.onRemoveWord === next.onRemoveWord &&
    prev.playbackStatus === next.playbackStatus
  )
})

export default WordItem
