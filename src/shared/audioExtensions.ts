// The one list of audio formats Cleanse accepts. Shared by the main process
// (file dialogs, music-folder listing) and the renderer (drop zone), so a
// format added here is accepted everywhere at once — there used to be three
// hand-copied lists that could drift apart.

export const AUDIO_EXTENSIONS = ['mp3', 'wav', 'ogg', 'm4a', 'flac', 'aac', 'wma'] as const

/** Human-readable version for the drop zone hint ("MP3, WAV, ..."). */
export const AUDIO_EXTENSIONS_LABEL = AUDIO_EXTENSIONS.map((e) => e.toUpperCase()).join(', ')

/** "Song.MP3" -> true. Case-insensitive; a file with no extension is not audio. */
export function isAudioFileName(name: string): boolean {
  const dot = name.lastIndexOf('.')
  if (dot < 0) return false
  const ext = name.slice(dot + 1).toLowerCase()
  return (AUDIO_EXTENSIONS as readonly string[]).includes(ext)
}
