import type { CensorType } from '../types'

interface ExportControlsProps {
  onExport: () => void
  disabled: boolean
  hasProfanity: boolean
  isCensoring: boolean
  defaultCensorType: CensorType
  onSetDefaultCensorType: (type: CensorType) => void
}

const censorOptions: { value: CensorType; label: string }[] = [
  { value: 'mute', label: 'Mute' },
  { value: 'beep', label: 'Beep' },
  { value: 'reverse', label: 'Reverse' }
]

export default function ExportControls({
  onExport,
  disabled,
  hasProfanity,
  isCensoring,
  defaultCensorType,
  onSetDefaultCensorType
}: ExportControlsProps): React.JSX.Element {
  return (
    <div className="flex items-center gap-4">
      <div className="flex items-center gap-2">
        <span className="text-xs text-zinc-500">Default censor:</span>
        <div className="flex rounded-md overflow-hidden border border-zinc-700">
          {censorOptions.map((opt) => (
            <button
              key={opt.value}
              onClick={() => onSetDefaultCensorType(opt.value)}
              className={`
                px-2.5 py-1 text-xs font-medium transition-colors
                ${
                  defaultCensorType === opt.value
                    ? 'bg-blue-600 text-white'
                    : 'bg-zinc-800 text-zinc-400 hover:bg-zinc-700 hover:text-zinc-300'
                }
              `}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      <button
        onClick={onExport}
        disabled={disabled || !hasProfanity || isCensoring}
        className={`
          px-5 py-2.5 rounded-lg font-medium text-sm transition-all
          ${
            disabled || !hasProfanity || isCensoring
              ? 'bg-zinc-800 text-zinc-600 cursor-not-allowed'
              : 'bg-blue-600 text-white hover:bg-blue-500 active:bg-blue-700'
          }
        `}
      >
        {isCensoring ? (
          <span className="flex items-center gap-2">
            <span className="inline-block w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
            Censoring...
          </span>
        ) : (
          'Censor & Export'
        )}
      </button>

      {!hasProfanity && !disabled && (
        <span className="text-sm text-zinc-500">No words flagged for censoring</span>
      )}
    </div>
  )
}
