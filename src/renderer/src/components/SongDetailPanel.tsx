import type { SongEntry, CensorType } from '../types'
import TranscriptEditor from './TranscriptEditor'
import AudioPreview from './AudioPreview'
import { usePlaybackTime } from '../hooks/usePlaybackTime'

interface SongDetailPanelProps {
  song: SongEntry
  onToggleProfanity: (songId: string, wordIndex: number) => void
  onSetCensorType: (songId: string, wordIndex: number, censorType: CensorType) => void
  onSetSongCensorType: (songId: string, censorType: CensorType) => void
  onMarkReviewed: (songId: string) => void
  onClose: () => void
}

export default function SongDetailPanel({
  song,
  onToggleProfanity,
  onSetCensorType,
  onSetSongCensorType,
  onMarkReviewed,
  onClose
}: SongDetailPanelProps): React.JSX.Element {
  const { currentTime, isPlaying, audioRef } = usePlaybackTime()

  const handleToggleProfanity = (index: number) => {
    onToggleProfanity(song.id, index)
  }

  const handleSetCensorType = (index: number, censorType: CensorType) => {
    onSetCensorType(song.id, index, censorType)
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

      {/* Transcript editor */}
      {song.words.length > 0 && (
        <TranscriptEditor
          words={song.words}
          onToggleProfanity={handleToggleProfanity}
          onSetCensorType={handleSetCensorType}
          defaultCensorType={song.defaultCensorType}
          language={song.language}
          duration={song.duration}
          currentTime={currentTime}
          isPlaying={isPlaying}
        />
      )}

      {/* Song-level censor type selector */}
      <div className="flex items-center gap-4">
        <span className="text-xs text-zinc-500">Censor type for this song:</span>
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
          <AudioPreview
            originalPath={song.filePath}
            censoredPath={song.censoredFilePath}
            audioRef={audioRef}
            onClearFile={song.censoredFilePath ? () => {} : undefined}
          />
        </div>
      )}
    </div>
  )
}
