import { useState, useEffect } from 'react'
import type { TranscribedWord } from '../types'

interface AddCensorFormProps {
  currentTime: number
  duration: number
  onConfirm: (word: TranscribedWord) => void
  onCancel: () => void
}

export default function AddCensorForm({
  currentTime,
  duration,
  onConfirm,
  onCancel
}: AddCensorFormProps): React.JSX.Element {
  const [wordText, setWordText] = useState('')
  const [startMin, setStartMin] = useState('')
  const [startSec, setStartSec] = useState('')
  const [endMin, setEndMin] = useState('')
  const [endSec, setEndSec] = useState('')

  useEffect(() => {
    const startTotal = Math.max(0, currentTime)
    const endTotal = Math.min(startTotal + 0.5, duration)
    setStartMin(String(Math.floor(startTotal / 60)))
    setStartSec(String(Math.floor(startTotal % 60)).padStart(2, '0'))
    setEndMin(String(Math.floor(endTotal / 60)))
    setEndSec(String(Math.ceil(endTotal % 60)).padStart(2, '0'))
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const parseTime = (min: string, sec: string): number | null => {
    const m = parseInt(min, 10)
    const s = parseInt(sec, 10)
    if (isNaN(m) || isNaN(s) || m < 0 || s < 0 || s >= 60) return null
    return m * 60 + s
  }

  const startTime = parseTime(startMin, startSec)
  const endTime = parseTime(endMin, endSec)
  const isValid =
    wordText.trim().length > 0 &&
    startTime !== null &&
    endTime !== null &&
    endTime > startTime &&
    startTime >= 0 &&
    endTime <= duration

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

  return (
    <div
      className="bg-zinc-800/50 border border-zinc-700 rounded-lg p-3 space-y-3"
      onKeyDown={handleKeyDown}
    >
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium text-zinc-300">Add Manual Censor</span>
        <button onClick={onCancel} className="text-zinc-500 hover:text-white text-sm">
          ✕
        </button>
      </div>

      <div>
        <label className="block text-xs text-zinc-500 mb-1">Word / phrase</label>
        <input
          type="text"
          value={wordText}
          onChange={(e) => setWordText(e.target.value)}
          placeholder="e.g. damn"
          autoFocus
          className="w-full px-2 py-1.5 bg-zinc-900 border border-zinc-700 rounded text-sm text-white placeholder-zinc-600 focus:outline-none focus:border-blue-500"
        />
      </div>

      <div className="flex gap-4">
        <div className="flex-1">
          <label className="block text-xs text-zinc-500 mb-1">Start time</label>
          <div className="flex items-center gap-1">
            <input
              type="number"
              min="0"
              value={startMin}
              onChange={(e) => setStartMin(e.target.value)}
              className="w-12 px-1.5 py-1.5 bg-zinc-900 border border-zinc-700 rounded text-sm text-white text-center focus:outline-none focus:border-blue-500"
            />
            <span className="text-zinc-500 text-sm">:</span>
            <input
              type="number"
              min="0"
              max="59"
              value={startSec}
              onChange={(e) => setStartSec(e.target.value)}
              className="w-12 px-1.5 py-1.5 bg-zinc-900 border border-zinc-700 rounded text-sm text-white text-center focus:outline-none focus:border-blue-500"
            />
          </div>
        </div>
        <div className="flex-1">
          <label className="block text-xs text-zinc-500 mb-1">End time</label>
          <div className="flex items-center gap-1">
            <input
              type="number"
              min="0"
              value={endMin}
              onChange={(e) => setEndMin(e.target.value)}
              className="w-12 px-1.5 py-1.5 bg-zinc-900 border border-zinc-700 rounded text-sm text-white text-center focus:outline-none focus:border-blue-500"
            />
            <span className="text-zinc-500 text-sm">:</span>
            <input
              type="number"
              min="0"
              max="59"
              value={endSec}
              onChange={(e) => setEndSec(e.target.value)}
              className="w-12 px-1.5 py-1.5 bg-zinc-900 border border-zinc-700 rounded text-sm text-white text-center focus:outline-none focus:border-blue-500"
            />
          </div>
        </div>
      </div>

      <div className="flex gap-2 justify-end">
        <button
          onClick={onCancel}
          className="px-3 py-1.5 text-xs text-zinc-400 hover:text-zinc-200 transition-colors"
        >
          Cancel
        </button>
        <button
          onClick={handleConfirm}
          disabled={!isValid}
          className={`px-3 py-1.5 text-xs rounded font-medium transition-colors ${
            isValid
              ? 'bg-blue-600 text-white hover:bg-blue-500'
              : 'bg-zinc-700 text-zinc-500 cursor-not-allowed'
          }`}
        >
          Add
        </button>
      </div>
    </div>
  )
}
