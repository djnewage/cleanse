import { useState, useRef, useCallback, useEffect } from 'react'

interface PlaybackTimeState {
  currentTime: number
  isPlaying: boolean
  audioRef: (node: HTMLAudioElement | null) => void
}

export function usePlaybackTime(): PlaybackTimeState {
  const [currentTime, setCurrentTime] = useState(0)
  const [isPlaying, setIsPlaying] = useState(false)
  const audioElRef = useRef<HTMLAudioElement | null>(null)
  const rafIdRef = useRef<number | null>(null)
  const lastReportedTimeRef = useRef(0)

  const tick = useCallback(() => {
    const el = audioElRef.current
    if (!el) return
    const t = el.currentTime
    // Only update React state when time changes by >=30ms (~33 updates/sec)
    if (Math.abs(t - lastReportedTimeRef.current) >= 0.03) {
      lastReportedTimeRef.current = t
      setCurrentTime(t)
    }
    rafIdRef.current = requestAnimationFrame(tick)
  }, [])

  const startLoop = useCallback(() => {
    if (rafIdRef.current !== null) return
    rafIdRef.current = requestAnimationFrame(tick)
  }, [tick])

  const stopLoop = useCallback(() => {
    if (rafIdRef.current !== null) {
      cancelAnimationFrame(rafIdRef.current)
      rafIdRef.current = null
    }
  }, [])

  const syncTime = useCallback(() => {
    const el = audioElRef.current
    if (!el) return
    lastReportedTimeRef.current = el.currentTime
    setCurrentTime(el.currentTime)
  }, [])

  // Stable handler refs to avoid stale closures in event listeners
  const startLoopRef = useRef(startLoop)
  const stopLoopRef = useRef(stopLoop)
  const syncTimeRef = useRef(syncTime)
  startLoopRef.current = startLoop
  stopLoopRef.current = stopLoop
  syncTimeRef.current = syncTime

  // Stable event handlers that delegate through refs
  const handlePlay = useCallback(() => {
    setIsPlaying(true)
    startLoopRef.current()
  }, [])

  const handlePause = useCallback(() => {
    setIsPlaying(false)
    stopLoopRef.current()
    syncTimeRef.current()
  }, [])

  const handleEnded = useCallback(() => {
    setIsPlaying(false)
    stopLoopRef.current()
    syncTimeRef.current()
  }, [])

  const handleSeeked = useCallback(() => {
    syncTimeRef.current()
  }, [])

  // Ref callback handles mount/unmount of the audio element
  const audioRef = useCallback(
    (node: HTMLAudioElement | null) => {
      const prev = audioElRef.current
      if (prev) {
        prev.removeEventListener('play', handlePlay)
        prev.removeEventListener('pause', handlePause)
        prev.removeEventListener('ended', handleEnded)
        prev.removeEventListener('seeked', handleSeeked)
        stopLoopRef.current()
      }

      audioElRef.current = node

      if (node) {
        node.addEventListener('play', handlePlay)
        node.addEventListener('pause', handlePause)
        node.addEventListener('ended', handleEnded)
        node.addEventListener('seeked', handleSeeked)
        // Sync initial state in case element is already playing
        if (!node.paused) {
          setIsPlaying(true)
          startLoopRef.current()
        }
      }
    },
    [handlePlay, handlePause, handleEnded, handleSeeked]
  )

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      stopLoopRef.current()
    }
  }, [])

  return { currentTime, isPlaying, audioRef }
}
