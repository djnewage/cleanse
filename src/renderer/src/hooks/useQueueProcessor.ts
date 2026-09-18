import { useEffect, useRef, useCallback } from 'react'
import * as Sentry from '@sentry/react'
import type { BatchAppAction, SongEntry } from '../types'
import { track, errorKind, type ProcessingStage } from '../lib/analytics'

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
      track('song_canceled')
    },
    []
  )

  // Process a single song (fetch lyrics, separate vocals, then dual-pass transcription)
  const processSong = useCallback(
    async (songId: string) => {
      const song = songs.find((s) => s.id === songId)
      if (!song) return

      // Which step was running when an error escapes, for song_failed.
      let stage: ProcessingStage = 'separation'

      try {
        // Step 1 + 2: Fetch lyrics AND separate vocals in parallel
        // Lyrics fetch is network I/O while separation is CPU/GPU — no conflict
        let plainLyrics: string | undefined
        let syncedLyrics: string | undefined
        // Lyrics found via a guessed metadata interpretation (dirty tags /
        // filename) must not bias Whisper's initial prompt — a wrong-song
        // guess degrades the transcription itself.
        let lyricsFromTags = true

        // Fetch even without clean tags: the backend derives (artist, title)
        // candidates from the file name when tags are missing or rip-site
        // polluted (channel name as artist, "Artist - Title" in the title field).
        const lyricsPromise = ((song.metadata?.artist && song.metadata?.title) || song.fileName)
          ? window.electronAPI.fetchLyrics(
              song.metadata?.artist ?? null,
              song.metadata?.title ?? null,
              song.metadata?.duration ?? undefined,
              song.fileName
            ).then((result) => {
              if (result.plain_lyrics || result.synced_lyrics) {
                plainLyrics = result.plain_lyrics ?? undefined
                syncedLyrics = result.synced_lyrics ?? undefined
                lyricsFromTags = result.from_tag_metadata !== false
                dispatch({
                  type: 'SET_SONG_LYRICS',
                  id: songId,
                  lyrics: {
                    plain: result.plain_lyrics,
                    synced: result.synced_lyrics,
                    source: (result.lyrics_source as 'genius' | 'lrclib' | null) ?? null,
                    durationMismatch: Boolean(result.duration_mismatch)
                  }
                })
                track('lyrics_fetched', {
                  source: (result.lyrics_source as string | null) ?? 'unknown',
                  duration_mismatch: Boolean(result.duration_mismatch),
                  from_tags: lyricsFromTags
                })
              }
            }).catch(() => { /* best-effort */ })
          : Promise.resolve()

        dispatch({ type: 'START_SEPARATING', id: songId })
        const separationStartedAt = performance.now()
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
        track('separation_completed', {
          elapsed_ms: Math.round(performance.now() - separationStartedAt),
          turbo: turboEnabled
        })

        // Step 3: Dual-pass Transcription (with lyrics as initial_prompt + synced lyrics cross-ref)
        stage = 'transcription'
        dispatch({ type: 'START_TRANSCRIPTION', id: songId })
        const transcriptionStartedAt = performance.now()
        const transcriptionResult = await window.electronAPI.transcribeFile(
          song.filePath,
          turboEnabled,
          separationResult.vocals_path,
          plainLyrics,
          syncedLyrics,
          dualPassEnabled,
          lyricsFromTags
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
        track('transcription_completed', {
          elapsed_ms: Math.round(performance.now() - transcriptionStartedAt),
          audio_duration_s: Math.round(transcriptionResult.duration),
          language: transcriptionResult.language || 'unknown',
          word_count: transcriptionResult.words.length,
          profanity_count: transcriptionResult.words.filter((w) => w.is_profanity).length,
          turbo: turboEnabled,
          dual_pass: dualPassEnabled,
          language_low_confidence: Boolean(transcriptionResult.language_low_confidence)
        })

        // Mark as ready
        dispatch({ type: 'SET_SONG_READY', id: songId })
        onSongReady?.()
      } catch (err) {
        // Ignore errors for cancelled songs
        if (isCancelled(songId)) return
        Sentry.captureException(err)
        const message = err instanceof Error ? err.message : String(err)
        track('song_failed', { stage, error_kind: errorKind(message) })
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
      track('song_retried')
      dispatch({ type: 'RETRY_SONG', id: songId })
    },
    [dispatch]
  )

  return { retrySong, cancelSong }
}
