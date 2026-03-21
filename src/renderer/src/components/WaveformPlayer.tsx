import { useEffect, useRef, useCallback, useState } from 'react'
import WaveSurfer from 'wavesurfer.js'

interface WaveformPlayerProps {
  src: string
  label: string
  labelColor?: string
  onPlay?: () => void
  audioRef?: (node: HTMLAudioElement | null) => void
  /** Called when this player should pause (e.g. the other player started) */
  externalPauseRef?: React.MutableRefObject<(() => void) | null>
}

function formatTime(seconds: number): string {
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

export default function WaveformPlayer({
  src,
  label,
  labelColor = 'text-zinc-300',
  onPlay,
  audioRef,
  externalPauseRef
}: WaveformPlayerProps): React.JSX.Element {
  const containerRef = useRef<HTMLDivElement>(null)
  const wavesurferRef = useRef<WaveSurfer | null>(null)
  const audioElRef = useRef<HTMLAudioElement | null>(null)
  const [isPlaying, setIsPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)

  // Expose pause function to parent for coordination
  useEffect(() => {
    if (externalPauseRef) {
      externalPauseRef.current = () => {
        wavesurferRef.current?.pause()
      }
    }
    return () => {
      if (externalPauseRef) {
        externalPauseRef.current = null
      }
    }
  }, [externalPauseRef])

  useEffect(() => {
    if (!containerRef.current) return

    // Create hidden audio element
    const audio = new Audio()
    audio.src = src
    audio.preload = 'auto'
    audioElRef.current = audio

    // Forward ref to parent
    audioRef?.(audio)

    const ws = WaveSurfer.create({
      container: containerRef.current,
      media: audio,
      waveColor: '#52525b',
      progressColor: '#3b82f6',
      cursorColor: '#3b82f6',
      cursorWidth: 1,
      height: 48,
      barWidth: 2,
      barGap: 1,
      barRadius: 2,
      normalize: true,
      hideScrollbar: true,
      fillParent: true,
      minPxPerSec: 0,
    })

    wavesurferRef.current = ws

    ws.on('play', () => {
      setIsPlaying(true)
      onPlay?.()
    })
    ws.on('pause', () => setIsPlaying(false))
    ws.on('timeupdate', (time) => setCurrentTime(time))
    ws.on('ready', () => setDuration(ws.getDuration()))

    return () => {
      audioRef?.(null)
      ws.destroy()
      wavesurferRef.current = null
      audioElRef.current = null
    }
  }, [src]) // eslint-disable-line react-hooks/exhaustive-deps

  const togglePlayPause = useCallback(() => {
    wavesurferRef.current?.playPause()
  }, [])

  return (
    <div>
      <label className={`block text-sm font-medium mb-2 ${labelColor}`}>{label}</label>
      <div className="bg-zinc-800/50 rounded-lg p-3 border border-zinc-700/50">
        <div ref={containerRef} className="w-full cursor-pointer" />
        <div className="flex items-center gap-3 mt-2">
          <button
            onClick={togglePlayPause}
            className="flex items-center justify-center w-8 h-8 rounded-full bg-zinc-700 hover:bg-zinc-600 transition-colors text-white"
          >
            {isPlaying ? (
              <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor">
                <rect x="2" y="1" width="3" height="10" rx="0.5" />
                <rect x="7" y="1" width="3" height="10" rx="0.5" />
              </svg>
            ) : (
              <svg width="12" height="12" viewBox="0 0 12 12" fill="currentColor">
                <path d="M3 1.5v9l7.5-4.5L3 1.5z" />
              </svg>
            )}
          </button>
          <span className="text-xs text-zinc-400 font-mono tabular-nums">
            {formatTime(currentTime)} / {formatTime(duration)}
          </span>
        </div>
      </div>
    </div>
  )
}
