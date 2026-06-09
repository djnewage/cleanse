import { useState } from 'react'
import type { SongEntry, SeparationProgress, BeatGrid, IntroEditResult } from '../types'
import WaveformPlayer from './WaveformPlayer'

interface IntroEditTabProps {
  song: SongEntry
}

type StemMode = 'drums' | 'drumsbass'
type OutputFormat = 'flac' | 'wav' | 'aiff'
const BAR_OPTIONS = [8, 16, 32] as const
const FORMAT_OPTIONS: OutputFormat[] = ['flac', 'wav', 'aiff']

function stemsForMode(mode: StemMode): string[] {
  return mode === 'drumsbass' ? ['drums', 'bass'] : ['drums']
}

// WAV and FLAC decode + play in Chromium; AIFF does not, so it can't drive the
// in-app waveform/player.
function isPreviewable(outputPath: string): boolean {
  const p = outputPath.toLowerCase()
  return p.endsWith('.wav') || p.endsWith('.flac')
}

/**
 * Self-contained "Intro Edit" tab for the per-track detail panel: generate a
 * phrase-aligned beat intro/outro, preview it, and nudge the grid for a fast
 * regenerate (the backend reuses the detected grid + separated stems).
 *
 * State is local — only one detail panel is mounted at a time, so a single
 * onIntroOutroProgress subscription per generation is safe. Collapsing the
 * panel drops the in-memory result + cached stems (v1 limitation).
 */
