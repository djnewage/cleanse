import type { ExportFormat } from '../types'

interface ExportFormatPickerProps {
  value: ExportFormat
  onChange: (format: ExportFormat) => void
  disabled?: boolean
}

const options: { value: ExportFormat; label: string }[] = [
  { value: 'source', label: 'Source' },
  { value: 'mp3', label: 'MP3' },
  { value: 'wav', label: 'WAV' },
  { value: 'flac', label: 'FLAC' }
]

export default function ExportFormatPicker({
  value,
  onChange,
  disabled
}: ExportFormatPickerProps): React.JSX.Element {
  return (
    <div className="flex items-center gap-2">
      <span
        className="text-xs text-text-tertiary cursor-help"
        title="Audio format for exported files. 'Source' matches the original file's format."
      >
        Format:
      </span>
      <div className="flex rounded-md overflow-hidden border border-border-strong">
        {options.map((opt) => (
          <button
            key={opt.value}
            onClick={() => onChange(opt.value)}
            disabled={disabled}
            className={`
              px-2.5 py-1 text-xs font-medium transition-colors
              ${
                value === opt.value
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
  )
}
