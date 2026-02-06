import { useMemo } from 'react'
import type { TranscribedWord } from '../types'

/**
 * Binary search to find the word whose [start, end) interval contains `time`.
 * Returns the index, or -1 if no word spans the given time.
 */
function findActiveWord(words: TranscribedWord[], time: number): number {
  if (words.length === 0 || time < 0) return -1

  let lo = 0
  let hi = words.length - 1

  while (lo <= hi) {
    const mid = (lo + hi) >>> 1
    const w = words[mid]

    if (time < w.start) {
      hi = mid - 1
    } else if (time >= w.end) {
      lo = mid + 1
    } else {
      // w.start <= time < w.end
      return mid
    }
  }

  return -1
}

export function useActiveWordIndex(words: TranscribedWord[], currentTime: number): number {
  return useMemo(() => findActiveWord(words, currentTime), [words, currentTime])
}
