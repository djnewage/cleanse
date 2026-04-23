import { useRef, useEffect, useCallback, useState, useMemo } from 'react'
import type { TranscribedWord, CensorType } from '../types'
import type { PlaybackStatus } from './WordItem'
import WordItem from './WordItem'
import AddCensorForm from './AddCensorForm'
import { useActiveWordIndex } from '../hooks/useActiveWordIndex'

interface TranscriptEditorProps {
  words: TranscribedWord[]
  onToggleProfanity: (index: number) => void
  onSetCensorType: (index: number, type: CensorType | undefined) => void
  onAddManualWord: (word: TranscribedWord) => void
  onRemoveWord: (index: number) => void
  defaultCensorType: CensorType
  language: string
  duration: number
  currentTime?: number
  isPlaying?: boolean
  onSeekTo?: (time: number) => void
  onTogglePlayback?: () => void
}

export default function TranscriptEditor({
  words,
  onToggleProfanity,
  onSetCensorType,
  onAddManualWord,
  onRemoveWord,
  defaultCensorType,
  language,
  duration,
  currentTime = 0,
  isPlaying = false,
  onSeekTo,
  onTogglePlayback
}: TranscriptEditorProps): React.JSX.Element {
  const profanityCount = words.filter((w) => w.is_profanity).length
  const activeIndex = useActiveWordIndex(words, currentTime)
  const wordRefsMap = useRef<Map<number, HTMLButtonElement>>(new Map())
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const [showAddForm, setShowAddForm] = useState(false)
  const [followLyrics, setFollowLyrics] = useState<boolean>(
    () => localStorage.getItem('cleanse-follow-lyrics') !== 'false'
  )

  useEffect(() => {
    localStorage.setItem('cleanse-follow-lyrics', String(followLyrics))
  }, [followLyrics])

  // Scroll the word into view within the transcript container only — never scrolls the page.
  // scrollIntoView() would scroll all scrollable ancestors (including the document), which
  // yanks the user back up when they've scrolled the page down to reach UI below this panel.
  const scrollWordIntoContainer = useCallback((wordIdx: number) => {
    const container = scrollContainerRef.current
    const el = wordRefsMap.current.get(wordIdx)
    if (!container || !el) return
    const containerRect = container.getBoundingClientRect()
    const elRect = el.getBoundingClientRect()
    if (elRect.top < containerRect.top) {
      container.scrollTop += elRect.top - containerRect.top
    } else if (elRect.bottom > containerRect.bottom) {
      container.scrollTop += elRect.bottom - containerRect.bottom
    }
  }, [])

  // Keyboard navigation between flagged words
  const profanityIndices = useMemo(
    () => words.map((w, i) => (w.is_profanity ? i : -1)).filter((i) => i >= 0),
    [words]
  )
  const [focusedProfanityPos, setFocusedProfanityPos] = useState(-1)

  // Reset focused position when profanity flags change
  useEffect(() => {
    setFocusedProfanityPos(-1)
  }, [profanityIndices.length])

  const navigateProfanity = useCallback(
    (delta: 1 | -1) => {
      if (profanityIndices.length === 0) return
      const nextPos =
        delta === 1
          ? focusedProfanityPos < profanityIndices.length - 1
            ? focusedProfanityPos + 1
            : 0
          : focusedProfanityPos > 0
            ? focusedProfanityPos - 1
            : profanityIndices.length - 1

      setFocusedProfanityPos(nextPos)
      const wordIdx = profanityIndices[nextPos]
      const el = wordRefsMap.current.get(wordIdx)
      if (el) {
        scrollWordIntoContainer(wordIdx)
        el.focus({ preventScroll: true })
      }
      const word = words[wordIdx]
      if (word && onSeekTo) {
        onSeekTo(word.start)
      }
    },
    [profanityIndices, focusedProfanityPos, words, onSeekTo, scrollWordIntoContainer]
  )

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (profanityIndices.length === 0) return

      if (e.key === ' ') {
        e.preventDefault()
        onTogglePlayback?.()
        return
      }

      if (e.key === 'ArrowRight') {
        e.preventDefault()
        navigateProfanity(1)
      } else if (e.key === 'ArrowLeft') {
        e.preventDefault()
        navigateProfanity(-1)
      }
    },
    [profanityIndices, navigateProfanity, onTogglePlayback]
  )

  const handleAddManualWord = (word: TranscribedWord): void => {
    onAddManualWord(word)
    setShowAddForm(false)
  }

  const formatDuration = (seconds: number): string => {
    const m = Math.floor(seconds / 60)
    const s = Math.floor(seconds % 60)
    return `${m}:${s.toString().padStart(2, '0')}`
  }

  // Auto-scroll active word into the transcript panel only (does not scroll the page).
  useEffect(() => {
    if (!followLyrics || activeIndex < 0 || !isPlaying) return
    scrollWordIntoContainer(activeIndex)
  }, [activeIndex, isPlaying, followLyrics, scrollWordIntoContainer])

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
      <div className="flex items-center justify-between text-sm text-text-secondary">
        <div className="flex gap-4">
          <span>Duration: {formatDuration(duration)}</span>
          <span>Language: {language.toUpperCase()}</span>
          <span>Words: {words.length}</span>
        </div>
        <div className="flex items-center gap-2">
          {profanityIndices.length > 0 && (
            <div className="flex items-center gap-1" title="Jump between flagged words (← →)">
              <button
                onClick={() => navigateProfanity(-1)}
                aria-label="Previous flagged word"
                className="inline-flex items-center justify-center w-6 h-6 rounded bg-action-blue-bg text-action-blue-text hover:bg-action-blue-hover transition-colors"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="15 18 9 12 15 6" />
                </svg>
              </button>
              <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-surface text-text-secondary tabular-nums">
                {focusedProfanityPos >= 0 ? focusedProfanityPos + 1 : 0} / {profanityIndices.length}
              </span>
              <button
                onClick={() => navigateProfanity(1)}
                aria-label="Next flagged word"
                className="inline-flex items-center justify-center w-6 h-6 rounded bg-action-blue-bg text-action-blue-text hover:bg-action-blue-hover transition-colors"
              >
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="9 18 15 12 9 6" />
                </svg>
              </button>
            </div>
          )}
          <div
            className="flex items-center gap-2"
            title="When on, the transcript scrolls to follow the playing word"
          >
            <span className="text-xs text-text-secondary">Follow Lyrics</span>
            <button
              onClick={() => setFollowLyrics((v) => !v)}
              aria-label="Toggle follow lyrics"
              aria-pressed={followLyrics}
              className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors cursor-pointer ${
                followLyrics ? 'bg-blue-600' : 'bg-muted'
              }`}
            >
              <span
                className={`inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform ${
                  followLyrics ? 'translate-x-[18px]' : 'translate-x-[3px]'
                }`}
              />
            </button>
          </div>
          <button
            onClick={() => setShowAddForm(true)}
            className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-action-blue-bg text-action-blue-text hover:bg-action-blue-hover transition-colors"
          >
            + Add Censor
          </button>
          <span
            className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
              profanityCount > 0
                ? 'bg-action-red-bg text-action-red-text'
                : 'bg-action-green-bg text-action-green-text'
            }`}
          >
            {profanityCount > 0 ? `${profanityCount} flagged` : 'No profanity detected'}
          </span>
        </div>
      </div>

      <p className="text-xs text-text-tertiary">
        Click a word to toggle its profanity flag. Right-click a flagged word to cycle censor type.
        Use &quot;Add Censor&quot; to manually mark missed words. Click &times; on manually added words to remove them.
        Use &larr; &rarr; arrow keys to jump between flagged words.
        Adjusting Crossfade or Censor Range above will automatically update the preview.
      </p>

      <p className="text-xs text-warning-text bg-warning-bg border border-warning-border rounded px-3 py-2 mt-1">
        <strong>Note:</strong> AI transcription may not be 100% accurate and can miss profanities.
        Please review the transcript carefully and use &quot;Add Censor&quot; to manually flag any missed words.
      </p>

      {showAddForm && (
        <AddCensorForm
          currentTime={currentTime}
          duration={duration}
          onConfirm={handleAddManualWord}
          onCancel={() => setShowAddForm(false)}
        />
      )}

      <div
        ref={scrollContainerRef}
        tabIndex={0}
        onKeyDown={handleKeyDown}
        className="bg-surface/50 rounded-lg p-4 max-h-80 overflow-y-auto border border-border focus:outline-none focus-within:border-blue-500 transition-colors"
      >
        <div className="flex flex-wrap">
          {words.map((word, idx) => (
            <WordItem
              key={idx}
              word={word}
              index={idx}
              defaultCensorType={defaultCensorType}
              onToggle={onToggleProfanity}
              onSetCensorType={onSetCensorType}
              onRemoveWord={onRemoveWord}
              playbackStatus={getPlaybackStatus(word, idx)}
              itemRef={(node) => setWordRef(idx, node)}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
