import type { CensorType } from '../types'

interface BatchControlsProps {
  songCount: number
  readyCount: number
  completedCount: number
  globalCensorType: CensorType
  onSetGlobalCensorType: (type: CensorType) => void
  crossfadeMs: number
  onSetCrossfadeMs: (ms: number) => void
  paddingMs: number
  onSetPaddingMs: (ms: number) => void
  onExportAll: () => void
  onClearAll: () => void
  isExporting: boolean
  exportProgress: { completed: number; total: number } | null
  disabled: boolean
}

const censorOptions: { value: CensorType; label: string }[] = [
  { value: 'mute', label: 'Mute' },
  { value: 'beep', label: 'Beep' },
  { value: 'reverse', label: 'Reverse' },
  { value: 'tape_stop', label: 'Tape Stop' }
]

export default function BatchControls({
  songCount,
  readyCount,
  completedCount,
  globalCensorType,
  onSetGlobalCensorType,
  crossfadeMs,
  onSetCrossfadeMs,
  paddingMs,
  onSetPaddingMs,
  onExportAll,
  onClearAll,
  isExporting,
  exportProgress,
  disabled
}: BatchControlsProps): React.JSX.Element {
  const exportableCount = readyCount + completedCount
  const canExport = exportableCount > 0 && !isExporting

  return (
    <div className="flex flex-col gap-3 bg-surface/50 rounded-lg p-4 border border-border">
      {/* Settings row */}
      <div className="flex items-center gap-4">
        {/* Global censor type */}
        <div className="flex items-center gap-2">
          <span
            className="text-xs text-text-tertiary cursor-help"
            title="Default for all songs (can override per song during review)"
          >
            Default:
          </span>
          <div className="flex rounded-md overflow-hidden border border-border-strong">
            {censorOptions.map((opt) => (
              <button
                key={opt.value}
                onClick={() => onSetGlobalCensorType(opt.value)}
                disabled={disabled}
                className={`
                  px-2.5 py-1 text-xs font-medium transition-colors
                  ${
                    globalCensorType === opt.value
                      ? 'bg-blue-600 text-white'
                      : 'bg-elevated text-text-secondary hover:bg-muted hover:text-text-secondary'
                  }
                  ${disabled ? 'opacity-50 cursor-not-allowed' : ''}
                `}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* Crossfade control */}
        <div className="flex items-center gap-2">
          <span className="text-xs text-text-tertiary">Crossfade:</span>
          <input
            type="range"
            min={5}
            max={50}
            step={5}
            value={crossfadeMs}
            onChange={(e) => onSetCrossfadeMs(Number(e.target.value))}
            disabled={disabled}
            className="w-20 h-1 accent-blue-600 bg-muted rounded-full appearance-none cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
          />
          <span className="text-xs text-text-secondary w-16">{crossfadeMs}ms{crossfadeMs <= 5 ? ' (Sharp)' : crossfadeMs >= 50 ? ' (Smooth)' : ''}</span>
        </div>

        {/* Censor Range control */}
        <div className="flex items-center gap-2">
          <span
            className="text-xs text-text-tertiary cursor-help"
            title="How far the censor extends around each word (higher = more aggressive)"
          >
            Censor Range:
          </span>
          <input
            type="range"
            min={0}
            max={200}
            step={10}
            value={paddingMs}
            onChange={(e) => onSetPaddingMs(Number(e.target.value))}
            disabled={disabled}
            className="w-20 h-1 accent-blue-600 bg-muted rounded-full appearance-none cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
          />
          <span className="text-xs text-text-secondary w-16">{paddingMs}ms{paddingMs === 0 ? ' (Tight)' : paddingMs >= 200 ? ' (Wide)' : ''}</span>
        </div>
      </div>

      {/* Action buttons row */}
      <div className="flex items-center gap-3">
        <button
          onClick={onClearAll}
          disabled={disabled || isExporting || songCount === 0}
          className={`
            px-3 py-2 rounded-lg text-sm font-medium transition-colors
            ${
              disabled || isExporting || songCount === 0
                ? 'bg-elevated text-text-disabled cursor-not-allowed'
                : 'bg-muted text-text-secondary hover:bg-muted hover:text-text-primary'
            }
          `}
        >
          Clear Queue
        </button>

        <button
          onClick={onExportAll}
          disabled={!canExport}
          className={`
            px-5 py-2 rounded-lg text-sm font-medium transition-all
            ${
              canExport
                ? 'bg-blue-600 text-white hover:bg-blue-500 active:bg-blue-700'
                : 'bg-elevated text-text-disabled cursor-not-allowed'
            }
          `}
        >
          {isExporting ? (
            <span className="flex items-center gap-2">
              <span className="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
              Exporting...
            </span>
          ) : (
            `Export All (${exportableCount})`
          )}
        </button>
      </div>

      {/* Export progress bar */}
      {isExporting && exportProgress && (
        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs text-text-secondary">
            <span>Exporting {exportProgress.completed} of {exportProgress.total}</span>
            <span>{Math.round((exportProgress.completed / exportProgress.total) * 100)}%</span>
          </div>
          <div className="w-full h-2 bg-elevated rounded-full overflow-hidden">
            <div
              className="h-full bg-blue-500 rounded-full transition-all duration-300"
              style={{ width: `${(exportProgress.completed / exportProgress.total) * 100}%` }}
            />
          </div>
        </div>
      )}

      {/* Info text */}
      {!isExporting && exportableCount === 0 && songCount > 0 && (
        <p className="text-xs text-text-tertiary">
          Waiting for songs to finish processing before export...
        </p>
      )}

      {exportableCount > 0 && !isExporting && (
        <p className="text-xs text-text-tertiary">
          {exportableCount} song{exportableCount !== 1 ? 's' : ''} ready to export.
          Unreviewed songs will use auto-detected profanity.
        </p>
      )}
    </div>
  )
}
