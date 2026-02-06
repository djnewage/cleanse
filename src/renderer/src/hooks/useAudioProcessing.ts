import { useCallback } from 'react'
import type { AppAction, TranscribedWord, CensorWord, CensorType } from '../types'

export function useAudioProcessing(dispatch: React.Dispatch<AppAction>, defaultCensorType: CensorType) {
  const censor = useCallback(
    async (filePath: string, words: TranscribedWord[], vocalsPath?: string | null, accompanimentPath?: string | null) => {
      const profaneWords = words.filter((w) => w.is_profanity)

      if (profaneWords.length === 0) {
        dispatch({ type: 'SET_ERROR', message: 'No words marked for censoring' })
        return
      }

      // Ask user where to save
      const baseName = filePath.split('/').pop() || 'output.mp3'
      const ext = baseName.split('.').pop() || 'mp3'
      const cleanName = baseName.replace(`.${ext}`, `_clean.${ext}`)
      const outputPath = await window.electronAPI.selectOutputPath(cleanName)

      if (!outputPath) return // User cancelled

      dispatch({ type: 'START_CENSORING' })

      try {
        const censorWords: CensorWord[] = profaneWords.map((w) => ({
          word: w.word,
          start: w.start,
          end: w.end,
          censor_type: w.censor_type ?? defaultCensorType
        }))

        const result = await window.electronAPI.censorAudio(
          filePath,
          censorWords,
          outputPath,
          vocalsPath ?? undefined,
          accompanimentPath ?? undefined
        )
        const outputResult = result.output_path
        console.log('[Censor] Backend returned output_path:', outputResult, 'Full result:', result)
        if (!outputResult) {
          console.warn('[Censor] output_path is falsy, cannot show player')
        }
        dispatch({ type: 'CENSORING_COMPLETE', outputPath: outputResult })
      } catch (err) {
        dispatch({ type: 'SET_ERROR', message: (err as Error).message })
      }
    },
    [dispatch, defaultCensorType]
  )

  return { censor }
}
