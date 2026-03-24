import { useState, useEffect, useCallback } from 'react'
import type { TranscribedWord } from '../types'

interface AddCensorFormProps {
  currentTime: number
  duration: number
  onConfirm: (word: TranscribedWord) => void
  onCancel: () => void
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = seconds % 60
  const whole = Math.floor(s)
  const tenths = Math.floor((s - whole) * 10)
  return `${m}:${String(whole).padStart(2, '0')}.${tenths}`
}

function parseTimeStr(str: string): number | null {
  const trimmed = str.trim()
  // Accepts: "1:23.4", "1:23", "83.4", "83"
  const colonMatch = trimmed.match(/^(\d+):(\d{1,2})(?:\.(\d))?$/)
  if (colonMatch) {
    const m = parseInt(colonMatch[1], 10)
    const s = parseInt(colonMatch[2], 10)
    const tenths = colonMatch[3] ? parseInt(colonMatch[3], 10) : 0
    if (s >= 60) return null
    return m * 60 + s + tenths / 10
  }
  // Plain number with optional decimal
  const num = parseFloat(trimmed)
  if (!isNaN(num) && num >= 0) return Math.round(num * 10) / 10
  return null
}

export default function AddCensorForm({
  currentTime,
  duration,
  onConfirm,
  onCancel
}: AddCensorFormProps): React.JSX.Element {
  const [wordText, setWordText] = useState('')
  const [startStr, setStartStr] = useState('')
  const [endStr, setEndStr] = useState('')

  useEffect(() => {
    const startTotal = Math.max(0, currentTime)
    const endTotal = Math.min(startTotal + 0.5, duration)
    setStartStr(formatTime(startTotal))
    setEndStr(formatTime(endTotal))
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const startTime = parseTimeStr(startStr)
  const endTime = parseTimeStr(endStr)
  const isValid =
    wordText.trim().length > 0 &&
    startTime !== null &&
    endTime !== null &&
    endTime > startTime &&
    startTime >= 0 &&
    endTime <= duration + 0.5

  const handleConfirm = (): void => {
    if (!isValid || startTime === null || endTime === null) return
    onConfirm({
      word: wordText.trim(),
      start: startTime,
      end: endTime,
      confidence: 1,
      is_profanity: true,
      detection_source: 'manual'
    })
  }

  const handleKeyDown = (e: React.KeyboardEvent): void => {
    if (e.key === 'Enter' && isValid) handleConfirm()
    if (e.key === 'Escape') onCancel()
  }

  const useCurrentForStart = useCallback(() => {
    setStartStr(formatTime(currentTime))
  }, [currentTime])

  const useCurrentForEnd = useCallback(() => {
    setEndStr(formatTime(currentTime))
  }, [currentTime])

  return (
    <div
      className="bg-elevated/50 border border-border-strong rounded-lg p-3 space-y-3"
      onKeyDown={handleKeyDown}
    >
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-text-secondary">Add Manual Censor</span>
        <button onClick={onCancel} className="text-text-tertiary hover:text-text-primary text-sm">
          ✕
        </button>
      </div>

      <div>
        <label className="block text-xs text-text-tertiary mb-1">Word / phrase</label>
        <input
          type="text"
          value={wordText}
          onChange={(e) => setWordText(e.target.value)}
          placeholder="e.g. damn"
          autoFocus
          className="w-full px-2 py-1.5 bg-surface border border-border-strong rounded text-sm text-text-primary placeholder-text-disabled focus:outline-none focus:border-blue-500"
        />
      </div>

      <div className="flex gap-4">
        <div className="flex-1">
          <label className="block text-xs text-text-tertiary mb-1">Start time</label>
          <div className="flex items-center gap-1">
            <input
              type="text"
              value={startStr}
              onChange={(e) => setStartStr(e.target.value)}
              placeholder="0:00.0"
              className="flex-1 px-2 py-1.5 bg-surface border border-border-strong rounded text-sm text-text-primary font-mono text-center focus:outline-none focus:border-blue-500"
            />
            <button
              type="button"
              onClick={useCurrentForStart}
              title="Use current playback position"
              className="px-1.5 py-1.5 bg-surface border border-border-strong rounded text-text-tertiary hover:text-blue-400 hover:border-blue-500 transition-colors text-sm"
            >
              &#9201;
            </button>
          </div>
        </div>
        <div className="flex-1">
          <label className="block text-xs text-text-tertiary mb-1">End time</label>
          <div className="flex items-center gap-1">
            <input
              type="text"
              value={endStr}
              onChange={(e) => setEndStr(e.target.value)}
              placeholder="0:00.0"
              className="flex-1 px-2 py-1.5 bg-surface border border-border-strong rounded text-sm text-text-primary font-mono text-center focus:outline-none focus:border-blue-500"
            />
            <button
              type="button"
              onClick={useCurrentForEnd}
              title="Use current playback position"
              className="px-1.5 py-1.5 bg-surface border border-border-strong rounded text-text-tertiary hover:text-blue-400 hover:border-blue-500 transition-colors text-sm"
            >
              &#9201;
            </button>
          </div>
        </div>
      </div>

      <p className="text-[10px] text-text-disabled">
        Pause playback at the word, then click the clock buttons to set times
      </p>

      <div className="flex gap-2 justify-end">
        <button
          onClick={onCancel}
          className="px-3 py-1.5 text-xs text-text-secondary hover:text-text-primary transition-colors"
        >
          Cancel
        </button>
        <button
          onClick={handleConfirm}
          disabled={!isValid}
          className={`px-3 py-1.5 text-xs rounded font-medium transition-colors ${
            isValid
              ? 'bg-blue-600 text-white hover:bg-blue-500'
              : 'bg-muted text-text-tertiary cursor-not-allowed'
          }`}
        >
          Add
        </button>
      </div>
    </div>
  )
}
