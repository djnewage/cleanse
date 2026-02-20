interface DualPassToggleProps {
  enabled: boolean
  isProcessing: boolean
  onToggle: (enabled: boolean) => void
}

export default function DualPassToggle({
  enabled,
  isProcessing,
  onToggle
}: DualPassToggleProps): React.JSX.Element {
  return (
    <div className="flex items-center gap-2" title="Scans vocal track separately to catch background vocals and ad-libs">
      <span className="text-xs text-zinc-400">Ad-lib Scan</span>
      <button
        onClick={() => onToggle(!enabled)}
        disabled={isProcessing}
        className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
          enabled ? 'bg-blue-600' : 'bg-zinc-700'
        } ${isProcessing ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
      >
        <span
          className={`inline-block h-3.5 w-3.5 rounded-full bg-white transition-transform ${
            enabled ? 'translate-x-[18px]' : 'translate-x-[3px]'
          }`}
        />
      </button>
    </div>
  )
}
