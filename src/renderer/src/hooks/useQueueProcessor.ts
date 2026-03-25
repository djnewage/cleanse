import { useEffect, useRef, useCallback } from 'react'
import * as Sentry from '@sentry/react'
import type { BatchAppAction, SongEntry } from '../types'
import {
  logSeparationCompleted,
  logSeparationFailed,
  logTranscriptionCompleted,
  logTranscriptionFailed,
  logLyricsFetched
} from '../lib/analytics'

interface UseQueueProcessorProps {
  songs: SongEntry[]
  currentlyProcessingId: string | null
  processingQueue: string[]
  turboEnabled: boolean
  dualPassEnabled: boolean
  dispatch: React.Dispatch<BatchAppAction>
  onSongReady?: () => void
}

export function useQueueProcessor({
  songs,
  currentlyProcessingId,
  processingQueue,
  turboEnabled,
  dualPassEnabled,
  dispatch,
  onSongReady
}: UseQueueProcessorProps) {
  const isProcessingRef = useRef(false)
  const startedIdsRef = useRef(new Set<string>())
  const cancelledIdsRef = useRef(new Set<string>())

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

  // Check if a song was cancelled (uses ref to avoid stale closures)
  const isCancelled = useCallback(
    (songId: string): boolean => {
      return cancelledIdsRef.current.has(songId)
    },
    []
  )

  // Cancel a song — called from outside via the returned function
  const cancelSong = useCallback(
    (songId: string) => {
      cancelledIdsRef.current.add(songId)
    },
    []
  )

  // Process a single song (fetch lyrics, separate vocals, then dual-pass transcription)
  const processSong = useCallback(
    async (songId: string) => {
      const song = songs.find((s) => s.id === songId)
      if (!song) return

      try {
        // Step 1 + 2: Fetch lyrics AND separate vocals in parallel
        // Lyrics fetch is network I/O while separation is CPU/GPU — no conflict
        let plainLyrics: string | undefined
        let syncedLyrics: string | undefined

        const lyricsPromise = (song.metadata?.artist && song.metadata?.title)
          ? window.electronAPI.fetchLyrics(
              song.metadata.artist,
              song.metadata.title,
              song.metadata.duration ?? undefined
            ).then((result) => {
              if (result.plain_lyrics || result.synced_lyrics) {
                plainLyrics = result.plain_lyrics ?? undefined
                syncedLyrics = result.synced_lyrics ?? undefined
                dispatch({
                  type: 'SET_SONG_LYRICS',
                  id: songId,
                  lyrics: {
                    plain: result.plain_lyrics,
                    synced: result.synced_lyrics,
                    source: (result.lyrics_source as 'genius' | 'lrclib' | null) ?? null
                  }
                })
                logLyricsFetched()
              }
            }).catch(() => { /* best-effort */ })
          : Promise.resolve()

        dispatch({ type: 'START_SEPARATING', id: songId })
        const [separationResult] = await Promise.all([
          window.electronAPI.separateAudio(song.filePath, turboEnabled),
          lyricsPromise
        ])

        // Check if cancelled before transcription
        if (isCancelled(songId)) return

        dispatch({
          type: 'SEPARATION_COMPLETE',
          id: songId,
          vocalsPath: separationResult.vocals_path,
          accompanimentPath: separationResult.accompaniment_path
        })
        logSeparationCompleted()

        // Step 3: Dual-pass Transcription (with lyrics as initial_prompt + synced lyrics cross-ref)
        dispatch({ type: 'START_TRANSCRIPTION', id: songId })
        const transcriptionResult = await window.electronAPI.transcribeFile(
          song.filePath,
          turboEnabled,
          separationResult.vocals_path,
          plainLyrics,
          syncedLyrics,
          dualPassEnabled
        )

        // Check if cancelled before applying results
        if (isCancelled(songId)) return

        dispatch({
          type: 'TRANSCRIPTION_COMPLETE',
          id: songId,
          words: transcriptionResult.words,
          duration: transcriptionResult.duration,
          language: transcriptionResult.language
        })
        logTranscriptionCompleted()

        // Mark as ready
        dispatch({ type: 'SET_SONG_READY', id: songId })
        onSongReady?.()
      } catch (err) {
        // Ignore errors for cancelled songs
        if (isCancelled(songId)) return
        Sentry.captureException(err)
        const message = err instanceof Error ? err.message : String(err)
        if (message.includes('Separation')) logSeparationFailed()
        else logTranscriptionFailed()
        dispatch({ type: 'SET_SONG_ERROR', id: songId, message })
      } finally {
        cancelledIdsRef.current.delete(songId)
        if (!isCancelled(songId)) {
          dispatch({ type: 'PROCESSING_COMPLETE', id: songId })
        }
      }
    },
    [songs, turboEnabled, dualPassEnabled, dispatch, isCancelled]
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

      // Prevent StrictMode double-fire from processing the same song twice
      if (startedIdsRef.current.has(nextId)) return
      startedIdsRef.current.add(nextId)

      isProcessingRef.current = true
      dispatch({ type: 'START_PROCESSING', id: nextId })

      await processSong(nextId)

      isProcessingRef.current = false
      startedIdsRef.current.delete(nextId)
    }

    processNext()
  }, [processingQueue, currentlyProcessingId, songs, processSong, dispatch])

  // Retry a failed song
  const retrySong = useCallback(
    (songId: string) => {
      startedIdsRef.current.delete(songId)
      dispatch({ type: 'RETRY_SONG', id: songId })
    },
    [dispatch]
  )

  return { retrySong, cancelSong }
}
