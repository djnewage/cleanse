import { useEffect, useRef, useCallback, useState } from 'react'
import WaveSurfer from 'wavesurfer.js'

interface WaveformPlayerProps {
  src: string
  label: string
  labelColor?: string
  onPlay?: () => void
  audioRef?: (node: HTMLAudioElement | null) => void
  externalPauseRef?: React.MutableRefObject<(() => void) | null>
  /** This player is serving the previous edit while a replacement renders.
   *  Shows an inline status on the label and dims the waveform; playback and
   *  seeking stay live so the listener keeps their place. */
  isUpdating?: boolean
}

function formatTime(seconds: number): string {
  if (!isFinite(seconds) || seconds < 0) return '0:00.0'
  const m = Math.floor(seconds / 60)
  const s = Math.floor(seconds % 60)
  const tenths = Math.floor((seconds % 1) * 10)
  return `${m}:${s.toString().padStart(2, '0')}.${tenths}`
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
  labelColor = 'text-text-secondary',
  onPlay,
  audioRef,
  externalPauseRef,
  isUpdating = false
}: WaveformPlayerProps): React.JSX.Element {
  const containerRef = useRef<HTMLDivElement>(null)
  const wavesurferRef = useRef<WaveSurfer | null>(null)
  const audioElRef = useRef<HTMLAudioElement | null>(null)
  // Playback position carried across a `src` swap (preview regenerated after an
  // edit). Null on first mount so a fresh song always starts at 0:00.
  const resumeRef = useRef<{ time: number; playing: boolean } | null>(null)
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

      // Create audio element for playback — media:// works natively with <audio>
      const audio = document.createElement('audio')
      audio.src = src
      audio.preload = 'auto'
      audioElRef.current = audio

      // Hand the element to the parent immediately (not after the decode) so
      // the karaoke highlight tracks resumed playback instead of freezing until
      // the waveform is ready.
      audioRef?.(audio)

      // Restore position BEFORE the (slow) peak decode: metadata lands in a few
      // ms, so an edit-triggered swap resumes almost seamlessly instead of going
      // silent for the length of a full decode.
      const resume = resumeRef.current
      if (resume && resume.time > 0) {
        const applyResume = (): void => {
          audio.currentTime = resume.time
          setCurrentTime(resume.time)
          if (resume.playing) {
            audio.play().catch((err: unknown) => {
              console.warn('[WaveformPlayer] resume failed:', err)
            })
          }
          // Consumed only once actually applied. If this source is swapped out
          // again before its metadata arrives (rapid edits), the pending
          // position survives in the ref instead of collapsing to 0:00.
          resumeRef.current = null
        }
        if (audio.readyState >= 1) applyResume()
        else audio.addEventListener('loadedmetadata', applyResume, { once: true })
      }

      // Load peaks so we can pass them at creation time.
      // This avoids loadBlob() which would disconnect the audio element
      const peakData = await loadPeaks(src)
      if (cancelled || !containerRef.current) return

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

      ws.on('play', () => {
        setIsPlaying(true)
        onPlay?.()
      })
      ws.on('pause', () => setIsPlaying(false))
      ws.on('timeupdate', (time) => setCurrentTime(time))
      ws.on('ready', () => setDuration(ws!.getDuration()))
      ws.on('error', (err) => console.error('[WaveformPlayer] Error:', err))

      // A resumed swap starts the element playing before WaveSurfer exists, so
      // its 'play' event fired before the listener above was attached — sync the
      // button state directly or it sticks on the play icon during playback.
      if (!audio.paused) {
        setIsPlaying(true)
        onPlay?.()
      }
    }

    init()

    return () => {
      cancelled = true
      // Capture position/playing state BEFORE pausing so the next source (a
      // regenerated preview) can pick up exactly where this one left off.
      const prevWs = wavesurferRef.current
      const prevAudio = audioElRef.current
      const prevTime = prevWs?.getCurrentTime() ?? prevAudio?.currentTime ?? 0
      if (prevTime > 0) {
        resumeRef.current = {
          time: prevTime,
          playing: prevAudio ? !prevAudio.paused : false
        }
      }
      // else: leave any still-unapplied pending resume in place.
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
    wavesurferRef.current?.playPause()?.catch((err: unknown) => {
      console.warn('[WaveformPlayer] play failed:', err)
    })
  }, [])

  return (
    <div>
      {/* Status lives ON the label rather than in a banner above the players:
          a banner appears and disappears on every edit and shifts the whole
          block down and back. Swapping text in place keeps the layout still. */}
      <label className={`flex items-baseline gap-2 text-sm font-medium mb-2 ${labelColor}`}>
        <span>{label}</span>
        {isUpdating && (
          <span className="flex items-center gap-1.5 text-xs font-normal text-text-tertiary">
            <span className="w-2.5 h-2.5 border-2 border-border-strong border-t-blue-400 rounded-full animate-spin" />
            updating&hellip;
          </span>
        )}
      </label>
      <div className="bg-elevated/50 rounded-lg p-3 border border-border-strong/50">
        {/* Dim the waveform only — the play button and time readout stay at full
            strength because the position is what the listener is tracking. */}
        <div
          ref={containerRef}
          className={`w-full cursor-pointer transition-opacity duration-200 ${
            isUpdating ? 'opacity-60' : ''
          }`}
        />
        <div className="flex items-center gap-3 mt-2">
          <button
            onClick={togglePlayPause}
            className="flex items-center justify-center w-8 h-8 rounded-full bg-muted hover:bg-muted transition-colors text-text-primary"
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
          <span className="text-xs text-text-tertiary font-mono tabular-nums">
            {formatTime(currentTime)} / {formatTime(duration)}
          </span>
        </div>
      </div>
    </div>
  )
}
