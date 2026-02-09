import { useEffect, useRef, useCallback } from 'react'
import type { BatchAppAction, SongEntry } from '../types'

interface UseQueueProcessorProps {
  songs: SongEntry[]
  currentlyProcessingId: string | null
  processingQueue: string[]
  turboEnabled: boolean
  dispatch: React.Dispatch<BatchAppAction>
}

export function useQueueProcessor({
  songs,
  currentlyProcessingId,
  processingQueue,
  turboEnabled,
  dispatch
}: UseQueueProcessorProps) {
  const isProcessingRef = useRef(false)

  // Subscribe to separation progress for the currently processing song
  useEffect(() => {
    if (!currentlyProcessingId) return

    const unsubscribe = window.electronAPI.onSeparationProgress((progress) => {
      dispatch({ type: 'SEPARATION_PROGRESS', id: currentlyProcessingId, progress })
    })

    return unsubscribe
  }, [currentlyProcessingId, dispatch])

  // Subscribe to transcription progress for the currently processing song
  useEffect(() => {
    if (!currentlyProcessingId) return

    const unsubscribe = window.electronAPI.onTranscriptionProgress((progress) => {
      dispatch({ type: 'TRANSCRIPTION_PROGRESS', id: currentlyProcessingId, progress })
    })

    return unsubscribe
  }, [currentlyProcessingId, dispatch])

  // Process a single song (fetch lyrics, separate vocals, then dual-pass transcription)
  const processSong = useCallback(
    async (songId: string) => {
      const song = songs.find((s) => s.id === songId)
      if (!song) return

      try {
        // Step 1: Fetch lyrics (if metadata available, fast ~1s)
        let plainLyrics: string | undefined
        let syncedLyrics: string | undefined

        if (song.metadata?.artist && song.metadata?.title) {
          dispatch({ type: 'START_FETCHING_LYRICS', id: songId })
          try {
            const lyricsResult = await window.electronAPI.fetchLyrics(
              song.metadata.artist,
              song.metadata.title,
              song.metadata.duration ?? undefined
            )
            if (lyricsResult.plain_lyrics || lyricsResult.synced_lyrics) {
              plainLyrics = lyricsResult.plain_lyrics ?? undefined
              syncedLyrics = lyricsResult.synced_lyrics ?? undefined
              dispatch({
                type: 'SET_SONG_LYRICS',
                id: songId,
                lyrics: { plain: lyricsResult.plain_lyrics, synced: lyricsResult.synced_lyrics }
              })
            }
          } catch {
            // Lyrics fetch is best-effort, continue without
          }
        }

        // Step 2: Vocal Separation
        dispatch({ type: 'START_SEPARATING', id: songId })
        const separationResult = await window.electronAPI.separateAudio(song.filePath, turboEnabled)
        dispatch({
          type: 'SEPARATION_COMPLETE',
          id: songId,
          vocalsPath: separationResult.vocals_path,
          accompanimentPath: separationResult.accompaniment_path
        })

        // Step 3: Dual-pass Transcription (with lyrics as initial_prompt + synced lyrics cross-ref)
        dispatch({ type: 'START_TRANSCRIPTION', id: songId })
        const transcriptionResult = await window.electronAPI.transcribeFile(
          song.filePath,
          turboEnabled,
          separationResult.vocals_path,
          plainLyrics,
          syncedLyrics
        )
        dispatch({
          type: 'TRANSCRIPTION_COMPLETE',
          id: songId,
          words: transcriptionResult.words,
          duration: transcriptionResult.duration,
          language: transcriptionResult.language
        })

        // Mark as ready
        dispatch({ type: 'SET_SONG_READY', id: songId })
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err)
        dispatch({ type: 'SET_SONG_ERROR', id: songId, message })
      } finally {
        dispatch({ type: 'PROCESSING_COMPLETE', id: songId })
      }
    },
    [songs, turboEnabled, dispatch]
  )

  // Watch the queue and process songs sequentially
  useEffect(() => {
    const processNext = async () => {
      // If already processing or queue is empty, do nothing
      if (isProcessingRef.current || processingQueue.length === 0) return
      if (currentlyProcessingId) return

      // Get the next song to process
      const nextId = processingQueue[0]
      const nextSong = songs.find((s) => s.id === nextId)

      // Skip if song doesn't exist or is already processed/errored
      if (!nextSong || nextSong.status !== 'pending') {
        dispatch({ type: 'PROCESSING_COMPLETE', id: nextId })
        return
      }

      isProcessingRef.current = true
      dispatch({ type: 'START_PROCESSING', id: nextId })

      await processSong(nextId)

      isProcessingRef.current = false
    }

    processNext()
  }, [processingQueue, currentlyProcessingId, songs, processSong, dispatch])

  // Retry a failed song
  const retrySong = useCallback(
    (songId: string) => {
      dispatch({ type: 'RETRY_SONG', id: songId })
    },
    [dispatch]
  )

  return { retrySong }
}
