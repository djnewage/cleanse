import { useCallback } from 'react'
import type { AppAction, TranscribedWord } from '../types'

export function useTranscription(dispatch: React.Dispatch<AppAction>) {
  const transcribe = useCallback(
    async (filePath: string): Promise<boolean> => {
      dispatch({ type: 'START_TRANSCRIPTION' })

      try {
        const result = await window.electronAPI.transcribeFile(filePath)
        dispatch({
          type: 'TRANSCRIPTION_COMPLETE',
          words: result.words as TranscribedWord[],
          duration: result.duration,
          language: result.language
        })
        return true
      } catch (err) {
        dispatch({ type: 'SET_ERROR', message: (err as Error).message })
        return false
      }
    },
    [dispatch]
  )

  return { transcribe }
}
