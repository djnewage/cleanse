import { useState, useCallback } from 'react'

interface CustomWordListProps {
  words: string[]
  onAddWord: (word: string) => void
  onRemoveWord: (word: string) => void
  onClose: () => void
}

export default function CustomWordList({
  words,
  onAddWord,
  onRemoveWord,
  onClose
}: CustomWordListProps): React.JSX.Element {
  const [input, setInput] = useState('')

  const handleAdd = useCallback(() => {
    const trimmed = input.trim().toLowerCase()
    if (trimmed && !words.includes(trimmed)) {
      onAddWord(trimmed)
      setInput('')
    }
  }, [input, words, onAddWord])

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter') handleAdd()
      if (e.key === 'Escape') onClose()
    },
    [handleAdd, onClose]
  )

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-surface border border-border-strong rounded-xl p-5 w-96 max-h-[70vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-semibold text-text-primary">Custom Word List</h3>
          <button onClick={onClose} className="text-text-tertiary hover:text-text-primary text-lg">
            ✕
          </button>
        </div>

        <p className="text-xs text-text-tertiary mb-3">
          Words added here will be automatically flagged as profanity in all songs.
        </p>

        <div className="flex gap-2 mb-4">
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Add a word..."
            autoFocus
            className="flex-1 px-3 py-2 bg-elevated border border-border-strong rounded-lg text-sm text-text-primary placeholder-text-disabled focus:outline-none focus:border-blue-500"
          />
          <button
            onClick={handleAdd}
            disabled={!input.trim() || words.includes(input.trim().toLowerCase())}
            className={`px-4 py-2 text-sm rounded-lg font-medium transition-colors ${
              input.trim() && !words.includes(input.trim().toLowerCase())
                ? 'bg-blue-600 text-white hover:bg-blue-500'
                : 'bg-muted text-text-disabled cursor-not-allowed'
            }`}
          >
            Add
          </button>
        </div>

        <div className="flex-1 overflow-y-auto min-h-0">
          {words.length === 0 ? (
            <p className="text-sm text-text-disabled text-center py-6">
              No custom words added yet
            </p>
          ) : (
            <div className="space-y-1">
              {words.map((word) => (
                <div
                  key={word}
                  className="flex items-center justify-between px-3 py-2 bg-elevated/50 rounded-lg group"
                >
                  <span className="text-sm text-text-primary font-mono">{word}</span>
                  <button
                    onClick={() => onRemoveWord(word)}
                    className="text-text-disabled hover:text-red-400 text-xs opacity-0 group-hover:opacity-100 transition-opacity"
                  >
                    Remove
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {words.length > 0 && (
          <p className="text-[10px] text-text-disabled mt-3 text-center">
            {words.length} custom word{words.length !== 1 ? 's' : ''} — applied to all songs
          </p>
        )}
      </div>
    </div>
  )
}
