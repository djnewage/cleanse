import { useState } from 'react'
import type { SongEntry, CensorType, TranscribedWord } from '../types'
import TranscriptEditor from './TranscriptEditor'
import AudioPreview from './AudioPreview'
import { usePlaybackTime } from '../hooks/usePlaybackTime'

interface SongDetailPanelProps {
  song: SongEntry
  onToggleProfanity: (songId: string, wordIndex: number) => void
  onSetCensorType: (songId: string, wordIndex: number, censorType: CensorType) => void
  onSetSongCensorType: (songId: string, censorType: CensorType) => void
  onAddManualWord: (songId: string, word: TranscribedWord) => void
  onRemoveWord: (songId: string, wordIndex: number) => void
  onMarkReviewed: (songId: string) => void
  onClose: () => void
}

export default function SongDetailPanel({
  song,
  onToggleProfanity,
  onSetCensorType,
  onSetSongCensorType,
  onAddManualWord,
  onRemoveWord,
  onMarkReviewed,
  onClose
}: SongDetailPanelProps): React.JSX.Element {
  const { currentTime, isPlaying, audioRef } = usePlaybackTime()
  const [lyricsExpanded, setLyricsExpanded] = useState(false)

  const handleToggleProfanity = (index: number) => {
    onToggleProfanity(song.id, index)
  }

  const handleSetCensorType = (index: number, censorType: CensorType) => {
    onSetCensorType(song.id, index, censorType)
  }

  const handleAddManualWord = (word: TranscribedWord) => {
    onAddManualWord(song.id, word)
  }

  const handleRemoveWord = (index: number) => {
    onRemoveWord(song.id, index)
  }

  const checkIfProfane = (word: string): boolean => {
    if (!word.trim()) return false

    // Remove punctuation from start/end
    const cleaned = word.trim().toLowerCase().replace(/^[^\w]+|[^\w]+$/g, '')
    if (!cleaned) return false

    // Common profanity list (matches backend custom_profanity.txt)
    const profanityList = [
      'fuck',
      'fuckin',
      'fucking',
      'shit',
      'bitch',
      'ass',
      'damn',
      'hell',
      'nigga',
      'niggas',
      'niggaz',
      'ho',
      'hoe',
      'hoes',
      'hos',
      'thot',
      'thots',
      'cunt',
      'pussy',
      'dick',
      'cock',
      'bastard'
    ]

    return profanityList.includes(cleaned)
  }

  const renderLyricsWithHighlights = (lyrics: string) => {
    // Split lyrics into words while preserving whitespace and line breaks
    const lines = lyrics.split('\n')

    return lines.map((line, lineIdx) => {
      const words = line.split(/(\s+)/) // Split by whitespace but keep delimiters

      return (
        <div key={lineIdx}>
          {words.map((word, wordIdx) => {
            // Check if this word (or its normalized form) is profane
            const isProfane = checkIfProfane(word)

            if (isProfane && word.trim()) {
              return (
                <span
                  key={wordIdx}
                  className="bg-red-900/40 text-red-300 px-0.5 rounded"
                  title="Profanity detected"
                >
                  {word}
                </span>
              )
            }
            return <span key={wordIdx}>{word}</span>
          })}
        </div>
      )
    })
  }

  const profanityCount = song.words.filter((w) => w.is_profanity).length

  // Show audio player during review (ready) or after export (completed)
  const showAudioPreview = song.status === 'ready' || song.censoredFilePath !== null

  return (
    <div className="mt-2 border-t border-zinc-800 pt-4 pb-2 px-4 space-y-4">
      {/* Header with close button */}
      <div className="flex items-center justify-between">
        <h3 className="font-medium">Edit: {song.fileName}</h3>
        <div className="flex items-center gap-3">
          {!song.userReviewed && (
            <button
              onClick={() => onMarkReviewed(song.id)}
              className="px-3 py-1.5 text-xs bg-green-600 hover:bg-green-500 text-white rounded transition-colors"
            >
              Mark as Reviewed
            </button>
          )}
          <button
            onClick={onClose}
            className="text-zinc-400 hover:text-white text-lg"
          >
            ✕
          </button>
        </div>
      </div>

      {/* Show error state if applicable */}
      {song.status === 'error' && (
        <div className="bg-red-950/50 border border-red-800 rounded-lg px-4 py-3">
          <p className="text-sm text-red-300">{song.errorMessage}</p>
        </div>
      )}

      {/* Fetched Lyrics Section */}
      {song.lyrics && (song.lyrics.plain || song.lyrics.synced) && (
        <div className="mb-6 rounded-lg border border-gray-700 bg-gray-800/50 p-4">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-sm font-semibold text-gray-300">
              Fetched Lyrics
              {song.lyrics.synced && (
                <span className="ml-2 rounded bg-green-900/30 px-2 py-0.5 text-xs text-green-400">
                  Synced
                </span>
              )}
            </h3>
            <button
              onClick={() => setLyricsExpanded(!lyricsExpanded)}
              className="text-xs text-gray-400 hover:text-gray-300"
            >
              {lyricsExpanded ? 'Collapse' : 'Expand'}
            </button>
          </div>

          {lyricsExpanded && song.lyrics.plain && (
            <div className="max-h-96 overflow-y-auto rounded bg-gray-900/50 p-3">
              <div className="text-xs leading-relaxed text-gray-300 font-mono whitespace-pre-wrap">
                {renderLyricsWithHighlights(song.lyrics.plain)}
              </div>
            </div>
          )}

          {!lyricsExpanded && (
            <p className="text-xs text-gray-500">
              {song.lyrics.plain
                ? `${song.lyrics.plain.split('\n').length} lines • Click Expand to view`
                : 'Synced lyrics available (timing data only)'}
            </p>
          )}
        </div>
      )}

      {/* Transcript editor */}
      {song.words.length > 0 && (
        <TranscriptEditor
          words={song.words}
          onToggleProfanity={handleToggleProfanity}
          onSetCensorType={handleSetCensorType}
          onAddManualWord={handleAddManualWord}
          onRemoveWord={handleRemoveWord}
          defaultCensorType={song.defaultCensorType}
          language={song.language}
          duration={song.duration}
          currentTime={currentTime}
          isPlaying={isPlaying}
        />
      )}

      {/* Song-level censor type selector */}
      <div className="flex items-center gap-4">
        <span
          className="text-xs text-zinc-500 cursor-help"
          title="Custom censor type for this song (overrides default)"
        >
          Censor type:
        </span>
        <div className="flex rounded-md overflow-hidden border border-zinc-700">
          {(['mute', 'beep', 'reverse', 'tape_stop'] as CensorType[]).map((type) => (
            <button
              key={type}
              onClick={() => onSetSongCensorType(song.id, type)}
              className={`
                px-2.5 py-1 text-xs font-medium transition-colors capitalize
                ${
                  song.defaultCensorType === type
                    ? 'bg-blue-600 text-white'
                    : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700 hover:text-zinc-300'
                }
              `}
            >
              {type}
            </button>
          ))}
        </div>
      </div>

      {/* Summary */}
      <div className="text-xs text-zinc-500 flex items-center gap-4">
        <span>{song.words.length} words total</span>
        <span>{profanityCount} marked for censoring</span>
        {song.userReviewed && <span className="text-green-400">User reviewed</span>}
        {song.censoredFilePath && <span className="text-emerald-400">Exported</span>}
      </div>

      {/* Audio preview: shown during review (ready) and after export */}
      {showAudioPreview && (
        <div className="pt-2">
          {/* Show preview generation status */}
          {song.isGeneratingPreview && (
            <div className="flex items-center gap-2 text-xs text-zinc-500 mb-3 px-3 py-2 bg-zinc-900 border border-zinc-800 rounded">
              <div className="w-3 h-3 border-2 border-zinc-600 border-t-blue-400 rounded-full animate-spin" />
              <span>Generating censored preview...</span>
            </div>
          )}

          {!song.isGeneratingPreview && !song.previewFilePath && !song.censoredFilePath && song.errorMessage && (
            <div className="text-xs text-red-400 mb-3 px-3 py-2 bg-red-900/20 border border-red-800 rounded">
              Preview failed: {song.errorMessage}
            </div>
          )}

          <AudioPreview
            originalPath={song.filePath}
            censoredPath={song.previewFilePath || song.censoredFilePath}
            audioRef={audioRef}
            onClearFile={song.censoredFilePath ? () => {} : undefined}
          />
        </div>
      )}
    </div>
  )
}