export default function IntroEditTab({ song }: IntroEditTabProps): React.JSX.Element {
  const [introBars, setIntroBars] = useState(16)
  const [outroBars, setOutroBars] = useState(16)
  const [stemMode, setStemMode] = useState<StemMode>('drums')
  const [outputFormat, setOutputFormat] = useState<OutputFormat>('flac')
  const [isGenerating, setIsGenerating] = useState(false)
  const [progress, setProgress] = useState<SeparationProgress | null>(null)
  const [result, setResult] = useState<IntroEditResult | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [genCount, setGenCount] = useState(0)

  const handleGenerate = async (opts?: { grid?: BeatGrid; stemPaths?: Record<string, string> }) => {
    setIsGenerating(true)
    setError(null)
    const unsub = window.electronAPI.onIntroOutroProgress(setProgress)
    try {
      const r = await window.electronAPI.createIntroOutroEdit({
        filePath: song.filePath,
        introBars,
        outroBars,
        loopBars: 4,
        stems: stemsForMode(stemMode),
        outputFormat,
        grid: opts?.grid,
        stemPaths: opts?.stemPaths
      })
      setResult({
        outputPath: r.output_path,
        grid: r.grid,
        stemPaths: r.stem_paths,
        loopSourceIdx: r.loop_source_idx
      })
      setGenCount((c) => c + 1)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      unsub()
      setIsGenerating(false)
      setProgress(null)
    }
  }

  // Regenerate reusing cached grid + stems. The backend re-separates only if a
  // newly-requested stem (e.g. bass) is missing from stemPaths.
  const handleRegenerate = (): void => {
    if (!result) return
    void handleGenerate({ grid: result.grid, stemPaths: result.stemPaths })
  }

  // Phase-nudge the whole grid by ±1 beat (or ±1 bar) to fix an off-by-one "1",
  // then regenerate fast.
  const handleNudge = (beats: number): void => {
    if (!result) return
    const { grid } = result
    const beat = Math.round((grid.sample_rate * 60) / grid.bpm)
    const delta = beat * beats
    const shift = (s: number): number => Math.max(0, s + delta)
    const nudged: BeatGrid = {
      ...grid,
      downbeats_samples: grid.downbeats_samples.map(shift),
      beats_samples: grid.beats_samples.map(shift)
    }
    void handleGenerate({ grid: nudged, stemPaths: result.stemPaths })
  }

  const handleReveal = (): void => {
    if (!result) return
    const dir = result.outputPath.replace(/\/[^/]*$/, '')
    void window.electronAPI.openExternal(`file://${encodeURI(dir)}`)
  }

  const segBtn = (active: boolean): string =>
    `px-2.5 py-1 text-xs font-medium transition-colors ${
      active
        ? 'bg-blue-600 text-white'
        : 'bg-elevated text-text-secondary hover:bg-muted hover:text-text-secondary'
    } ${isGenerating ? 'opacity-50 cursor-not-allowed' : ''}`

  return (
    <div className="rounded-lg border border-border-strong bg-elevated/50 p-4 space-y-4">
      <h3 className="text-sm font-semibold text-text-secondary">Intro Edit</h3>

      {/* Controls */}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
        {/* Stem source */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-tertiary">Loop:</span>
          <div className="flex rounded-md overflow-hidden border border-border-strong">
            <button
              onClick={() => setStemMode('drums')}
              disabled={isGenerating}
              className={segBtn(stemMode === 'drums')}
            >
              Drums
            </button>
            <button
              onClick={() => setStemMode('drumsbass')}
              disabled={isGenerating}
              className={segBtn(stemMode === 'drumsbass')}
            >
              Drums + Bass
            </button>
          </div>
        </div>

        {/* Intro bars */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-tertiary">Intro bars:</span>
          <div className="flex rounded-md overflow-hidden border border-border-strong">
            {BAR_OPTIONS.map((n) => (
              <button
                key={n}
                onClick={() => setIntroBars(n)}
                disabled={isGenerating}
                className={segBtn(introBars === n)}
              >
                {n}
              </button>
            ))}
          </div>
        </div>

        {/* Outro bars */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-tertiary">Outro bars:</span>
          <div className="flex rounded-md overflow-hidden border border-border-strong">
            {BAR_OPTIONS.map((n) => (
              <button
                key={n}
                onClick={() => setOutroBars(n)}
                disabled={isGenerating}
                className={segBtn(outroBars === n)}
              >
                {n}
              </button>
            ))}
          </div>
        </div>

        {/* Output format */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-tertiary">Format:</span>
          <div className="flex rounded-md overflow-hidden border border-border-strong">
            {FORMAT_OPTIONS.map((f) => (
              <button
                key={f}
                onClick={() => setOutputFormat(f)}
                disabled={isGenerating}
                className={`${segBtn(outputFormat === f)} uppercase`}
              >
                {f}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Generate / Regenerate */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => (result ? handleRegenerate() : void handleGenerate())}
          disabled={isGenerating}
          className="px-4 py-1.5 text-xs font-semibold rounded bg-blue-600 hover:bg-blue-500 text-white transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {result ? 'Regenerate' : 'Generate Intro Edit'}
        </button>
        {isGenerating && progress && (
          <div className="flex items-center gap-2 text-xs text-text-tertiary">
            <div className="w-3 h-3 border-2 border-border-strong border-t-blue-400 rounded-full animate-spin" />
            <span>{progress.message}</span>
          </div>
        )}
      </div>

      {/* Error */}
      {error && !isGenerating && (
        <div className="text-xs text-red-400 px-3 py-2 bg-red-900/20 border border-red-800 rounded">
          Intro edit failed: {error}
        </div>
      )}

      {/* Preview + nudge */}
      {result && (
        <div className="space-y-3">
          {isPreviewable(result.outputPath) ? (
            <WaveformPlayer
              key={`introedit-${genCount}`}
              src={`media://${encodeURIComponent(result.outputPath)}`}
              label={`Intro Edit • ${result.grid.bpm.toFixed(0)} BPM`}
              labelColor="text-blue-400"
            />
          ) : (
            <div className="text-xs text-text-tertiary px-3 py-3 bg-surface border border-border rounded">
              <span className="text-blue-400">Intro Edit • {result.grid.bpm.toFixed(0)} BPM</span>
              {' — '}
              In-app preview isn’t available for AIFF. Use “Reveal in Finder” to open the
              exported file, or switch the format to FLAC/WAV and Regenerate to preview here.
            </div>
          )}

          <div className="flex flex-wrap items-center gap-3">
            <span className="text-xs text-text-tertiary">Nudge the “1”:</span>
            <div className="flex rounded-md overflow-hidden border border-border-strong">
              <button onClick={() => handleNudge(-1)} disabled={isGenerating} className={segBtn(false)}>
                −1 beat
              </button>
              <button onClick={() => handleNudge(1)} disabled={isGenerating} className={segBtn(false)}>
                +1 beat
              </button>
            </div>
            <button
              onClick={handleReveal}
              disabled={isGenerating}
              className="px-2.5 py-1 text-xs font-medium text-blue-400 hover:text-blue-300 bg-elevated hover:bg-muted border border-border-strong rounded-md transition-colors disabled:opacity-50"
            >
              Reveal in Finder
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
