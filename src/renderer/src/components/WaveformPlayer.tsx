import { useEffect, useRef, useCallback, useState } from 'react'
import WaveSurfer from 'wavesurfer.js'

interface WaveformPlayerProps {
  src: string
  label: string
  labelColor?: string
  onPlay?: () => void
  audioRef?: (node: HTMLAudioElement | null) => void
  externalPauseRef?: React.MutableRefObject<(() => void) | null>
}

function formatTime(seconds: number): string {
  if (!isFinite(seconds) || seconds < 0) return '0:00'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  return `${m}:${s.toString().padStart(2, '0')}`
}

/** Extract the file path from a media:// URL */
function mediaUrlToPath(url: string): string {
  return decodeURIComponent(url.replace(/^media:\/\//, ''))
}

/** Read audio file via IPC and decode to peaks for waveform rendering */
async function loadPeaks(src: string): Promise<{ peaks: Float32Array; duration: number } | null> {
  try {
    const filePath = mediaUrlToPath(src)
    const buffer = await window.electronAPI.readAudioFile(filePath)
    const audioContext = new AudioContext()
    const decoded = await audioContext.decodeAudioData(buffer)
    const peaks = decoded.getChannelData(0)
    const duration = decoded.duration
    audioContext.close()
    return { peaks, duration }
  } catch (err) {
    console.warn('[WaveformPlayer] Could not load peaks:', err)
    return null
  }
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

    let cancelled = false
    let ws: WaveSurfer | null = null

    const init = async () => {
      if (!containerRef.current) return

      // Load peaks first so we can pass them at creation time
      // This avoids loadBlob() which would disconnect the audio element
      const peakData = await loadPeaks(src)
      if (cancelled || !containerRef.current) return

      // Create audio element for playback — media:// works natively with <audio>
      const audio = document.createElement('audio')
      audio.src = src
      audio.preload = 'auto'
      audioElRef.current = audio

      // Create wavesurfer with pre-computed peaks + our audio element
      ws = WaveSurfer.create({
        container: containerRef.current,
        media: audio,
        peaks: peakData ? [Array.from(peakData.peaks)] : undefined,
        duration: peakData?.duration,
        waveColor: '#52525b',
        progressColor: '#3b82f6',
        cursorColor: '#3b82f6',
        cursorWidth: 2,
        dragToSeek: { debounceTime: 0 },
        interact: true,
        height: 48,
        barWidth: 2,
        barGap: 1,
        barRadius: 2,
        normalize: true,
        hideScrollbar: true,
        fillParent: true,
      })

      wavesurferRef.current = ws

      // Forward ref to parent for karaoke word tracking
      audioRef?.(audio)

      ws.on('play', () => {
        setIsPlaying(true)
        onPlay?.()
      })
      ws.on('pause', () => setIsPlaying(false))
      ws.on('timeupdate', (time) => setCurrentTime(time))
      ws.on('ready', () => setDuration(ws!.getDuration()))
      ws.on('error', (err) => console.error('[WaveformPlayer] Error:', err))
    }

    init()

    return () => {
      cancelled = true
      audioRef?.(null)
      // Explicitly stop and release the audio element to prevent ghost playback
      if (audioElRef.current) {
        audioElRef.current.pause()
        audioElRef.current.src = ''
        audioElRef.current = null
      }
      if (ws) ws.destroy()
      wavesurferRef.current = null
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
