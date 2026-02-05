import { useEffect, useRef, useCallback } from 'react'
import type { BatchAppAction, SongEntry } from '../types'

interface UseQueueProcessorProps {
  songs: SongEntry[]
  currentlyProcessingId: string | null
  processingQueue: string[]
  dispatch: React.Dispatch<BatchAppAction>
}

export function useQueueProcessor({
  songs,
  currentlyProcessingId,
  processingQueue,
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

  // Process a single song (transcribe then separate)
  const processSong = useCallback(
    async (songId: string) => {
      const song = songs.find((s) => s.id === songId)
      if (!song) return

      try {
        // Step 1: Transcription
        dispatch({ type: 'START_TRANSCRIPTION', id: songId })
        const transcriptionResult = await window.electronAPI.transcribeFile(song.filePath)
        dispatch({
          type: 'TRANSCRIPTION_COMPLETE',
          id: songId,
          words: transcriptionResult.words,
          duration: transcriptionResult.duration,
          language: transcriptionResult.language
        })

        // Step 2: Vocal Separation
        dispatch({ type: 'START_SEPARATING', id: songId })
        const separationResult = await window.electronAPI.separateAudio(song.filePath)
        dispatch({
          type: 'SEPARATION_COMPLETE',
          id: songId,
          vocalsPath: separationResult.vocals_path,
          accompanimentPath: separationResult.accompaniment_path
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
    [songs, dispatch]
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
